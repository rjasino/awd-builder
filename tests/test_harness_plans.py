import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from awd_builder.lib import WorkflowError, validate_plan, workflow_generator, workflow_harnesses  # noqa: E402


class HarnessPlanTests(unittest.TestCase):
    def test_multi_harness_plan_uses_separate_generator_and_targets(self):
        plan = {
            "name": "sample",
            "generator": "opencode",
            "harnesses": ["opencode", "claude-code", "codex", "github-copilot", "pi", "cursor"],
            "agents": [],
            "skills": [],
            "commands": [],
        }
        validate_plan(plan)
        self.assertEqual(workflow_generator(plan), "opencode")
        self.assertEqual(workflow_harnesses(plan), plan["harnesses"])

    def test_legacy_single_tool_plan_remains_supported(self):
        plan = {"name": "legacy", "tool": "claude-code", "agents": [], "skills": [], "commands": []}
        validate_plan(plan)
        self.assertEqual(workflow_generator(plan), "claude-code")
        self.assertEqual(workflow_harnesses(plan), ["claude-code"])

    def test_unknown_or_duplicate_harnesses_are_rejected(self):
        for harnesses in (["unknown"], ["codex", "codex"]):
            with self.subTest(harnesses=harnesses), self.assertRaises(WorkflowError):
                validate_plan({"name": "invalid", "generator": "claude-code", "harnesses": harnesses})


if __name__ == "__main__":
    unittest.main()
