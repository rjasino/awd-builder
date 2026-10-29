"""`awd-builder app`: scaffold an application project with GitHub Spec Kit (specify)."""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .lib import (
    APP_PLAN_FILE,
    APP_PLAN_TEMPLATE,
    WorkflowError,
    check_folders,
    find_executable,
    load_yaml,
    run_checked,
    write_template,
)
from .scaffold import print_step

SPECKIT_PACKAGE = "specify-cli"
SPECKIT_EXTENSIONS = ("assess", "bug")
INTEGRATION_ROW = re.compile(r"^│\s*([a-z0-9][a-z0-9-]*)\s*│")
UV_BIN_DIR = Path.home() / ".local" / "bin"
UV_INSTALL_COMMAND = (
    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://astral.sh/uv/install.ps1 | iex"]
    if sys.platform == "win32"
    else ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]
)


def load_app_plan(path):
    plan = load_yaml(path)
    validate_app_plan(plan)
    return plan


def validate_app_plan(plan):
    if not isinstance(plan, dict):
        raise WorkflowError("the app plan must be a YAML mapping")
    if not plan.get("name"):
        raise WorkflowError("the plan needs a 'name'")
    integration = plan.get("integration")
    if not isinstance(integration, str) or not integration.strip():
        raise WorkflowError("'integration' must be the Spec Kit key of your coding agent, for example claude or opencode")
    check_folders(plan.get("folders") or [])
    extensions = plan.get("extensions") or []
    if not isinstance(extensions, list):
        raise WorkflowError("'extensions' must be a list")
    for extension in extensions:
        if extension not in SPECKIT_EXTENSIONS:
            raise WorkflowError(
                f"extension '{extension}' is not supported; choose from: {', '.join(SPECKIT_EXTENSIONS)}"
            )


def add_to_path(folder):
    os.environ["PATH"] = os.pathsep.join([str(folder), os.environ.get("PATH", "")])


def json_output(args, cwd):
    return json.loads(run_checked(args, cwd).stdout)


def ensure_tools(dry_run):
    print_step("Tools")
    if shutil.which("uv"):
        print("  ok uv")
    elif dry_run:
        print("  would install uv with the official installer")
    else:
        print("  installing uv with the official installer ...", flush=True)
        run_checked(UV_INSTALL_COMMAND, Path.cwd())
        add_to_path(UV_BIN_DIR)
        find_executable("uv")
        print("  ok uv installed")

    if shutil.which("specify"):
        print("  ok specify (Spec Kit) installed")
    elif dry_run:
        print(f"  would run: uv tool install {SPECKIT_PACKAGE}")
    else:
        uv = find_executable("uv")
        print(f"  installing Spec Kit with uv ({SPECKIT_PACKAGE}, latest) ...", flush=True)
        run_checked([uv, "tool", "install", SPECKIT_PACKAGE], Path.cwd())
        add_to_path(run_checked([uv, "tool", "dir", "--bin"], Path.cwd()).stdout.strip())
        find_executable("specify")
        print("  ok specify (Spec Kit) installed")


def supported_integrations():
    with tempfile.TemporaryDirectory() as temp_dir:
        (Path(temp_dir) / ".specify").mkdir()
        output = run_checked([find_executable("specify"), "integration", "list"], Path(temp_dir)).stdout
    keys = [match.group(1) for match in map(INTEGRATION_ROW.match, output.splitlines()) if match]
    return [key for key in keys if key != "none"]


def check_integration(integration, dry_run):
    print_step("Integration")
    if dry_run and not shutil.which("specify"):
        print(f"  would verify '{integration}' with: specify integration list")
        return
    keys = supported_integrations()
    if integration not in keys:
        raise WorkflowError(
            f"'{integration}' is not a supported integration. Supported keys: {', '.join(keys)}"
        )
    print(f"  ok {integration}")


def create_folders(plan, target, dry_run):
    print_step("Folders")
    for folder in plan.get("folders") or []:
        if dry_run:
            print(f"  would create {folder}")
        else:
            (target / folder).mkdir(parents=True, exist_ok=True)
            print(f"  ok {folder}")


def run_speckit(specify, args, target, dry_run):
    line = " ".join(["specify", *args])
    if dry_run:
        print(f"  would run: {line}")
        return
    run_checked([specify, *args], target)
    print(f"  ok {line}")


def setup_speckit(integration, extensions, target, dry_run):
    print_step("Spec Kit project")
    specify = shutil.which("specify") if dry_run else find_executable("specify")
    initialized = (target / ".specify").is_dir()
    installed_integrations = []
    installed_extensions = []
    if specify and initialized:
        status = json_output([specify, "integration", "status", "--json"], target)
        installed_integrations = status.get("installed_integrations") or []
        installed_extensions = [item["id"] for item in json_output([specify, "extension", "list", "--json"], target)]
    specify = specify or "specify"

    if not initialized:
        args = ["init", "--here", "--integration", integration, "--force", "--non-interactive"]
        run_speckit(specify, args, target, dry_run)
    elif integration in installed_integrations:
        print(f"  ok {integration} already installed")
    else:
        run_speckit(specify, ["integration", "install", integration], target, dry_run)

    print_step("Extensions")
    if not extensions:
        print("  none in the plan")
    for extension in extensions:
        if extension in installed_extensions:
            print(f"  ok {extension} already installed")
        else:
            run_speckit(specify, ["extension", "add", extension], target, dry_run)


def scaffold(plan, target, dry_run):
    ensure_tools(dry_run)
    check_integration(plan["integration"], dry_run)
    create_folders(plan, target, dry_run)
    extensions = list(dict.fromkeys(plan.get("extensions") or []))
    setup_speckit(plan["integration"], extensions, target, dry_run)


def run_init(args):
    target = Path(args.path).resolve()
    try:
        dest = write_template(APP_PLAN_TEMPLATE, target, APP_PLAN_FILE, args.force)
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {dest}")
    print(f'Edit it, then run: awd-builder app run "{target}"')
    return 0


def run(args):
    target = Path(args.path).resolve()
    try:
        plan = load_app_plan(target / args.plan)
        print(f"Scaffolding application '{plan['name']}' with Spec Kit ({plan['integration']}) in {target}")
        if args.dry_run:
            print("(dry run: nothing will be changed)")
        scaffold(plan, target, args.dry_run)
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"\nDone. Open {target} in {plan['integration']} and start with the Spec Kit constitution step.")
    return 0


def register(subparsers):
    parser = subparsers.add_parser("app", help="scaffold an application project with GitHub Spec Kit")
    actions = parser.add_subparsers(dest="action", required=True, metavar="action")

    init = actions.add_parser("init", help=f"write an {APP_PLAN_FILE} template into a project")
    init.add_argument("path", help='project folder, for example "." for the current folder')
    init.add_argument("--force", action="store_true", help="overwrite an existing plan")
    init.set_defaults(func=run_init)

    run_parser = actions.add_parser("run", help="scaffold the application project from the plan")
    run_parser.add_argument("path", help='project folder, for example "." for the current folder')
    run_parser.add_argument("--plan", default=APP_PLAN_FILE, help=f"plan file, relative to the project folder (default: {APP_PLAN_FILE})")
    run_parser.add_argument("--dry-run", action="store_true", help="print what would happen and change nothing")
    run_parser.set_defaults(func=run)
