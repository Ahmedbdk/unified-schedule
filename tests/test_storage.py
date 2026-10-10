"""Shared event and SQLite behavior using synthetic snapshots and temporary DBs."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import date, datetime, timezone
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from unified_schedule.events import Event, EventError, read_snapshot
from unified_schedule.storage import import_events, list_events


def example(source="ade", source_id="example-1"):
    return Event(source, source_id, "Example event",
                 datetime.fromisoformat("2026-10-10T23:30:00+02:00"),
                 datetime.fromisoformat("2026-10-11T00:30:00+02:00"))


class EventTests(unittest.TestCase):
    def test_timed_events_normalize_to_utc(self):
        event = example()
        self.assertEqual(event.to_dict()["start"], "2026-10-10T21:30:00+00:00")
        self.assertEqual(event.start.tzinfo, timezone.utc)
        self.assertFalse(event.all_day)

    def test_all_day_dates_remain_dates(self):
        event = Event("ade", "day", "Day", date(2026, 10, 10), date(2026, 10, 11))
        self.assertTrue(event.all_day)
        self.assertEqual(event.to_dict()["end"], "2026-10-11")

    def test_invalid_event_fields(self):
        for changes in (
            {"source_id": ""}, {"source": "unknown"}, {"title": None},
            {"start": datetime(2026, 10, 10)},
            {"end": date(2026, 10, 11)},
            {"end": datetime.fromisoformat("2026-10-10T20:00:00+00:00")},
        ):
            with self.subTest(changes=changes), self.assertRaises(EventError):
                replace(example(), **changes)

    def test_snapshot_adapters(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps({"source": "ADE", "event_count": 1, "events": [{
                "uid": "class", "summary": "Class", "start": "2026-10-10",
                "end": "2026-10-11", "all_day": True, "status": "CANCELLED",
            }]}))
            self.assertEqual(read_snapshot(path, "ade")[0].status, "CANCELLED")
            path.write_text(json.dumps({"source": "Workforce", "shift_count": 1, "shifts": [{
                "schedule_id": "shift", "role": "Role", "label": "Role @ Location",
                "start": "2026-10-10T19:00:00+02:00", "end": "2026-10-10T23:30:00+02:00",
            }]}))
            event = read_snapshot(path, "workforce")[0]
            self.assertEqual(event.to_dict()["uid"], "workforce:shift")
            self.assertEqual(event.description, "Role @ Location")

    def test_bad_count_source_and_duplicate_snapshot_ids(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            row = {"uid": "class", "start": "2026-10-10", "end": "2026-10-11", "all_day": True}
            for data in (
                {"source": "Workforce", "event_count": 0, "events": []},
                {"source": "ADE", "event_count": 0, "events": [row]},
                {"source": "ADE", "event_count": 2, "events": [row, row]},
                {"source": "ADE", "event_count": 1, "events": [{**row, "all_day": "true"}]},
            ):
                path.write_text(json.dumps(data))
                with self.subTest(data=data), self.assertRaises(EventError):
                    read_snapshot(path, "ade")


class StorageTests(unittest.TestCase):
    def test_repeat_import_update_and_source_identity(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "calendar.sqlite3"
            events = [example(), example("workforce")]
            self.assertEqual(import_events(database, events), {"created": 2, "updated": 0, "unchanged": 0})
            self.assertEqual(import_events(database, events), {"created": 0, "updated": 0, "unchanged": 2})
            self.assertEqual(import_events(database, [replace(events[0], title="Moved class")]),
                             {"created": 0, "updated": 1, "unchanged": 0})
            stored = list_events(database)
            self.assertEqual(len(stored), 2)
            self.assertEqual(list_events(database, source="ade")[0].title, "Moved class")

    def test_missing_events_are_not_deleted(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "calendar.sqlite3"
            import_events(database, [example(), example(source_id="another")])
            import_events(database, [])
            import_events(database, [example()])
            self.assertEqual(len(list_events(database)), 2)

    def test_duplicate_batch_fails_before_creating_database(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "calendar.sqlite3"
            with self.assertRaises(EventError):
                import_events(database, [example(), example()])
            self.assertFalse(database.exists())

    def test_local_date_overlap_and_exclusive_boundaries(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "calendar.sqlite3"
            all_day = Event("ade", "day", "Day", date(2026, 10, 10), date(2026, 10, 11))
            instant = replace(example(), source_id="instant", start=example().end)
            import_events(database, [example(), all_day, instant])
            first = list_events(database, start_date=date(2026, 10, 10), end_date=date(2026, 10, 11))
            self.assertEqual({event.source_id for event in first}, {"example-1", "day"})
            second = list_events(database, start_date=date(2026, 10, 11), end_date=date(2026, 10, 12))
            self.assertEqual({event.source_id for event in second}, {"example-1", "instant"})
            self.assertEqual(list_events(database, start_date=date(2026, 10, 12)), [])

    def test_list_missing_database_does_not_create_it(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "missing.sqlite3"
            with self.assertRaises(EventError):
                list_events(database)
            self.assertFalse(database.exists())

    def test_cancelled_status_is_updated_and_retained(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "calendar.sqlite3"
            import_events(database, [example()])
            import_events(database, [replace(example(), status="CANCELLED")])
            self.assertEqual(list_events(database)[0].status, "CANCELLED")

    def test_invalid_second_snapshot_prevents_partial_import(self):
        from unified_schedule.calendar import main
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ade, workforce, database = root / "ade.json", root / "workforce.json", root / "calendar.sqlite3"
            ade.write_text(json.dumps({"source": "ADE", "events": [], "event_count": 0}))
            workforce.write_text("invalid JSON")
            with patch("sys.argv", ["calendar", "--database", str(database), "import", "--ade", str(ade), "--workforce", str(workforce)]), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(), 1)
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
