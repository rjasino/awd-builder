import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from awd_builder.cli import build_parser, main  # noqa: E402


class CliDefaultTargetTests(unittest.TestCase):
    def test_scaffold_app_and_evals_default_to_current_directory(self):
        parser = build_parser()
        commands = (
            ["scaffold", "init"],
            ["scaffold", "run"],
            ["app", "init"],
            ["app", "run"],
            ["evals", "init"],
            ["evals", "run"],
            ["overrides", "init", "--harness", "opencode", "--agent", "planner"],
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(parser.parse_args(command).path, ".")

    def test_legacy_evals_path_invocation_maps_to_run(self):
        captured = []
        with patch("awd_builder.evals.run", side_effect=lambda args: captured.append(args) or 0):
            self.assertEqual(main(["evals", "my-project", "--dry-run"]), 0)

        self.assertEqual(captured[0].path, "my-project")
        self.assertTrue(captured[0].dry_run)


if __name__ == "__main__":
    unittest.main()
