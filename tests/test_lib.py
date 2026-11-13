import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from awd_builder.lib import run_agent  # noqa: E402


class RunAgentTests(unittest.TestCase):
    def test_opencode_automation_uses_builtin_build_agent(self):
        with patch("awd_builder.lib.find_executable", return_value="opencode"), \
                patch("awd_builder.lib._run", return_value=(0, "done", "")) as run:
            result = run_agent(
                "opencode",
                "Create the routing eval file.",
                Path.cwd(),
                write=True,
                timeout=30,
                model="opencode-go/model",
            )

        self.assertEqual(result, (0, "done", ""))
        args = run.call_args[0][0]
        self.assertEqual(args[:4], ["opencode", "run", "--agent", "build"])
        self.assertIn("--auto", args)
        self.assertIn("--model", args)

    def test_claude_code_invocation_is_unchanged(self):
        with patch("awd_builder.lib.find_executable", return_value="claude"), \
                patch("awd_builder.lib._run", return_value=(0, "done", "")) as run:
            result = run_agent(
                "claude-code",
                "Create the routing eval file.",
                Path.cwd(),
                write=True,
                timeout=30,
            )

        self.assertEqual(result, (0, "done", ""))
        args = run.call_args[0][0]
        self.assertNotIn("--agent", args)


if __name__ == "__main__":
    unittest.main()
