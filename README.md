# awd-builder

Scaffold an agentic workflow (agents, skills, commands, private memory, folders, and routing evals) for Claude Code or OpenCode from one YAML plan.

## Prerequisites

- Python 3.9 or newer
- Node.js (provides `npx`, used to install `skill-creator` and `command-creator`)
- Claude Code (`claude`) or OpenCode (`opencode`) on your PATH and signed in

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

1. Create a plan in your project. Use `.` for the current folder, or the path of the project:

   ```
   awd-builder scaffold init .
   ```

   Edit `<project>/workflow-plan.yaml`. Set `tool` to `claude-code` or `opencode`, and list the folders, agents, skills, and commands you want.

   Set `model` to the model name your tool accepts, for example `sonnet` for claude-code or `opencode-go/claude-haiku-5-5` for opencode. It is used for scaffolding and the routing evals. Each agent can set its own `model` to override it. Leave both out to use the tool's default.

2. Preview, then scaffold:

   ```
   awd-builder scaffold run <project> --dry-run
   awd-builder scaffold run <project>
   ```

   The scaffold creates the folders, installs `skill-creator` (anthropics/skills) and `command-creator` (softaworks/agent-toolkit) with `npx skills`, copies the built-in `eval-creator` and `workflow-memory` skills, installs a `/memory` command, and then asks your agent to write each planned agent, skill, and command. Each agent call costs tokens, so use `--dry-run` first.

   The generated workflow has private, project-local memory at `.awd-builder/memory/memories.json`; the scaffold adds it to the project's `.gitignore`. Generated agents are instructed to recall relevant memories and ask before saving useful new information. Use `/memory remember`, `/memory recall`, `/memory forget`, `/memory compact`, `/memory export`, or `/memory import` to manage it. Memory export/import are performed by the generated workflow, not by `awd-builder`. The built-in skill/command names `workflow-memory` and `memory` are reserved.

3. Create routing evals. In the project, ask your agent to use the `eval-creator` skill. It writes `evals/routing.yaml`.

4. Run the routing evals:

   ```
   awd-builder evals <project>
   ```

   Options: `--dry-run` prints the prompts without calling the agent, `--only <id>` runs one case. The exit code is 0 when every case passes, 1 when any fails, and 2 on a configuration error.

## Application projects (Spec Kit)

For building an application rather than an agent workflow, `awd-builder app` sets up a project with [GitHub Spec Kit](https://github.com/github/spec-kit) for your coding agent.

1. Write an app plan template into the project:

   ```
   awd-builder app init .
   ```

   Edit `<project>/app-workflow-plan.yaml`. Set `integration` to a Spec Kit integration key such as `claude`, `codex`, `copilot`, `cursor-agent`, `opencode`, or `pi`. Set `folders` and the `extensions` to install (`assess` for idea assessment, `bug` for bug fixing).

2. Preview, then scaffold:

   ```
   awd-builder app run <project> --dry-run
   awd-builder app run <project>
   ```

   The scaffold installs `uv` if it is missing, then installs the latest `specify-cli` with `uv tool install` if `specify` is missing. It checks the integration key against `specify integration list` and stops before changing anything if the key is not supported. Then it creates the folders, runs `specify init --integration <key>`, and installs the extensions. Running it again skips what is already in place.

## Commands

| Command                        | Purpose                                                           |
| ------------------------------ | ----------------------------------------------------------------- |
| `awd-builder scaffold init <p>` | Write a `workflow-plan.yaml` template into a project              |
| `awd-builder scaffold run <p>`  | Create the folders, external skills, planned components, and private memory |
| `awd-builder evals <p>`        | Run the routing evals in `evals/routing.yaml`                     |
| `awd-builder app init <p>`     | Write an `app-workflow-plan.yaml` template into a project         |
| `awd-builder app run <p>`      | Scaffold the application project with Spec Kit from the plan      |

`<p>` is the project folder. Use `.` for the current folder.

Run any command with `--help` for all options.

## Output locations

| Component     | Claude Code                                | OpenCode                           |
| ------------- | ------------------------------------------ | ---------------------------------- |
| Agents        | `.claude/agents/<name>.md`                 | `.opencode/agents/<name>.md`       |
| Skills        | `.claude/skills/<name>/SKILL.md`           | `.opencode/skills/<name>/SKILL.md` |
| Commands      | `.claude/commands/<name>.md`               | `.opencode/commands/<name>.md`     |
| Routing evals | `evals/routing.yaml` (same for both tools) |                                    |
| Private memory | `.awd-builder/memory/memories.json` (ignored by git) | `.awd-builder/memory/memories.json` (ignored by git) |

The external `skill-creator` and `command-creator` skills are installed by `npx skills`. They go to `.claude/skills/` for Claude Code and to `.agents/skills/` for OpenCode, which reads that folder too.

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
