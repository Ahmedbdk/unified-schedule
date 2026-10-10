"""Verify orchestration ordering and failure isolation without network access."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from unified_schedule.sync import main


class PipelineTests(unittest.TestCase):
    def run_pipeline(self, arguments, fail=None):
        calls = []
        def step(label, module, args):
            calls.append((module, args))
            if len(calls) == fail:
                return False
            if "--output" in args and module in {"unified_schedule", "unified_schedule.workforce"}:
                output = Path(args[args.index("--output") + 1])
                output.write_text("{}")
                if module == "unified_schedule":
                    output.with_suffix(".ics").write_text("fixture")
            return True
        previous = Path.cwd()
        with TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch("sys.argv", ["sync", *arguments]), patch("unified_schedule.sync.run_step", side_effect=step):
                    result = main()
            finally:
                os.chdir(previous)
        return result, calls

    def test_source_failure_stops_before_import_and_google(self):
        result, calls = self.run_pipeline([], fail=2)
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 2)

    def test_conflict_command_failure_stops_before_google(self):
        result, calls = self.run_pipeline([], fail=4)
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 4)

    def test_success_runs_all_steps_with_noninteractive_and_preview(self):
        result, calls = self.run_pipeline(["--non-interactive", "--preview", "--weeks", "3"])
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 5)
        self.assertIn("--non-interactive", calls[1][1])
        self.assertEqual(calls[-1][1], ["preview"])

    def test_default_applies_google_sync(self):
        result, calls = self.run_pipeline([])
        self.assertEqual(result, 0)
        self.assertEqual(calls[-1][1], ["sync"])
