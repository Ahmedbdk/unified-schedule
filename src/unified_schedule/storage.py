"""Small SQLite event store; no deletion inferred from limited source exports."""

from datetime import date, datetime, time, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from unified_schedule.events import Event, EventError


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    all_day INTEGER NOT NULL CHECK (all_day IN (0, 1)),
    location TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
"""


def _values(event: Event) -> tuple:
    return (event.source, event.source_id, event.title, event.start.isoformat(),
            event.end.isoformat(), int(event.all_day), event.location, event.description, event.status)


def import_events(path: Path, events: list[Event]) -> dict[str, int]:
    """Upsert a validated batch atomically; preserve events absent from it."""
    keys = [(event.source, event.source_id) for event in events]
    if len(set(keys)) != len(keys):
        raise EventError("Duplicate event identity in import batch.")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    try:
        with connection:
            connection.execute(SCHEMA)
            now = datetime.now(timezone.utc).isoformat()
            for event in events:
                values = _values(event)
                existing = connection.execute(
                    "SELECT source, source_id, title, start, end, all_day, location, description, status "
                    "FROM events WHERE source = ? AND source_id = ?", values[:2],
                ).fetchone()
                if existing is not None and tuple(existing) == values:
                    counts["unchanged"] += 1
                    continue
                connection.execute(
                    "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(source, source_id) DO UPDATE SET "
                    "title=excluded.title, start=excluded.start, end=excluded.end, "
                    "all_day=excluded.all_day, location=excluded.location, "
                    "description=excluded.description, status=excluded.status, updated_at=excluded.updated_at",
                    values + (now,),
                )
                counts["created" if existing is None else "updated"] += 1
        return counts
    finally:
        connection.close()


def list_events(path: Path, *, source: str | None = None, start_date: date | None = None,
                end_date: date | None = None, timezone_name: str = "Europe/Paris") -> list[Event]:
    """List chronologically; date filters include events overlapping local days."""
    zone = ZoneInfo(timezone_name)
    if start_date and end_date and end_date <= start_date:
        raise EventError("The exclusive end date must follow the start date.")
    if not path.is_file():
        raise EventError("Database not found. Run the calendar import command first.")
    # Read-only access prevents a list command from creating or modifying a DB.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT * FROM events" + (" WHERE source = ?" if source else ""),
            (source,) if source else (),
        ).fetchall()
    finally:
        connection.close()
    left = datetime.combine(start_date, time(), zone).timestamp() if start_date else None
    right = datetime.combine(end_date, time(), zone).timestamp() if end_date else None
    result = []
    for row in rows:
        parse = date.fromisoformat if row["all_day"] else datetime.fromisoformat
        event = Event(row["source"], row["source_id"], row["title"],
                      parse(row["start"]), parse(row["end"]),
                      row["location"], row["description"], row["status"])
        begin, finish = event_bounds(event, zone)
        if begin == finish:
            include = (left is None or begin >= left) and (right is None or begin < right)
        else:
            include = (left is None or finish > left) and (right is None or begin < right)
        if include:
            result.append(event)
    return sorted(result, key=lambda event: (event_bounds(event, zone)[0], event.source, event.source_id))


def event_bounds(event: Event, zone: ZoneInfo) -> tuple[float, float]:
    if event.all_day:
        return (datetime.combine(event.start, time(), zone).timestamp(),
                datetime.combine(event.end, time(), zone).timestamp())
    return event.start.timestamp(), event.end.timestamp()
