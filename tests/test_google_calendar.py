"""Google preview and read-only access tests; all API/OAuth calls are mocked."""

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, datetime
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from google.auth.exceptions import RefreshError

from unified_schedule.events import Event
from unified_schedule.google_preview import build_preview, event_key, event_payload
from unified_schedule.integrations.google_calendar import (
    SCOPES, GoogleCalendarError, get_credentials, list_calendars, list_managed_events,
)
from unified_schedule.storage import import_events


def example():
    return Event("ade", "example", "Class", datetime.fromisoformat("2026-10-12T14:00:00+02:00"),
                 datetime.fromisoformat("2026-10-12T16:00:00+02:00"))


def remote(event):
    return {**event_payload(event), "id": "google-example"}


class PreviewTests(unittest.TestCase):
    def test_create_then_unchanged_then_update(self):
        event = example()
        self.assertEqual(build_preview([event], [], remote_checked=True)["counts"], {"create": 1})
        self.assertEqual(build_preview([event], [remote(event)], remote_checked=True)["counts"], {"unchanged": 1})
        result = build_preview([replace(event, title="New title")], [remote(event)], remote_checked=True)
        self.assertEqual(result["counts"], {"update": 1})
        self.assertEqual(result["items"][0]["google_event_id"], "google-example")
        self.assertTrue(result["read_only"])

    def test_identity_survives_changed_times_but_is_source_specific(self):
        event = example()
        self.assertEqual(event_key(event), event_key(replace(event, title="Other")))
        self.assertNotEqual(event_key(event), event_key(replace(event, source="workforce")))

    def test_equivalent_remote_timezone_offsets_are_unchanged(self):
        event = example()
        stored = remote(event)
        stored["start"] = {"dateTime": "2026-10-12T14:00:00+02:00", "timeZone": "Europe/Paris"}
        stored["end"] = {"dateTime": "2026-10-12T16:00:00+02:00"}
        self.assertEqual(build_preview([event], [stored], remote_checked=True)["counts"], {"unchanged": 1})

    def test_all_day_payload_preserves_exclusive_end(self):
        day = Event("ade", "day", "Day", date(2026, 10, 12), date(2026, 10, 13))
        payload = event_payload(day)
        self.assertEqual(payload["start"], {"date": "2026-10-12"})
        self.assertEqual(payload["end"], {"date": "2026-10-13"})

    def test_cancelled_and_zero_duration_are_not_created(self):
        cancelled = replace(example(), status="CANCELLED")
        instant = replace(example(), source_id="instant", end=example().start)
        result = build_preview([cancelled, instant], [], remote_checked=True)
        self.assertEqual(result["counts"], {"skip": 2})
        self.assertEqual(build_preview([cancelled], [remote(example())], remote_checked=True)["counts"], {"cancel": 1})

    def test_unmanaged_events_are_ignored_and_missing_local_events_not_deleted(self):
        event = example()
        unmanaged = {"id": "personal", "summary": "Personal event"}
        self.assertEqual(build_preview([event], [unmanaged], remote_checked=True)["counts"], {"create": 1})
        self.assertEqual(build_preview([], [remote(event)], remote_checked=True)["items"], [])

    def test_duplicate_managed_ids_and_recurring_managed_events_fail(self):
        event = example()
        for entries in ([remote(event), remote(event)], [{**remote(event), "recurrence": ["RRULE:FREQ=WEEKLY"]}]):
            with self.subTest(entries=entries), self.assertRaises(GoogleCalendarError):
                build_preview([event], entries, remote_checked=True)

    def test_export_footer_does_not_trigger_update(self):
        event = replace(example(), description="Group A\n(Exporté le:10/10/2026 12:56)")
        self.assertEqual(event_payload(event)["description"], "Group A")
        later = replace(event, description=event.description.replace("12:56", "12:57"))
        self.assertEqual(build_preview([later], [remote(event)], remote_checked=True)["counts"], {"unchanged": 1})


class AccessTests(unittest.TestCase):
    def test_scopes_are_read_only(self):
        self.assertTrue(all(scope.endswith(".readonly") for scope in SCOPES))

    def test_missing_token_requires_explicit_authorization(self):
        with TemporaryDirectory() as directory, patch("unified_schedule.integrations.google_calendar.InstalledAppFlow") as flow:
            with self.assertRaisesRegex(GoogleCalendarError, "authorization is required"):
                get_credentials(token_path=Path(directory) / "token.json")
            flow.from_client_config.assert_not_called()

    def test_missing_desktop_client_has_setup_instruction(self):
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(GoogleCalendarError, "Desktop app"):
                get_credentials(authorize=True, token_path=Path(directory) / "token.json", client_path=Path(directory) / "client.json")

    def test_refreshes_saved_token_and_does_not_open_browser(self):
        with TemporaryDirectory() as directory, \
                patch("unified_schedule.integrations.google_calendar.Credentials") as credentials_type, \
                patch("unified_schedule.integrations.google_calendar.Request"), \
                patch("unified_schedule.integrations.google_calendar.InstalledAppFlow") as flow:
            token = Path(directory) / "token.json"
            token.write_text(json.dumps({"scopes": SCOPES}))
            credentials = credentials_type.from_authorized_user_info.return_value
            credentials.expired = True
            credentials.refresh_token = "dummy"
            credentials.valid = True
            credentials.to_json.return_value = json.dumps({"scopes": SCOPES})
            self.assertIs(get_credentials(token_path=token), credentials)
            credentials.refresh.assert_called_once()
            flow.from_client_config.assert_not_called()
            self.assertEqual(list(token.parent.glob("*.tmp")), [])

    def test_revoked_refresh_requires_reauthorization(self):
        with TemporaryDirectory() as directory, \
                patch("unified_schedule.integrations.google_calendar.Credentials") as credentials_type, \
                patch("unified_schedule.integrations.google_calendar.Request"):
            token = Path(directory) / "token.json"
            token.write_text(json.dumps({"scopes": SCOPES}))
            credentials = credentials_type.from_authorized_user_info.return_value
            credentials.expired = True
            credentials.refresh_token = "dummy"
            credentials.refresh.side_effect = RefreshError("dummy-private-data")
            with self.assertRaises(GoogleCalendarError) as caught:
                get_credentials(token_path=token)
            self.assertNotIn("dummy-private-data", str(caught.exception))

    def test_read_only_lists_follow_all_pages(self):
        service = MagicMock()
        service.calendarList.return_value.list.return_value.execute.side_effect = [
            {"items": [{"id": "first"}], "nextPageToken": "next"}, {"items": [{"id": "second"}]},
        ]
        self.assertEqual(len(list_calendars(service)), 2)
        service.events.return_value.list.return_value.execute.side_effect = [
            {"items": [{"id": "one"}], "nextPageToken": "next"}, {"items": [{"id": "two"}]},
        ]
        self.assertEqual(len(list_managed_events(service, "selected")), 2)
        call = service.events.return_value.list.call_args.kwargs
        self.assertEqual(call["pageToken"], "next")
        self.assertEqual(call["privateExtendedProperty"], ["unified_schedule_app=unified-schedule"])
        service.events.return_value.insert.assert_not_called()
        service.events.return_value.update.assert_not_called()
        service.events.return_value.delete.assert_not_called()

    def test_offline_command_never_contacts_google(self):
        from unified_schedule.google_calendar import main
        with TemporaryDirectory() as directory:
            database, output = Path(directory) / "calendar.sqlite3", Path(directory) / "plan.json"
            import_events(database, [example()])
            with patch("sys.argv", ["google", "preview", "--offline", "--from", "2026-10-10", "--output", str(output)]), \
                    patch.dict("os.environ", {"DATABASE_PATH": str(database), "APP_TIMEZONE": "Europe/Paris"}), \
                    patch("unified_schedule.google_calendar.calendar_service") as service, redirect_stdout(StringIO()):
                self.assertEqual(main(), 0)
            service.assert_not_called()
            plan = json.loads(output.read_text())
            self.assertFalse(plan["remote_checked"])
            self.assertEqual(plan["counts"], {"create": 1})


class SyncTests(unittest.TestCase):
    @patch("unified_schedule.google_sync.time.sleep")
    def test_rate_limits_retry_but_permissions_do_not(self, sleep):
        from googleapiclient.errors import HttpError
        from httplib2 import Response
        from unified_schedule.google_sync import execute_write
        def failure(reason):
            return HttpError(Response({"status": "403"}), json.dumps({"error": {"errors": [{"reason": reason}]}}).encode())
        request = MagicMock()
        request.execute.side_effect = [failure("rateLimitExceeded"), {"id": "ok"}]
        self.assertEqual(execute_write(request), {"id": "ok"})
        sleep.assert_called_once()
        request.execute.side_effect = failure("insufficientPermissions")
        sleep.reset_mock()
        with self.assertRaises(HttpError):
            execute_write(request)
        sleep.assert_not_called()

    @patch("unified_schedule.google_sync.time.sleep")
    def test_retries_are_bounded(self, sleep):
        from googleapiclient.errors import HttpError
        from httplib2 import Response
        from unified_schedule.google_sync import execute_write
        request = MagicMock()
        request.execute.side_effect = HttpError(Response({"status": "429"}), b'{}')
        with self.assertRaises(HttpError):
            execute_write(request)
        self.assertEqual(request.execute.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    def test_create_uses_stable_google_id_then_rerun_does_not_write(self):
        from unified_schedule.google_sync import apply_plan
        service = MagicMock()
        event = example()
        plan = build_preview([event], [], remote_checked=True)
        self.assertEqual(apply_plan(service, "selected", plan), {"create": 1})
        body = service.events.return_value.insert.call_args.kwargs["body"]
        self.assertEqual(body["id"], "us" + event_key(event))
        service.reset_mock()
        self.assertEqual(apply_plan(service, "selected", build_preview([event], [body], remote_checked=True)), {"unchanged": 1})
        service.events.return_value.insert.assert_not_called()
        service.events.return_value.patch.assert_not_called()

    def test_updates_and_explicit_cancellations_patch_managed_ids_only(self):
        from unified_schedule.google_sync import apply_plan
        service = MagicMock()
        event = example()
        for changed in (replace(event, title="Updated"), replace(event, status="CANCELLED")):
            apply_plan(service, "selected", build_preview([changed], [remote(event)], remote_checked=True))
            self.assertEqual(service.events.return_value.patch.call_args.kwargs["eventId"], "google-example")
        self.assertEqual(service.events.return_value.patch.call_args.kwargs["body"], {"status": "cancelled"})
        service.events.return_value.delete.assert_not_called()

    def test_offline_plan_rejected_before_writes(self):
        from unified_schedule.google_sync import apply_plan
        service = MagicMock()
        with self.assertRaises(GoogleCalendarError):
            apply_plan(service, "selected", build_preview([example()], [], remote_checked=False))
        service.events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
