"""Command-line entry point: awd-builder <command>."""

import argparse

from . import __version__, app, evals, scaffold


def build_parser():
    parser = argparse.ArgumentParser(
        prog="awd-builder",
        description=(
            "Scaffold agentic workflows (agents, skills, commands, folders) for Claude Code "
            "or OpenCode from a YAML plan, run workflow-wide routing evals, and scaffold "
            "application projects with GitHub Spec Kit."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")

    scaffold.register(subparsers)
    app.register(subparsers)
    evals.register(subparsers)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
