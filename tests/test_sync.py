import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from awd_builder.lib import CANONICAL_AGENTS, CANONICAL_COMMANDS, CANONICAL_SKILLS, WorkflowError  # noqa: E402
from awd_builder.sync import sync_workflow  # noqa: E402


class SyncTests(unittest.TestCase):
    def make_canonical_workflow(self, target):
        agent = target / CANONICAL_AGENTS / "planner.md"
        agent.parent.mkdir(parents=True)
        agent.write_text(
            "---\nname: planner\ndescription: Plans features\nmodel: sonnet\n---\n\nPlan work carefully.\n",
            encoding="utf-8",
        )
        command = target / CANONICAL_COMMANDS / "review.md"
        command.parent.mkdir(parents=True)
        command.write_text(
            "---\nname: review\ndescription: Review changes\n---\n\nReview $ARGUMENTS.\n",
            encoding="utf-8",
        )
        skill = target / CANONICAL_SKILLS / "workflow-memory" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\nname: workflow-memory\ndescription: Manage private memory\n---\n\nRemember with consent.\n",
            encoding="utf-8",
        )

    def test_sync_creates_native_files_and_best_effort_fallbacks_for_all_harnesses(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_canonical_workflow(target)
            harnesses = ("opencode", "claude-code", "codex", "github-copilot", "pi", "cursor")

            with redirect_stdout(StringIO()):
                sync_workflow(target, harnesses)

            expected = (
                ".opencode/agents/planner.md",
                ".claude/agents/planner.md",
                ".codex/agents/planner.toml",
                ".github/agents/planner.agent.md",
                ".cursor/agents/planner.md",
                ".agents/skills/awd-agent-planner/SKILL.md",
                ".claude/skills/workflow-memory/SKILL.md",
                ".cursor/skills/workflow-memory/SKILL.md",
                ".github/prompts/review.prompt.md",
                ".pi/prompts/review.md",
                ".agents/skills/awd-command-review/SKILL.md",
            )
            for relative in expected:
                with self.subTest(path=relative):
                    self.assertTrue((target / relative).is_file())

            codex_agent = (target / ".codex/agents/planner.toml").read_text(encoding="utf-8")
            self.assertIn('name = "planner"', codex_agent)
            self.assertIn('developer_instructions = "Plan work carefully.\\n"', codex_agent)
            self.assertIn("Review $ARGUMENTS.", (target / ".github/prompts/review.prompt.md").read_text(encoding="utf-8"))

    def test_sync_is_repeatable_and_refuses_to_overwrite_unmanaged_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_canonical_workflow(target)
            destination = target / ".claude/agents/planner.md"
            destination.parent.mkdir(parents=True)
            destination.write_text("user-owned", encoding="utf-8")

            with self.assertRaisesRegex(WorkflowError, "unmanaged"):
                sync_workflow(target, ["claude-code"])

            with redirect_stdout(StringIO()):
                sync_workflow(target, ["claude-code"], force=True)
                expected = destination.read_bytes()
                sync_workflow(target, ["claude-code"])
            self.assertEqual(destination.read_bytes(), expected)

            destination.write_text("local edit", encoding="utf-8")
            with self.assertRaisesRegex(WorkflowError, "locally modified"):
                sync_workflow(target, ["claude-code"])


if __name__ == "__main__":
    unittest.main()
