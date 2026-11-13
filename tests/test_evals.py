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

from awd_builder.evals import (  # noqa: E402
    DEFAULT_RESULTS_FILE,
    DEFAULT_SUMMARY_FILE,
    init,
    load_cases,
    load_canonical_components,
    run,
)


class EvalResultTests(unittest.TestCase):
    def make_project(self, target):
        (target / "workflow-plan.yaml").write_text(
            "name: sample\ntool: opencode\nagents:\n  - name: planner\n    description: Stale plan description\n",
            encoding="utf-8",
        )
        canonical_agent = target / ".agents/agents/planner.md"
        canonical_agent.parent.mkdir(parents=True)
        canonical_agent.write_text(
            "---\nname: planner\ndescription: Current canonical planner description\n---\n\nPlan work.\n",
            encoding="utf-8",
        )
        canonical_skill = target / ".agents/skills/triage/SKILL.md"
        canonical_skill.parent.mkdir(parents=True)
        canonical_skill.write_text(
            "---\nname: Triage helper\ndescription: Current canonical triage description\n---\n\nTriage.\n",
            encoding="utf-8",
        )
        canonical_command = target / ".agents/commands/review.md"
        canonical_command.parent.mkdir(parents=True)
        canonical_command.write_text(
            "---\nname: review\ndescription: Review changes\n---\n\nReview.\n",
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
            "summary": DEFAULT_SUMMARY_FILE,
            "no_analysis": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def write_canonical_agent(self, target):
        agent = target / ".agents/agents/planner.md"
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_text(
            "---\nname: planner\ndescription: Canonical planner\n---\n\nPlan work.\n",
            encoding="utf-8",
        )
        return agent

    def test_run_saves_case_outputs_and_summary_even_when_a_case_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            responses = iter((
                (0, "ROUTE: agent/planner\n", ""),
                (0, "ROUTE: skill/triage\n", "agent warning"),
                (
                    0,
                    "### `unrelated`\n"
                    "- **Likely cause:** The prompt overlaps with a skill description.\n"
                    "- **Evidence:** The actual route was skill/planner.\n"
                    "- **Recommendation:** Make the descriptions more distinct.\n"
                    "\n## Recommended Changes\n"
                    "Update the skill description.\n",
                    "",
                ),
            ))

            with patch("awd_builder.evals.run_agent", side_effect=lambda *args, **kwargs: next(responses)) as agent, \
                    redirect_stdout(StringIO()):
                result = run(self.make_args(target))

            self.assertEqual(result, 1)
            results_path = target / DEFAULT_RESULTS_FILE
            payload = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["format"], "awd-builder-routing-eval-results")
            self.assertEqual(payload["summary"], {"total": 2, "passed": 1, "failed": 1})
            self.assertEqual(payload["results"][0]["actual"], "agent/planner")
            self.assertTrue(payload["results"][0]["passed"])
            self.assertEqual(payload["results"][1]["actual"], "skill/triage")
            self.assertFalse(payload["results"][1]["passed"])
            self.assertEqual(payload["results"][1]["stderr"], "agent warning")
            self.assertTrue(payload["run_at"].endswith("Z"))

            summary = (target / DEFAULT_SUMMARY_FILE).read_text(encoding="utf-8")
            self.assertIn("# Routing Eval Results", summary)
            self.assertIn("**FAILED** — 1 of 2 routing cases failed.", summary)
            self.assertIn("## Failure Analysis", summary)
            self.assertIn("The prompt overlaps with a skill description.", summary)
            self.assertIn("## Recommended Changes", summary)
            self.assertIn("## Failed Cases", summary)
            self.assertIn("### `unrelated`", summary)
            self.assertIn("- Expected: `none`", summary)
            self.assertIn("- Actual: `skill/triage`", summary)
            self.assertIn("| planning | PASS | agent/planner | agent/planner |", summary)
            self.assertIn("| unrelated | FAIL | none | skill/triage |", summary)
            routing_prompts = [call[0][1] for call in agent.call_args_list[:2]]
            self.assertTrue(all("agent/planner: Current canonical planner description" in prompt for prompt in routing_prompts))
            self.assertTrue(all("skill/triage: Current canonical triage description" in prompt for prompt in routing_prompts))
            self.assertTrue(all("command/review: Review changes" in prompt for prompt in routing_prompts))
            self.assertTrue(all("Stale plan description" not in prompt for prompt in routing_prompts))
            analysis_prompt = agent.call_args_list[2][0][1]
            self.assertIn("Current canonical triage description", analysis_prompt)

    def test_expected_routes_are_validated_against_canonical_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            eval_path = target / "evals/routing.yaml"
            eval_path.write_text(
                "cases:\n  - id: triage\n    prompt: Triage this request\n    expected: skill/triage\n",
                encoding="utf-8",
            )

            cases = load_cases(eval_path, load_canonical_components(target))

            self.assertEqual(cases[0]["expected"], "skill/triage")

    def test_failure_analysis_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            responses = iter((
                (0, "ROUTE: agent/planner\n", ""),
                (0, "ROUTE: skill/triage\n", ""),
            ))

            with patch("awd_builder.evals.run_agent", side_effect=lambda *args, **kwargs: next(responses)) as agent, \
                    redirect_stdout(StringIO()):
                result = run(self.make_args(target, no_analysis=True))

            self.assertEqual(result, 1)
            self.assertEqual(agent.call_count, 2)
            summary = (target / DEFAULT_SUMMARY_FILE).read_text(encoding="utf-8")
            self.assertNotIn("## Failure Analysis", summary)

    def test_failure_analysis_falls_back_when_generator_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            responses = iter((
                (0, "ROUTE: agent/planner\n", ""),
                (0, "ROUTE: skill/triage\n", ""),
                (1, "", "analysis failed"),
            ))

            with patch("awd_builder.evals.run_agent", side_effect=lambda *args, **kwargs: next(responses)), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = run(self.make_args(target))

            self.assertEqual(result, 1)
            summary = (target / DEFAULT_SUMMARY_FILE).read_text(encoding="utf-8")
            self.assertIn("_Failure analysis unavailable: analysis failed_", summary)
            self.assertIn("## Failed Cases", summary)

    def test_summary_reports_success_when_all_cases_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            responses = iter((
                (0, "ROUTE: agent/planner\n", ""),
                (0, "ROUTE: none\n", ""),
            ))

            with patch("awd_builder.evals.run_agent", side_effect=lambda *args, **kwargs: next(responses)), \
                    redirect_stdout(StringIO()):
                result = run(self.make_args(target))

            self.assertEqual(result, 0)
            summary = (target / DEFAULT_SUMMARY_FILE).read_text(encoding="utf-8")
            self.assertIn("All 2 routing cases completed successfully.", summary)
            self.assertNotIn("## Failed Cases", summary)
            self.assertIn("| planning | PASS | agent/planner | agent/planner |", summary)
            self.assertIn("| unrelated | PASS | none | none |", summary)

    def test_custom_summary_path_is_written(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            responses = iter((
                (0, "ROUTE: agent/planner\n", ""),
                (0, "ROUTE: none\n", ""),
            ))

            with patch("awd_builder.evals.run_agent", side_effect=lambda *args, **kwargs: next(responses)), \
                    redirect_stdout(StringIO()):
                result = run(self.make_args(target, summary="evals/custom-summary.md"))

            self.assertEqual(result, 0)
            self.assertTrue((target / "evals/custom-summary.md").is_file())
            self.assertFalse((target / DEFAULT_SUMMARY_FILE).exists())

    def test_dry_run_does_not_write_results(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            with redirect_stdout(StringIO()):
                result = run(self.make_args(target, dry_run=True))

            self.assertEqual(result, 0)
            self.assertFalse((target / DEFAULT_RESULTS_FILE).exists())
            self.assertFalse((target / DEFAULT_SUMMARY_FILE).exists())

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

    def test_summary_output_cannot_overwrite_eval_cases_or_results_json(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            evals_path = target / "evals/routing.yaml"
            original = evals_path.read_text(encoding="utf-8")

            for summary, output in (
                ("evals/routing.yaml", DEFAULT_RESULTS_FILE),
                (DEFAULT_RESULTS_FILE, DEFAULT_RESULTS_FILE),
            ):
                with self.subTest(summary=summary):
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        result = run(self.make_args(target, summary=summary, output=output))
                    self.assertEqual(result, 2)
                    self.assertEqual(evals_path.read_text(encoding="utf-8"), original)

    def test_init_generates_and_validates_routing_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            (target / "workflow-plan.yaml").write_text(
                "name: sample\ntool: opencode\nagents:\n  - name: planner\n    description: Plans work\n",
                encoding="utf-8",
            )
            self.write_canonical_agent(target)
            canonical_skill = target / ".agents/skills/triage/SKILL.md"
            canonical_skill.parent.mkdir(parents=True)
            canonical_skill.write_text(
                "---\nname: Triage helper\ndescription: Canonical triage\n---\n\nTriage.\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                path=str(target), plan="workflow-plan.yaml", force=False,
                timeout=30, dry_run=False,
            )

            def generate(_tool, _prompt, cwd, **_kwargs):
                self.assertIn(".agents/agents", _prompt)
                self.assertIn("canonical files", _prompt)
                self.assertIn(".agents/skills", _prompt)
                self.assertIn("skill/triage: Canonical triage", _prompt)
                self.assertIn(".agents/skills/eval-creator/SKILL.md", _prompt)
                evals_path = Path(cwd) / "evals/routing.yaml"
                evals_path.parent.mkdir(parents=True)
                evals_path.write_text(
                    "cases:\n  - id: triage-direct-1\n    prompt: Triage this request\n    expected: skill/triage\n",
                    encoding="utf-8",
                )
                return 0, "generated", ""

            with patch("awd_builder.evals.run_agent", side_effect=generate) as run_agent, \
                    redirect_stdout(StringIO()):
                result = init(args)

            self.assertEqual(result, 0)
            run_agent.assert_called_once()
            self.assertTrue((target / "evals/routing.yaml").is_file())

    def test_init_dry_run_does_not_call_agent_or_create_eval_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            (target / "workflow-plan.yaml").write_text(
                "name: sample\ntool: opencode\nagents: []\n", encoding="utf-8"
            )
            self.write_canonical_agent(target)
            args = SimpleNamespace(
                path=str(target), plan="workflow-plan.yaml", force=False,
                timeout=30, dry_run=True,
            )
            with patch("awd_builder.evals.run_agent") as run_agent, redirect_stdout(StringIO()) as output:
                result = init(args)

            self.assertEqual(result, 0)
            self.assertIn("eval-creator", output.getvalue())
            run_agent.assert_not_called()
            self.assertFalse((target / "evals/routing.yaml").exists())

    def test_init_does_not_overwrite_existing_eval_file_without_force(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            self.make_project(target)
            existing = (target / "evals/routing.yaml").read_text(encoding="utf-8")
            args = SimpleNamespace(
                path=str(target), plan="workflow-plan.yaml", force=False,
                timeout=30, dry_run=False,
            )
            with patch("awd_builder.evals.run_agent") as run_agent, \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = init(args)

            self.assertEqual(result, 2)
            run_agent.assert_not_called()
            self.assertEqual((target / "evals/routing.yaml").read_text(encoding="utf-8"), existing)


if __name__ == "__main__":
    unittest.main()
