"""`awd-builder evals`: run the workflow-wide routing evals in evals/routing.yaml."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .lib import EVAL_FILE, PLAN_FILE, WorkflowError, components, load_plan, load_yaml, run_agent

DEFAULT_TIMEOUT = 300
DEFAULT_RESULTS_FILE = "evals/results.json"
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
        "tool": plan["tool"],
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


def run(args):
    target = Path(args.path).resolve()
    output_arg = getattr(args, "output", DEFAULT_RESULTS_FILE)
    output_path = (target / output_arg).resolve()
    try:
        plan_path = (target / args.plan).resolve()
        evals_path = (target / args.evals).resolve()
        if output_path in (plan_path, evals_path):
            raise WorkflowError("the results output must not overwrite the workflow plan or eval cases")
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

    tool = plan["tool"]
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
        save_results(output_path, plan, args.evals, results)
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"results saved to {output_path}")
    if failed:
        print(f"failed: {', '.join(failed)}")
        return 1
    return 0


def register(subparsers):
    parser = subparsers.add_parser("evals", help="run the routing evals against the scaffolded workflow")
    parser.add_argument("path", help='project folder to test, for example "." for the current folder')
    parser.add_argument("--plan", default=PLAN_FILE, help=f"plan file, relative to the project folder (default: {PLAN_FILE})")
    parser.add_argument("--evals", default=EVAL_FILE, help=f"eval file, relative to the project folder (default: {EVAL_FILE})")
    parser.add_argument("--only", action="append", default=[], metavar="ID", help="run only this case id (repeatable)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds per case (default: %(default)s)")
    parser.add_argument("--output", default=DEFAULT_RESULTS_FILE, help=f"results JSON path, relative to the project (default: {DEFAULT_RESULTS_FILE})")
    parser.add_argument("--dry-run", action="store_true", help="print the routing prompts without calling the agent")
    parser.set_defaults(func=run)
