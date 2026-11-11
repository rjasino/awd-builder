"""`awd-builder evals`: generate and run workflow-wide routing evals."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .lib import (
    EVAL_FILE,
    PLAN_FILE,
    WorkflowError,
    components,
    load_plan,
    load_yaml,
    run_agent,
    workflow_generator,
    workflow_harnesses,
)

DEFAULT_TIMEOUT = 300
DEFAULT_RESULTS_FILE = "evals/results.json"
DEFAULT_SUMMARY_FILE = "evals/results.md"
EXPECTED_PATTERN = re.compile(r"^(?:(agent|skill|command)/([a-z0-9]+(?:-[a-z0-9]+)*)|none)$")
ROUTE_PATTERN = re.compile(
    r"ROUTE:\s*(?:(agent|skill|command)/([a-z0-9]+(?:-[a-z0-9]+)*)|(none))",
    re.IGNORECASE,
)
ROUTING_PROMPT = """\
ROUTING TEST ONLY. Do not carry out the request below, do not use any tools, and do not create or edit files.

Decide which single agent, skill, or command in this project should handle the request. If none of them fits, choose none.

<request>
{prompt}
</request>

Reply with exactly one line and nothing else, in one of these forms:
ROUTE: agent/<name>
ROUTE: skill/<name>
ROUTE: command/<name>
ROUTE: none
"""
EVAL_CREATION_PROMPT = """\
Use the eval-creator skill in this project to create a comprehensive workflow-wide routing eval suite.

Read the workflow plan at `{plan}` and write exactly one file: `{evals}`.
Create parent folders as needed. Do not create, edit, or run anything else.
Follow the skill's case-generation guidance and YAML schema. Every expected route must refer to a component
in the plan (or be `none`). Make the prompts realistic and self-contained.
"""


def load_cases(evals_path, plan):
    data = load_yaml(evals_path)
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        raise WorkflowError(f"{evals_path} needs a non-empty 'cases' list")

    known = {f"{kind}/{item['name']}" for kind, item in components(plan)}
    ids = set()
    loaded = []
    for case in cases:
        if not isinstance(case, dict):
            raise WorkflowError("every case must be a mapping with 'id', 'prompt' and 'expected'")
        case_id = str(case.get("id") or "").strip()
        prompt = str(case.get("prompt") or "").strip()
        expected = str(case.get("expected") or "").strip().lower()
        if not case_id:
            raise WorkflowError("every case needs an 'id'")
        if case_id in ids:
            raise WorkflowError(f"duplicate case id '{case_id}'")
        ids.add(case_id)
        if not prompt:
            raise WorkflowError(f"case '{case_id}' needs a 'prompt'")
        if not EXPECTED_PATTERN.match(expected):
            raise WorkflowError(f"case '{case_id}': 'expected' must be agent/<name>, skill/<name>, or none")
        if expected != "none" and expected not in known:
            raise WorkflowError(f"case '{case_id}': '{expected}' is not defined in the plan")
        loaded.append({"id": case_id, "prompt": prompt, "expected": expected})
    return loaded


def parse_route(output):
    matches = list(ROUTE_PATTERN.finditer(output))
    if not matches:
        return None
    last = matches[-1]
    if last.group(3):
        return "none"
    return f"{last.group(1).lower()}/{last.group(2).lower()}"


def save_results(path, plan, evals_path, results):
    passed = sum(result["passed"] for result in results)
    payload = {
        "format": "awd-builder-routing-eval-results",
        "version": 1,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "workflow": plan["name"],
        "tool": workflow_generator(plan),
        "harnesses": workflow_harnesses(plan),
        "model": plan.get("model"),
        "evals_file": str(evals_path),
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "results": results,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as error:
        raise WorkflowError(f"could not save eval results to {path}: {error}") from error
    return payload


def _markdown_cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _indented_block(value):
    text = str(value).strip()
    if not text:
        return ""
    return "\n".join(f"    {line}" for line in text.splitlines())


def save_summary(path, payload):
    summary = payload["summary"]
    total = summary["total"]
    failed = summary["failed"]
    case_word = "case" if total == 1 else "cases"
    lines = [
        "# Routing Eval Results",
        "",
        f"- Workflow: `{payload['workflow']}`",
        f"- Generator: `{payload['tool']}`",
        f"- Harnesses: `{', '.join(payload['harnesses'])}`",
        f"- Model: `{payload['model'] or 'generator default'}`",
        f"- Run at: `{payload['run_at']}`",
        f"- Cases: `{total}` total, `{summary['passed']}` passed, `{failed}` failed",
        "",
        "## Status",
        "",
    ]
    if failed:
        lines.append(
            f"**FAILED** — {failed} of {total} routing {case_word} failed."
        )
    else:
        lines.append(
            f"All {total} routing {case_word} completed successfully."
        )

    failed_results = [result for result in payload["results"] if not result["passed"]]
    if failed_results:
        lines.extend(("", "## Failed Cases"))
        for result in failed_results:
            actual = result["actual"] or "no route"
            lines.extend((
                "",
                f"### `{result['id']}`",
                "",
                f"- Expected: `{result['expected']}`",
                f"- Actual: `{actual}`",
                f"- Return code: `{result['returncode'] if result['returncode'] is not None else 'not run'}`",
                "",
                "**Prompt**",
                "",
            ))
            prompt_lines = result["prompt"].splitlines() or [""]
            lines.extend(f"> {line}" for line in prompt_lines)
            detail = "\n".join(
                part for part in (result["stderr"].strip(), result["stdout"].strip()) if part
            ).strip()
            if detail:
                lines.extend((
                    "",
                    "**Agent output**",
                    "",
                    _indented_block(detail),
                ))

    lines.extend((
        "",
        "## All Cases",
        "",
        "| Case | Status | Expected | Actual |",
        "| --- | --- | --- | --- |",
    ))
    for result in payload["results"]:
        actual = result["actual"] or "no route"
        lines.append(
            f"| {_markdown_cell(result['id'])} | "
            f"{'PASS' if result['passed'] else 'FAIL'} | "
            f"{_markdown_cell(result['expected'])} | "
            f"{_markdown_cell(actual)} |"
        )
    lines.append("")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as error:
        raise WorkflowError(f"could not save eval summary to {path}: {error}") from error


def init(args):
    target = Path(args.path).resolve()
    plan_path = (target / args.plan).resolve()
    evals_path = (target / EVAL_FILE).resolve()
    prompt = EVAL_CREATION_PROMPT.format(plan=args.plan, evals=EVAL_FILE)
    try:
        plan = load_plan(plan_path)
        if evals_path.exists() and not args.force:
            raise WorkflowError(f"{evals_path} already exists (use --force to overwrite)")
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    generator = workflow_generator(plan)
    if args.dry_run:
        print(f"Would generate routing evals for '{plan['name']}' with {generator} in {target}")
        print("(dry run: no agent call or files changed)")
        print("\n== Prompt ==")
        print(prompt)
        return 0

    try:
        code, stdout, stderr = run_agent(
            generator,
            prompt,
            target,
            write=True,
            timeout=args.timeout,
            model=plan.get("model"),
        )
        if code != 0 or not evals_path.is_file():
            detail = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)[-500:]
            reason = detail or f"agent exited with code {code} and did not write {EVAL_FILE}"
            raise WorkflowError(f"could not generate routing evals: {reason}")
        cases = load_cases(evals_path, plan)
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"Generated {len(cases)} routing case(s) in {evals_path}")
    print(f'Edit the cases if needed, then run: awd-builder evals run "{target}"')
    return 0


def run(args):
    target = Path(args.path).resolve()
    output_arg = getattr(args, "output", DEFAULT_RESULTS_FILE)
    summary_arg = getattr(args, "summary", DEFAULT_SUMMARY_FILE)
    output_path = (target / output_arg).resolve()
    summary_path = (target / summary_arg).resolve()
    try:
        plan_path = (target / args.plan).resolve()
        evals_path = (target / args.evals).resolve()
        if output_path in (plan_path, evals_path):
            raise WorkflowError("the results output must not overwrite the workflow plan or eval cases")
        if summary_path in (plan_path, evals_path, output_path):
            raise WorkflowError(
                "the summary output must not overwrite the workflow plan, eval cases, or results JSON"
            )
        plan = load_plan(plan_path)
        cases = load_cases(evals_path, plan)
        if args.only:
            cases = [case for case in cases if case["id"] in args.only]
            if not cases:
                raise WorkflowError(f"no case matches --only {', '.join(args.only)}")
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.dry_run:
        for case in cases:
            print(f"== {case['id']} (expected {case['expected']})")
            print(ROUTING_PROMPT.format(prompt=case["prompt"]))
        return 0

    tool = workflow_generator(plan)
    model = plan.get("model")
    model_note = f" model {model}" if model else ""
    print(f"Running {len(cases)} routing case(s) for '{plan['name']}' with {tool}{model_note}\n")
    failed = []
    results = []
    for case in cases:
        try:
            code, stdout, stderr = run_agent(
                tool,
                ROUTING_PROMPT.format(prompt=case["prompt"]),
                target,
                write=False,
                timeout=args.timeout,
                model=model,
            )
        except WorkflowError as error:
            code, stdout, stderr = None, "", str(error)

        actual = parse_route(stdout)
        passed = actual == case["expected"]
        results.append({
            "id": case["id"],
            "prompt": case["prompt"],
            "expected": case["expected"],
            "actual": actual,
            "passed": passed,
            "returncode": code,
            "stdout": stdout,
            "stderr": stderr,
        })
        print(f"[{'PASS' if passed else 'FAIL'}] {case['id']}: expected {case['expected']}, got {actual or 'no route'}")
        if not passed:
            failed.append(case["id"])
            if code not in (0, None) or actual is None:
                detail = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)[-200:]
                if detail:
                    print(f"       {detail}")

    total = len(cases)
    print(f"\n{total - len(failed)}/{total} passed")
    try:
        payload = save_results(output_path, plan, args.evals, results)
        save_summary(summary_path, payload)
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"results saved to {output_path}")
    print(f"summary saved to {summary_path}")
    if failed:
        print(f"failed: {', '.join(failed)}")
        return 1
    return 0


def register(subparsers):
    parser = subparsers.add_parser("evals", help="generate and run workflow routing evals")
    actions = parser.add_subparsers(dest="action", required=True, metavar="action")

    init_parser = actions.add_parser("init", help="generate routing eval cases for the workflow")
    init_parser.add_argument("path", nargs="?", default=".", help="project folder (default: current folder)")
    init_parser.add_argument("--plan", default=PLAN_FILE, help=f"plan file, relative to the project folder (default: {PLAN_FILE})")
    init_parser.add_argument("--force", action="store_true", help="overwrite an existing eval file")
    init_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds allowed for generation (default: %(default)s)")
    init_parser.add_argument("--dry-run", action="store_true", help="print the generation prompt without calling the agent")
    init_parser.set_defaults(func=init)

    run_parser = actions.add_parser("run", help="run the routing evals against the workflow")
    run_parser.add_argument("path", nargs="?", default=".", help="project folder (default: current folder)")
    run_parser.add_argument("--plan", default=PLAN_FILE, help=f"plan file, relative to the project folder (default: {PLAN_FILE})")
    run_parser.add_argument("--evals", default=EVAL_FILE, help=f"eval file, relative to the project folder (default: {EVAL_FILE})")
    run_parser.add_argument("--only", action="append", default=[], metavar="ID", help="run only this case id (repeatable)")
    run_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds per case (default: %(default)s)")
    run_parser.add_argument("--output", default=DEFAULT_RESULTS_FILE, help=f"results JSON path, relative to the project (default: {DEFAULT_RESULTS_FILE})")
    run_parser.add_argument("--summary", default=DEFAULT_SUMMARY_FILE, help=f"results summary Markdown path, relative to the project (default: {DEFAULT_SUMMARY_FILE})")
    run_parser.add_argument("--dry-run", action="store_true", help="print the routing prompts without calling the agent")
    run_parser.set_defaults(func=run)
