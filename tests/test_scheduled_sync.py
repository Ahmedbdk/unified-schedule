from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from unified_schedule.scheduled_sync import main


class ScheduledSyncTests(unittest.TestCase):
    def test_unattended_failure_is_logged_and_returned(self):
        with TemporaryDirectory() as directory:
            fake_source = Path(directory) / "src" / "unified_schedule" / "scheduled_sync.py"
            with patch("unified_schedule.scheduled_sync.__file__", str(fake_source)), patch("unified_schedule.scheduled_sync.subprocess.run") as run:
                run.return_value = SimpleNamespace(returncode=1, stdout="ADE OK", stderr="Workforce session expired")
                self.assertEqual(main(), 1)
                self.assertIn("--non-interactive", run.call_args.args[0])
                self.assertEqual(run.call_args.kwargs["cwd"], Path(directory))
            log = (Path(directory) / "data" / "logs" / "sync.log").read_text(encoding="utf-8")
            self.assertIn("Workforce session expired", log)
            self.assertIn("Échec", log)
