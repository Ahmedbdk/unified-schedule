"""Find positive overlaps between ADE events and Workforce shifts."""

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from unified_schedule.events import Event, EventError
from unified_schedule.storage import event_bounds


@dataclass(frozen=True)
class Conflict:
    university: Event
    work: Event
    start: datetime
    end: datetime

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "duration_minutes": self.duration_minutes,
            "university": self.university.to_dict(), "work": self.work.to_dict(),
        }


def find_conflicts(events: list[Event], *, timezone_name: str = "Europe/Paris",
                   start_date: date | None = None, end_date: date | None = None) -> list[Conflict]:
    """Report each ADE/Workforce pair once; endpoints are exclusive.

    Date filters select conflicts whose actual overlap intersects local days,
    without truncating the reported overlap. All-day events span local dates.
    """
    if start_date and end_date and end_date <= start_date:
        raise EventError("The exclusive end date must follow the start date.")
    zone = ZoneInfo(timezone_name)
    left = datetime.combine(start_date, time(), zone).timestamp() if start_date else None
    right = datetime.combine(end_date, time(), zone).timestamp() if end_date else None
    eligible = [event for event in events if event.status.strip().upper() != "CANCELLED"]
    university = [(event, event_bounds(event, zone)) for event in eligible if event.source == "ade"]
    work = [(event, event_bounds(event, zone)) for event in eligible if event.source == "workforce"]
    conflicts = []
    for lecture, (lecture_start, lecture_end) in university:
        for shift, (shift_start, shift_end) in work:
            begin = max(lecture_start, shift_start)
            finish = min(lecture_end, shift_end)
            if finish <= begin:
                continue
            if (left is not None and finish <= left) or (right is not None and begin >= right):
                continue
            conflicts.append(Conflict(
                lecture, shift, datetime.fromtimestamp(begin, timezone.utc),
                datetime.fromtimestamp(finish, timezone.utc),
            ))
    return sorted(conflicts, key=lambda conflict: (
        conflict.start, conflict.university.source_id, conflict.work.source_id,
    ))
