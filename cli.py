"""Command-line entry point: awd-builder <command>."""

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__, evals, scaffold
from .lib import PLAN_FILE, PLAN_TEMPLATE


def run_init(args):
    target = Path(args.target).resolve()
    dest = target / PLAN_FILE
    if dest.exists() and not args.force:
        print(f"error: {dest} already exists (use --force to overwrite)", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLAN_TEMPLATE, dest)
    print(f"Wrote {dest}")
    print(f'Edit it, then run: awd-builder scaffold --target "{target}"')
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="awd-builder",
        description=(
            "Scaffold agentic workflows (agents, skills, commands, folders) for Claude Code "
            "or OpenCode from a YAML plan, and run workflow-wide routing evals."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")

    init = subparsers.add_parser("init", help=f"write a {PLAN_FILE} template into a project")
    init.add_argument("--target", default=".", help="project folder (default: current folder)")
    init.add_argument("--force", action="store_true", help="overwrite an existing plan")
    init.set_defaults(func=run_init)

    scaffold.register(subparsers)
    evals.register(subparsers)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
