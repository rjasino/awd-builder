# awd-builder

Scaffold an agentic workflow (agents, skills, commands, folders, and routing evals) for Claude Code or OpenCode from one YAML plan.

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

## Quick start

1. Create a plan in your project:

   ```
   awd-builder init --target <project>
   ```

   Edit `<project>/workflow-plan.yaml`. Set `tool` to `claude-code` or `opencode`, and list the folders, agents, skills, and commands you want.

   Set `model` to the model name your tool accepts, for example `sonnet` for claude-code or `opencode-go/claude-haiku-5-5` for opencode. It is used for scaffolding and the routing evals. Each agent can set its own `model` to override it. Leave both out to use the tool's default.

2. Preview, then scaffold:

   ```
   awd-builder scaffold --target <project> --dry-run
   awd-builder scaffold --target <project>
   ```

   The scaffold creates the folders, installs `skill-creator` (anthropics/skills) and `command-creator` (softaworks/agent-toolkit) with `npx skills`, copies the `eval-creator` skill into the project, then asks your agent to write each agent, skill, and command. Each agent call costs tokens, so use `--dry-run` first.

3. Create routing evals. In the project, ask your agent to use the `eval-creator` skill. It writes `evals/routing.yaml`.

4. Run the routing evals:

   ```
   awd-builder evals --target <project>
   ```

   Options: `--dry-run` prints the prompts without calling the agent, `--only <id>` runs one case. The exit code is 0 when every case passes, 1 when any fails, and 2 on a configuration error.

## Commands

| Command                | Purpose                                                           |
| ---------------------- | ----------------------------------------------------------------- |
| `awd-builder init`     | Write a `workflow-plan.yaml` template into a project              |
| `awd-builder scaffold` | Create the folders, external skills, and components from the plan |
| `awd-builder evals`    | Run the routing evals in `evals/routing.yaml`                     |

Run any command with `--help` for all options.

## Output locations

| Component     | Claude Code                                | OpenCode                           |
| ------------- | ------------------------------------------ | ---------------------------------- |
| Agents        | `.claude/agents/<name>.md`                 | `.opencode/agents/<name>.md`       |
| Skills        | `.claude/skills/<name>/SKILL.md`           | `.opencode/skills/<name>/SKILL.md` |
| Commands      | `.claude/commands/<name>.md`               | `.opencode/commands/<name>.md`     |
| Routing evals | `evals/routing.yaml` (same for both tools) |                                    |

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

Source layout:

| Path                                   | Purpose                                 |
| -------------------------------------- | --------------------------------------- |
| `src/awd_builder/cli.py`               | Command-line entry point and `init`     |
| `src/awd_builder/scaffold.py`          | `scaffold` command                      |
| `src/awd_builder/evals.py`             | `evals` command                         |
| `src/awd_builder/lib.py`               | Plan validation and agent CLI helpers   |
| `src/awd_builder/templates/`           | Plan template                           |
| `src/awd_builder/skills/eval-creator/` | Skill that writes the routing eval file |
| `docs/`                                | Notes and the original plan             |
