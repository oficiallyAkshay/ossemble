"""The `ossemble scaffold` subcommand: not built yet."""

from __future__ import annotations

import sys


def add_parser(subparsers):
    """Register the `scaffold` subcommand and wire it to `run`."""
    parser = subparsers.add_parser("scaffold", help="scaffold a new repo (not built yet)")
    parser.set_defaults(run=run)
    return parser


def run(args) -> int:
    """Print the not-built-yet stub message and report failure."""
    print("ossemble scaffold: not built yet", file=sys.stderr)
    return 1
