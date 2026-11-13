"""Shared helpers for the awd-builder commands."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
OPENCODE_MODEL_PATTERN = re.compile(r"^[^\s#/]+/[^\s#]+(?:#[^\s#]+)?$")
PLAN_FILE = "workflow-plan.yaml"
APP_PLAN_FILE = "app-workflow-plan.yaml"
EVAL_FILE = "evals/routing.yaml"
MEMORY_DIR = ".awd-builder/memory"
MEMORY_FILE = f"{MEMORY_DIR}/memories.json"
MEMORY_GITIGNORE = f"/{MEMORY_DIR}/"
MEMORY_SKILL_NAME = "workflow-memory"
CANONICAL_AGENTS = Path(".agents/agents")
CANONICAL_COMMANDS = Path(".agents/commands")
CANONICAL_SKILLS = Path(".agents/skills")
ITEM_KINDS = ("agents", "skills", "commands")

PACKAGE_DIR = Path(__file__).resolve().parent
PLAN_TEMPLATE = PACKAGE_DIR / "templates" / "workflow-plan.template.yaml"
APP_PLAN_TEMPLATE = PACKAGE_DIR / "templates" / "app-workflow-plan.template.yaml"
EVAL_CREATOR_DIR = PACKAGE_DIR / "skills" / "eval-creator"
MEMORY_SKILL_DIR = PACKAGE_DIR / "skills" / MEMORY_SKILL_NAME
MEMORY_COMMAND_FILE = PACKAGE_DIR / "commands" / "memory.md"

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
HARNESS_NAMES = (
    "opencode",
    "claude-code",
    "codex",
    "github-copilot",
    "pi",
    "cursor",
)
GENERATOR_NAMES = tuple(TOOLS)


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


def write_template(template, target, file_name, force):
    dest = target / file_name
    if dest.exists() and not force:
        raise WorkflowError(f"{dest} already exists (use --force to overwrite)")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, dest)
    return dest


def load_plan(path):
    plan = load_yaml(path)
    validate_plan(plan)
    return plan


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise WorkflowError("the plan must be a YAML mapping")
    if not plan.get("name"):
        raise WorkflowError("the plan needs a 'name'")
    harnesses = workflow_harnesses(plan)
    if not harnesses:
        raise WorkflowError(f"'harnesses' must contain at least one of: {', '.join(HARNESS_NAMES)}")
    generator = workflow_generator(plan)
    if generator not in GENERATOR_NAMES:
        raise WorkflowError(f"'generator' must be one of: {', '.join(GENERATOR_NAMES)}")
    if plan.get("model") is not None:
        if generator == "opencode":
            check_opencode_model(plan["model"], "'model'")
        else:
            check_model(plan["model"], "'model'")

    check_folders(plan.get("folders") or [])

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
            if item.get("model") is not None:
                if kind != "agents":
                    raise WorkflowError(f"'model' is only supported on agents, not on '{name}' in '{kind}'")
                where = f"'model' of agent '{name}'"
                if "opencode" in harnesses:
                    check_opencode_model(item["model"], where)
                else:
                    check_model(item["model"], where)


def check_folders(folders):
    if not isinstance(folders, list) or not all(isinstance(f, str) and f for f in folders):
        raise WorkflowError("'folders' must be a list of paths")
    for folder in folders:
        if Path(folder).is_absolute() or ".." in Path(folder).parts:
            raise WorkflowError(f"folder '{folder}' must be a relative path inside the project")


def check_model(value, where):
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"{where} must be a non-empty string, for example sonnet or opencode-go/claude-haiku-5-5")


def check_opencode_model(value, where):
    check_model(value, where)
    if not OPENCODE_MODEL_PATTERN.fullmatch(value):
        raise WorkflowError(
            f"{where} must use OpenCode's provider/model format with an optional #variant, "
            "for example opencode-go/claude-haiku-5-5"
        )


def components(plan):
    """Yield (kind, item) for every agent, skill and command, with kind singular."""
    for kind in ITEM_KINDS:
        for item in plan.get(kind) or []:
            yield kind[:-1], item


def workflow_harnesses(plan):
    """Return output harnesses, with legacy `tool` plans mapped to one harness."""
    harnesses = plan.get("harnesses")
    if harnesses is None:
        tool = plan.get("tool")
        return [tool] if tool in HARNESS_NAMES else []
    if not isinstance(harnesses, list):
        raise WorkflowError("'harnesses' must be a list")
    invalid = [name for name in harnesses if name not in HARNESS_NAMES]
    if invalid:
        raise WorkflowError(f"unsupported harness(es): {', '.join(map(str, invalid))}; choose from: {', '.join(HARNESS_NAMES)}")
    if len(set(harnesses)) != len(harnesses):
        raise WorkflowError("'harnesses' must not contain duplicates")
    return harnesses


def workflow_generator(plan):
    """Return the CLI used to author canonical components."""
    return plan.get("generator") or plan.get("tool") or "claude-code"


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


def run_agent(tool_name, prompt, cwd, *, write, timeout, model=None, agent="build"):
    """Send one non-interactive prompt to the chosen agentic CLI.

    write=True lets the agent edit files. write=False runs in read-only mode.
    model=None uses the CLI's default model.
    Returns (returncode, stdout, stderr).
    """
    tool = TOOLS[tool_name]
    exe = find_executable(tool["cli"])
    model_args = ["--model", model] if model else []

    if tool_name == "claude-code":
        args = [exe, "-p", "--permission-mode", "acceptEdits" if write else "plan", *model_args]
        return _run(args, cwd, {"input": prompt}, timeout)

    with tempfile.TemporaryDirectory() as temp_dir:
        prompt_file = Path(temp_dir) / "prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        args = [exe, "run"]
        if tool_name == "opencode" and agent:
            # Ignore a project's workflow default agent (for example, game-producer)
            # for awd-builder automation; use OpenCode's standard build agent.
            args += ["--agent", agent]
        if write:
            args.append("--auto")
        args += [*model_args, "--file", str(prompt_file), "Follow the attached instructions."]
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
