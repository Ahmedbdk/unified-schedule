"""Shared calendar events and adapters for validated local integration snapshots."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path


class EventError(ValueError):
    """An event or integration snapshot is invalid."""


@dataclass(frozen=True)
class Event:
    source: str
    source_id: str
    title: str
    start: date | datetime
    end: date | datetime
    location: str = ""
    description: str = ""
    status: str = ""

    def __post_init__(self):
        if self.source not in {"ade", "workforce"} or not isinstance(self.source_id, str) or not self.source_id.strip():
            raise EventError("Event requires a supported source and a nonempty source ID.")
        if any(not isinstance(value, str) for value in (self.title, self.location, self.description, self.status)):
            raise EventError("Event text fields must be strings.")
        if not isinstance(self.start, date) or type(self.start) is not type(self.end):
            raise EventError("Event start/end must both be dates or both be datetimes.")
        if isinstance(self.start, datetime):
            if self.start.utcoffset() is None or self.end.utcoffset() is None:
                raise EventError("Timed events must include timezone offsets.")
            start, end = self.start.astimezone(timezone.utc), self.end.astimezone(timezone.utc)
            if end < start:
                raise EventError("Event end precedes start.")
            object.__setattr__(self, "start", start)
            object.__setattr__(self, "end", end)
        elif self.end <= self.start:
            raise EventError("All-day end dates must be exclusive and follow the start.")

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)

    def to_dict(self) -> dict:
        return {
            "uid": f"{self.source}:{self.source_id}", "source": self.source,
            "source_id": self.source_id, "title": self.title,
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "all_day": self.all_day, "location": self.location,
            "description": self.description, "status": self.status,
        }


def read_snapshot(path: Path, expected_source: str) -> list[Event]:
    """Validate a full export before allowing any database modification."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("source") != {"ade": "ADE", "workforce": "Workforce"}[expected_source]:
            raise EventError("Snapshot source does not match the requested integration.")
        list_key, count_key = ("events", "event_count") if expected_source == "ade" else ("shifts", "shift_count")
        records = data[list_key]
        if not isinstance(records, list) or type(data.get(count_key)) is not int or data[count_key] != len(records):
            raise EventError("Snapshot event count is missing or inconsistent.")
        result, seen = [], set()
        for record in records:
            if not isinstance(record, dict):
                raise EventError("Invalid event record in snapshot.")
            all_day = record.get("all_day", False)
            if type(all_day) is not bool or (expected_source == "workforce" and all_day):
                raise EventError("Invalid all-day flag.")
            parse = date.fromisoformat if all_day else datetime.fromisoformat
            event = Event(
                source=expected_source,
                source_id=record["uid"] if expected_source == "ade" else record["schedule_id"],
                title=record.get("summary", "") if expected_source == "ade" else record["role"],
                start=parse(record["start"]), end=parse(record["end"]),
                location=record.get("location", ""),
                description=record.get("description", "") if expected_source == "ade" else record.get("label", ""),
                status=record.get("status", ""),
            )
            if event.source_id in seen:
                raise EventError("Duplicate source ID in snapshot.")
            seen.add(event.source_id)
            result.append(event)
        return result
    except EventError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError):
        raise EventError("Malformed integration snapshot; check required fields and timestamps.") from None
