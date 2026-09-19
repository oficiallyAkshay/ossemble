"""The `ossemble floor` subcommand: raises the coverage floor to the achieved number.

Reads a coverage.py XML report, computes the combined line-and-branch
percentage coverage.py itself would print as TOTAL, rounds it down to a
whole number, and raises `fail_under` in `pyproject.toml` to that number.
It never lowers `fail_under`, even if the achieved number is lower.
"""

from __future__ import annotations

import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

FAIL_UNDER_LINE = re.compile(
    r"^(?P<prefix>fail_under\s*=\s*)(?P<value>\d+)(?P<trailing>[ \t]*)$", re.MULTILINE
)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `floor` subcommand and wire it to `run`."""
    parser = subparsers.add_parser(
        "floor", help="raise the coverage floor in pyproject.toml to the achieved number"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="the repo whose pyproject.toml to update (default: the current directory)",
    )
    parser.add_argument("--coverage-xml", required=True, help="the coverage.py XML report to read")
    parser.set_defaults(run=run)
    return parser


def run(args: argparse.Namespace) -> int:
    """Raise `pyproject.toml`'s `fail_under` to the achieved coverage, never lowering it."""
    root = _resolve_target_root(args.path)
    if root is None:
        return 1

    achieved = _resolve_achieved_coverage(args.coverage_xml)
    if achieved is None:
        return 1

    message = _raise_fail_under(root / "pyproject.toml", achieved)
    if message is None:
        return 1

    print(message)
    return 0


def _resolve_target_root(path_arg: str) -> Path | None:
    """Resolve `path_arg` to a real directory, or print one line and return None."""
    root = Path(path_arg)
    if root.is_symlink():
        print("ossemble floor: refusing to follow a symlink as the target path", file=sys.stderr)
        return None
    if not root.is_dir():
        print(f"ossemble floor: {path_arg} is not a directory", file=sys.stderr)
        return None
    return root.resolve()


def _resolve_achieved_coverage(coverage_xml_arg: str) -> int | None:
    """Read the achieved coverage percentage from `coverage_xml_arg`.

    Prints one line and returns None on failure.
    """
    coverage_xml = Path(coverage_xml_arg)
    if coverage_xml.is_symlink():
        print(
            "ossemble floor: refusing to follow a symlink as the coverage XML file", file=sys.stderr
        )
        return None

    achieved = _achieved_percent(coverage_xml)
    if achieved is None:
        print(
            f"ossemble floor: cannot read achieved coverage from {coverage_xml_arg}",
            file=sys.stderr,
        )
        return None
    return achieved


def _raise_fail_under(pyproject_path: Path, achieved: int) -> str | None:
    """Raise `fail_under` in `pyproject_path` to `achieved`, or print one line and return None.

    Returns the one line to print on success, whether or not the floor
    actually moved; never lowers `fail_under`.
    """
    if pyproject_path.is_symlink():
        print("ossemble floor: refusing to follow a symlink as pyproject.toml", file=sys.stderr)
        return None
    try:
        text = pyproject_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ossemble floor: cannot read {pyproject_path}: {exc}", file=sys.stderr)
        return None

    match = FAIL_UNDER_LINE.search(text)
    if not match:
        print("ossemble floor: no fail_under line found in pyproject.toml", file=sys.stderr)
        return None

    current = int(match.group("value"))
    new_value = max(current, achieved)
    if new_value == current:
        return f"fail_under stays at {current}; achieved coverage is {achieved}"

    updated = (
        text[: match.start()]
        + f"{match.group('prefix')}{new_value}{match.group('trailing')}"
        + text[match.end() :]
    )
    try:
        pyproject_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        print(f"ossemble floor: cannot write {pyproject_path}: {exc}", file=sys.stderr)
        return None

    return f"fail_under raised from {current} to {new_value}"


def _achieved_percent(coverage_xml: Path) -> int | None:
    try:
        # This repo's own coverage.py output, never a document from outside
        # the build; defusedxml is not an option since only the standard
        # library is a runtime dependency here.
        tree = ET.parse(coverage_xml)  # noqa: S314 -- this repo's own trusted output
    except (OSError, ET.ParseError):
        return None
    root_element = tree.getroot()

    try:
        lines_covered = float(root_element.get("lines-covered", "0"))
        lines_valid = float(root_element.get("lines-valid", "0"))
        branches_covered = float(root_element.get("branches-covered", "0"))
        branches_valid = float(root_element.get("branches-valid", "0"))
    except (TypeError, ValueError):
        return None

    total_valid = lines_valid + branches_valid
    if total_valid <= 0:
        return None
    percent = (lines_covered + branches_covered) / total_valid * 100
    return math.floor(percent)
