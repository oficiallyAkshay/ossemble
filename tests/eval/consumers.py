"""The consumers eval: freezes `ossemble audit`'s output on real-world repos.

False positives found by auditing popular public repos were the main
source of probe fixes in the battle test of 2026-09-19. This eval freezes
that: each repo is pinned to a commit, the audit's rows on it are stored
in `tests/eval/consumers.json`, and a probe change that alters them must
update the snapshot in the same pull request, where a reviewer sees
exactly which rows appeared or vanished.

Run as `python3 tests/eval/consumers.py [--clone-dir DIR] [--update]
[--only owner/name]`. Standard library only; it clones each pinned repo
(shallow, at its exact commit) into a clone directory outside the repo
(never a gate file, never anything git-tracked), runs `ossemble audit
--json` against it, and compares the result with the stored snapshot.
`--update` rewrites the snapshot instead of failing on a difference.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

# Sorted by "owner/name", the same order the snapshot file is kept in.
REPOS: tuple[tuple[str, str], ...] = (
    ("actions/checkout", "f548e57e544e1ff5a4c46bf1e1b8685f8e4a348a"),
    ("anthropics/skills", "34040c9c568585f6929bedeaad110ad08f079624"),
    ("astral-sh/setup-uv", "f5548c55522a1db0af3c84f2af3d058bc9bc2de2"),
    ("github/ruleset-recipes", "82adf8954a5cafb9722c18c421b9834c24ec0cd0"),
    ("hynek/structlog", "73393f34b40c15688b3fdd0982889b225f11b59b"),
    ("oficiallyAkshay/clonometer", "2c82a8779a68d2babb1e5e856d2ae69253dcd611"),
    ("ossf/scorecard-action", "e8e61e86ea0a152be84d03729c02a7300065c17d"),
    ("pypa/pipx", "cba4115aa7589306560e62dd42e9259340744e7d"),
    ("python-attrs/attrs", "8f767776326faaed11e6c2974798787f6e19b343"),
    ("sethvargo/ratchet", "a7ead07a89972fef4316ad196af18f87ac77bb97"),
    ("step-security/harden-runner", "e14015d583714f6e62063499dc959a02595150a1"),
    ("vercel-labs/agent-skills", "063bee94c3f4df8453406c830b0a7df0f2860278"),
    ("zizmorcore/zizmor", "e5b9690d7341830c494cdd24f1803623917873d9"),
)


class _EvalError(RuntimeError):
    """A failure the eval reports as one stderr line, never a traceback."""


def _repo_root() -> Path:
    """The ossemble repo root, three levels up from this file (`tests/eval/consumers.py`)."""
    return Path(__file__).resolve().parent.parent.parent


def _default_clone_dir() -> Path:
    """`$RUNNER_TEMP/consumers` when set (a CI runner), else a system temp directory.

    Never inside the repo: nothing this eval clones is ever a file git
    needs to know about, so there is nothing to `.gitignore`.
    """
    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        return Path(runner_temp) / "consumers"
    return Path(tempfile.gettempdir()) / "ossemble-consumers"


# --------------------------------------------------------------------- cloning


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run `git <args>` in `cwd`, capturing output; never raises for a non-zero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_git_step(cwd: Path, repo: str, step: str, *args: str) -> None:
    """Run a git step that must succeed; raise `_EvalError` naming `step` when it does not."""
    result = _git(cwd, *args)
    if result.returncode != 0:
        raise _EvalError(f"{step} failed for {repo}: {result.stderr.strip()}")


def _current_commit(cwd: Path) -> str | None:
    """The commit currently checked out at `cwd`, or None when that cannot be read."""
    result = _git(cwd, "rev-parse", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _fetch_and_checkout(path: Path, repo: str, commit: str) -> None:
    """Shallow-fetch `commit` from `origin` and detach `path`'s HEAD onto it."""
    _run_git_step(
        path,
        repo,
        "git fetch",
        "-c",
        "protocol.version=2",
        "fetch",
        "-q",
        "--depth",
        "1",
        "origin",
        commit,
    )
    _run_git_step(path, repo, "git checkout", "checkout", "-q", "--detach", "FETCH_HEAD")


def _ensure_clone(clone_dir: Path, repo: str, commit: str) -> Path:
    """Make sure `repo` is checked out at `commit` under `clone_dir`; return its path.

    Missing: init a bare-ish working repo, add `origin`, fetch and check
    out `commit`. Present at the wrong commit: fetch and check out again,
    without redoing init or remote add. Present at the right commit:
    nothing.
    """
    owner, name = repo.split("/", 1)
    path = clone_dir / f"{owner}-{name}"
    if not path.is_dir():
        path.mkdir(parents=True)
        _run_git_step(path, repo, "git init", "init", "-q")
        _run_git_step(
            path,
            repo,
            "git remote add",
            "remote",
            "add",
            "origin",
            f"https://github.com/{repo}.git",
        )
        _fetch_and_checkout(path, repo, commit)
    elif _current_commit(path) != commit:
        _fetch_and_checkout(path, repo, commit)
    return path


# --------------------------------------------------------------------- auditing


def _run_audit(repo_root: Path, clone_path: Path) -> subprocess.CompletedProcess[str]:
    """Run `ossemble audit --json` against `clone_path`, with `repo_root` as cwd."""
    return subprocess.run(
        [sys.executable, "scripts/ossemble", "audit", "--json", str(clone_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def _audit_rows(repo_root: Path, clone_path: Path, repo: str) -> list[str]:
    """The audit's rows on `clone_path`, as sorted `"ID  FILE"` strings, duplicates kept."""
    result = _run_audit(repo_root, clone_path)
    if result.returncode not in (0, 1):
        raise _EvalError(f"audit crashed on {repo}: exit {result.returncode}")
    try:
        objects = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _EvalError(f"audit produced invalid JSON for {repo}: {exc}") from exc
    return sorted(f"{obj['id']}  {obj['file']}" for obj in objects)


# --------------------------------------------------------------------- snapshot


def _load_snapshot(path: Path) -> dict[str, dict]:
    """The stored snapshot, keyed by repo. Empty when the file does not exist yet."""
    if not path.is_file():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _EvalError(f"could not parse {path.name}: {exc}") from exc
    return {entry["repo"]: entry for entry in entries}


def _write_snapshot(path: Path, entries_by_repo: dict[str, dict]) -> None:
    """Rewrite the snapshot file, sorted by repo, keys ordered repo, commit, rows."""
    ordered = [
        {"repo": entry["repo"], "commit": entry["commit"], "rows": entry["rows"]}
        for entry in sorted(entries_by_repo.values(), key=lambda entry: entry["repo"])
    ]
    path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")


def _diff(repo: str, stored_rows: list[str], current_rows: list[str]) -> tuple[list[str], bool]:
    """Lines describing the difference between `stored_rows` and `current_rows`.

    Multiset comparison, since a row may repeat (a rule can fire once per
    workflow file). Returns the printable lines and whether they differ.
    """
    stored_counts = Counter(stored_rows)
    current_counts = Counter(current_rows)
    added = sorted((current_counts - stored_counts).elements())
    vanished = sorted((stored_counts - current_counts).elements())
    if not added and not vanished:
        return [f"{repo}  ok"], False
    lines = [f"{repo}  +{len(added)} -{len(vanished)}"]
    lines.extend(f"+ {row}" for row in added)
    lines.extend(f"- {row}" for row in vanished)
    return lines, True


# --------------------------------------------------------------------- cli


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse `--clone-dir`, `--update` and `--only` for `python3 tests/eval/consumers.py`."""
    parser = argparse.ArgumentParser(prog="tests/eval/consumers.py")
    parser.add_argument(
        "--clone-dir", default=None, help="where to clone the pinned repos (default: see below)"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite tests/eval/consumers.json instead of failing",
    )
    parser.add_argument(
        "--only", default=None, metavar="owner/name", help="check a single pinned repo"
    )
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    """Clone each pinned repo, audit it, compare with the snapshot, and report."""
    repo_root = _repo_root()
    snapshot_path = repo_root / "tests" / "eval" / "consumers.json"
    clone_dir = Path(args.clone_dir) if args.clone_dir is not None else _default_clone_dir()

    known_repos = {repo for repo, _commit in REPOS}
    if args.only is not None and args.only not in known_repos:
        raise _EvalError(f"unknown repo: {args.only}")

    targets = [(repo, commit) for repo, commit in REPOS if args.only in (None, repo)]
    stored = _load_snapshot(snapshot_path)
    updated = dict(stored)

    lines: list[str] = []
    any_diff = False
    for repo, commit in targets:
        clone_path = _ensure_clone(clone_dir, repo, commit)
        rows = _audit_rows(repo_root, clone_path, repo)
        stored_rows = stored.get(repo, {}).get("rows", [])
        repo_lines, differs = _diff(repo, stored_rows, rows)
        lines.extend(repo_lines)
        any_diff = any_diff or differs
        updated[repo] = {"repo": repo, "commit": commit, "rows": rows}

    print("\n".join(lines))

    if args.update:
        _write_snapshot(snapshot_path, updated)
        return 0
    return 1 if any_diff else 0


def main(argv: list[str] | None = None) -> int:
    """Parse argv and run the eval, returning its exit code."""
    args = _parse_args(argv)
    try:
        return _run(args)
    except _EvalError as exc:
        print(f"tests/eval/consumers.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover -- exercised by running the script, not by unit tests
    sys.exit(main())
