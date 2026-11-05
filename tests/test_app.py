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

from awd_builder.app import app_integration_keys, ensure_tools, setup_speckit, validate_app_plan  # noqa: E402
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

    def test_tools_always_upgrade_spec_kit_even_when_already_on_path(self):
        calls = []

        def run(args, _cwd):
            calls.append(args)
            return SimpleNamespace(stdout="uv-bin" if args[1:3] == ["tool", "dir"] else "")

        with patch("awd_builder.app.shutil.which", return_value="uv.exe"), \
                patch("awd_builder.app.find_executable", side_effect=lambda name: f"{name}.exe"), \
                patch("awd_builder.app.run_checked", side_effect=run), \
                patch("awd_builder.app.add_to_path"), redirect_stdout(StringIO()):
            ensure_tools(dry_run=False)

        self.assertEqual(calls[0], ["uv.exe", "tool", "install", "--upgrade", "specify-cli"])
        self.assertEqual(calls[1], ["uv.exe", "tool", "dir", "--bin"])

    def test_tools_dry_run_reports_latest_spec_kit_upgrade(self):
        with patch("awd_builder.app.shutil.which", return_value="uv.exe"), \
                patch("awd_builder.app.run_checked") as run, redirect_stdout(StringIO()) as output:
            ensure_tools(dry_run=True)

        self.assertIn("uv tool install --upgrade specify-cli (latest)", output.getvalue())
        run.assert_not_called()

    def test_rerun_does_not_reinstall_existing_integration_or_extension(self):
        with patch("awd_builder.app.shutil.which", return_value="specify"), \
                patch("awd_builder.app.run_checked", side_effect=self.installed_state), \
                redirect_stdout(StringIO()):
            setup_speckit("claude", ["assess"], self.target, dry_run=False)
            setup_speckit("claude", ["assess"], self.target, dry_run=False)

        self.assertEqual(self.commands, [
            ["integration", "status", "--json"],
            ["extension", "list", "--json"],
            ["integration", "use", "claude"],
            ["integration", "status", "--json"],
            ["extension", "list", "--json"],
            ["integration", "use", "claude"],
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

    def test_app_plan_accepts_multiple_harnesses_and_maps_spec_kit_keys(self):
        plan = {
            "name": "sample",
            "harnesses": ["claude-code", "codex", "github-copilot", "cursor"],
            "extensions": [],
        }
        validate_app_plan(plan)
        self.assertEqual(app_integration_keys(plan), ["claude", "codex", "copilot", "cursor-agent"])

    def test_new_project_initializes_first_harness_and_installs_the_rest(self):
        (self.target / ".specify").rmdir()
        with patch("awd_builder.app.shutil.which", return_value="specify"), \
                patch("awd_builder.app.run_checked", side_effect=self.installed_state), \
                redirect_stdout(StringIO()):
            setup_speckit(["claude", "codex"], ["assess"], self.target, dry_run=False)

        self.assertIn(["init", "--here", "--integration", "claude", "--force", "--non-interactive"], self.commands)
        self.assertIn(["integration", "install", "codex"], self.commands)
        self.assertIn(["extension", "add", "assess"], self.commands)

    def test_extensions_are_registered_for_every_selected_integration(self):
        with patch("awd_builder.app.shutil.which", return_value="specify"), \
                patch("awd_builder.app.run_checked", side_effect=self.installed_state), \
                redirect_stdout(StringIO()):
            setup_speckit(["opencode", "claude", "codex"], ["assess", "bug"], self.target, dry_run=False)

        self.assertIn(["extension", "add", "bug"], self.commands)
        self.assertLess(self.commands.index(["integration", "use", "opencode"]),
                        self.commands.index(["extension", "add", "bug"]))
        self.assertIn(["integration", "use", "claude"], self.commands)
        self.assertIn(["integration", "use", "codex"], self.commands)
        self.assertEqual(self.commands[-1], ["integration", "use", "opencode"])


if __name__ == "__main__":
    unittest.main()
