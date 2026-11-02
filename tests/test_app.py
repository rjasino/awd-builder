import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from awd_builder.app import setup_speckit  # noqa: E402
from awd_builder.lib import WorkflowError  # noqa: E402


class AppScaffoldIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.target = Path(self.temp.name)
        (self.target / ".specify").mkdir()
        self.commands = []

    def tearDown(self):
        self.temp.cleanup()

    def installed_state(self, args, _cwd):
        self.commands.append(args[1:])
        if args[1:] == ["integration", "status", "--json"]:
            return SimpleNamespace(stdout=json.dumps({"installed_integrations": ["claude"]}))
        if args[1:] == ["extension", "list", "--json"]:
            return SimpleNamespace(stdout=json.dumps([{"id": "assess"}]))
        return SimpleNamespace(stdout="")

    def test_rerun_does_not_reinstall_existing_integration_or_extension(self):
        with patch("awd_builder.app.shutil.which", return_value="specify"), \
                patch("awd_builder.app.run_checked", side_effect=self.installed_state), \
                redirect_stdout(StringIO()):
            setup_speckit("claude", ["assess"], self.target, dry_run=False)
            setup_speckit("claude", ["assess"], self.target, dry_run=False)

        self.assertEqual(self.commands, [
            ["integration", "status", "--json"],
            ["extension", "list", "--json"],
            ["integration", "status", "--json"],
            ["extension", "list", "--json"],
        ])

    def test_rerun_installs_only_missing_extensions(self):
        with patch("awd_builder.app.shutil.which", return_value="specify"), \
                patch("awd_builder.app.run_checked", side_effect=self.installed_state), \
                redirect_stdout(StringIO()):
            setup_speckit("claude", ["assess", "bug"], self.target, dry_run=False)

        self.assertIn(["extension", "add", "bug"], self.commands)
        self.assertNotIn(["extension", "add", "assess"], self.commands)
        self.assertNotIn(["integration", "install", "claude"], self.commands)

    def test_dry_run_reports_unknown_state_when_specify_is_unavailable(self):
        with patch("awd_builder.app.shutil.which", return_value=None), redirect_stdout(StringIO()) as output:
            setup_speckit("claude", ["assess"], self.target, dry_run=True)

        self.assertIn("cannot inspect installed integrations or extensions", output.getvalue())
        self.assertNotIn("would run: specify integration install", output.getvalue())
        self.assertNotIn("would run: specify extension add", output.getvalue())

    def test_unreadable_existing_state_fails_safely_without_reinitializing(self):
        def fail_status(args, _cwd):
            self.commands.append(args[1:])
            raise WorkflowError("status failed")

        with patch("awd_builder.app.shutil.which", return_value="specify"), \
                patch("awd_builder.app.run_checked", side_effect=fail_status), redirect_stdout(StringIO()):
            with self.assertRaisesRegex(WorkflowError, "no re-initialization was attempted"):
                setup_speckit("claude", ["assess"], self.target, dry_run=False)

        self.assertEqual(self.commands, [["integration", "status", "--json"]])


if __name__ == "__main__":
    unittest.main()
