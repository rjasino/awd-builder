"""Shared helpers for the awd-builder commands."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLAN_FILE = "workflow-plan.yaml"
EVAL_FILE = "evals/routing.yaml"
ITEM_KINDS = ("agents", "skills", "commands")

PACKAGE_DIR = Path(__file__).resolve().parent
PLAN_TEMPLATE = PACKAGE_DIR / "templates" / "workflow-plan.template.yaml"
EVAL_CREATOR_DIR = PACKAGE_DIR / "skills" / "eval-creator"

TOOLS = {
    "claude-code": {
        "label": "Claude Code",
        "cli": "claude",
        "skills_agent": "claude-code",
        "agents_dir": ".claude/agents",
        "commands_dir": ".claude/commands",
        "skills_dir": ".claude/skills",
    },
    "opencode": {
        "label": "OpenCode",
        "cli": "opencode",
        "skills_agent": "opencode",
        "agents_dir": ".opencode/agents",
        "commands_dir": ".opencode/commands",
        "skills_dir": ".opencode/skills",
    },
}


class WorkflowError(Exception):
    """A problem with the plan, the eval file, or the environment that stops the run."""


def load_yaml(path):
    if not path.is_file():
        raise WorkflowError(f"file not found: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except yaml.YAMLError as error:
        raise WorkflowError(f"invalid YAML in {path}: {error}") from error


def load_plan(path):
    plan = load_yaml(path)
    validate_plan(plan)
    return plan


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise WorkflowError("the plan must be a YAML mapping")
    if not plan.get("name"):
        raise WorkflowError("the plan needs a 'name'")
    if plan.get("tool") not in TOOLS:
        raise WorkflowError(f"'tool' must be one of: {', '.join(TOOLS)}")

    folders = plan.get("folders") or []
    if not isinstance(folders, list) or not all(isinstance(f, str) and f for f in folders):
        raise WorkflowError("'folders' must be a list of paths")
    for folder in folders:
        if Path(folder).is_absolute() or ".." in Path(folder).parts:
            raise WorkflowError(f"folder '{folder}' must be a relative path inside the project")

    seen = {}
    for kind in ITEM_KINDS:
        items = plan.get(kind) or []
        if not isinstance(items, list):
            raise WorkflowError(f"'{kind}' must be a list")
        for item in items:
            if not isinstance(item, dict) or not item.get("name") or not item.get("description"):
                raise WorkflowError(f"every entry in '{kind}' needs a 'name' and a 'description'")
            name = str(item["name"])
            if not NAME_PATTERN.match(name):
                raise WorkflowError(f"name '{name}' must be kebab-case, for example code-review")
            if name in seen:
                raise WorkflowError(f"name '{name}' is used more than once ({seen[name]} and {kind})")
            seen[name] = kind


def components(plan):
    """Yield (kind, item) for every agent, skill and command, with kind singular."""
    for kind in ITEM_KINDS:
        for item in plan.get(kind) or []:
            yield kind[:-1], item


def find_executable(name):
    path = shutil.which(name)
    if not path:
        raise WorkflowError(f"'{name}' was not found on PATH")
    return path


def run_checked(args, cwd):
    result = subprocess.run(
        args,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise WorkflowError(f"command failed ({result.returncode}): {' '.join(args)}\n{output[-800:]}")
    return result


def run_agent(tool_name, prompt, cwd, *, write, timeout):
    """Send one non-interactive prompt to the chosen agentic CLI.

    write=True lets the agent edit files. write=False runs in read-only mode.
    Returns (returncode, stdout, stderr).
    """
    tool = TOOLS[tool_name]
    exe = find_executable(tool["cli"])

    if tool_name == "claude-code":
        args = [exe, "-p", "--permission-mode", "acceptEdits" if write else "plan"]
        return _run(args, cwd, {"input": prompt}, timeout)

    with tempfile.TemporaryDirectory() as temp_dir:
        prompt_file = Path(temp_dir) / "prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        args = [exe, "run"]
        if write:
            args.append("--auto")
        args += ["--file", str(prompt_file), "Follow the attached instructions."]
        return _run(args, cwd, {"stdin": subprocess.DEVNULL}, timeout)


def _run(args, cwd, stdin_options, timeout):
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **stdin_options,
        )
    except subprocess.TimeoutExpired as error:
        raise WorkflowError(f"agent timed out after {timeout}s") from error
    return result.returncode, result.stdout, result.stderr
