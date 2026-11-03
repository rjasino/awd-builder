"""Command-line entry point: awd-builder <command>."""

import argparse

from . import __version__, app, evals, scaffold, sync


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
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
