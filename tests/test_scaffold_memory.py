import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from awd_builder.lib import (  # noqa: E402
    MEMORY_FILE,
    MEMORY_GITIGNORE,
    MEMORY_SKILL_NAME,
    TOOLS,
    WorkflowError,
)
from awd_builder.scaffold import (  # noqa: E402
    build_prompt,
    ensure_gitignore,
    install_memory_files,
    scaffold,
)


class MemoryScaffoldTests(unittest.TestCase):
    def test_installs_memory_for_each_supported_tool(self):
        for tool_name in ("claude-code", "opencode"):
            with self.subTest(tool=tool_name), tempfile.TemporaryDirectory() as temp:
                target = Path(temp)
                (target / ".gitignore").write_text("build/\n", encoding="utf-8")

                with redirect_stdout(StringIO()):
                    install_memory_files(target, TOOLS[tool_name], dry_run=False)

                tool = TOOLS[tool_name]
                self.assertTrue((target / tool["skills_dir"] / MEMORY_SKILL_NAME / "SKILL.md").is_file())
                self.assertTrue((target / tool["commands_dir"] / "memory.md").is_file())
                self.assertEqual(
                    json.loads((target / MEMORY_FILE).read_text(encoding="utf-8")),
                    {"version": 1, "memories": []},
                )
                ignore_text = (target / ".gitignore").read_text(encoding="utf-8")
                self.assertIn("build/", ignore_text)
                self.assertIn(MEMORY_GITIGNORE, ignore_text)

    def test_re_run_preserves_user_memory_and_customized_builtin_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            tool = TOOLS["claude-code"]
            with redirect_stdout(StringIO()):
                install_memory_files(target, tool, dry_run=False)

            memory_file = target / MEMORY_FILE
            memory_file.write_text('{"version": 1, "memories": [{"id": "keep-me"}]}', encoding="utf-8")
            skill_file = target / tool["skills_dir"] / MEMORY_SKILL_NAME / "SKILL.md"
            skill_file.write_text("customized skill", encoding="utf-8")
            command_file = target / tool["commands_dir"] / "memory.md"
            command_file.write_text("customized command", encoding="utf-8")

            with redirect_stdout(StringIO()):
                install_memory_files(target, tool, dry_run=False)

            self.assertIn("keep-me", memory_file.read_text(encoding="utf-8"))
            self.assertEqual(skill_file.read_text(encoding="utf-8"), "customized skill")
            self.assertEqual(command_file.read_text(encoding="utf-8"), "customized command")
            self.assertEqual((target / ".gitignore").read_text(encoding="utf-8").count(MEMORY_GITIGNORE), 1)

    def test_gitignore_is_added_without_replacing_existing_rules_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            ignore = target / ".gitignore"
            ignore.write_text("# keep me\n*.log", encoding="utf-8")

            self.assertTrue(ensure_gitignore(target))
            result = ignore.read_text(encoding="utf-8")
            self.assertIn("# keep me\n*.log", result)
            self.assertTrue(result.endswith(f"{MEMORY_GITIGNORE}\n"))
            self.assertFalse(ensure_gitignore(target))

    def test_dry_run_does_not_create_memory_files_or_gitignore(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            with redirect_stdout(StringIO()) as output:
                install_memory_files(target, TOOLS["opencode"], dry_run=True)

            self.assertIn("would install /memory command", output.getvalue())
            self.assertFalse((target / ".gitignore").exists())
            self.assertFalse((target / MEMORY_FILE).exists())

    def test_agent_prompt_requires_consent_based_memory_and_skill_use(self):
        prompt, _ = build_prompt(
            "agent",
            {"name": "planner", "description": "Plans work", "instructions": "Make a plan."},
            "claude-code",
        )
        self.assertIn("workflow-memory", prompt)
        self.assertIn("skills` frontmatter", prompt)
        self.assertIn("ask the user whether it should be saved", prompt)
        self.assertIn("Never save anything without explicit approval", prompt)

    def test_bundled_skill_and_command_cover_all_memory_operations(self):
        skill = (Path(__file__).resolve().parents[1] / "src/awd_builder/skills/workflow-memory/SKILL.md").read_text(
            encoding="utf-8"
        )
        command = (Path(__file__).resolve().parents[1] / "src/awd_builder/commands/memory.md").read_text(
            encoding="utf-8"
        )
        for operation in ("remember", "recall", "forget", "compact", "export", "import"):
            with self.subTest(operation=operation):
                self.assertIn(operation, skill)
                self.assertIn(operation, command)
        self.assertIn('"format": "awd-builder-workflow-memory"', skill)
        self.assertIn("Do not save unless the user explicitly agrees", skill)

    def test_reserved_memory_component_names_fail_before_creating_project_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            plan = {"tool": "claude-code", "commands": [{"name": "memory", "description": "custom"}]}
            with self.assertRaisesRegex(WorkflowError, "reserved"):
                scaffold(plan, target, dry_run=False)
            self.assertFalse((target / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
