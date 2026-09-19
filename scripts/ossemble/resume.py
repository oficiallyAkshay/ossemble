"""The `ossemble resume` subcommand.

Every sitting starts here: a cheap, deterministic check of the
environment, the repo's stage (read from its coverage floor, never
stored), the regressions a live audit finds, any gate the agent lowered,
and the next runbook step. `audit` is never imported at module import
time: the import happens inside `_audit_check`, lazily, so a missing or
broken sibling module degrades this one check instead of breaking every
other subcommand.

Regressions are found by comparing the current gap ids from `audit.gaps`
against the baseline recorded the last time `resume` ran, stored in
`.ossemble/state.json` under `checks.audit`. A gap id present now and
absent from that baseline is a regression. After reporting, the baseline
is written back for next time.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

_TOOLS = ("git", "gh", "uv")
_NOREPLY_SUFFIX = "@users.noreply.github.com"
_STATE_RELATIVE_PATH = ".ossemble/state.json"
_LIST_KEYS = ("shapes", "gos", "lowered", "findings")
_DICT_KEYS = ("scope", "optins", "prior_art", "checks")


def add_parser(subparsers):
    """Register the `resume` subcommand and wire it to `run`."""
    parser = subparsers.add_parser("resume", help="check the environment, stage and next step")
    parser.add_argument("path", nargs="?", default=".", help="the repo to resume (default: .)")
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON instead of lines"
    )
    parser.set_defaults(run=run)
    return parser


def run(args) -> int:
    """Print the environment, stage, regressions, lowered gates and next step."""
    path = Path(args.path)

    environment = _check_environment(path)
    stage, coverage_floor = _read_stage(path)
    state, state_error = _read_state(path)
    lowered = state.get("lowered", [])
    regressions, gap_count, new_baseline = _audit_check(path, state)
    next_step = _next_step(environment, stage, lowered)

    report = {
        "environment": environment,
        "stage": stage,
        "coverage_floor": coverage_floor,
        "regressions": regressions,
        "gaps": gap_count,
        "lowered": lowered,
        "next_step": next_step,
    }

    if state_error:
        print(f"ossemble resume: {state_error}", file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for line in _format_report(report):
            print(line)

    if new_baseline is not None and state_error is None:
        _write_baseline(path, new_baseline)

    return 0 if environment["ok"] and state_error is None else 1


def _check_environment(path: Path) -> dict:
    """Report which required tools are on PATH and whether identity is set."""
    tools = {tool: shutil.which(tool) is not None for tool in _TOOLS}
    identity = tools["git"] and _has_noreply_identity(path)
    return {**tools, "identity": identity, "ok": all(tools.values()) and identity}


def _has_noreply_identity(path: Path) -> bool:
    """Check that the repo-local git identity is a no-reply GitHub address."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    return result.stdout.strip().endswith(_NOREPLY_SUFFIX)


def _read_stage(path: Path) -> tuple[str, float | None]:
    """Read the coverage floor from pyproject.toml and derive the stage from it."""
    try:
        with (path / "pyproject.toml").open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return "unknown", None
    fail_under = data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if not isinstance(fail_under, (int, float)) or isinstance(fail_under, bool):
        return "unknown", None
    return ("finish" if fail_under >= 100 else "build"), fail_under


def _read_state(path: Path) -> tuple[dict, str | None]:
    """Read and shape-check .ossemble/state.json, defaulting to empty if absent."""
    state_file = path / _STATE_RELATIVE_PATH
    if state_file.is_symlink():
        return {}, f"{_STATE_RELATIVE_PATH} is a symlink, refused"
    if not state_file.exists():
        return {}, None
    try:
        data = json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return {}, f"{_STATE_RELATIVE_PATH} could not be read: {error}"
    if not isinstance(data, dict):
        return {}, f"{_STATE_RELATIVE_PATH} must hold a JSON object"
    problems = sorted(
        [key for key in _LIST_KEYS if key in data and not isinstance(data[key], list)]
        + [key for key in _DICT_KEYS if key in data and not isinstance(data[key], dict)]
    )
    if problems:
        return {}, f"{_STATE_RELATIVE_PATH} has the wrong shape for: {', '.join(problems)}"
    return data, None


def _audit_check(path: Path, state: dict) -> tuple[str, int, dict | None]:
    """Run a live audit and compare it to the recorded baseline.

    Returns (regressions text, current gap count, the new `checks.audit`
    baseline to write back, or None when there is nothing to write).
    """
    try:
        import audit as audit_module
    except ImportError:
        return "audit not available", 0, None

    try:
        gap_ids = sorted(row["id"] for row in audit_module.gaps(path))
    except (AttributeError, TypeError, ValueError, KeyError, RuntimeError, OSError):
        return "audit not available", 0, None

    commit = _head_commit(path)
    if commit is None:
        return "no baseline", len(gap_ids), None

    baseline = state.get("checks", {}).get("audit") or {}
    if baseline:
        new_ids = sorted(set(gap_ids) - set(baseline.get("gaps", [])))
        regressions = ", ".join(new_ids) if new_ids else "none"
    else:
        regressions = "none"

    new_baseline = {
        "commit": commit,
        "hash": _rules_hash(audit_module),
        "gaps": gap_ids,
    }
    return regressions, len(gap_ids), new_baseline


def _head_commit(path: Path) -> str | None:
    """The repo's current commit sha, or None when it has no commits yet."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _rules_hash(audit_module) -> str | None:
    """A sha256 of the rules.json audit scored against."""
    try:
        text = audit_module._rules_path().read_text(encoding="utf-8")
    except OSError:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_baseline(path: Path, new_baseline: dict) -> None:
    """Write the new audit baseline into .ossemble/state.json, keeping every other key."""
    state_file = path / _STATE_RELATIVE_PATH
    if state_file.is_symlink():
        return
    try:
        raw = state_file.read_text(encoding="utf-8") if state_file.exists() else "{}"
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}

    checks = data.get("checks")
    data["checks"] = checks if isinstance(checks, dict) else {}
    data["checks"]["audit"] = new_baseline

    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


def _next_step(environment: dict, stage: str, lowered: list) -> str:
    """Name the single next action for this sitting."""
    if not environment["ok"]:
        parts = []
        missing = [tool for tool in _TOOLS if not environment[tool]]
        if missing:
            parts.append(f"install {', '.join(missing)}")
        if not environment["identity"]:
            parts.append("set a no-reply git identity")
        return "fix the environment: " + "; ".join(parts)
    if stage == "unknown":
        return (
            "no ossemble scaffolding found; read references/build-runbook.md for a new repo "
            "or references/modify-runbook.md for an existing one"
        )
    if lowered:
        names = ", ".join(sorted(str(entry.get("gate", "?")) for entry in lowered))
        return f"raise the lowered gate(s) ({names}) back to their finish value"
    if stage == "finish":
        return "the repo is at the finish stage; read references/build-runbook.md from the review step on"
    return "continue the build stage; read references/build-runbook.md"


def _format_report(report: dict) -> list[str]:
    """Turn the report dict into the fixed set of human-readable lines."""
    env = report["environment"]
    lines = [f"environment: {'ok' if env['ok'] else 'not ok'}"]
    if not env["ok"]:
        missing = [tool for tool in _TOOLS if not env[tool]]
        if missing:
            lines.append(f"  missing: {', '.join(missing)}")
        if not env["identity"]:
            lines.append("  identity: not a no-reply git identity")
    floor_text = (
        f" (coverage floor {report['coverage_floor']})"
        if report["coverage_floor"] is not None
        else ""
    )
    lines.append(f"stage: {report['stage']}{floor_text}")
    lines.append(f"gaps: {report['gaps']}")
    lines.append(f"regressions: {report['regressions']}")
    if report["lowered"]:
        entries = "; ".join(
            f"{entry.get('gate', '?')} ({entry.get('from', '?')} -> {entry.get('to', '?')}): {entry.get('why', '')}"
            for entry in report["lowered"]
        )
        lines.append(f"lowered: {entries}")
    else:
        lines.append("lowered: none")
    lines.append(f"next step: {report['next_step']}")
    return lines
