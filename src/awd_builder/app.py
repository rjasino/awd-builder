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
    HARNESS_NAMES,
    WorkflowError,
    check_folders,
    find_executable,
    load_yaml,
    run_checked,
    write_template,
)
from .scaffold import print_step
from .sync import SPEC_KIT_INTEGRATIONS, sync_workflow

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
    if plan.get("harnesses") is None:
        integration = plan.get("integration")
        if not isinstance(integration, str) or not integration.strip():
            raise WorkflowError("'harnesses' must contain at least one supported agent harness")
    else:
        harnesses = app_harnesses(plan)
        if not harnesses:
            raise WorkflowError("'harnesses' must contain at least one supported agent harness")
        if len(set(harnesses)) != len(harnesses):
            raise WorkflowError("'harnesses' must not contain duplicates")
    check_folders(plan.get("folders") or [])
    extensions = plan.get("extensions") or []
    if not isinstance(extensions, list):
        raise WorkflowError("'extensions' must be a list")
    for extension in extensions:
        if extension not in SPECKIT_EXTENSIONS:
            raise WorkflowError(
                f"extension '{extension}' is not supported; choose from: {', '.join(SPECKIT_EXTENSIONS)}"
            )


def app_harnesses(plan):
    """Return canonical harness ids for a new multi-harness app plan."""
    harnesses = plan.get("harnesses")
    if harnesses is not None:
        if not isinstance(harnesses, list):
            raise WorkflowError("'harnesses' must be a list")
        invalid = [name for name in harnesses if name not in HARNESS_NAMES]
        if invalid:
            raise WorkflowError(
                f"unsupported harness(es): {', '.join(map(str, invalid))}; choose from: {', '.join(HARNESS_NAMES)}"
            )
        return harnesses

    reverse = {value: key for key, value in SPEC_KIT_INTEGRATIONS.items()}
    integration = plan.get("integration")
    return [reverse[integration]] if integration in reverse else []


def app_integration_keys(plan):
    harnesses = app_harnesses(plan)
    if harnesses:
        return [SPEC_KIT_INTEGRATIONS[harness] for harness in harnesses]
    integration = plan.get("integration")
    return [integration] if isinstance(integration, str) and integration.strip() else []


def add_to_path(folder):
    os.environ["PATH"] = os.pathsep.join([str(folder), os.environ.get("PATH", "")])


def json_output(args, cwd):
    result = run_checked(args, cwd)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise WorkflowError(f"Spec Kit returned invalid JSON for {' '.join(args)}") from error


def ensure_tools(dry_run):
    print_step("Tools")
    if shutil.which("uv"):
        print("  ok uv")
        uv = find_executable("uv")
    elif dry_run:
        print("  would install uv with the official installer")
        uv = "uv"
    else:
        print("  installing uv with the official installer ...", flush=True)
        run_checked(UV_INSTALL_COMMAND, Path.cwd())
        add_to_path(UV_BIN_DIR)
        uv = find_executable("uv")
        print("  ok uv installed")

    if dry_run:
        print(f"  would run: uv tool install --upgrade {SPECKIT_PACKAGE} (latest)")
        return

    print(f"  installing/upgrading Spec Kit with uv ({SPECKIT_PACKAGE}, latest) ...", flush=True)
    run_checked([uv, "tool", "install", "--upgrade", SPECKIT_PACKAGE], Path.cwd())
    add_to_path(run_checked([uv, "tool", "dir", "--bin"], Path.cwd()).stdout.strip())
    find_executable("specify")
    print("  ok specify (Spec Kit, latest)")


def supported_integrations():
    with tempfile.TemporaryDirectory() as temp_dir:
        (Path(temp_dir) / ".specify").mkdir()
        output = run_checked([find_executable("specify"), "integration", "list"], Path(temp_dir)).stdout
    keys = [match.group(1) for match in map(INTEGRATION_ROW.match, output.splitlines()) if match]
    return [key for key in keys if key != "none"]


def check_integration(integrations, dry_run):
    print_step("Integration")
    if isinstance(integrations, str):
        integrations = [integrations]
    if dry_run and not shutil.which("specify"):
        print(f"  would verify {', '.join(integrations)} with: specify integration list")
        return
    keys = supported_integrations()
    missing = [integration for integration in integrations if integration not in keys]
    if missing:
        raise WorkflowError(
            f"unsupported Spec Kit integration(s): {', '.join(missing)}. Supported keys: {', '.join(keys)}"
        )
    print(f"  ok {', '.join(integrations)}")


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


def setup_speckit(integrations, extensions, target, dry_run):
    print_step("Spec Kit project")
    if isinstance(integrations, str):
        integrations = [integrations]
    specify = shutil.which("specify") if dry_run else find_executable("specify")
    initialized = (target / ".specify").is_dir()
    installed_integrations = []
    installed_extensions = []
    if dry_run and initialized and not specify:
        print("  cannot inspect installed integrations or extensions because specify is not installed")
        print("  install Spec Kit, then rerun --dry-run to see which setup actions are needed")
        return
    if specify and initialized:
        try:
            status = json_output([specify, "integration", "status", "--json"], target)
            extension_rows = json_output([specify, "extension", "list", "--json"], target)
        except WorkflowError as error:
            raise WorkflowError(
                f"could not inspect existing Spec Kit state in {target / '.specify'}; "
                f"no re-initialization was attempted: {error}"
            ) from error
        if not isinstance(status, dict) or not isinstance(status.get("installed_integrations", []), list):
            raise WorkflowError(f"Spec Kit returned an invalid integration status for {target}")
        if not isinstance(extension_rows, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in extension_rows
        ):
            raise WorkflowError(f"Spec Kit returned an invalid extension list for {target}")
        installed_integrations = status.get("installed_integrations") or []
        installed_extensions = [item["id"] for item in extension_rows]
    specify = specify or "specify"

    initialized_by_run = False
    if not initialized:
        args = ["init", "--here", "--integration", integrations[0], "--force", "--non-interactive"]
        run_speckit(specify, args, target, dry_run)
        initialized_by_run = True

    for index, integration in enumerate(integrations):
        if initialized_by_run and index == 0:
            action = "would initialize" if dry_run else "initialized"
            print(f"  {action} {integration}")
        elif integration in installed_integrations:
            print(f"  ok {integration} already installed")
        else:
            run_speckit(specify, ["integration", "install", integration], target, dry_run)

    if extensions and integrations:
        # Spec Kit registers extensions only for the active integration. Make
        # the plan's first integration active before adding extensions, then
        # activate each remaining integration so it gets its own commands.
        run_speckit(specify, ["integration", "use", integrations[0]], target, dry_run)

    print_step("Extensions")
    if not extensions:
        print("  none in the plan")
    for extension in extensions:
        if extension in installed_extensions:
            print(f"  ok {extension} already installed")
        else:
            run_speckit(specify, ["extension", "add", extension], target, dry_run)

    if extensions and len(integrations) > 1:
        print_step("Register extensions for integrations")
        for integration in [*integrations[1:], integrations[0]]:
            run_speckit(specify, ["integration", "use", integration], target, dry_run)


def scaffold(plan, target, dry_run):
    ensure_tools(dry_run)
    integrations = app_integration_keys(plan)
    check_integration(integrations, dry_run)
    create_folders(plan, target, dry_run)
    extensions = list(dict.fromkeys(plan.get("extensions") or []))
    setup_speckit(integrations, extensions, target, dry_run)
    harnesses = app_harnesses(plan)
    if harnesses:
        print_step("Sync harnesses")
        if dry_run:
            print(f"  would sync canonical .agents files for: {', '.join(harnesses)}")
        else:
            sync_workflow(target, harnesses)


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
        integrations = app_integration_keys(plan)
        print(f"Scaffolding application '{plan['name']}' with Spec Kit ({', '.join(integrations)}) in {target}")
        if args.dry_run:
            print("(dry run: nothing will be changed)")
        scaffold(plan, target, args.dry_run)
    except WorkflowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    destinations = app_harnesses(plan) or app_integration_keys(plan)
    destination_note = f" in {', '.join(destinations)}" if destinations else ""
    print(f"\nDone. Open {target}{destination_note} and start with the Spec Kit constitution step.")
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
