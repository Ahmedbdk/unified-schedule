from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ActionsRunnerTests(unittest.TestCase):
    def test_fallback_reports_stage_and_only_static_error_messages(self):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "run-actions.py"))
        output = StringIO()
        result = SimpleNamespace(
            returncode=1,
            stdout="1/5 — ADE\n2/5 — Workforce\nPRIVATE_EVENT_NAME",
            stderr="Error: The personal schedule frame is missing; check login and page layout.\nError: PRIVATE_TOKEN",
        )
        with patch("subprocess.run", return_value=result), redirect_stdout(output):
            self.assertEqual(namespace["main"](), 1)
        self.assertIn("Étape : Workforce", output.getvalue())
        self.assertIn("The personal schedule frame is missing", output.getvalue())
        self.assertNotIn("PRIVATE", output.getvalue())

    def test_known_failures_have_private_safe_diagnostics(self):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "run-actions.py"))
        cases = [
            ("Google authorization or token refresh failed", "GOOGLE_WRITE_TOKEN_JSON"),
            ("No usable session.", "WORKFORCE_STATE_JSON"),
            ("Login needs verification or corrected credentials.", "WORKFORCE_STATE_JSON"),
            ("ADE download failed", "Téléchargement ADE"),
            ("ADE download timed out", "Téléchargement ADE"),
            ("ADE returned HTTP 503; expected 200.", "ADE HTTP 503"),
            ("ADE did not return an ICS calendar", "calendrier ICS"),
            ("Configured calendar ID is not in your accessible calendar list.", "GOOGLE_*_CALENDAR_ID"),
            ("browser or schedule request failed", "Chromium"),
        ]
        for error, expected in cases:
            with self.subTest(error=error):
                output = StringIO()
                result = SimpleNamespace(returncode=1, stdout="PRIVATE_EVENT_NAME", stderr=error + " PRIVATE_TOKEN")
                with patch("subprocess.run", return_value=result), redirect_stdout(output):
                    self.assertEqual(namespace["main"](), 1)
                self.assertIn(expected, output.getvalue())
                self.assertNotIn("PRIVATE", output.getvalue())

    def test_remote_setup_blocks_missing_category_secrets(self):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "prepare-actions.py"))
        output = StringIO()
        with patch.dict("os.environ", {"GOOGLE_ADE_CALENDAR_ID": "old", "GOOGLE_WORKFORCE_CALENDAR_ID": "work"}, clear=True), redirect_stdout(output):
            self.assertEqual(namespace["main"](), 1)
        self.assertIn("GOOGLE_ADE_IA_CALENDAR_ID", output.getvalue())

    def test_http_diagnostic_preserves_code_without_private_output(self):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "run-actions.py"))
        output = StringIO()
        result = SimpleNamespace(returncode=1, stdout="PRIVATE_EVENT_NAME", stderr="Error: Google Calendar API returned HTTP 404 (unknown). PRIVATE_TOKEN")
        with patch("subprocess.run", return_value=result), redirect_stdout(output):
            self.assertEqual(namespace["main"](), 1)
        self.assertIn("HTTP 404 (unknown)", output.getvalue())
        self.assertNotIn("PRIVATE", output.getvalue())

    def test_unknown_reason_cannot_leak_into_annotation(self):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "run-actions.py"))
        output = StringIO()
        result = SimpleNamespace(returncode=1, stdout="", stderr="Google Calendar API returned HTTP 403 (PrivateSecret).")
        with patch("subprocess.run", return_value=result), redirect_stdout(output):
            namespace["main"]()
        self.assertNotIn("PrivateSecret", output.getvalue())
