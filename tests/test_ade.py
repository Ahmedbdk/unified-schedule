"""Synthetic ICS fixtures only; tests never download personal calendars."""

from datetime import date, timedelta
import unittest
from unittest.mock import MagicMock, patch

import requests

from unified_schedule.integrations.ade import (
    ADEError, event_fingerprint, fetch_calendar, parse_calendar,
)


def calendar(*events):
    body = "\r\n".join("BEGIN:VEVENT\r\n" + event + "\r\nEND:VEVENT" for event in events)
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n" + body
            + "\r\nEND:VCALENDAR\r\n").encode()


TIMED = "UID:class-1\r\nDTSTART:20261109T121500Z\r\nDTEND:20261109T141500Z\r\nSUMMARY:Example"


class ParseTests(unittest.TestCase):
    def test_utc_to_paris_and_text_decoding(self):
        content = calendar(TIMED.replace("SUMMARY:Example", "SUMMARY:Cours\\, algo\r\n rithmes")
                           + "\r\nLOCATION:Room 1\r\nDESCRIPTION:First\\nSecond")
        event = parse_calendar(content)[0]
        self.assertEqual(event.start.isoformat(), "2026-11-09T13:15:00+01:00")
        self.assertEqual(event.summary, "Cours, algorithmes")
        self.assertEqual(event.description, "First\nSecond")
        self.assertFalse(event.all_day)

    def test_summer_offset(self):
        event = parse_calendar(calendar(TIMED.replace("20261109", "20260909")))[0]
        self.assertEqual(event.start.utcoffset(), timedelta(hours=2))

    def test_floating_and_explicit_local_times(self):
        for properties in (
            "DTSTART:20261109T121500\r\nDTEND:20261109T141500",
            "DTSTART;TZID=Europe/Paris:20261109T121500\r\nDTEND;TZID=Europe/Paris:20261109T141500",
        ):
            with self.subTest(properties=properties):
                event = parse_calendar(calendar("UID:x\r\n" + properties))[0]
                self.assertEqual(event.start.isoformat(), "2026-11-09T12:15:00+01:00")

    def test_all_day_exclusive_default_end(self):
        event = parse_calendar(calendar("UID:day\r\nDTSTART;VALUE=DATE:20261109"))[0]
        self.assertTrue(event.all_day)
        self.assertEqual(event.end, date(2026, 11, 10))
        self.assertEqual(event.to_dict()["start"], "2026-11-09")

    def test_duration_and_instant_defaults(self):
        for suffix, expected in (("", 0), ("\r\nDURATION:PT2H", 7200)):
            event = parse_calendar(calendar("UID:x\r\nDTSTART:20261109T121500Z" + suffix))[0]
            self.assertEqual((event.end - event.start).total_seconds(), expected)

    def test_invalid_events_fail_import(self):
        invalid = (
            "UID:x",  # missing start
            "DTSTART:20261109T121500Z",  # missing uid
            TIMED.replace("DTEND:20261109T141500Z", "DTEND:20261109T111500Z"),
            TIMED.replace("DTEND:20261109T141500Z", "DTEND;VALUE=DATE:20261110"),
            TIMED + "\r\nDURATION:PT2H",
            "UID:x\r\nDTSTART:garbage",
            "UID:x\r\nDTSTART;TZID=Unknown/Zone:20261109T121500",
        )
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(ADEError):
                parse_calendar(calendar(event))
        with self.assertRaises(ADEError):
            parse_calendar(calendar(TIMED, TIMED))

    def test_recurrence_is_explicitly_rejected(self):
        with self.assertRaisesRegex(ADEError, "recurrence"):
            parse_calendar(calendar(TIMED + "\r\nRRULE:FREQ=WEEKLY"))

    def test_empty_and_non_calendar_payloads(self):
        self.assertEqual(parse_calendar(calendar()), [])
        for payload in (b"<html>Error</html>", b"", b"BEGIN:VEVENT\r\nEND:VEVENT"):
            with self.subTest(payload=payload), self.assertRaises(ADEError):
                parse_calendar(payload)

    def test_fingerprint_ignores_export_metadata_and_order(self):
        other = TIMED.replace("class-1", "class-2")
        first = parse_calendar(calendar(TIMED + "\r\nDTSTAMP:20261010T100000Z", other))
        second = parse_calendar(calendar(other, TIMED + "\r\nDTSTAMP:20261010T110000Z"))
        self.assertEqual(event_fingerprint(first), event_fingerprint(second))
        changed = parse_calendar(calendar(TIMED.replace("Example", "New class"), other))
        self.assertNotEqual(event_fingerprint(first), event_fingerprint(changed))

    def test_fingerprint_ignores_only_ade_export_footer(self):
        description = "\r\nDESCRIPTION:Group A\\n(Exporté le:10/10/2026 12:56)"
        first = parse_calendar(calendar(TIMED + description))
        second = parse_calendar(calendar(TIMED + description.replace("12:56", "12:57")))
        self.assertEqual(event_fingerprint(first), event_fingerprint(second))
        self.assertIn("12:56", first[0].description)
        changed = parse_calendar(calendar(TIMED + description.replace("Group A", "Group B")))
        self.assertNotEqual(event_fingerprint(first), event_fingerprint(changed))


class DownloadTests(unittest.TestCase):
    @patch("unified_schedule.integrations.ade.requests.get")
    def test_download_headers_and_timeout(self, get):
        response = MagicMock(status_code=200, content=calendar(TIMED))
        response.headers = {"Content-Type": "text/calendar", "Set-Cookie": "private"}
        get.return_value.__enter__.return_value = response
        result = fetch_calendar("https://example.org/feed")
        self.assertEqual(result.content, calendar(TIMED))
        self.assertNotIn("Set-Cookie", result.headers)
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 30))

    @patch("unified_schedule.integrations.ade.requests.get")
    def test_http_html_and_connection_errors(self, get):
        response = MagicMock(status_code=403, content=b"denied")
        get.return_value.__enter__.return_value = response
        with self.assertRaisesRegex(ADEError, "HTTP 403"):
            fetch_calendar("https://example.org/private-token")
        response.status_code = 200
        response.content = b"<html>Login</html>"
        with self.assertRaisesRegex(ADEError, "ICS"):
            fetch_calendar("https://example.org/private-token")
        for error in (requests.Timeout("private-token"), requests.ConnectionError("private-token")):
            get.side_effect = error
            with self.assertRaises(ADEError) as caught:
                fetch_calendar("https://example.org/private-token")
            self.assertNotIn("private-token", str(caught.exception))

    def test_invalid_urls(self):
        for url in ("", "http://example.org", "https://user:pass@example.org", "https://["):
            with self.subTest(url=url), self.assertRaises(ADEError):
                fetch_calendar(url)


if __name__ == "__main__":
    unittest.main()
