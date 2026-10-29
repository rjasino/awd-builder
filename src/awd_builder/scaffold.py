"""`awd-builder scaffold`: create the workflow described in a plan file."""

import shutil
import sys
from pathlib import Path

from .lib import (
    EVAL_CREATOR_DIR,
    PLAN_FILE,
    TOOLS,
    WorkflowError,
    components,
    find_executable,
    load_plan,
    run_agent,
    run_checked,
)

EXTERNAL_SKILLS = (
    ("anthropics/skills", "skill-creator"),
    ("softaworks/agent-toolkit", "command-creator"),
)
AGENT_FORMAT_HINTS = {
    "claude-code": (
        "Use Claude Code's subagent format: YAML frontmatter with `name` and `description`, "
        "followed by the system prompt as the Markdown body."
    ),
    "opencode": (
        "Use OpenCode's agent format: YAML frontmatter with `description` and `mode: subagent`, "
        "followed by the system prompt as the Markdown body."
    ),
}
AGENT_TIMEOUT = 900


def item_path(kind, name, tool):
    if kind == "agent":
        return f"{tool['agents_dir']}/{name}.md"
    if kind == "skill":
        return f"{tool['skills_dir']}/{name}/SKILL.md"
    return f"{tool['commands_dir']}/{name}.md"


def build_prompt(kind, item, tool_name, agent_model=None):
    tool = TOOLS[tool_name]
    name = str(item["name"])
    description = str(item["description"]).strip()
    instructions = str(item.get("instructions") or "").strip() or "(none given; derive the details from the description)"
    rel_path = item_path(kind, name, tool)
    rules = (
        f"Write exactly one file: {rel_path}\n"
        "Create parent folders as needed. Do not create or change any other file.\n"
        "Work non-interactively: all details are provided above, so do not ask questions. "
        "Make reasonable choices yourself."
    )

    if kind == "agent":
        model_hint = f' Set its `model` frontmatter field to exactly "{agent_model}".' if agent_model else ""
        body = (
            f'Using the skill-creator skill\'s guidance on writing clear, well-scoped instructions, '
            f'create one {tool["label"]} subagent named "{name}".\n\n'
            f"{AGENT_FORMAT_HINTS[tool_name]}{model_hint}\n\n"
        )
    elif kind == "skill":
        body = (
            f'Use the skill-creator skill to create one new skill named "{name}".\n'
            "Skip its interview and its eval, benchmark, and description-optimization loops.\n\n"
        )
    else:
        body = (
            f'Use the command-creator skill to create one {tool["label"]} slash command named "/{name}". '
            "Skip its interactive questions and pattern selection, and go straight to writing the file. "
            "Use $ARGUMENTS for any arguments the user passes.\n\n"
        )

    return (
        f"{body}"
        f"Description: {description}\n\n"
        f"Instructions:\n{instructions}\n\n"
        f"{rules}"
    ), rel_path


def print_step(title):
    print(f"\n== {title}")


def scaffold(plan, target, dry_run):
    tool_name = plan["tool"]
    tool = TOOLS[tool_name]

    print_step("Folders")
    folders = [*(plan.get("folders") or []), tool["agents_dir"], tool["commands_dir"], tool["skills_dir"]]
    for folder in dict.fromkeys(folders):
        if dry_run:
            print(f"  would create {folder}")
        else:
            (target / folder).mkdir(parents=True, exist_ok=True)
            print(f"  ok {folder}")

    print_step("External skills (skill-creator, command-creator)")
    npx = "npx" if dry_run else find_executable("npx")
    for repo, skill in EXTERNAL_SKILLS:
        args = [npx, "--yes", "skills", "add", repo, "--skill", skill, "-a", tool["skills_agent"], "--copy", "-y"]
        if dry_run:
            print(f"  would run: {' '.join(args)}")
        else:
            run_checked(args, target)
            print(f"  ok {skill}")

    print_step("Local skill: eval-creator")
    eval_dst = target / tool["skills_dir"] / "eval-creator"
    if dry_run:
        print(f"  would copy {EVAL_CREATOR_DIR} -> {eval_dst}")
    else:
        shutil.copytree(EVAL_CREATOR_DIR, eval_dst, dirs_exist_ok=True)
        print(f"  ok {eval_dst.relative_to(target)}")

    print_step("Agents, skills and commands")
    default_model = plan.get("model")
    failures = []
    for kind, item in components(plan):
        name = str(item["name"])
        agent_model = (item.get("model") or default_model) if kind == "agent" else None
        prompt, rel_path = build_prompt(kind, item, tool_name, agent_model)
        if dry_run:
            print(f"  [{kind}] {name} -> {rel_path}")
            print("  ---- prompt ----")
            print("\n".join(f"  {line}" for line in prompt.splitlines()))
            print("  ----------------")
            continue

        print(f"  [{kind}] {name} -> {rel_path} ...", flush=True)
        code, stdout, stderr = run_agent(
            tool_name, prompt, target, write=True, timeout=AGENT_TIMEOUT, model=default_model
        )
        if code == 0 and (target / rel_path).is_file():
            print("    ok")
        else:
            output = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)
            reason = output[-300:] or f"exit code {code}, file not written"
            print(f"    FAILED: {reason}")
            failures.append(f"{kind}/{name}")

    if failures:
        raise WorkflowError(f"these components failed: {', '.join(failures)}")


def run(args):
    target = Path(args.target).resolve()
    try:
        plan = load_plan(target / args.plan)
        model_note = f" (default model: {plan['model']})" if plan.get("model") else ""
        print(f"Scaffolding '{plan['name']}' for {plan['tool']}{model_note} in {target}")
        if args.dry_run:
            print("(dry run: nothing will be changed)")
        scaffold(plan, target, args.dry_run)
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print("\nDone. Next: ask your agent to use the eval-creator skill to create the routing evals,")
    print(f'then run: awd-builder evals --target "{target}"')
    return 0


def register(subparsers):
    parser = subparsers.add_parser("scaffold", help="scaffold the workflow described in the plan")
    parser.add_argument("--target", default=".", help="project folder to scaffold into (default: current folder)")
    parser.add_argument("--plan", default=PLAN_FILE, help=f"plan file, relative to --target (default: {PLAN_FILE})")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen, including prompts, and change nothing")
    parser.set_defaults(func=run)
