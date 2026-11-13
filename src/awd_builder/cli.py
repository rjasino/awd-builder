"""Command-line entry point: awd-builder <command>."""

import argparse
import sys

from . import __version__, app, evals, overrides, scaffold, sync


def build_parser():
    parser = argparse.ArgumentParser(
        prog="awd-builder",
        description=(
            "Scaffold canonical agent workflows and sync them to OpenCode, Claude Code, Codex, "
            "GitHub Copilot, Pi, or Cursor; run routing evals and scaffold Spec Kit applications."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")

    scaffold.register(subparsers)
    app.register(subparsers)
    evals.register(subparsers)
    sync.register(subparsers)
    overrides.register(subparsers)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Keep the original `evals <project>` runner invocation working after
    # introducing `evals init` and `evals run` subcommands.
    if argv and argv[0] == "evals" and (
        len(argv) == 1 or argv[1] not in {"init", "run", "diagnose", "-h", "--help"}
    ):
        argv.insert(1, "run")
    args = build_parser().parse_args(argv)
    return args.func(args)
