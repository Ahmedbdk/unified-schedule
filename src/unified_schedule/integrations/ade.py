"""Retrieve ADE ICS feeds and parse individual timetable events."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from icalendar import Calendar
import requests


class ADEError(ValueError):
    """An ADE download or calendar could not be safely processed."""


@dataclass(frozen=True)
class Download:
    content: bytes
    headers: dict[str, str]

    @property
    def sha256(self) -> str:
        return sha256(self.content).hexdigest()


@dataclass(frozen=True)
class ADEEvent:
    uid: str
    summary: str
    start: date | datetime
    end: date | datetime
    location: str
    description: str
    status: str

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)

    def to_dict(self) -> dict:
        result = asdict(self)
        result.update(start=self.start.isoformat(), end=self.end.isoformat(),
                      all_day=self.all_day)
        return result


def fetch_calendar(url: str) -> Download:
    """Download over HTTPS with timeouts; never expose the URL in errors."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise ADEError("ADE_ICS_URL is not a valid HTTPS URL.") from None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ADEError("ADE_ICS_URL must be an HTTPS URL without embedded credentials.")
    try:
        with requests.get(
            url, timeout=(5, 30),
            headers={"Accept": "text/calendar", "Cache-Control": "no-cache"},
        ) as response:
            if response.status_code != 200:
                raise ADEError(f"ADE returned HTTP {response.status_code}; expected 200.")
            content = response.content
            # Export endpoints sometimes return HTML with a successful HTTP status.
            if not content.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"BEGIN:VCALENDAR"):
                raise ADEError("ADE did not return an ICS calendar (possibly an error/login page).")
            headers = {
                name: response.headers[name]
                for name in ("Date", "Content-Type", "Cache-Control", "ETag", "Last-Modified")
                if name in response.headers
            }
            return Download(content, headers)
    except requests.Timeout:
        raise ADEError("ADE download timed out; try again later.") from None
    except requests.RequestException:
        raise ADEError("ADE download failed; check connectivity and the configured URL.") from None


def parse_calendar(content: bytes, timezone: str = "Europe/Paris") -> list[ADEEvent]:
    """Parse event times into the configured zone; preserve all-day dates.

    Floating times are interpreted in the configured zone. End dates are
    exclusive. Recurrence is deliberately rejected until expansion is implemented.
    A malformed event fails the import rather than silently losing a class.
    """
    zone = ZoneInfo(timezone)
    try:
        calendar = Calendar.from_ical(content)
        if calendar.name != "VCALENDAR":
            raise ValueError("Expected VCALENDAR")
        if any(component.errors for component in calendar.walk()):
            raise ValueError("ICS property decoding errors")
        events = []
        seen = set()
        for index, item in enumerate(calendar.walk("VEVENT"), start=1):
            if any(key in item for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
                raise ADEError(f"Event {index} uses recurrence, which this milestone does not support.")
            uid = str(item.get("UID", "")).strip()
            if not uid or uid in seen:
                raise ADEError(f"Event {index} has a missing or duplicate UID.")
            seen.add(uid)
            start = item.decoded("DTSTART")
            if not isinstance(start, date):
                raise ValueError("Invalid DTSTART")
            if (isinstance(start, datetime) and not start.tzinfo
                    and item["DTSTART"].params.get("TZID")):
                raise ValueError("Unrecognized DTSTART timezone")
            if "DTEND" in item and "DURATION" in item:
                raise ValueError("Both DTEND and DURATION")
            if "DTEND" in item:
                end = item.decoded("DTEND")
            else:
                duration = item.decoded("DURATION") if "DURATION" in item else (
                    timedelta(0) if isinstance(start, datetime) else timedelta(days=1)
                )
                if not isinstance(duration, timedelta):
                    raise ValueError("Invalid DURATION")
                if not isinstance(start, datetime) and duration.seconds:
                    raise ValueError("All-day duration must use whole days")
                end = start + duration
            if type(start) is not type(end):
                raise ValueError("Start/end value types differ")
            if ("DTEND" in item and isinstance(end, datetime) and not end.tzinfo
                    and item["DTEND"].params.get("TZID")):
                raise ValueError("Unrecognized DTEND timezone")
            if isinstance(start, datetime):
                start = (start if start.tzinfo else start.replace(tzinfo=zone)).astimezone(zone)
                end = (end if end.tzinfo else end.replace(tzinfo=zone)).astimezone(zone)
                # Compare instants across daylight saving transitions.
                if end.timestamp() < start.timestamp():
                    raise ValueError("End precedes start")
            elif end <= start:
                raise ValueError("All-day end must follow start")
            events.append(ADEEvent(
                uid, str(item.get("SUMMARY", "")), start, end,
                str(item.get("LOCATION", "")), str(item.get("DESCRIPTION", "")),
                str(item.get("STATUS", "")),
            ))
        return sorted(events, key=lambda event: (
            event.start.isoformat(), event.uid,
        ))
    except ADEError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ADEError("Malformed ICS calendar: check event dates and required fields.") from None


def event_fingerprint(events: list[ADEEvent]) -> str:
    """Compare timetable content independently of ordering/export timestamps."""
    records = []
    for event in events:
        record = event.to_dict()
        # ADE adds this volatile export footer to every description. Preserve
        # the raw description in JSON but exclude only this exact footer here.
        record["description"] = re.sub(
            r"(?:\r?\n)?\(Exporté le:\d{2}/\d{2}/\d{4} \d{2}:\d{2}\)\s*\Z",
            "", record["description"],
        )
        records.append(record)
    records.sort(key=lambda item: item["uid"])
    payload = json.dumps(records, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return sha256(payload).hexdigest()
