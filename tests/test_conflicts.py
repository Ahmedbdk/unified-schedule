"""Overlap boundaries and reporting, using synthetic events only."""

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, datetime
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from unified_schedule.conflicts import find_conflicts
from unified_schedule.events import Event, EventError
from unified_schedule.storage import import_events


def event(source, start, end, source_id="1", status=""):
    return Event(source, source_id, f"Example {source}", datetime.fromisoformat(start),
                 datetime.fromisoformat(end), status=status)


CLASS = event("ade", "2026-10-12T14:00:00+02:00", "2026-10-12T16:00:00+02:00")
SHIFT = event("workforce", "2026-10-12T15:00:00+02:00", "2026-10-12T18:00:00+02:00")


class ConflictTests(unittest.TestCase):
    def test_partial_overlap_and_json(self):
        match = find_conflicts([SHIFT, CLASS])[0]
        self.assertEqual(match.duration_minutes, 60)
        self.assertEqual(match.start.isoformat(), "2026-10-12T13:00:00+00:00")
        self.assertEqual(match.to_dict()["university"]["source"], "ade")
        self.assertEqual(match.to_dict()["work"]["source"], "workforce")

    def test_containment_and_identical_intervals(self):
        for work in (
            event("workforce", "2026-10-12T13:00:00+02:00", "2026-10-12T17:00:00+02:00"),
            replace(CLASS, source="workforce"),
        ):
            with self.subTest(work=work):
                self.assertEqual(find_conflicts([CLASS, work])[0].duration_minutes, 120)

    def test_back_to_back_separated_and_zero_duration_do_not_conflict(self):
        for work in (
            event("workforce", "2026-10-12T16:00:00+02:00", "2026-10-12T17:00:00+02:00"),
            event("workforce", "2026-10-12T12:00:00+02:00", "2026-10-12T14:00:00+02:00"),
            event("workforce", "2026-10-12T15:00:00+02:00", "2026-10-12T15:00:00+02:00"),
        ):
            with self.subTest(work=work):
                self.assertEqual(find_conflicts([CLASS, work]), [])

    def test_cancelled_events_excluded_from_both_sources(self):
        self.assertEqual(find_conflicts([replace(CLASS, status="CANCELLED"), SHIFT]), [])
        self.assertEqual(find_conflicts([CLASS, replace(SHIFT, status=" cancelled ")]), [])

    def test_same_source_events_are_not_compared(self):
        self.assertEqual(find_conflicts([CLASS, replace(SHIFT, source="ade")]), [])
        self.assertEqual(find_conflicts([]), [])

    def test_timezones_compared_as_instants(self):
        shift = event("workforce", "2026-10-12T13:00:00+00:00", "2026-10-12T16:00:00+00:00")
        self.assertEqual(find_conflicts([CLASS, shift])[0].duration_minutes, 60)

    def test_daylight_saving_elapsed_duration(self):
        lecture = event("ade", "2026-10-25T01:30:00+02:00", "2026-10-25T03:30:00+01:00")
        shift = replace(lecture, source="workforce")
        self.assertEqual(find_conflicts([lecture, shift])[0].duration_minutes, 180)

    def test_all_day_exclusive_end_and_local_timezone(self):
        day = Event("ade", "day", "Day", date(2026, 10, 12), date(2026, 10, 13))
        self.assertEqual(find_conflicts([day, SHIFT])[0].duration_minutes, 180)
        tomorrow = event("workforce", "2026-10-13T00:00:00+02:00", "2026-10-13T01:00:00+02:00")
        self.assertEqual(find_conflicts([day, tomorrow]), [])

    def test_filters_actual_overlap_not_only_event_dates(self):
        lecture = event("ade", "2026-10-12T22:00:00+02:00", "2026-10-13T00:30:00+02:00")
        shift = event("workforce", "2026-10-12T23:00:00+02:00", "2026-10-13T00:00:00+02:00")
        self.assertEqual(find_conflicts([lecture, shift], start_date=date(2026, 10, 13)), [])
        self.assertEqual(len(find_conflicts([lecture, shift], end_date=date(2026, 10, 13))), 1)
        self.assertEqual(find_conflicts([CLASS, SHIFT], end_date=date(2026, 10, 12)), [])
        with self.assertRaises(EventError):
            find_conflicts([], start_date=date(2026, 10, 13), end_date=date(2026, 10, 12))

    def test_one_pair_once_and_deterministic_order(self):
        second = replace(CLASS, source_id="2")
        matches = find_conflicts([second, SHIFT, CLASS])
        self.assertEqual([match.university.source_id for match in matches], ["1", "2"])

    def test_command_exports_all_matches_in_paris_time_without_changing_db(self):
        from unified_schedule.calendar import main
        with TemporaryDirectory() as directory:
            database, output = Path(directory) / "calendar.sqlite3", Path(directory) / "conflicts.json"
            import_events(database, [CLASS, replace(CLASS, source_id="2"), SHIFT])
            before = database.read_bytes()
            console = StringIO()
            with patch("sys.argv", ["calendar", "--database", str(database), "conflicts", "--limit", "1", "--output", str(output)]), \
                    patch.dict("os.environ", {"APP_TIMEZONE": "Europe/Paris"}), redirect_stdout(console):
                self.assertEqual(main(), 0)
            self.assertIn("2026-10-12T15:00:00+02:00", console.getvalue())
            self.assertIn("60 min overlap", console.getvalue())
            self.assertEqual(json.loads(output.read_text())["conflict_count"], 2)
            self.assertEqual(database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
