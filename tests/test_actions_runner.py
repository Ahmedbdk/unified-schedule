from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ActionsRunnerTests(unittest.TestCase):
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
