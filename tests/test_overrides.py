import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from awd_builder.cli import main  # noqa: E402


class OverrideInitTests(unittest.TestCase):
    def test_creates_harness_starter_file_for_canonical_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            agents = target / ".agents/agents"
            agents.mkdir(parents=True)
            (agents / "planner.md").write_text(
                "---\nname: planner\ndescription: Plans work\n---\n\nPlan carefully.\n",
                encoding="utf-8",
            )

            original = Path.cwd()
            try:
                os.chdir(target)
                with redirect_stdout(StringIO()):
                    result = main(
                        [
                            "overrides",
                            "--harness",
                            "opencode",
                            "--agent",
                            "planner",
                        ]
                    )
            finally:
                os.chdir(original)

            destination = target / ".awd-builder/overrides/opencode/agents/planner.yaml"
            self.assertEqual(result, 0)
            self.assertTrue(destination.is_file())
            content = destination.read_text(encoding="utf-8")
            self.assertIn("Harness-specific metadata", content)
            self.assertIn("# mode: primary", content)
            self.assertIn("# permissions:", content)
            self.assertIn("#   - action: edit", content)
            self.assertIn("# steps: 8", content)
            self.assertIn("Set model on the agent in workflow-plan.yaml", content)
            self.assertNotIn("# temperature:", content)
            self.assertNotIn("# tools:", content)
            self.assertNotIn("# permission:", content)

    def test_does_not_overwrite_existing_override(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            agents = target / ".agents/agents"
            agents.mkdir(parents=True)
            (agents / "planner.md").write_text(
                "---\nname: planner\ndescription: Plans work\n---\n\nPlan carefully.\n",
                encoding="utf-8",
            )
            destination = target / ".awd-builder/overrides/opencode/agents/planner.yaml"
            destination.parent.mkdir(parents=True)
            destination.write_text("mode: primary\n", encoding="utf-8")

            original = Path.cwd()
            try:
                os.chdir(target)
                with redirect_stderr(StringIO()):
                    result = main(
                        [
                            "overrides",
                            "--harness",
                            "opencode",
                            "--agent",
                            "planner",
                        ]
                    )
            finally:
                os.chdir(original)

            self.assertEqual(result, 2)
            self.assertEqual(destination.read_text(encoding="utf-8"), "mode: primary\n")


if __name__ == "__main__":
    unittest.main()
