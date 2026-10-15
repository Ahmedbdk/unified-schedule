"""Parse the personal schedule HTML shown by Workforce's EU mobile web app.

This reads the same schedules/me frame as the browser, not the restricted
API token portal. No authentication secrets or raw HTML are saved.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone as utc_timezone
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


BASE_URL = "https://eu.workforce.com"


class WorkforceError(ValueError):
    """The personal schedule cannot be extracted without guessing."""


class WorkforceSessionExpired(WorkforceError):
    """The server requires a fresh login, rather than a parsing retry."""


@dataclass
class _Element:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Element):
                yield from child.walk()

    def text(self) -> str:
        return " ".join("".join(
            child.text() if isinstance(child, _Element) else child
            for child in self.children
        ).split())


class _HTMLTree(HTMLParser):
    """Minimal HTML tree for the observed server-rendered schedule cards."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Element("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Element(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input",
                       "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Element(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c)).replace("’", "'")


MONTHS = {
    "jan": 1, "janv": 1, "janvier": 1, "fev": 2, "fevr": 2, "fevrier": 2,
    "mars": 3, "avr": 4, "avril": 4, "mai": 5, "juin": 6,
    "juil": 7, "juillet": 7, "aout": 8, "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10, "nov": 11, "novembre": 11,
    "dec": 12, "decembre": 12,
}
WEEKDAYS = {"lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6}


def parse_date_label(label: str, week_start: date, observed_on: date) -> date:
    """Resolve French dates against the requested week, including year rollover."""
    if week_start.weekday() != 0:
        raise WorkforceError("The requested week must start on Monday.")
    normalized = _plain(label).strip()
    relative = {"aujourd'hui": 0, "demain": 1, "hier": -1}
    if normalized in relative:
        result = observed_on + timedelta(days=relative[normalized])
    else:
        match = re.fullmatch(
            r"(?:(lun|mar|mer|jeu|ven|sam|dim)\.?\s*,?\s+)?"
            r"(\d{1,2})\s+([a-z]+)\.?(?:\s+(\d{4}))?", normalized,
        )
        if not match or match[3] not in MONTHS:
            raise WorkforceError("Unrecognized date label in a shift card.")
        candidates = [week_start + timedelta(days=index) for index in range(7)]
        candidates = [day for day in candidates if day.day == int(match[2])
                      and day.month == MONTHS[match[3]]
                      and (not match[4] or day.year == int(match[4]))]
        if len(candidates) != 1:
            raise WorkforceError("A shift date does not belong to the requested week.")
        result = candidates[0]
        if match[1] and result.weekday() != WEEKDAYS[match[1]]:
            raise WorkforceError("A shift's weekday and calendar date disagree.")
    if not week_start <= result < week_start + timedelta(days=7):
        raise WorkforceError("A relative shift date does not belong to the requested week.")
    return result


def _parse_clock(value: str) -> time:
    """Accept the observed 24-hour and English AM/PM display formats."""
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", value.strip(), re.IGNORECASE)
    if not match:
        raise WorkforceError("Invalid clock time in a shift card.")
    hour = int(match[1])
    minute = int(match[2] or 0)
    period = match[3]
    if minute > 59:
        raise WorkforceError("Invalid clock time in a shift card.")
    if period:
        if not 1 <= hour <= 12:
            raise WorkforceError("Invalid AM/PM hour in a shift card.")
        hour = hour % 12 + (12 if period.upper() == "PM" else 0)
    elif match[2] is None or hour > 23:
        raise WorkforceError("Invalid 24-hour clock time in a shift card.")
    return time(hour, minute)


def _local_datetime(day: date, clock: time, zone: ZoneInfo) -> datetime:
    naive = datetime.combine(day, clock)
    candidates = {}
    for fold in (0, 1):
        value = naive.replace(tzinfo=zone, fold=fold)
        roundtrip = value.astimezone(utc_timezone.utc).astimezone(zone)
        if roundtrip.replace(tzinfo=None) == naive:
            candidates[value.timestamp()] = value
    if len(candidates) != 1:
        raise WorkforceError("A shift time is ambiguous or nonexistent during a daylight saving change.")
    return next(iter(candidates.values()))


@dataclass(frozen=True)
class WorkShift:
    schedule_id: str
    start: datetime
    end: datetime
    role: str
    location: str
    label: str

    def to_dict(self) -> dict:
        return {
            "uid": f"workforce:{self.schedule_id}", "schedule_id": self.schedule_id,
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "role": self.role, "location": self.location, "label": self.label,
        }


def _field_text(card: _Element, classes: set[str]) -> str:
    matches = [node for node in card.walk() if node.tag == "span"
               and classes <= set((node.attrs.get("class") or "").split())]
    if len(matches) != 1 or not matches[0].text():
        raise WorkforceError("A shift card field is missing or ambiguous; the page layout may have changed.")
    return matches[0].text()


def personal_week(src: str) -> date:
    """Verify the selected frame is Mine on the EU host, never Team."""
    try:
        parsed = urlsplit(src)
    except ValueError:
        raise WorkforceError("Invalid personal schedule frame URL.") from None
    if parsed.scheme and (parsed.scheme != "https" or parsed.netloc != "eu.workforce.com"):
        raise WorkforceError("The schedule frame is not on the expected EU Workforce host.")
    if parsed.netloc and parsed.netloc != "eu.workforce.com":
        raise WorkforceError("Unexpected schedule frame host.")
    match = re.fullmatch(r"/mobile_app/schedules/me/(\d{4}-\d{2}-\d{2})/list", parsed.path)
    if not match:
        raise WorkforceError("Open Liste and select Mine before continuing.")
    try:
        result = date.fromisoformat(match[1])
    except ValueError:
        raise WorkforceError("Invalid week in the schedule frame URL.") from None
    if result.weekday() != 0:
        raise WorkforceError("The schedule frame week does not start on Monday.")
    return result


def parse_schedule_html(html: str, week_start: date, observed_on: date,
                        timezone: str = "Europe/Paris") -> list[WorkShift]:
    """Extract cards independently; accept empty frames only when fully loaded."""
    if week_start.weekday() != 0:
        raise WorkforceError("The requested week must start on Monday.")
    zone = ZoneInfo(timezone)
    tree = _HTMLTree()
    tree.feed(html)
    frames = [node for node in tree.root.walk()
              if node.tag == "turbo-frame" and node.attrs.get("id") == "schedules"]
    if len(frames) != 1:
        if any(node.tag == "input" and (node.attrs.get("type") or "").lower() == "password"
               for node in tree.root.walk()):
            raise WorkforceSessionExpired("Workforce requires a fresh login.")
        raise WorkforceError("The personal schedule frame is missing; check login and page layout.")
    frame = frames[0]
    if frame.attrs.get("src") and personal_week(frame.attrs["src"]) != week_start:
        raise WorkforceError("The returned schedule frame belongs to a different week.")
    cards = [node for node in frame.walk()
             if (node.attrs.get("data-test-id") or "").startswith("schedule_")]
    if not cards:
        # Match the observed empty-state heading and explanatory sentence,
        # not just the absence of cards. Holiday notices may also be present.
        loaded = not frame.attrs.get("src") or "complete" in frame.attrs
        messages = [_plain(node.text()) for node in frame.walk() if node.tag in {"span", "p"}]
        empty_messages = (
            ("aucun quart de travail a venir",
             "une fois que votre travail sera planifie, vous verrez vos quarts de travail ici."),
            ("no upcoming shifts",
             "once you're rostered to work, you'll see your shifts here."),
        )
        recognized_empty = any(
            messages.count(heading) == 1 and explanation in messages
            for heading, explanation in empty_messages
        )
        suspicious = any(
            node.tag in {"form", "input", "script"}
            or node.attrs.get("id", "").startswith("schedule_")
            or node.attrs.get("data-test-id", "").startswith("schedule")
            for node in frame.walk()
        )
        if loaded and recognized_empty and not suspicious:
            return []
        raise WorkforceError("No shift cards found, but this is not a recognized empty week. Check the page layout.")
    shifts = {}
    for card in cards:
        match = re.fullmatch(r"schedule_(\d+)", card.attrs["data-test-id"])
        if not match or card.attrs.get("id") != match[0]:
            raise WorkforceError("A shift card has an invalid schedule ID.")
        label = _field_text(card, {"font-bold", "text-xl"})
        day = parse_date_label(label, week_start, observed_on)
        hours = _field_text(card, {"text-base", "font-bold"})
        clock_pattern = r"\d{1,2}(?::\d{2})?(?:\s*(?:AM|PM))?"
        match_hours = re.fullmatch(
            rf"({clock_pattern})\s*[-–—]\s*({clock_pattern})", hours, re.IGNORECASE,
        )
        if not match_hours:
            raise WorkforceError(
                f"Unrecognized hours for shift {match[1]} in week {week_start.isoformat()}: {hours!r}. "
                "Share this hours text or the shift card HTML so its format can be verified."
            )
        start_clock, end_clock = (_parse_clock(value) for value in match_hours.groups())
        if start_clock == end_clock:
            raise WorkforceError("A shift has identical start/end times; its duration needs verification.")
        end_day = day + timedelta(days=1) if end_clock < start_clock else day
        start = _local_datetime(day, start_clock, zone)
        end = _local_datetime(end_day, end_clock, zone)
        text = _field_text(card, {"text-sm", "text-gray-800"})
        role, separator, location = text.partition(" @ ")
        shift = WorkShift(match[1], start, end, role, location if separator else "", text)
        if shift.schedule_id in shifts:
            raise WorkforceError("Duplicate schedule ID in a week; export aborted.")
        shifts[shift.schedule_id] = shift
    return sorted(shifts.values(), key=lambda shift: (shift.start.timestamp(), shift.schedule_id))


def fetch_week(context, week_start: date, timezone: str = "Europe/Paris") -> list[WorkShift]:
    """Use the browser's logged-in cookies to read its personal HTML frame."""
    zone = ZoneInfo(timezone)
    observed_on = datetime.now(zone).date()
    path = f"/mobile_app/schedules/me/{week_start.isoformat()}/list"
    response = context.request.get(
        BASE_URL + path, headers={"Turbo-Frame": "schedules"}, timeout=30_000,
        max_redirects=0,
    )
    try:
        if response.status != 200:
            location = response.headers.get("location", "")
            if response.status == 401 or (
                response.status in {301, 302, 303, 307, 308}
                and urlsplit(location).path in {"/login", "/mobile_app/login"}
            ):
                raise WorkforceSessionExpired(f"Workforce requires a fresh login (HTTP {response.status}).")
            raise WorkforceError(f"Personal schedule returned HTTP {response.status}; check login and access.")
        shifts = parse_schedule_html(response.text(), week_start, observed_on, timezone)
        if datetime.now(zone).date() != observed_on:
            raise WorkforceError("The date changed while downloading; rerun to resolve relative dates safely.")
        return shifts
    finally:
        response.dispose()
