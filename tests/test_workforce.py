"""Synthetic Workforce cards only; no real identifiers or account data."""

from datetime import date, datetime, timedelta
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from unified_schedule.integrations.workforce import (
    WorkforceError, WorkforceSessionExpired, fetch_week, parse_date_label, parse_schedule_html, personal_week,
)


WEEK = date(2026, 10, 5)
TODAY = date(2026, 10, 10)


def card(identifier="100", day="Aujourd'hui", hours="17:45 - 21:15", label="Role @ Test location"):
    return f'''<div class="relative flex flex-col">
      <div data-test-id="schedule_{identifier}" id="schedule_{identifier}">
        <div><span class="text-gray-800 font-bold text-xl grow">{day}</span>
          <span><div role="status" data-test="pill"><svg><path /></svg><span>3.5 hrs</span></div></span>
        </div>
        <div><svg><path /></svg><span class="text-base text-gray-800 font-bold leading-relaxed">{hours}</span></div>
        <div><span class="text-gray-800 text-sm">{label}</span></div>
      </div>
      <a href="/mobile_app/schedules/{identifier}?context=schedule"><span>View shift details</span></a>
    </div>'''


def frame(*cards, week=WEEK, source=True):
    src = f' src="https://eu.workforce.com/mobile_app/schedules/me/{week}/list"' if source else ""
    return f'<turbo-frame id="schedules"{src} complete>{"".join(cards)}</turbo-frame>'


def empty_frame(week=WEEK, source=True):
    return frame('''<div class="pb-2"><div class="w-full flex flex-col mt-10 mb-2">
      <img class="w-52 mx-auto" src="/empty.png">
      <div class="flex flex-col space-y-1 items-center my-4 px-4">
        <span class="text-xl text-gray-800 font-bold">Aucun quart de travail à venir</span>
        <span class="text-base text-gray-700 text-center">Une fois que votre travail sera planifié, vous verrez vos quarts de travail ici.</span>
      </div></div></div>
      <p class="px-4 py-1 text-sm text-gray-700 mb-2" data-test-id="holiday">Holiday notice</p>''',
      week=week, source=source)


class DateTests(unittest.TestCase):
    def test_relative_dates(self):
        for label, offset in (("Aujourd'hui", 0), ("Aujourd’hui", 0), ("Hier", -1), ("Demain", 1)):
            with self.subTest(label=label):
                self.assertEqual(parse_date_label(label, WEEK, TODAY), TODAY + timedelta(days=offset))

    def test_week_disambiguates_year(self):
        week = date(2026, 12, 28)
        self.assertEqual(parse_date_label("ven, 1 janv.", week, TODAY), date(2027, 1, 1))
        self.assertEqual(parse_date_label("lun, 28 déc. 2026", week, TODAY), week)

    def test_weekdays_and_out_of_week_dates(self):
        for label in ("lun, 11 oct.", "dim, 18 oct.", "11 oct. 2027", "unknown"):
            with self.subTest(label=label), self.assertRaises(WorkforceError):
                parse_date_label(label, WEEK, TODAY)
        with self.assertRaises(WorkforceError):
            parse_date_label("Demain", WEEK, date(2026, 10, 11))


class ParseTests(unittest.TestCase):
    def test_two_cards_keep_dates_and_ids_separate(self):
        html = frame(card(), card("101", "dim, 11 oct.", "19:45 - 23:30"))
        shifts = parse_schedule_html(html, WEEK, TODAY)
        self.assertEqual(len(shifts), 2)
        self.assertEqual(shifts[0].start.isoformat(), "2026-10-10T17:45:00+02:00")
        self.assertEqual(shifts[1].start.isoformat(), "2026-10-11T19:45:00+02:00")
        self.assertEqual(shifts[0].to_dict()["uid"], "workforce:100")
        self.assertEqual(shifts[0].role, "Role")
        self.assertEqual(shifts[0].location, "Test location")

    def test_html_entities_and_role_without_location(self):
        shift = parse_schedule_html(frame(card(label="Role &amp; Support")), WEEK, TODAY)[0]
        self.assertEqual(shift.role, "Role & Support")
        self.assertEqual(shift.location, "")

    def test_overnight_shift(self):
        shift = parse_schedule_html(frame(card(hours="22:00 – 02:30")), WEEK, TODAY)[0]
        self.assertEqual(shift.end.isoformat(), "2026-10-11T02:30:00+02:00")

    def test_am_pm_hours(self):
        cases = (
            ("7 PM - 11:30 PM", "19:00", "23:30", "2026-10-10"),
            ("12 AM - 12 PM", "00:00", "12:00", "2026-10-10"),
            ("11:30 PM - 1 AM", "23:30", "01:00", "2026-10-11"),
            ("7:15 am - 9 am", "07:15", "09:00", "2026-10-10"),
        )
        for hours, start, end, end_day in cases:
            with self.subTest(hours=hours):
                shift = parse_schedule_html(frame(card(hours=hours)), WEEK, TODAY)[0]
                self.assertEqual(shift.start.isoformat(), f"2026-10-10T{start}:00+02:00")
                self.assertEqual(shift.end.isoformat(), f"{end_day}T{end}:00+02:00")

    def test_invalid_am_pm_hours_fail(self):
        for hours in ("0 AM - 2 AM", "13 PM - 2 PM", "7:60 PM - 9 PM", "7 - 9"):
            with self.subTest(hours=hours), self.assertRaises(WorkforceError):
                parse_schedule_html(frame(card(hours=hours)), WEEK, TODAY)

    def test_winter_timezone_offset(self):
        week = date(2026, 11, 9)
        shift = parse_schedule_html(frame(card(day="lun, 9 nov."), week=week), week, TODAY)[0]
        self.assertEqual(shift.start.utcoffset(), timedelta(hours=1))

    def test_dst_ambiguity_and_nonexistent_time_fail(self):
        for week, label in ((date(2026, 10, 19), "dim, 25 oct."),
                            (date(2026, 3, 23), "dim, 29 mars")):
            with self.subTest(week=week), self.assertRaisesRegex(WorkforceError, "daylight saving"):
                parse_schedule_html(frame(card(day=label, hours="02:15 - 04:00"), week=week), week, TODAY)

    def test_zero_duration_or_invalid_time_fails(self):
        for hours in ("24:10 - 25:15", "17:45 - 17:45", "tbd", "17:60 - 21:15"):
            with self.subTest(hours=hours), self.assertRaises(WorkforceError):
                parse_schedule_html(frame(card(hours=hours)), WEEK, TODAY)

    def test_unknown_hours_error_identifies_shift_week_and_text(self):
        with self.assertRaises(WorkforceError) as caught:
            parse_schedule_html(frame(card(hours="Unknown format")), WEEK, TODAY)
        message = str(caught.exception)
        self.assertIn("shift 100", message)
        self.assertIn("2026-10-05", message)
        self.assertIn("'Unknown format'", message)

    def test_missing_fields_and_duplicate_ids_fail(self):
        for html in (
            frame(card().replace("text-xl", "changed")),
            frame(card(), card()),
            frame(card().replace('id="schedule_100"', 'id="wrong"')),
        ):
            with self.subTest(html=html), self.assertRaises(WorkforceError):
                parse_schedule_html(html, WEEK, TODAY)

    def test_wrong_week_team_frame_login_and_unknown_layouts_fail(self):
        for html in (
            frame(card(), week=date(2026, 10, 12)),
            frame(card()).replace("/schedules/me/", "/schedules/team/"),
            "<html><input name='password'></html>",
            frame(),
            frame("<p>Unexpected error</p>"),
            frame('<div id="schedule_100">Changed card layout</div>'),
            frame('<form><input name="password"></form>'),
        ):
            with self.subTest(html=html), self.assertRaises(WorkforceError):
                parse_schedule_html(html, WEEK, TODAY)

    def test_known_empty_state_with_holiday_is_an_empty_week(self):
        for html in (empty_frame(), empty_frame(source=False),
                     empty_frame(source=False).replace(" complete", "")):
            with self.subTest(html=html):
                self.assertEqual(parse_schedule_html(html, WEEK, TODAY), [])

    def test_loading_frame_is_not_an_empty_week(self):
        with self.assertRaises(WorkforceError):
            parse_schedule_html(empty_frame().replace(" complete", ""), WEEK, TODAY)

    def test_empty_heading_alone_or_changed_card_is_not_confirmed_empty(self):
        for html in (
            frame("<span>Aucun quart de travail à venir</span>"),
            empty_frame().replace("</turbo-frame>", '<div id="schedule_100">Unknown layout</div></turbo-frame>'),
        ):
            with self.subTest(html=html), self.assertRaises(WorkforceError):
                parse_schedule_html(html, WEEK, TODAY)

    def test_frame_only_response_and_outside_cards(self):
        html = card("999") + frame(card(), source=False)
        shifts = parse_schedule_html(html, WEEK, TODAY)
        self.assertEqual([shift.schedule_id for shift in shifts], ["100"])


class FetchTests(unittest.TestCase):
    def test_personal_frame_url(self):
        self.assertEqual(personal_week("https://eu.workforce.com/mobile_app/schedules/me/2026-10-05/list"), WEEK)
        for src in (
            "https://[",
            "https://another.example/mobile_app/schedules/me/2026-10-05/list",
            "http://eu.workforce.com/mobile_app/schedules/me/2026-10-05/list",
            "/mobile_app/schedules/team/2026-10-05/list",
            "/mobile_app/schedules/me/2026-10-06/list",
        ):
            with self.subTest(src=src), self.assertRaises(WorkforceError):
                personal_week(src)

    @patch("unified_schedule.integrations.workforce.datetime", wraps=datetime)
    def test_reads_personal_html_using_context_request(self, mock_datetime):
        mock_datetime.now.return_value = datetime(2026, 10, 10)
        context = MagicMock()
        response = context.request.get.return_value
        response.status = 200
        response.text.return_value = frame(card(), source=False)
        shifts = fetch_week(context, WEEK)
        self.assertEqual(len(shifts), 1)
        self.assertEqual(context.request.get.call_args.args[0],
                         "https://eu.workforce.com/mobile_app/schedules/me/2026-10-05/list")
        self.assertEqual(context.request.get.call_args.kwargs["max_redirects"], 0)
        response.dispose.assert_called_once()

    def test_denied_and_login_redirects_fail(self):
        for status in (302, 401, 403, 500):
            context = MagicMock()
            response = context.request.get.return_value
            response.status = status
            response.headers = {}
            with self.subTest(status=status), self.assertRaisesRegex(WorkforceError, f"HTTP {status}"):
                fetch_week(context, WEEK)
            response.dispose.assert_called_once()

    def test_authentication_failures_are_distinct_from_access_denied(self):
        for status, location in ((401, ""), (302, "/mobile_app/login"), (303, "https://eu.workforce.com/login")):
            context = MagicMock()
            response = context.request.get.return_value
            response.status = status
            response.headers = {"location": location}
            with self.subTest(status=status), self.assertRaises(WorkforceSessionExpired):
                fetch_week(context, WEEK)
        with self.assertRaises(WorkforceSessionExpired):
            parse_schedule_html('<form><input type="password"></form>', WEEK, TODAY)


class CommandTests(unittest.TestCase):
    def run_command(self, args, responses):
        from unified_schedule.workforce import main
        with patch("sys.argv", ["workforce"] + args), \
                patch("playwright.sync_api.sync_playwright"), \
                patch("unified_schedule.workforce.schedule_session") as session, \
                patch("unified_schedule.workforce.fetch_week", side_effect=responses[1:]), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            session.return_value.__enter__.return_value = (MagicMock(), responses[0])
            result = main()
            session.return_value.__exit__.assert_called_once()
            return result

    def test_command_filters_past_shifts_and_writes_structured_json(self):
        shifts = parse_schedule_html(frame(card(), card("101", "dim, 11 oct.")), WEEK, TODAY)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "workforce.json"
            status = self.run_command(["--start", "2026-10-11", "--weeks", "1", "--output", str(output)], [shifts])
            self.assertEqual(status, 0)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["shift_count"], 1)
            self.assertEqual(data["shifts"][0]["schedule_id"], "101")
            self.assertEqual(data["end_date_exclusive"], "2026-10-12")
            self.assertNotIn("cookies", data)

    def test_first_empty_week_stops_and_saves_collected_shifts(self):
        shifts = parse_schedule_html(frame(card()), WEEK, TODAY)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "workforce.json"
            status = self.run_command(
                ["--start", "2026-10-10", "--output", str(output)],
                [shifts, [], AssertionError("Must not fetch after the first empty week")],
            )
            self.assertEqual(status, 0)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["shift_count"], 1)
            self.assertEqual(data["weeks_requested"], 4)
            self.assertEqual(data["weeks_checked"], 2)
            self.assertEqual(data["first_empty_week"], "2026-10-12")
            self.assertEqual(data["checked_end_date_exclusive"], "2026-10-19")
            self.assertEqual(data["stop_reason"], "empty_week")

    def test_empty_first_week_is_a_successful_zero_shift_export(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "workforce.json"
            status = self.run_command(["--start", "2026-10-10", "--output", str(output)], [[]])
            self.assertEqual(status, 0)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["shifts"], [])
            self.assertEqual(data["weeks_checked"], 1)
            self.assertEqual(data["stop_reason"], "empty_week")

    def test_later_week_failure_preserves_existing_export(self):
        shifts = parse_schedule_html(frame(card()), WEEK, TODAY)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "workforce.json"
            output.write_text("previous export", encoding="utf-8")
            status = self.run_command(
                ["--start", "2026-10-10", "--weeks", "2", "--output", str(output)],
                [shifts, WorkforceError("Unknown empty week")],
            )
            self.assertEqual(status, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous export")


if __name__ == "__main__":
    unittest.main()
