"""Sync canonical `.agents` workflow components to selected agent harnesses."""

import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

from .lib import (
    APP_PLAN_FILE,
    CANONICAL_AGENTS,
    CANONICAL_COMMANDS,
    CANONICAL_SKILLS,
    NAME_PATTERN,
    PLAN_FILE,
    WorkflowError,
    check_opencode_model,
    load_plan,
    workflow_harnesses,
)

SYNC_MANIFEST = Path(".awd-builder/sync-manifest.json")
OPENCODE_AGENT_FIELDS = {
    "description",
    "mode",
    "permissions",
    "steps",
    "hidden",
    "color",
    "disabled",
    "request",
}
OPENCODE_DEPRECATED_AGENT_FIELDS = {
    "temperature",
    "top_p",
    "prompt",
    "permission",
    "tools",
    "disable",
    "maxSteps",
}
SPEC_KIT_INTEGRATIONS = {
    "opencode": "opencode",
    "claude-code": "claude",
    "codex": "codex",
    "github-copilot": "copilot",
    "pi": "pi",
    "cursor": "cursor-agent",
}


def _markdown_parts(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    try:
        metadata = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError as error:
        raise WorkflowError(f"invalid YAML frontmatter in {path}: {error}") from error
    if not isinstance(metadata, dict):
        raise WorkflowError(f"frontmatter in {path} must be a YAML mapping")
    body = text[end + len("\n---\n"):]
    return metadata, body.lstrip("\n")


def _yaml_frontmatter(metadata, body):
    lines = ["---"]
    for key, value in metadata.items():
        if value is None:
            continue
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(("---", body.rstrip(), ""))
    return "\n".join(lines)


def _toml_key(value):
    value = str(value)
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        fields = [
            f"{_toml_key(key)} = {_toml_value(item)}"
            for key, item in value.items()
            if item is not None
        ]
        return "{ " + ", ".join(fields) + " }"
    raise WorkflowError(f"unsupported value in Codex agent override: {value!r}")


def _validate_override_value(value, path, ancestors=None):
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        ancestors = ancestors or set()
        if id(value) in ancestors:
            raise WorkflowError(f"agent override {path} cannot contain recursive YAML values")
        ancestors.add(id(value))
        for item in value:
            _validate_override_value(item, path, ancestors)
        ancestors.remove(id(value))
        return
    if isinstance(value, dict):
        ancestors = ancestors or set()
        if id(value) in ancestors:
            raise WorkflowError(f"agent override {path} cannot contain recursive YAML values")
        ancestors.add(id(value))
        for key, item in value.items():
            if not isinstance(key, str):
                raise WorkflowError(f"agent override {path} mapping keys must be strings")
            _validate_override_value(item, path, ancestors)
        ancestors.remove(id(value))
        return
    raise WorkflowError(
        f"agent override {path} values must be YAML scalars, lists, or mappings"
    )


def _agent_overrides(target, harness, source):
    metadata, _ = _markdown_parts(source)
    name = _component_name(metadata, source)
    path = target / ".awd-builder" / "overrides" / harness / "agents" / f"{name}.yaml"
    if not path.exists():
        return {}
    try:
        overrides = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise WorkflowError(f"could not read agent override {path}: {error}") from error
    if not isinstance(overrides, dict):
        raise WorkflowError(f"agent override {path} must be a YAML mapping")
    if any(
        not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key)
        for key in overrides
    ):
        raise WorkflowError(f"agent override {path} keys must be simple frontmatter field names")
    for value in overrides.values():
        _validate_override_value(value, path)
    if "name" in overrides:
        raise WorkflowError(
            f"agent override {path} cannot set 'name'; the canonical agent name determines the output identity"
        )
    if harness == "opencode":
        deprecated = sorted(set(overrides) & OPENCODE_DEPRECATED_AGENT_FIELDS)
        if deprecated:
            raise WorkflowError(
                f"agent override {path} uses deprecated OpenCode V1 fields: "
                f"{', '.join(deprecated)}; use V2 fields such as 'permissions' instead"
            )
        if "model" in overrides:
            raise WorkflowError(
                f"agent override {path} cannot set 'model'; set 'model' on the agent "
                "in workflow-plan.yaml instead"
            )
        unsupported = sorted(set(overrides) - OPENCODE_AGENT_FIELDS)
        if unsupported:
            raise WorkflowError(
                f"agent override {path} has unsupported OpenCode V2 fields: "
                f"{', '.join(unsupported)}"
            )
    if harness == "codex" and "developer_instructions" in overrides:
        raise WorkflowError(
            f"agent override {path} cannot set 'developer_instructions'; "
            "instructions come from the canonical agent body"
        )
    return overrides


def _merge_metadata(metadata, overrides):
    merged = dict(metadata)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _description(metadata, path):
    return str(metadata.get("description") or path.stem.replace("-", " ")).strip()


def _component_name(metadata, path):
    name = str(metadata.get("name") or path.stem)
    if not NAME_PATTERN.fullmatch(name):
        raise WorkflowError(f"invalid component name '{name}' in {path}")
    return name


def _agent_output(harness, source, overrides=None):
    overrides = overrides or {}
    metadata, body = _markdown_parts(source)
    name = _component_name(metadata, source)
    description = _description(metadata, source)
    model = metadata.get("model")

    if harness == "claude-code":
        fields = {"name": name, "description": description}
        if model:
            fields["model"] = model
        skills = metadata.get("skills") or []
        if isinstance(skills, str):
            skills = [skills]
        if not isinstance(skills, list) or not all(isinstance(skill, str) for skill in skills):
            raise WorkflowError(f"'skills' in {source} must be a list of skill names")
        if "workflow-memory" in body and "workflow-memory" not in skills:
            skills.append("workflow-memory")
        if skills:
            fields["skills"] = skills
        return Path(".claude/agents") / f"{name}.md", _yaml_frontmatter(
            _merge_metadata(fields, overrides), body
        )
    if harness == "opencode":
        fields = {"description": description, "mode": "subagent"}
        if model:
            check_opencode_model(model, f"'model' in {source}")
            fields["model"] = model
        return Path(".opencode/agents") / f"{name}.md", _yaml_frontmatter(
            _merge_metadata(fields, overrides), body
        )
    if harness == "codex":
        fields = {
            "name": name,
            "description": description,
            "developer_instructions": body,
        }
        if model:
            fields["model"] = model
        fields = _merge_metadata(fields, overrides)
        lines = [f"{_toml_key(key)} = {_toml_value(value)}" for key, value in fields.items()]
        return Path(".codex/agents") / f"{name}.toml", "\n".join(lines) + "\n"
    if harness == "github-copilot":
        fields = {"name": name, "description": description}
        if model:
            fields["model"] = model
        return Path(".github/agents") / f"{name}.agent.md", _yaml_frontmatter(
            _merge_metadata(fields, overrides), body
        )
    if harness == "cursor":
        fields = {"name": name, "description": description}
        if model:
            fields["model"] = model
        return Path(".cursor/agents") / f"{name}.md", _yaml_frontmatter(
            _merge_metadata(fields, overrides), body
        )
    return _fallback_skill("agent", name, description, body, overrides)


def _command_output(harness, source):
    metadata, body = _markdown_parts(source)
    name = _component_name(metadata, source)
    description = _description(metadata, source)

    if harness in ("claude-code", "cursor"):
        directory = ".claude/commands" if harness == "claude-code" else ".cursor/commands"
        return Path(directory) / f"{name}.md", _yaml_frontmatter({"description": description}, body)
    if harness == "opencode":
        return Path(".opencode/commands") / f"{name}.md", _yaml_frontmatter(
            {"description": description}, body
        )
    if harness == "github-copilot":
        return Path(".github/prompts") / f"{name}.prompt.md", _yaml_frontmatter(
            {"name": name, "description": description}, body
        )
    if harness == "pi":
        return Path(".pi/prompts") / f"{name}.md", body.rstrip() + "\n"
    return _fallback_skill("command", name, description, body)


def _fallback_skill(kind, name, description, body, overrides=None):
    skill_name = f"awd-{kind}-{name}"
    metadata = _merge_metadata({"name": skill_name, "description": description}, overrides or {})
    skill = _yaml_frontmatter(metadata, body)
    return Path(".agents/skills") / skill_name / "SKILL.md", skill


def _skill_outputs(harness, source_dir):
    if harness == "claude-code":
        destination_root = Path(".claude/skills")
    elif harness == "cursor":
        destination_root = Path(".cursor/skills")
    else:
        # OpenCode, Codex, Copilot and Pi discover skills in `.agents/skills`.
        return {}

    outputs = {}
    for source in source_dir.rglob("*"):
        if source.is_file():
            destination = destination_root / source.relative_to(source_dir)
            data = source.read_bytes()
            if source.name == "SKILL.md":
                metadata, body = _markdown_parts(source)
                if "name" in metadata and "description" in metadata:
                    data = _yaml_frontmatter(metadata, body).encode("utf-8")
            outputs[destination] = data
    return outputs


def build_outputs(target, harnesses):
    outputs = {}
    warnings = []
    skills_dir = target / CANONICAL_SKILLS
    fallback_skills = {}
    for harness in harnesses:
        for source in sorted((target / CANONICAL_AGENTS).glob("*.md")):
            overrides = _agent_overrides(target, harness, source)
            destination, content = _agent_output(harness, source, overrides)
            outputs[destination] = content.encode("utf-8")
            if harness == "pi":
                warnings.append(
                    f"{harness}: agent '{source.stem}' exported as a skill fallback; isolated subagent/model behavior is not preserved"
                )
                fallback_skills[destination.relative_to(CANONICAL_SKILLS)] = content.encode("utf-8")

        for source in sorted((target / CANONICAL_COMMANDS).glob("*.md")):
            destination, content = _command_output(harness, source)
            outputs[destination] = content.encode("utf-8")
            if harness == "codex":
                warnings.append(f"{harness}: command '{source.stem}' exported as a skill fallback")
            elif harness == "pi":
                warnings.append(f"{harness}: command '{source.stem}' exported as a prompt template")
                if "$ARGUMENTS" in content:
                    warnings.append(f"{harness}: review argument placeholders in prompt '{source.stem}'")
            elif harness == "github-copilot":
                warnings.append(f"{harness}: command '{source.stem}' exported as a prompt file, not a slash command")
                try:
                    relative = destination.relative_to(CANONICAL_SKILLS)
                except ValueError:
                    pass
                else:
                    fallback_skills[relative] = content.encode("utf-8")

    for harness in harnesses:
        outputs.update(_skill_outputs(harness, skills_dir))
        if harness in ("claude-code", "cursor"):
            root = Path(".claude/skills") if harness == "claude-code" else Path(".cursor/skills")
            for relative, content in fallback_skills.items():
                outputs[root / relative] = content
    return outputs, warnings


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _load_manifest(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkflowError(f"could not read sync manifest {path}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("files", {}), dict):
        raise WorkflowError(f"invalid sync manifest: {path}")
    return data.get("files", {})


def adopt_existing_files(target, relative_paths):
    """Mark legacy outputs as managed after their contents are imported canonically."""
    target = Path(target)
    manifest_path = target / SYNC_MANIFEST
    files = _load_manifest(manifest_path)
    updated = dict(files)
    for relative in relative_paths:
        path = target / relative
        if path.is_file():
            updated[Path(relative).as_posix()] = _digest(path.read_bytes())
    if updated == files:
        return
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"version": 1, "files": updated}, indent=2) + "\n", encoding="utf-8")


def sync_workflow(target, harnesses, *, force=False):
    """Materialize canonical components, refusing to overwrite unmanaged edits."""
    target = Path(target)
    try:
        outputs, warnings = build_outputs(target, harnesses)
    except OSError as error:
        raise WorkflowError(f"could not read canonical workflow files in {target}: {error}") from error
    manifest_path = target / SYNC_MANIFEST
    previous = _load_manifest(manifest_path)
    conflicts = []
    for relative, data in outputs.items():
        destination = target / relative
        if not destination.exists():
            continue
        try:
            current = destination.read_bytes()
        except OSError as error:
            raise WorkflowError(f"could not inspect sync target {destination}: {error}") from error
        if current == data:
            continue
        previous_hash = previous.get(relative.as_posix())
        if not force and (not previous_hash or _digest(current) != previous_hash):
            conflicts.append(relative.as_posix())
    if conflicts:
        raise WorkflowError(
            "sync would overwrite unmanaged or locally modified files: "
            f"{', '.join(conflicts)} (edit the canonical .agents source, or rerun with --force)"
        )

    updated = dict(previous)
    for relative, data in outputs.items():
        destination = target / relative
        try:
            if destination.exists() and destination.read_bytes() == data:
                updated[relative.as_posix()] = _digest(data)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        except OSError as error:
            raise WorkflowError(f"could not write sync target {destination}: {error}") from error
        updated[relative.as_posix()] = _digest(data)

    manifest_text = json.dumps({"version": 1, "files": updated}, indent=2) + "\n"
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != manifest_text:
            manifest_path.write_text(manifest_text, encoding="utf-8")
    except OSError as error:
        raise WorkflowError(f"could not write sync manifest {manifest_path}: {error}") from error
    print(f"  synced {len(outputs)} file(s) for: {', '.join(harnesses)}")
    for warning in dict.fromkeys(warnings):
        print(f"  warning: {warning}")


def run(args):
    target = Path(args.path).resolve()
    try:
        plan_path = target / args.plan
        if Path(args.plan).name == APP_PLAN_FILE:
            from .app import load_app_plan, app_harnesses

            plan = load_app_plan(plan_path)
            harnesses = app_harnesses(plan)
            if not harnesses:
                raise WorkflowError("this app plan uses a custom Spec Kit integration without an awd-builder sync adapter")
        else:
            plan = load_plan(plan_path)
            harnesses = workflow_harnesses(plan)
        if args.dry_run:
            outputs, warnings = build_outputs(target, harnesses)
            print(f"Would sync {len(outputs)} file(s) for: {', '.join(harnesses)}")
            for warning in dict.fromkeys(warnings):
                print(f"  warning: {warning}")
            return 0
        sync_workflow(target, harnesses, force=args.force)
    except (WorkflowError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


def register(subparsers):
    parser = subparsers.add_parser("sync", help="sync canonical .agents workflow files to selected harnesses")
    parser.add_argument("path", help='project folder, for example "."')
    parser.add_argument("--plan", default=PLAN_FILE, help="workflow plan file (use app-workflow-plan.yaml for app plans)")
    parser.add_argument("--force", action="store_true", help="overwrite unmanaged or locally modified target files")
    parser.add_argument("--dry-run", action="store_true", help="show planned sync outputs without changing files")
    parser.set_defaults(func=run)
