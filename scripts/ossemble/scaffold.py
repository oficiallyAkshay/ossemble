"""The `ossemble scaffold` subcommand: stamps a template set into a repo."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

_TEMPLATES_ROOT = Path(__file__).resolve().parents[2] / "templates"
_MANIFEST_PATH = _TEMPLATES_ROOT / "manifest.json"


class ScaffoldError(Exception):
    """A scaffold failure with a one-line message, printed and never raised past run()."""


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `scaffold` subcommand and wire it to `run`."""
    parser = subparsers.add_parser("scaffold", help="stamp a template set into a repo")
    parser.add_argument("path", nargs="?", default=".", help="target repo root")
    parser.add_argument("--set", dest="set_name", required=True, help="template set to stamp")
    parser.add_argument(
        "--var",
        dest="variables",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="a template variable, repeatable",
    )
    parser.add_argument(
        "--check", action="store_true", help="report what would change, write nothing"
    )
    parser.set_defaults(run=run)
    return parser


def _load_manifest() -> list[dict]:
    """Read and parse templates/manifest.json, failing with one clear line."""
    try:
        text = _MANIFEST_PATH.read_text(encoding="utf-8")
    except OSError as error:
        raise ScaffoldError(f"cannot read manifest: {error}") from error
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as error:
        raise ScaffoldError(f"manifest is not valid json: {error}") from error
    return manifest


def _parse_variables(raw_variables: list[str]) -> dict[str, str]:
    """Turn a list of KEY=VALUE strings into a dict, or fail on a bad one."""
    variables: dict[str, str] = {}
    for item in raw_variables:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise ScaffoldError(f"--var must be KEY=VALUE, got: {item}")
        variables[key] = value
    return variables


def _render(text: str, variables: dict[str, str]) -> str:
    """Replace every {{KEY}} placeholder in text with its variable's value."""
    rendered = text
    for key, value in variables.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def _stamped_content(entry: dict, variables: dict[str, str]) -> str:
    """Render one manifest entry's template file, failing if a var is missing.

    A var missing from `variables` falls back to the entry's `defaults` when
    one is set for it; only a var with neither a supplied value nor a
    default is a failure.
    """
    needed = entry.get("vars", [])
    defaults = entry.get("defaults", {})
    missing = sorted(name for name in needed if name not in variables and name not in defaults)
    if missing:
        raise ScaffoldError(f"missing --var for {', '.join(missing)}")
    effective = {**defaults, **variables}
    src_path = _TEMPLATES_ROOT / entry["src"]
    try:
        text = src_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ScaffoldError(f"cannot read template {entry['src']}: {error}") from error
    return _render(text, effective)


def _entries_by_dest(manifest: list[dict]) -> dict[str, list[dict]]:
    """Group manifest entries by their destination path."""
    by_dest: dict[str, list[dict]] = {}
    for entry in manifest:
        by_dest.setdefault(entry["dest"], []).append(entry)
    return by_dest


def _is_symlink_in_path(root: Path, dest: str) -> bool:
    """Report whether any component of dest, under root, is a symlink."""
    current = root
    for part in Path(dest).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _known_contents(
    by_dest: dict[str, list[dict]], dest: str, variables: dict[str, str]
) -> list[str]:
    """Render every version of dest that any set in the manifest can produce.

    A sibling entry that needs a variable this call did not supply cannot be
    a known prior stamp for this run, so it is skipped rather than failing
    the whole call.
    """
    contents = []
    for other in by_dest[dest]:
        try:
            contents.append(_stamped_content(other, variables))
        except ScaffoldError:
            continue
    return contents


def _stamp_one(
    root: Path, dest: str, content: str, known_contents: list[str], *, check: bool
) -> str:
    """Write (or, in check mode, plan) one destination file.

    Returns "unchanged", "create", "update" or "drift". "update" only
    happens when the file on disk equals a content this manifest is known to
    have stamped before; anything else on disk is drift, refused untouched.
    """
    if _is_symlink_in_path(root, dest):
        raise ScaffoldError(f"refuses to write through a symlink: {dest}")
    full_dest = root / dest
    if not full_dest.exists():
        if not check:
            full_dest.parent.mkdir(parents=True, exist_ok=True)
            full_dest.write_text(content, encoding="utf-8")
        return "create"
    current_text = full_dest.read_text(encoding="utf-8")
    if current_text == content:
        return "unchanged"
    if current_text in known_contents:
        if not check:
            full_dest.write_text(content, encoding="utf-8")
        return "update"
    return "drift"


def _scaffold(args: argparse.Namespace) -> int:
    """Do the actual work of run(), raising ScaffoldError on any failure."""
    manifest = _load_manifest()
    variables = _parse_variables(args.variables)
    selected = sorted(
        (entry for entry in manifest if entry["set"] == args.set_name),
        key=lambda entry: entry["dest"],
    )
    if not selected:
        raise ScaffoldError(f"no templates in set: {args.set_name}")

    root = Path(args.path).resolve()
    by_dest = _entries_by_dest(manifest)

    any_drift = False
    any_pending = False
    for entry in selected:
        content = _stamped_content(entry, variables)
        known = _known_contents(by_dest, entry["dest"], variables)
        status = _stamp_one(root, entry["dest"], content, known, check=args.check)
        if status == "drift":
            print(f"drift: {entry['dest']}", file=sys.stderr)
            any_drift = True
        elif status != "unchanged":
            if args.check:
                print(f"{status}: {entry['dest']}")
            any_pending = True

    if any_drift:
        return 1
    if args.check and any_pending:
        return 1
    return 0


def run(args: argparse.Namespace) -> int:
    """Stamp, or with --check report drift for, one template set."""
    try:
        return _scaffold(args)
    except ScaffoldError as error:
        print(f"ossemble scaffold: {error}", file=sys.stderr)
        return 1
