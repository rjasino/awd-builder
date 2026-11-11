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
            "---\nname: planner\ndescription: Plans features\nmodel: opencode/test-model\n---\n\nPlan work carefully.\n",
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

    def test_agent_overrides_add_harness_metadata_without_owning_instructions(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_canonical_workflow(target)
            override = target / ".awd-builder/overrides/opencode/agents/planner.yaml"
            override.parent.mkdir(parents=True)
            override.write_text(
                "mode: primary\n"
                "permissions:\n"
                "  - action: edit\n"
                '    resource: "*"\n'
                "    effect: deny\n"
                "steps: 8\n"
                "hidden: true\n"
                'color: "#ff6b6b"\n',
                encoding="utf-8",
            )

            with redirect_stdout(StringIO()):
                sync_workflow(target, ["opencode"])

            destination = target / ".opencode/agents/planner.md"
            first_output = destination.read_text(encoding="utf-8")
            self.assertIn('model: "opencode/test-model"', first_output)
            self.assertIn('mode: "primary"', first_output)
            self.assertIn(
                'permissions: [{"action": "edit", "resource": "*", "effect": "deny"}]',
                first_output,
            )
            self.assertIn("steps: 8", first_output)
            self.assertIn("hidden: true", first_output)
            self.assertIn('color: "#ff6b6b"', first_output)
            self.assertIn("Plan work carefully.", first_output)

            canonical = target / CANONICAL_AGENTS / "planner.md"
            canonical.write_text(
                canonical.read_text(encoding="utf-8").replace(
                    "Plan work carefully.", "Plan work carefully and verify."
                ),
                encoding="utf-8",
            )
            with redirect_stdout(StringIO()):
                sync_workflow(target, ["opencode"])

            updated_output = destination.read_text(encoding="utf-8")
            self.assertIn('mode: "primary"', updated_output)
            self.assertIn("Plan work carefully and verify.", updated_output)

    def test_opencode_overrides_reject_v1_fields_and_model(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_canonical_workflow(target)
            override = target / ".awd-builder/overrides/opencode/agents/planner.yaml"
            override.parent.mkdir(parents=True)

            for content, message in (
                ("temperature: 0.2\n", "deprecated OpenCode V1 fields"),
                ("tools:\n  write: true\n", "deprecated OpenCode V1 fields"),
                ("model: opencode/custom-model\n", "workflow-plan.yaml"),
                ("system: replace instructions\n", "unsupported OpenCode V2 fields"),
                ("unknown: value\n", "unsupported OpenCode V2 fields"),
            ):
                with self.subTest(content=content):
                    override.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(WorkflowError, message):
                        sync_workflow(target, ["opencode"])

    def test_opencode_agent_model_must_use_provider_model_format(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_canonical_workflow(target)
            canonical = target / CANONICAL_AGENTS / "planner.md"
            canonical.write_text(
                canonical.read_text(encoding="utf-8").replace(
                    "opencode/test-model", "sonnet"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(WorkflowError, "provider/model"):
                sync_workflow(target, ["opencode"])

    def test_codex_overrides_are_toml_fields_but_cannot_replace_instructions(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_canonical_workflow(target)
            override = target / ".awd-builder/overrides/codex/agents/planner.yaml"
            override.parent.mkdir(parents=True)
            override.write_text(
                'sandbox_mode: workspace-write\napproval_policy: "never"\nfeatures: [one, two]\n',
                encoding="utf-8",
            )

            with redirect_stdout(StringIO()):
                sync_workflow(target, ["codex"])
            output = (target / ".codex/agents/planner.toml").read_text(encoding="utf-8")
            self.assertIn('sandbox_mode = "workspace-write"', output)
            self.assertIn('approval_policy = "never"', output)
            self.assertIn('features = ["one", "two"]', output)
            self.assertIn('developer_instructions = "Plan work carefully.\\n"', output)

            override.write_text("developer_instructions: Replace canonical instructions\n", encoding="utf-8")
            with self.assertRaisesRegex(WorkflowError, "developer_instructions"):
                sync_workflow(target, ["codex"])


if __name__ == "__main__":
    unittest.main()
