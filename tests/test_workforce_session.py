"""Session tests use dummy state, never real login cookies."""

from contextlib import redirect_stdout
from datetime import date
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from unified_schedule.integrations.workforce import WorkforceError, WorkforceSessionExpired
from unified_schedule.workforce_session import _load_state, _save_state, schedule_session


WEEK = date(2026, 10, 5)
STATE = {"cookies": [], "origins": []}


def setup_browser():
    browser = MagicMock()
    context = browser.new_context.return_value
    context.storage_state.return_value = STATE
    page = context.new_page.return_value
    page.url = "https://eu.workforce.com/mobile_app/schedules"
    page.locator.return_value.get_attribute.return_value = (
        "https://eu.workforce.com/mobile_app/schedules/me/2026-10-05/list"
    )
    return browser, context


class SessionTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"WORKFORCE_EMAIL": "", "WORKFORCE_PASSWORD": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def test_configured_credentials_log_in_without_prompt(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            playwright = MagicMock()
            browser, context = setup_browser()
            playwright.chromium.launch.return_value = browser
            with patch.dict(os.environ, {"WORKFORCE_EMAIL": "user@example.invalid", "WORKFORCE_PASSWORD": "dummy-password"}), \
                    patch("builtins.input") as prompt, \
                    patch("unified_schedule.workforce_session.fetch_week", return_value=[]), redirect_stdout(StringIO()):
                with schedule_session(playwright, "Europe/Paris", WEEK, session_path=path) as (active, _):
                    self.assertIs(active, context)
            prompt.assert_not_called()
            playwright.chromium.launch.assert_called_once_with(headless=False)
            page = context.new_page.return_value
            page.get_by_placeholder.assert_any_call("Email", exact=True)
            page.get_by_placeholder.assert_any_call("Password", exact=True)
            page.get_by_placeholder.return_value.fill.assert_any_call("dummy-password")
            check_url = page.wait_for_url.call_args.args[0]
            self.assertFalse(check_url("https://eu.workforce.com/mobile_app/login?error=true"))
            self.assertFalse(check_url("https://another.example/schedules"))
            self.assertTrue(check_url("https://eu.workforce.com/mobile_app/schedules"))
            self.assertEqual(json.loads(path.read_text()), STATE)
            browser.close.assert_called_once()

    def test_expired_session_renews_using_credentials(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            path.write_text(json.dumps(STATE))
            playwright = MagicMock()
            cached, _ = setup_browser()
            automatic, _ = setup_browser()
            playwright.chromium.launch.side_effect = [cached, automatic]
            with patch.dict(os.environ, {"WORKFORCE_EMAIL": "user@example.invalid", "WORKFORCE_PASSWORD": "dummy-password"}), \
                    patch("builtins.input") as prompt, \
                    patch("unified_schedule.workforce_session.fetch_week",
                          side_effect=[WorkforceSessionExpired("Expired"), []]), redirect_stdout(StringIO()):
                with schedule_session(playwright, "Europe/Paris", WEEK, non_interactive=True, session_path=path):
                    pass
            prompt.assert_not_called()
            self.assertEqual([call.kwargs["headless"] for call in playwright.chromium.launch.call_args_list], [True, True])
            cached.close.assert_called_once()
            automatic.close.assert_called_once()

    def test_failed_automatic_login_does_not_print_credentials_or_save_state(self):
        from playwright.sync_api import TimeoutError as LoginTimeout
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            playwright = MagicMock()
            browser, context = setup_browser()
            playwright.chromium.launch.return_value = browser
            context.new_page.return_value.wait_for_url.side_effect = LoginTimeout("dummy-password")
            output = StringIO()
            with patch.dict(os.environ, {"WORKFORCE_EMAIL": "user@example.invalid", "WORKFORCE_PASSWORD": "dummy-password"}), \
                    patch("builtins.input") as prompt, redirect_stdout(output):
                with self.assertRaises(WorkforceSessionExpired):
                    with schedule_session(playwright, "Europe/Paris", WEEK, non_interactive=True, session_path=path):
                        self.fail("Must not continue after failed login")
            prompt.assert_not_called()
            self.assertFalse(path.exists())
            self.assertNotIn("dummy-password", output.getvalue())
            self.assertNotIn("user@example.invalid", output.getvalue())
            browser.close.assert_called_once()

    def test_verification_completes_in_same_browser_and_saves_session(self):
        from playwright.sync_api import TimeoutError as LoginTimeout
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            playwright = MagicMock()
            automatic, automatic_context = setup_browser()
            automatic_context.new_page.return_value.wait_for_url.side_effect = LoginTimeout("Challenge")
            playwright.chromium.launch.return_value = automatic
            with patch.dict(os.environ, {"WORKFORCE_EMAIL": "user@example.invalid", "WORKFORCE_PASSWORD": "dummy-password"}), \
                    patch("builtins.input", return_value="") as prompt, \
                    patch("unified_schedule.workforce_session.fetch_week", return_value=[]), redirect_stdout(StringIO()):
                with schedule_session(playwright, "Europe/Paris", WEEK, session_path=path) as (active, _):
                    self.assertIs(active, automatic_context)
            prompt.assert_called_once()
            automatic.close.assert_called_once()
            playwright.chromium.launch.assert_called_once_with(headless=False)
            self.assertEqual(json.loads(path.read_text()), STATE)

    def test_credentials_never_submitted_to_unexpected_host(self):
        with TemporaryDirectory() as directory:
            playwright = MagicMock()
            browser, context = setup_browser()
            context.new_page.return_value.url = "https://another.example/login"
            playwright.chromium.launch.return_value = browser
            with patch.dict(os.environ, {"WORKFORCE_EMAIL": "user@example.invalid", "WORKFORCE_PASSWORD": "dummy-password"}), \
                    redirect_stdout(StringIO()):
                with self.assertRaisesRegex(WorkforceError, "credentials were not submitted"):
                    with schedule_session(playwright, "Europe/Paris", WEEK, session_path=Path(directory) / "workforce.json"):
                        self.fail("Unexpected host must abort")
            context.new_page.return_value.get_by_placeholder.assert_not_called()

    def test_partial_credential_configuration_is_an_error(self):
        with TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"WORKFORCE_EMAIL": "user@example.invalid"}):
            playwright = MagicMock()
            with self.assertRaisesRegex(WorkforceError, "Set both"):
                with schedule_session(playwright, "Europe/Paris", WEEK, session_path=Path(directory) / "workforce.json"):
                    self.fail("Partial credentials must not trigger a login")
            playwright.chromium.launch.assert_not_called()

    def test_first_login_saves_state(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".auth/workforce.json"
            playwright = MagicMock()
            browser, context = setup_browser()
            playwright.chromium.launch.return_value = browser
            with patch("builtins.input", return_value="") as prompt, \
                    patch("unified_schedule.workforce_session.fetch_week", return_value=[]), redirect_stdout(StringIO()):
                with schedule_session(playwright, "Europe/Paris", WEEK, session_path=path) as (active, first):
                    self.assertIs(active, context)
                    self.assertEqual(first, [])
                    self.assertEqual(json.loads(path.read_text()), STATE)
            prompt.assert_called_once()
            playwright.chromium.launch.assert_called_once_with(headless=False)
            browser.close.assert_called_once()

    def test_valid_session_reused_headlessly_without_prompt(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            path.write_text(json.dumps(STATE))
            playwright = MagicMock()
            browser, context = setup_browser()
            playwright.chromium.launch.return_value = browser
            with patch("builtins.input") as prompt, \
                    patch("unified_schedule.workforce_session.fetch_week", return_value=[]), redirect_stdout(StringIO()):
                with schedule_session(playwright, "Europe/Paris", WEEK, session_path=path) as (active, _):
                    self.assertIs(active, context)
            prompt.assert_not_called()
            playwright.chromium.launch.assert_called_once_with(headless=True)
            browser.new_context.assert_called_once_with(timezone_id="Europe/Paris", storage_state=STATE)
            context.new_page.assert_not_called()
            browser.close.assert_called_once()

    def test_expired_session_falls_back_to_manual_login(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            path.write_text(json.dumps(STATE))
            playwright = MagicMock()
            cached, _ = setup_browser()
            manual, manual_context = setup_browser()
            playwright.chromium.launch.side_effect = [cached, manual]
            with patch("builtins.input", return_value="") as prompt, \
                    patch("unified_schedule.workforce_session.fetch_week",
                          side_effect=[WorkforceSessionExpired("Login required"), []]), redirect_stdout(StringIO()):
                with schedule_session(playwright, "Europe/Paris", WEEK, session_path=path) as (active, _):
                    self.assertIs(active, manual_context)
            prompt.assert_called_once()
            self.assertEqual([call.kwargs["headless"] for call in playwright.chromium.launch.call_args_list], [True, False])
            cached.close.assert_called_once()
            manual.close.assert_called_once()

    def test_non_interactive_missing_or_expired_session_never_prompts(self):
        for existing in (False, True):
            with self.subTest(existing=existing), TemporaryDirectory() as directory:
                path = Path(directory) / "workforce.json"
                if existing:
                    path.write_text(json.dumps(STATE))
                playwright = MagicMock()
                browser, _ = setup_browser()
                playwright.chromium.launch.return_value = browser
                with patch("builtins.input") as prompt, \
                        patch("unified_schedule.workforce_session.fetch_week",
                              side_effect=WorkforceSessionExpired("Login required")), redirect_stdout(StringIO()):
                    with self.assertRaises(WorkforceSessionExpired):
                        with schedule_session(playwright, "Europe/Paris", WEEK,
                                              non_interactive=True, session_path=path):
                            self.fail("Must not yield an unauthenticated context")
                prompt.assert_not_called()
                if existing:
                    playwright.chromium.launch.assert_called_once_with(headless=True)
                    browser.close.assert_called_once()
                else:
                    playwright.chromium.launch.assert_not_called()

    def test_parsing_failure_does_not_trigger_relogin(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            path.write_text(json.dumps(STATE))
            playwright = MagicMock()
            browser, _ = setup_browser()
            playwright.chromium.launch.return_value = browser
            with patch("builtins.input") as prompt, \
                    patch("unified_schedule.workforce_session.fetch_week", side_effect=WorkforceError("Layout changed")):
                with self.assertRaisesRegex(WorkforceError, "Layout changed"):
                    with schedule_session(playwright, "Europe/Paris", WEEK, session_path=path):
                        self.fail("Must not yield after a parsing error")
            prompt.assert_not_called()
            playwright.chromium.launch.assert_called_once_with(headless=True)
            browser.close.assert_called_once()

    def test_force_login_ignores_saved_state(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            path.write_text(json.dumps(STATE))
            playwright = MagicMock()
            browser, _ = setup_browser()
            playwright.chromium.launch.return_value = browser
            with patch("builtins.input", return_value=""), \
                    patch("unified_schedule.workforce_session._load_state") as load, \
                    patch("unified_schedule.workforce_session.fetch_week", return_value=[]), redirect_stdout(StringIO()):
                with schedule_session(playwright, "Europe/Paris", WEEK, force_login=True, session_path=path):
                    pass
            load.assert_not_called()
            playwright.chromium.launch.assert_called_once_with(headless=False)

    def test_invalid_state_is_not_printed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            path.write_text("invalid dummy cookie content")
            output = StringIO()
            with redirect_stdout(output):
                self.assertIsNone(_load_state(path))
            self.assertNotIn("dummy cookie content", output.getvalue())

    def test_failed_save_preserves_existing_state_and_removes_temp_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workforce.json"
            path.write_text(json.dumps(STATE))
            context = MagicMock()
            context.storage_state.return_value = {"invalid": object()}
            with self.assertRaises(TypeError):
                _save_state(context, path)
            self.assertEqual(json.loads(path.read_text()), STATE)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
