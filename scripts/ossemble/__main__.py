"""The ossemble CLI entry point: `python3 scripts/ossemble <subcommand>`.

This module only parses arguments and dispatches; each subcommand's own
behaviour lives in its sibling module (audit, scaffold, name, resume,
floor).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Parse argv and run the chosen subcommand, returning its exit code."""
    # Running this file as `python3 scripts/ossemble` already puts this
    # directory on sys.path, but importing it as a regular module (as the
    # test suite does) does not, so the insert happens here, once, before
    # the sibling imports below.
    package_dir = str(Path(__file__).resolve().parent)
    if package_dir not in sys.path:
        sys.path.insert(0, package_dir)

    import audit
    import floor
    import name
    import resume
    import scaffold

    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    for module in (audit, scaffold, name, resume, floor):
        module.add_parser(subparsers)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":  # pragma: no cover -- exercised by running the script, not by unit tests
    sys.exit(main())
