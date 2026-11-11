# awd-builder

Scaffold one canonical agent workflow and sync it to OpenCode, Claude Code, Codex, GitHub Copilot, Pi, and Cursor from a YAML plan.

## Prerequisites

- Python 3.9 or newer
- Node.js (provides `npx`, used to install `skill-creator` and `command-creator`)
- Claude Code (`claude`) or OpenCode (`opencode`) on your PATH and signed in as the authoring generator

## Install

Recommended, with [pipx](https://pipx.pypa.io):

```
pipx install git+https://github.com/rjasino/awd-builder.git
```

With uv:

```
uv tool install git+https://github.com/rjasino/awd-builder.git
```

Pin a release tag:

```
pipx install git+https://github.com/rjasino/awd-builder.git@v0.1.0
```

Upgrade later with `pipx upgrade awd-builder`.

From a clone of this repo, `scripts/install.py` installs or upgrades to the version in `src/awd_builder/__init__.py`. It does nothing when that version is already installed, so it is safe to run again after each version bump:

```
python scripts/install.py
```

## Quick start

1. Create a plan in your project. The current folder is the default; optionally pass a project path:

   ```
   awd-builder scaffold init
   ```

   Edit `<project>/workflow-plan.yaml`. Set `generator` to `claude-code` or `opencode` (the CLI that authors canonical files), choose one or more output `harnesses`, and list the folders, agents, skills, and commands you want. Supported output harnesses are `opencode`, `claude-code`, `codex`, `github-copilot`, `pi`, and `cursor`. Existing plans using the old `tool` field remain valid and map that tool as both generator and single output harness.

   Set `model` to the model name your generator accepts, for example `sonnet` for Claude Code or `opencode-go/claude-haiku-5-5` for OpenCode. It is used for scaffolding and routing evals. Each agent can set its own `model` to override it. Leave it out to use the generator's default.

2. Preview, then scaffold:

   ```
   awd-builder scaffold run <project> --dry-run
   awd-builder scaffold run <project>
   ```

   The scaffold creates canonical agents, skills, and commands under `.agents/`, asks the selected generator to author missing components, then syncs them to each selected harness. It also installs the generator helpers `skill-creator` and `command-creator` with `npx skills`. Skills use the Agent Skills format in `.agents/skills`; Claude Code and Cursor receive native skill copies because they do not discover that shared directory. Each authoring call costs tokens, so use `--dry-run` first.

   Canonical source files live in `.agents/agents`, `.agents/skills`, and `.agents/commands`. Use `awd-builder sync <project>` to re-sync after editing canonical files. Synced outputs are tracked in `.awd-builder/sync-manifest.json`; conflicts with untracked or locally modified target files stop the sync. Review before using `awd-builder sync <project> --force`, which overwrites those files. Sync does not delete stale outputs when a component or harness is removed from the plan.

   Generate a starter override with `awd-builder overrides init <project> --harness opencode --agent planner`. This creates `.awd-builder/overrides/opencode/agents/planner.yaml` without overwriting an existing file. Keep harness-specific agent metadata in these override files rather than editing generated agent files. For example, an OpenCode override can contain:

   ```yaml
   mode: primary
   temperature: 0.2
   tools:
     write: true
   ```

   Sync merges these fields into the generated agent metadata; override values take precedence over generated metadata, and a `null` value removes a generated field. The canonical agent name and instruction body remain controlled by `.agents/agents/<agent-name>.md`. For Codex, overrides are emitted as TOML fields, and `developer_instructions` cannot be overridden.

   The generated workflow has private, project-local memory at `.awd-builder/memory/memories.json`; this store is gitignored. Generated agents are instructed to recall relevant memories and ask before saving useful new information. Use `/memory remember`, `/memory recall`, `/memory forget`, `/memory compact`, `/memory export`, or `/memory import` to manage it. The built-in skill/command names `workflow-memory` and `memory` are reserved.

   Re-running `scaffold run` is safe: it creates missing canonical components and syncs target copies. Existing generated files are not regenerated. Edit the canonical file or remove it to change/regenerate a component.

3. Generate routing eval cases with the project's configured generator:

   ```
   awd-builder evals init
   ```

   This uses the `eval-creator` skill to write `evals/routing.yaml`. Use `--dry-run` to preview the prompt or `--force` to replace an existing eval file. Review and edit the generated cases as needed.

4. Run the routing evals:

   ```
   awd-builder evals run
   ```

   Each run saves a JSON report to `evals/results.json`, including per-case expected and actual routes, pass status, and agent output. This file is overwritten on each run. Use `--output <path>` to choose another project-relative path. `--dry-run` prints prompts without calling the agent or saving results; `--only <id>` runs one case. The exit code is 0 when every case passes, 1 when any fails, and 2 on a configuration or results-writing error. The previous `awd-builder evals <project>` form remains supported as an alias for `evals run <project>`.

## Application projects (Spec Kit)

For building an application rather than an agent workflow, `awd-builder app` sets up a project with [GitHub Spec Kit](https://github.com/github/spec-kit) for your coding agent.

1. Write an app plan template into the project:

   ```
   awd-builder app init
   ```

   Edit `<project>/app-workflow-plan.yaml`. Set `harnesses` to one or more of `opencode`, `claude-code`, `codex`, `github-copilot`, `pi`, and `cursor`. `app run` maps these names to Spec Kit integration keys and initializes/installs all selected integrations. Set `folders` and the `extensions` to install (`assess` for idea assessment, `bug` for bug fixing). The older single `integration` field remains supported.

2. Preview, then scaffold:

   ```
   awd-builder app run <project> --dry-run
   awd-builder app run <project>
   ```

   The scaffold installs `uv` if it is missing. On every non-dry-run invocation, it runs `uv tool install --upgrade specify-cli` to install or upgrade Spec Kit to the latest version—even when `specify` is already on `PATH`; `--dry-run` only previews this action. It verifies every requested integration against `specify integration list`, initializes the project with the first integration, and installs the remaining missing integrations and extensions. Because Spec Kit registers extensions only for the active integration, `app run` activates each selected integration to register the extensions for it, then leaves the first integration active. Re-running with the same plan skips extensions that are already installed and refreshes their registrations for the selected integrations. Removing an integration from the plan does not uninstall it. Use `awd-builder sync <project> --plan app-workflow-plan.yaml` to re-sync canonical skills and workflow components for the app's selected harnesses.

## Commands

| Command                        | Purpose                                                           |
| ------------------------------ | ----------------------------------------------------------------- |
| `awd-builder scaffold init [p]` | Write a `workflow-plan.yaml` template into a project               |
| `awd-builder scaffold run [p]`  | Generate canonical workflow files and sync the selected harnesses  |
| `awd-builder evals init [p]`    | Generate routing eval cases in `evals/routing.yaml`                 |
| `awd-builder evals run [p]`     | Run routing evals and save a JSON report to `evals/results.json`     |
| `awd-builder sync <p>`          | Sync canonical `.agents` components to selected harnesses           |
| `awd-builder overrides init [p] --harness H --agent A` | Create a starter harness-specific agent override YAML |
| `awd-builder app init [p]`      | Write an `app-workflow-plan.yaml` template into a project            |
| `awd-builder app run [p]`       | Scaffold a Spec Kit app for all selected harness integrations        |

`[p]` is an optional project folder and defaults to the current folder. `sync` still requires its project folder.

Run any command with `--help` for all options.

## Output locations

| Harness | Agents | Skills | Commands |
| --- | --- | --- | --- |
| OpenCode | `.opencode/agents/` | `.agents/skills/` | `.opencode/commands/` |
| Claude Code | `.claude/agents/` | `.claude/skills/` (synced from `.agents/skills/`) | `.claude/commands/` |
| Codex | `.codex/agents/` (TOML) | `.agents/skills/` | `.agents/skills/awd-command-*` fallback |
| GitHub Copilot | `.github/agents/` | `.agents/skills/` | `.github/prompts/` prompt files |
| Pi | `.agents/skills/awd-agent-*` fallback | `.agents/skills/` | `.pi/prompts/` |
| Cursor | `.cursor/agents/` | `.cursor/skills/` (synced from `.agents/skills/`) | `.cursor/commands/` |

All canonical agent and command sources live under `.agents/agents/` and `.agents/commands/`. The generator is currently Claude Code or OpenCode; the target harnesses are configured separately in the plan. Routing evals run through the configured generator. Private memory stays in `.awd-builder/memory/memories.json` and is ignored by git.

The external `skill-creator` and `command-creator` skills are installed by `npx skills` for the selected generator. For Codex and Pi, agents or commands that do not have a native equivalent are exposed as best-effort skills or prompt templates; the sync command reports these fallbacks.

## Development

```
git clone https://github.com/rjasino/awd-builder.git
cd awd-builder
python -m venv .venv
.venv\Scripts\activate
pip install -e .
awd-builder --help
```

### Test the checkout in a temporary environment (Windows PowerShell)

To try the current checkout without changing a globally installed `awd-builder`, create a virtual environment outside the repository. Run these commands from the repository root and use a disposable test project; a normal scaffold run can invoke external installers and agent generators.

```powershell
$testRoot = Join-Path $env:TEMP "awd-builder-test-$(Get-Date -Format yyyyMMdd-HHmmss)"
py -3.13 -m venv "$testRoot\venv"
& "$testRoot\venv\Scripts\python.exe" -m pip install -e .
& "$testRoot\venv\Scripts\awd-builder.exe" --version
& "$testRoot\venv\Scripts\awd-builder.exe" scaffold run "C:\path\to\test-project" --dry-run
```

After reviewing the dry run, omit `--dry-run` to scaffold the test project. Change `3.13` to an installed Python version 3.9 or newer if needed. This environment uses the current source checkout and does not replace the global CLI. Removing it does **not** undo files written to the test project.

When finished, remove only the temporary environment:

```powershell
Remove-Item -Recurse -Force "$testRoot"
```

Local testing does not require a Git tag or push. Tag and push only when you intend to publish the tested code.

### Tag and push a release

1. Update `__version__` in `src/awd_builder/__init__.py` to the next unused version (for example, `0.1.6`), then run the tests and review `git status`.
2. Commit the release changes, then create a tag whose version matches `__version__`. Do not reuse an existing tag.

   ```powershell
   git add <the-files-being-released>
   git commit -m "Release v0.1.6"
   git tag v0.1.6
   ```

3. Push the branch and the tag to GitHub:

   ```powershell
   git push origin main
   git push origin v0.1.6
   ```

   Replace `0.1.6` with the version you set, and `main` with the release branch if different. The tag makes the release installable using the version-pinning command in [Install](#install).

Source layout:

| Path                                   | Purpose                                 |
| -------------------------------------- | --------------------------------------- |
| `src/awd_builder/cli.py`               | Command-line entry point                |
| `src/awd_builder/scaffold.py`          | `scaffold` command                      |
| `src/awd_builder/app.py`               | `app` command (Spec Kit project)        |
| `src/awd_builder/evals.py`             | `evals` command                         |
| `src/awd_builder/lib.py`               | Plan validation and agent CLI helpers   |
| `src/awd_builder/templates/`           | Plan template                           |
| `src/awd_builder/skills/eval-creator/` | Skill that writes the routing eval file |
| `src/awd_builder/skills/workflow-memory/` | Private memory instructions copied into scaffolded workflows |
| `src/awd_builder/commands/`           | Built-in workflow commands copied into projects |
| `docs/`                                | Notes and the original plan             |
