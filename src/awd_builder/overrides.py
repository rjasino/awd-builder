"""Create harness-specific agent metadata override files."""

import sys
from pathlib import Path

from .lib import CANONICAL_AGENTS, HARNESS_NAMES, WorkflowError
from .sync import _component_name, _markdown_parts

HARNESS_HINTS = {
    "opencode": (
        "# mode: primary",
        "# permissions:",
        "#   - action: edit",
        '#     resource: "*"',
        "#     effect: deny",
        "# steps: 8",
        "# hidden: true",
        '# color: "#ff6b6b"',
        "# Set model on the agent in workflow-plan.yaml, not in this override.",
    ),
    "claude-code": (
        "# model: sonnet",
        "# tools:",
        "#   - Read",
        "# permissionMode: plan",
    ),
    "codex": (
        "# sandbox_mode: workspace-write",
        "# approval_policy: on-request",
        "# model_reasoning_effort: medium",
    ),
    "github-copilot": (
        "# tools:",
        '#   - "search/codebase"',
        "# user-invocable: true",
    ),
    "pi": (
        "# Pi agent exports use a skill fallback; add only metadata supported by that format.",
    ),
    "cursor": (
        "# model: sonnet-4",
        "# readonly: true",
    ),
}


def _find_agent(target, requested_name):
    agents_dir = target / CANONICAL_AGENTS
    if not agents_dir.is_dir():
        raise WorkflowError(f"canonical agent directory not found: {agents_dir}")

    matches = []
    try:
        sources = sorted(agents_dir.glob("*.md"))
        for source in sources:
            metadata, _ = _markdown_parts(source)
            name = _component_name(metadata, source)
            if requested_name in (name, source.stem):
                matches.append(name)
    except (OSError, UnicodeError) as error:
        raise WorkflowError(f"could not read canonical agents in {agents_dir}: {error}") from error

    if not matches:
        available = sorted({_component_name(_markdown_parts(source)[0], source) for source in sources})
        names = ", ".join(available) or "none"
        raise WorkflowError(f"agent '{requested_name}' not found in {agents_dir}; available agents: {names}")
    if len(matches) > 1:
        raise WorkflowError(f"agent name '{requested_name}' is ambiguous in {agents_dir}")
    return matches[0]


def init(args):
    target = Path(args.path).resolve()
    try:
        name = _find_agent(target, args.agent)
        destination = target / ".awd-builder" / "overrides" / args.harness / "agents" / f"{name}.yaml"
        if destination.exists():
            raise WorkflowError(f"{destination} already exists; it was left unchanged")
        destination.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# Harness-specific metadata for the '{name}' agent ({args.harness}).",
            "# Uncomment and edit the fields you need, then run awd-builder sync.",
            "# Override values take precedence over generated metadata; null removes a generated field.",
        ]
        lines.extend(HARNESS_HINTS[args.harness])
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except (WorkflowError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"created {destination}")
    return 0


def register(subparsers):
    parser = subparsers.add_parser("overrides", help="manage harness-specific agent metadata overrides")
    actions = parser.add_subparsers(dest="action", required=True, metavar="action")
    init_parser = actions.add_parser("init", help="create a starter agent metadata override YAML file")
    init_parser.add_argument("path", nargs="?", default=".", help="project folder (default: current folder)")
    init_parser.add_argument("--harness", required=True, choices=HARNESS_NAMES, help="target harness")
    init_parser.add_argument("--agent", required=True, help="canonical agent name (from .agents/agents)")
    init_parser.set_defaults(func=init)
