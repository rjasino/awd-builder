import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from awd_builder.evals import DEFAULT_RESULTS_FILE, run  # noqa: E402


class EvalResultTests(unittest.TestCase):
    def make_project(self, target):
        (target / "workflow-plan.yaml").write_text(
            "name: sample\ntool: opencode\nagents:\n  - name: planner\n    description: Plans work\n",
            encoding="utf-8",
        )
        evals_dir = target / "evals"
        evals_dir.mkdir()
        (evals_dir / "routing.yaml").write_text(
            "cases:\n"
            "  - id: planning\n"
            "    prompt: Plan a feature\n"
            "    expected: agent/planner\n"
            "  - id: unrelated\n"
            "    prompt: Tell me a joke\n"
            "    expected: none\n",
            encoding="utf-8",
        )

    def make_args(self, target, **overrides):
        values = {
            "path": str(target),
            "plan": "workflow-plan.yaml",
            "evals": "evals/routing.yaml",
            "only": [],
            "timeout": 30,
            "dry_run": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_run_saves_case_outputs_and_summary_even_when_a_case_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            responses = iter((
                (0, "ROUTE: agent/planner\n", ""),
                (0, "ROUTE: skill/planner\n", "agent warning"),
            ))

            with patch("awd_builder.evals.run_agent", side_effect=lambda *args, **kwargs: next(responses)), \
                    redirect_stdout(StringIO()):
                result = run(self.make_args(target))

            self.assertEqual(result, 1)
            results_path = target / DEFAULT_RESULTS_FILE
            payload = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["format"], "awd-builder-routing-eval-results")
            self.assertEqual(payload["summary"], {"total": 2, "passed": 1, "failed": 1})
            self.assertEqual(payload["results"][0]["actual"], "agent/planner")
            self.assertTrue(payload["results"][0]["passed"])
            self.assertEqual(payload["results"][1]["actual"], "skill/planner")
            self.assertFalse(payload["results"][1]["passed"])
            self.assertEqual(payload["results"][1]["stderr"], "agent warning")
            self.assertTrue(payload["run_at"].endswith("Z"))

    def test_dry_run_does_not_write_results(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            with redirect_stdout(StringIO()):
                result = run(self.make_args(target, dry_run=True))

            self.assertEqual(result, 0)
            self.assertFalse((target / DEFAULT_RESULTS_FILE).exists())

    def test_results_output_cannot_overwrite_eval_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            evals_path = target / "evals/routing.yaml"
            original = evals_path.read_text(encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = run(self.make_args(target, output="evals/routing.yaml"))

            self.assertEqual(result, 2)
            self.assertEqual(evals_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
