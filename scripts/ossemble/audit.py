"""The `ossemble audit` subcommand: scores a repo against `rules/rules.json`.

A probe returns `None` when its rule holds, else an `(file, message)` gap.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

try:
    from . import _git
except ImportError:
    import _git

_CacheT = TypeVar("_CacheT")

ALLOWED_STATE_KEYS = {
    "scope",
    "shapes",
    "optins",
    "prior_art",
    "gos",
    "lowered",
    "findings",
    "checks",
}

LOCKFILE_NAMES = (
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
)

# readmerlin's closed section order (its `sectionOrder` config, readmerlin.mjs). A README
# heading must come from this set, in this order.
README_SECTION_ORDER = [
    "features",
    "in action",
    "fit",
    "how it compares",
    "security and limits",
    "badges",
]
README_ALLOWED_HEADINGS = set(README_SECTION_ORDER)

STEP_START = re.compile(r"^( *)- ", re.MULTILINE)

_BUILD_COVERAGE_FLOOR = 70
_FINISH_COVERAGE_FLOOR = 100
_HUMAN_DOC_LINE_LIMIT = 300

# Every probe reads (root, facts) and returns None when the rule holds, or
# an (file, message) pair naming the gap.
ProbeResult = tuple[str, str] | None


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `audit` subcommand and wire it to `run`."""
    parser = subparsers.add_parser("audit", help="audit an existing repo against rules/rules.json")
    parser.add_argument(
        "path", nargs="?", default=".", help="the repo to audit (default: the current directory)"
    )
    parser.add_argument(
        "--json", dest="as_json", action="store_true", help="print the gap table as JSON"
    )
    parser.add_argument(
        "--api", action="store_true", help="also check repo settings and the ruleset through gh api"
    )
    parser.set_defaults(run=run)
    return parser


class _RuleError(RuntimeError):
    """A rule fails validation: a missing or wrong-typed field, or an unknown probe."""


def rules_path() -> Path:
    """The path to ossemble's own rules/rules.json, never the audited repo's."""
    return Path(__file__).resolve().parents[2] / "rules" / "rules.json"


def _load_rules() -> list[dict]:
    """Load and parse ossemble's own rules.json."""
    path = rules_path()
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


_RULE_KIND_VALUES = ("default", "recommendation")
_RULE_STAGE_VALUES = ("build", "finish")
_RULE_CHECK_VALUES = ("audit", "api", "judgment")
_RULE_REQUIRED_TEXT_FIELDS = ("id", "text", "basis", "category")


def _validate_rules(rules: list[dict]) -> None:
    """Confirm every rule's fields, correctly typed, before any is scored."""
    for index, rule in enumerate(rules):
        rule_id = rule.get("id")
        label = rule_id if isinstance(rule_id, str) and rule_id else f"#{index}"
        for field in _RULE_REQUIRED_TEXT_FIELDS:
            value = rule.get(field)
            if not isinstance(value, str) or not value:
                raise _RuleError(f"rule {label} has a missing or invalid {field!r} field")
        if rule.get("kind") not in _RULE_KIND_VALUES:
            raise _RuleError(f"rule {label} has a missing or invalid 'kind' field")
        if rule.get("stage") not in _RULE_STAGE_VALUES:
            raise _RuleError(f"rule {label} has a missing or invalid 'stage' field")
        if rule.get("check") not in _RULE_CHECK_VALUES:
            raise _RuleError(f"rule {label} has a missing or invalid 'check' field")
        if rule.get("check") in ("audit", "api"):
            probe_name = rule.get("probe")
            if not isinstance(probe_name, str) or not probe_name:
                raise _RuleError(f"rule {label} has a missing or invalid 'probe' field")


def _score(
    root: Path, facts: dict, rules: list[dict], *, use_api: bool
) -> tuple[list[dict], list[dict], list[str]]:
    """Evaluate `rules` against `root`/`facts`, returning (gaps, recommendations, unverified).

    `unverified` names the rule ids whose probe could not reach a verdict
    this run, meaning it depends on `--api` data an unauthenticated or
    missing `gh` never supplied. Never a gap by itself: a probe that finds
    itself unverified records that in `facts["unverified_probes"]` (by
    its own function name) rather than returning a row.
    """
    _validate_rules(rules)
    gaps: list[dict[str, str]] = []
    recommendations: list[dict[str, str]] = []
    for rule in rules:
        check = rule.get("check")
        if check not in ("audit", "api"):
            continue
        if check == "api" and not use_api:
            continue
        if not _applies(rule.get("when") or {}, facts):
            continue
        if rule.get("stage") == "finish" and facts["stage"] != "finish":
            continue

        probe_name = rule.get("probe")
        probe = PROBES.get(probe_name)
        if probe is None:
            raise _RuleError(f"rule {rule.get('id')} names an unknown probe {probe_name!r}")

        try:
            result = probe(root, facts)
        except OSError as exc:
            result = ("", f"the probe could not read the repo: {exc}")

        if result is None:
            continue
        file_, message = result
        row = {
            "id": rule["id"],
            "kind": rule["kind"],
            "stage": rule["stage"],
            "file": file_,
            "message": message,
        }
        (recommendations if rule["kind"] == "recommendation" else gaps).append(row)

    gaps.sort(key=lambda row: row["id"])
    recommendations.sort(key=lambda row: row["id"])
    unverified_probe_names = facts.get("unverified_probes") or set()
    unverified_ids = sorted(
        rule["id"] for rule in rules if rule.get("probe") in unverified_probe_names
    )
    return gaps, recommendations, unverified_ids


def gaps(root: Path, *, use_api: bool = False) -> list[dict]:
    """Score `root` against ossemble's own rules.json and return the sorted gap rows."""
    root = Path(root).resolve()
    rules = _load_rules()
    facts = _gather_facts(root, use_api=use_api)
    gap_rows, _recommendations, _unverified = _score(root, facts, rules, use_api=use_api)
    return gap_rows


def run(args: argparse.Namespace) -> int:
    """Audit `args.path` and print the gap table (and, with a `--json` twin, JSON)."""
    root = Path(args.path)
    if root.is_symlink():
        print("ossemble audit: refusing to follow a symlink as the target path", file=sys.stderr)
        return 1
    if not root.is_dir():
        print(f"ossemble audit: {args.path} is not a directory", file=sys.stderr)
        return 1
    root = root.resolve()

    try:
        rules = _load_rules()
    except FileNotFoundError:
        print(
            "ossemble audit: no rules/rules.json found beside the ossemble script",
            file=sys.stderr,
        )
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ossemble audit: cannot read rules/rules.json: {exc}", file=sys.stderr)
        return 1

    facts = _gather_facts(root, use_api=args.api)
    try:
        gap_rows, recommendation_rows, unverified_ids = _score(root, facts, rules, use_api=args.api)
    except _RuleError as exc:
        print(f"ossemble audit: {exc}", file=sys.stderr)
        return 1

    _print_report(gap_rows, recommendation_rows, unverified_ids, as_json=args.as_json, api=args.api)

    return 1 if gap_rows else 0


def _print_report(
    gap_rows: list[dict],
    recommendation_rows: list[dict],
    unverified_ids: list[str],
    *,
    as_json: bool,
    api: bool,
) -> None:
    """Print `audit`'s report, as the gap table or, with `as_json`, JSON."""
    if as_json:
        # Only `--api` can leave a rule unverified (an `audit`-check rule
        # always reaches a verdict from the tree alone), so the plain
        # `--json` shape consumers already parse as a bare list never
        # changes; `--api --json` nests it so the unverified ids have
        # somewhere to go.
        if api:
            print(
                json.dumps(
                    {"gaps": gap_rows, "unverified": unverified_ids}, indent=2, sort_keys=True
                )
            )
        else:
            print(json.dumps(gap_rows, indent=2, sort_keys=True))
        return

    for row in gap_rows:
        print(f"{row['id']}  {row['kind']}  {row['stage']}  {row['file']}  {row['message']}")
    if recommendation_rows:
        print("Recommendations")
        for row in recommendation_rows:
            print(f"{row['id']}  {row['kind']}  {row['stage']}  {row['file']}  {row['message']}")
    if unverified_ids:
        print(f"Unverified: {', '.join(unverified_ids)}")


# --------------------------------------------------------------------- facts


def _gather_facts(root: Path, *, use_api: bool) -> dict:
    workflow_items = _workflow_item_list(root)
    pyproject = _load_toml(root / "pyproject.toml")
    tracked_files = _tracked_files(root)
    facts: dict = {
        "has_workflows": bool(workflow_items),
        "language": _detect_language(root, tracked_files),
        "shape": None,
        "public": None,
        "stage": _stage_from_config(pyproject),
        "repo_settings": None,
        "ruleset": None,
        "automated_security_fixes": None,
        "private_vulnerability_reporting": None,
        "workflow_items": workflow_items,
        "pyproject": pyproject,
        "tracked_files": tracked_files,
    }
    if use_api:
        owner_repo = _remote_owner_repo(root)
        if owner_repo:
            try:
                repo_settings = cast("dict", _gh_api(f"repos/{owner_repo}"))
                facts["repo_settings"] = repo_settings
                facts["public"] = not bool(repo_settings.get("private", True))
                rulesets = cast("list", _gh_api(f"repos/{owner_repo}/rulesets") or [])
                for candidate in rulesets:
                    if candidate.get("name") == "main":
                        facts["ruleset"] = _gh_api(f"repos/{owner_repo}/rulesets/{candidate['id']}")
                        break
                facts["automated_security_fixes"] = cast(
                    "dict", _gh_api(f"repos/{owner_repo}/automated-security-fixes")
                )
            except (RuntimeError, OSError, json.JSONDecodeError, KeyError):
                pass
            # Kept in its own suppress: a repo with no ruleset or automated
            # security fixes endpoint (both caught above) must not also
            # blank this fact, and this endpoint's own failure (gh missing,
            # unauthenticated, a 403 on a fine-grained token without
            # Administration) must not blank those.
            with contextlib.suppress(RuntimeError, OSError, json.JSONDecodeError, KeyError):
                facts["private_vulnerability_reporting"] = cast(
                    "dict", _gh_api(f"repos/{owner_repo}/private-vulnerability-reporting")
                )
    return facts


_PYTHON_MARKER_NAMES = ("pyproject.toml", "setup.py", "setup.cfg")

_OTHER_SOURCE_EXTENSIONS = (
    ".ts",
    ".js",
    ".go",
    ".rs",
    ".rb",
    ".sh",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".cpp",
    ".cs",
)


def _detect_language(root: Path, tracked_files: set[str] | None) -> str:
    """`python` for a marker file, else the majority tracked source extension."""
    if any((root / name).is_file() for name in _PYTHON_MARKER_NAMES):
        return "python"
    if any(root.glob("requirements*.txt")):
        return "python"
    if tracked_files is None:
        return "other"
    counts: dict[str, int] = {}
    for relative in tracked_files:
        top = relative.split("/", 1)[0]
        if top == "tests" or top.startswith("."):
            continue
        suffix = Path(relative).suffix
        if suffix == ".py" or suffix in _OTHER_SOURCE_EXTENSIONS:
            counts[suffix] = counts.get(suffix, 0) + 1
    python_count = counts.get(".py", 0)
    if python_count == 0:
        return "other"
    other_counts = [count for suffix, count in counts.items() if suffix != ".py"]
    if python_count > max(other_counts, default=0):
        return "python"
    return "other"


def _applies(when: dict, facts: dict) -> bool:
    return all(facts.get(key) == expected for key, expected in when.items())


def _has_workflows(root: Path) -> bool:
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return False
    return any(_workflow_files(root))


def _workflow_files(root: Path) -> list[Path]:
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    files = []
    for pattern in ("*.yml", "*.yaml"):
        files.extend(path for path in sorted(workflows_dir.glob(pattern)) if not path.is_symlink())
    return files


def _workflow_item_list(root: Path) -> list[tuple[Path, str]]:
    """Read every workflow file's text exactly once, in `_workflow_files` order."""
    return [(path, _read_text(path) or "") for path in _workflow_files(root)]


def _cached(facts: dict, key: str, compute: Callable[[], _CacheT]) -> _CacheT:
    """Return `facts[key]` when `_gather_facts` already put it there, else compute it now."""
    if key in facts:
        return facts[key]
    return compute()


def _stage(root: Path) -> str:
    return _stage_from_config(_load_toml(root / "pyproject.toml"))


def _stage_from_config(config: dict | None) -> str:
    if config is None:
        return "build"
    fail_under = config.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if isinstance(fail_under, (int, float)) and fail_under >= _FINISH_COVERAGE_FLOOR:
        return "finish"
    return "build"


def _load_toml(path: Path) -> dict | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _load_json(path: Path) -> object | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# `resume` runs the same git subcommands and shares this wrapper; kept here
# since audit is the module every other subcommand may lazily import, the
# way resume already does for `gaps`.
_run_git = _git.run_git


def _until_dedent(text: str, indent: int, *, skip_list_items: bool = False) -> str:
    hold = r"(?!-([ \t]|$))" if skip_list_items else ""
    boundary = re.search(rf"^[ \t]{{0,{indent}}}{hold}\S", text, re.MULTILINE)
    return text[: boundary.start()] if boundary else text


def _list_items_under(text: str, key: str) -> list[str]:
    key_pattern = re.compile(rf"^([ \t]*){re.escape(key)}:[ \t]*$", re.MULTILINE)
    chunks: list[str] = []
    for key_match in key_pattern.finditer(text):
        key_indent = len(key_match.group(1))
        block = _until_dedent(text[key_match.end() :], key_indent, skip_list_items=True)
        item_matches = list(STEP_START.finditer(block))
        if not item_matches:
            continue
        item_indent = len(item_matches[0].group(1))
        item_matches = [match for match in item_matches if len(match.group(1)) == item_indent]
        for index, match in enumerate(item_matches):
            end = item_matches[index + 1].start() if index + 1 < len(item_matches) else len(block)
            chunks.append(block[match.start() : end])
    return chunks


def _steps(text: str) -> list[str]:
    return _list_items_under(text, "steps")


def _run_value(step: str) -> str | None:
    run_match = re.search(
        r"^([ \t]*(?:-[ \t]+)?)run:[ \t]*(\|[+-]?|>[+-]?)?[ \t]*(.*)$", step, re.MULTILINE
    )
    if not run_match:
        return None
    run_indent = len(run_match.group(1))
    block = _until_dedent(step[run_match.end() :], run_indent)
    return run_match.group(3) + block


_ON_LINE = re.compile(r"^on:[ \t]*(.*)$", re.MULTILINE)


def _on_triggers(text: str) -> set[str]:
    """The event names a workflow's `on:` section declares, block or inline."""
    line_match = _ON_LINE.search(text)
    if not line_match:
        return set()
    inline = line_match.group(1).strip()
    if inline:
        return set(re.findall(r"[\w-]+", inline))
    rest = text[line_match.end() :]
    body_match = re.match(r"\n(.*?)(?=\n\S|\Z)", rest, re.DOTALL)
    body = body_match.group(1) if body_match else ""
    return set(re.findall(r"^  ([\w-]+):", body, re.MULTILINE))


def _jobs(text: str) -> dict[str, str]:
    """Split a workflow's raw text into one chunk per top-level job."""
    jobs_match = re.search(r"^jobs:\s*$", text, re.MULTILINE)
    if not jobs_match:
        return {}
    body = text[jobs_match.end() :]
    names = list(re.finditer(r"^  ([\w-]+):\s*$", body, re.MULTILINE))
    jobs = {}
    for index, match in enumerate(names):
        end = names[index + 1].start() if index + 1 < len(names) else len(body)
        jobs[match.group(1)] = body[match.start() : end]
    return jobs


# --------------------------------------------------------------------- gh api


def _gh_api(path: str) -> object:
    """Read one GitHub API path through the `gh` CLI. Tests fake this function."""
    result = subprocess.run(  # noqa: S603 -- fixed argv, never a shell
        ["gh", "api", path],  # noqa: S607 -- gh is a trusted binary name
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh api {path} failed")
    return json.loads(result.stdout)


def _remote_owner_repo(root: Path) -> str | None:
    result = _run_git(root, "remote", "get-url", "origin")
    if result is None or result.returncode != 0:
        return None
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", result.stdout.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


# --------------------------------------------------------------------- probes
#
# Each probe takes (root, facts) and returns None (rule holds) or an
# (file, message) pair naming the gap.


def stdlib_only_runtime_dependencies(root: Path, facts: dict) -> ProbeResult:
    """Depend on nothing beyond the standard library at runtime."""
    config = _cached(facts, "pyproject", lambda: _load_toml(root / "pyproject.toml"))
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    deps = config.get("project", {}).get("dependencies", [])
    if deps:
        return ("pyproject.toml", f"[project] dependencies is not empty: {deps}")
    return None


def dev_tooling_in_dependency_group(root: Path, facts: dict) -> ProbeResult:
    """Confirm dev tooling lives in a dependency group with no build backend."""
    config = _cached(facts, "pyproject", lambda: _load_toml(root / "pyproject.toml"))
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    dev_group = config.get("dependency-groups", {}).get("dev")
    if not dev_group:
        return ("pyproject.toml", "no [dependency-groups] dev entry")
    if config.get("tool", {}).get("uv", {}).get("package") is not False:
        return ("pyproject.toml", "[tool.uv] package is not set to false")
    return None


def docs_under_300_lines(root: Path, _facts: dict) -> ProbeResult:
    """Keep each human-facing doc under 300 lines."""
    for name in ("README.md", "CONTRIBUTING.md"):
        text = _read_text(root / name)
        if text is None:
            continue
        line_count = len(text.splitlines())
        if line_count > _HUMAN_DOC_LINE_LIMIT:
            return (name, f"{line_count} lines, over the {_HUMAN_DOC_LINE_LIMIT}-line limit")
    return None


def leanness_tool_never_wired_into_ci(root: Path, facts: dict) -> ProbeResult:
    """Confirm no workflow references ponytail; it stays dev-only, report-only."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if "ponytail" in text.lower():
            return (
                str(path.relative_to(root)),
                "ponytail is referenced in a workflow, but it must stay dev-only",
            )
    return None


def workflow_top_level_permissions_empty(root: Path, facts: dict) -> ProbeResult:
    """Set `permissions: {}` at the top of every workflow."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if not re.search(r"^permissions:\s*\{\}\s*$", text, re.MULTILINE):
            return (str(path.relative_to(root)), "no top-level `permissions: {}`")
    return None


def job_level_permissions_declared(root: Path, facts: dict) -> ProbeResult:
    """Grant each job only the permissions it needs, declared on the job itself."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for name, body in _jobs(text).items():
            if not re.search(r"^\s+permissions:", body, re.MULTILINE):
                return (str(path.relative_to(root)), f"job {name!r} has no permissions of its own")
    return None


def job_timeout_minutes_set(root: Path, facts: dict) -> ProbeResult:
    """Set `timeout-minutes` on every job."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for name, body in _jobs(text).items():
            if "timeout-minutes:" not in body:
                return (str(path.relative_to(root)), f"job {name!r} has no timeout-minutes")
    return None


def checkout_persist_credentials_false(root: Path, facts: dict) -> ProbeResult:
    """Set `persist-credentials: false` on every checkout step."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for step in _steps(text):
            if "actions/checkout@" in step and "persist-credentials: false" not in step:
                return (
                    str(path.relative_to(root)),
                    "a checkout step does not set persist-credentials: false",
                )
    return None


ZIZMOR_UNPINNED_IGNORE = re.compile(r"zizmor:\s*ignore\[unpinned-uses\]\s*(\S.*)?")


def _is_unpinnable_reference(value: str) -> bool:
    value = value.strip("'\"")
    return value.startswith("docker://") or (not value[:1].isalnum() and value[1:2] == "/")


def actions_pinned_to_full_sha_with_version_comment(root: Path, facts: dict) -> ProbeResult:
    """Confirm every `uses:` is pinned to a full commit SHA with a version comment."""
    pin_pattern = re.compile(r"uses:\s*[\"']?([^\s#'\"]+)@([0-9a-fA-F]{40})[\"']?(\s*#\s*(\S.*))?")
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            uses_match = re.match(r"[ \t]*(?:-[ \t]*)?uses:\s*(\S+)", line)
            if not uses_match or _is_unpinnable_reference(uses_match.group(1)):
                continue
            pinned = pin_pattern.search(line)
            if pinned and pinned.group(4):
                continue
            ignore_match = ZIZMOR_UNPINNED_IGNORE.search(line)
            if ignore_match and ignore_match.group(1):
                continue
            return (
                str(path.relative_to(root)),
                f"not pinned to a full SHA with a version comment: {line.strip()}",
            )
    return None


def pinact_verify_runs_on_pull_request(root: Path, facts: dict) -> ProbeResult:
    """Run `pinact-action` with `verify: "true"` in some CI workflow triggered on pull_request."""
    for _path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if "pull_request" not in _on_triggers(text):
            continue
        for step in _steps(text):
            if "suzuki-shunsuke/pinact-action@" not in step:
                continue
            if re.search(r"verify:\s*[\"']?true[\"']?", step):
                return None
    return (
        ".github/workflows",
        'no pull_request workflow runs suzuki-shunsuke/pinact-action with verify: "true"',
    )


_ZIZMOR_PRECOMMIT_HOOK = re.compile(r"^[ \t]*-[ \t]*id:[ \t]*zizmor[ \t]*$", re.MULTILINE)


def zizmor_runs_in_precommit_or_ci(root: Path, facts: dict) -> ProbeResult:
    """Run zizmor, either as a pre-commit hook or as a CI step."""
    pre_commit = _read_text(root / ".pre-commit-config.yaml") or ""
    if _ZIZMOR_PRECOMMIT_HOOK.search(pre_commit):
        return None
    for _path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for step in _steps(text):
            if "zizmor" in step.lower():
                return None
    return (
        ".github/workflows",
        "zizmor does not run as a pre-commit hook (id: zizmor) or a CI step",
    )


def no_expression_interpolation_in_run_steps(root: Path, facts: dict) -> ProbeResult:
    """Never put `${{ }}` inside a `run:` step; pass the value through `env:` instead."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for step in _steps(text):
            run_value = _run_value(step)
            if run_value is None:
                continue
            if "${{" in run_value:
                return (
                    str(path.relative_to(root)),
                    "a run: step interpolates ${{ }} directly instead of using env:",
                )
    return None


def secrets_scan_configured_over_full_history(root: Path, facts: dict) -> ProbeResult:
    """Run the secrets scan over full history from the first commit."""
    pre_commit = _read_text(root / ".pre-commit-config.yaml") or ""
    if "gitleaks" not in pre_commit.lower():
        return (".pre-commit-config.yaml", "no gitleaks hook configured")
    for _path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if "gitleaks" in text.lower() and "fetch-depth: 0" in text:
            return None
    return (
        ".github/workflows",
        "no workflow runs a full-history secrets scan (gitleaks with fetch-depth: 0)",
    )


_DEPENDABOT_NAMES = (".github/dependabot.yml", ".github/dependabot.yaml")
_COOLDOWN_DAYS = re.compile(r"cooldown:.*?default-days:\s*(\d+)", re.DOTALL)
_MIN_COOLDOWN_DAYS = 7
_DEPENDENCY_MANIFEST_PATTERNS = (
    "pyproject.toml",
    "requirements*.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "*.csproj",
    "composer.json",
    "Dockerfile",
)


def _has_dependency_manifest(root: Path, facts: dict) -> bool:
    """A dependency manifest anywhere in the tracked tree Dependabot could open updates against.

    Reuses the tracked-files cache instead of walking the tree again; a
    target with no tracked-files cache and no `.git` is treated as having
    none, rather than falling back to a fresh filesystem walk.
    """
    tracked = _cached(facts, "tracked_files", lambda: _tracked_files(root))
    if tracked is None:
        return False
    for relative in tracked:
        name = Path(relative).name
        for pattern in _DEPENDENCY_MANIFEST_PATTERNS:
            if fnmatch.fnmatch(name, pattern):
                return True
    return False


def _dependabot_entry_issue(entry: str) -> str | None:
    """The problem with one Dependabot update entry, or None when it is well configured."""
    if not re.search(r"interval:\s*[\"']?weekly[\"']?", entry):
        return "an ecosystem has no weekly schedule interval"
    cooldown = _COOLDOWN_DAYS.search(entry)
    if not cooldown or int(cooldown.group(1)) < _MIN_COOLDOWN_DAYS:
        return "an ecosystem has no seven-day cooldown"
    if "groups:" not in entry:
        return "an ecosystem's updates are not grouped"
    return None


def dependabot_grouped_weekly_with_cooldown(root: Path, facts: dict) -> ProbeResult:
    """Confirm every configured Dependabot ecosystem is grouped weekly with a cooldown.

    Only where Dependabot would have something to update: a repo with no
    workflow and no dependency manifest gets a pass rather than a gap for
    a file that would configure nothing.
    """
    name = next((n for n in _DEPENDABOT_NAMES if (root / n).is_file()), None)
    if name is None:
        if not facts.get("has_workflows") and not _has_dependency_manifest(root, facts):
            return None
        return (_DEPENDABOT_NAMES[0], "file is missing")
    entries = _list_items_under(_read_text(root / name) or "", "updates")
    if not entries:
        return (name, "no package-ecosystem update is configured")
    for entry in entries:
        issue = _dependabot_entry_issue(entry)
        if issue:
            return (name, issue)
    return None


def ruff_select_all_with_ignores_justified(root: Path, facts: dict) -> ProbeResult:
    """Confirm ruff selects every rule and each ignore is justified in a comment."""
    config = _cached(facts, "pyproject", lambda: _load_toml(root / "pyproject.toml"))
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    select = config.get("tool", {}).get("ruff", {}).get("lint", {}).get("select")
    if select != ["ALL"]:
        return ("pyproject.toml", f'[tool.ruff.lint] select is {select!r}, not ["ALL"]')
    raw = _read_text(root / "pyproject.toml") or ""
    ignore_match = re.search(r"ignore\s*=\s*\[(.*?)\]", raw, re.DOTALL)
    if ignore_match:
        for line in ignore_match.group(1).splitlines():
            stripped = line.strip()
            if stripped and "#" not in stripped:
                return (
                    "pyproject.toml",
                    f"an ignored ruff rule has no justifying comment: {stripped}",
                )
    per_file = config.get("tool", {}).get("ruff", {}).get("lint", {}).get("per-file-ignores", {})
    for glob, codes in per_file.items():
        if "tests" in glob:
            continue
        for code in codes:
            if code.startswith("S"):
                return (
                    "pyproject.toml",
                    f"security rule {code} is ignored outside tests, for {glob!r}",
                )
    return None


def concurrency_keyed_by_ref_on_pr_and_sha_on_push(root: Path, facts: dict) -> ProbeResult:
    """Confirm concurrency is keyed by ref on pull requests and sha on pushes."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        triggers = _on_triggers(text)
        needs_ref = "pull_request" in triggers
        needs_sha = "push" in triggers
        if not needs_ref and not needs_sha:
            continue
        match = re.search(r"^concurrency:\s*$(.*?)(^\S|\Z)", text, re.MULTILINE | re.DOTALL)
        if not match:
            return (str(path.relative_to(root)), "no concurrency block")
        block = match.group(1)
        if needs_ref and "github.ref" not in block:
            return (
                str(path.relative_to(root)),
                "concurrency is not keyed by ref on pull requests",
            )
        if needs_sha and "github.sha" not in block:
            return (str(path.relative_to(root)), "concurrency is not keyed by sha on pushes")
        if needs_ref and "cancel-in-progress" not in block:
            return (str(path.relative_to(root)), "concurrency has no cancel-in-progress")
    return None


_GATE_ALWAYS_MARKERS = ("if: always()", "if: ${{ !cancelled() }}")
_ALLS_GREEN_USES = re.compile(r"uses:\s*[\"']?re-actors/alls-green")
_NEEDS_RESULT = re.compile(r"needs\.\S+\.result")
_NEEDS_INLINE = re.compile(r"needs:\s*\[([^\]]*)\]")


def _needs(body: str) -> set[str]:
    inline = _NEEDS_INLINE.search(body)
    if inline:
        return {item.strip().strip("'\"") for item in inline.group(1).split(",") if item.strip()}
    return {
        re.sub(r"^[ \t]*-[ \t]*", "", chunk).strip().strip("'\"")
        for chunk in _list_items_under(body, "needs")
    }


_MIN_JOBS_NEEDING_A_GATE = 2


def ci_gate_job_fails_closed(root: Path, facts: dict) -> ProbeResult:
    """Confirm a multi-job pull-request workflow has a gate that fails closed."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if "pull_request" not in _on_triggers(text):
            continue
        jobs = _jobs(text)
        if len(jobs) < _MIN_JOBS_NEEDING_A_GATE:
            continue
        job_names = set(jobs)
        candidates = [
            (name, body)
            for name, body in jobs.items()
            if any(marker in body for marker in _GATE_ALWAYS_MARKERS)
        ]
        if not candidates:
            return (str(path.relative_to(root)), "no job runs regardless of its dependencies")
        for name, body in candidates:
            if job_names - {name} - _needs(body):
                continue
            if (
                _ALLS_GREEN_USES.search(body)
                or _NEEDS_RESULT.search(body)
                or '!= "success"' in body
                or "!= 'success'" in body
            ):
                return None
        return (str(path.relative_to(root)), "no job depends on every job and fails closed")
    return None


def dependency_audit_workflow_separate_and_scheduled(root: Path, facts: dict) -> ProbeResult:
    """Confirm pip-audit runs in its own scheduled workflow, outside the main gate."""
    for _path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if "pip-audit" not in text:
            continue
        if "cron" in text and "pyproject.toml" in text:
            return None
    return (".github/workflows", "no separate, weekly, pyproject.toml-triggered pip-audit workflow")


def diff_cover_runs_on_one_ci_leg(root: Path, facts: dict) -> ProbeResult:
    """Confirm diff-cover runs on one CI leg at the finish stage."""
    for _path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if "diff-cover" in text:
            return None
    return (".github/workflows", "no workflow runs diff-cover")


def full_interpreter_matrix_everywhere(root: Path, facts: dict) -> ProbeResult:
    """Confirm no job still narrows its Python matrix on pull requests."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for name, body in _jobs(text).items():
            match = re.search(r"python-version:.*", body)
            if match and "pull_request" in match.group(0):
                return (
                    str(path.relative_to(root)),
                    f"job {name!r} still narrows its matrix on pull requests",
                )
    return None


def readme_has_no_ci_badge_code_or_workflow_link_before_content(
    root: Path, _facts: dict
) -> ProbeResult:
    """Confirm nothing appears before the README's first heading but plain prose."""
    text = _read_text(root / "README.md")
    if text is None:
        return ("README.md", "file is missing")
    heading = re.search(r"^##\s", text, re.MULTILINE)
    hero = text[: heading.start()] if heading else text
    if "```" in hero:
        return ("README.md", "a fenced code block appears before the first section heading")
    if "actions/workflows" in hero or ".github/workflows" in hero:
        return ("README.md", "a CI badge or workflow link appears before the first section heading")
    return None


def readme_headings_are_only_the_fixed_set(root: Path, _facts: dict) -> ProbeResult:
    """Confirm every README heading is in readmerlin's closed set, in its order."""
    text = _read_text(root / "README.md")
    if text is None:
        return ("README.md", "file is missing")
    seen: list[str] = []
    for match in re.finditer(r"^##\s+(.+)$", text, re.MULTILINE):
        normalized = match.group(1).strip().lower()
        if normalized not in README_ALLOWED_HEADINGS:
            return ("README.md", f"heading {match.group(1)!r} is not in the fixed set")
        seen.append(normalized)
    positions = [README_SECTION_ORDER.index(heading) for heading in seen]
    if positions != sorted(positions):
        return ("README.md", "headings are out of readmerlin's fixed order")
    return None


def readme_security_section_is_never_only(root: Path, _facts: dict) -> ProbeResult:
    """Write the README's Security and limits section as a never-only checklist."""
    text = _read_text(root / "README.md")
    if text is None:
        return ("README.md", "file is missing")
    match = re.search(
        r"^##\s+Security and limits\s*$(.*?)(^##\s|\Z)", text, re.MULTILINE | re.DOTALL
    )
    if not match:
        return None
    body = match.group(1)
    if "✅" in body:
        return (
            "README.md",
            "the Security and limits section has a checked (✅) item; it must be never-only",
        )
    if "❌" not in body:
        return ("README.md", "the Security and limits section has no never (❌) items")
    return None


def readme_check_exec_flag_is_true(root: Path, _facts: dict) -> ProbeResult:
    """When readme-check.yml runs `oficiallyAkshay/readmerlin`, its `exec` input must be true."""
    path = root / ".github" / "workflows" / "readme-check.yml"
    text = _read_text(path)
    if text is None:
        return None
    for step in _steps(text):
        if "oficiallyAkshay/readmerlin" not in step:
            continue
        if not re.search(r"exec:\s*[\"']?true[\"']?", step):
            return (
                ".github/workflows/readme-check.yml",
                'the readmerlin step does not set exec: "true"',
            )
    return None


def no_lockfile_committed(root: Path, facts: dict) -> ProbeResult:
    """Never commit a lockfile."""
    tracked = _cached(facts, "tracked_files", lambda: _tracked_files(root))
    for name in LOCKFILE_NAMES:
        if not (root / name).exists():
            continue
        if tracked is None or name in tracked:
            return (name, "a lockfile is committed")
    return None


_BADGES_BRANCH_PATTERN = re.compile(
    r"HEAD:badges\b"
    r"|refs/heads/badges\b"
    r"|git\s+init\s+-b\s+badges\b"
    r"|git\s+push\b.*\bbadges\b"
    r"|--force\b.*\bbadges\b"
    r"|\bbadges\b.*--force\b",
    re.DOTALL,
)


def only_clonometer_pushes_to_badges_branch(root: Path, facts: dict) -> ProbeResult:
    """Never push to the `badges` branch from a workflow other than `oficiallyAkshay/clonometer`."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if "oficiallyAkshay/clonometer@" in text:
            continue
        for step in _steps(text):
            run_value = _run_value(step)
            if run_value and _BADGES_BRANCH_PATTERN.search(run_value):
                return (
                    str(path.relative_to(root)),
                    "pushes to the badges branch outside oficiallyAkshay/clonometer",
                )
    return None


def _tracked_files(root: Path) -> set[str] | None:
    """The repo's git-tracked paths, or None when `root` is not a git repo."""
    if not (root / ".git").exists():
        return None
    result = _run_git(root, "ls-files")
    if result is None or result.returncode != 0:
        return None
    return set(result.stdout.splitlines())


def _python_source_files(root: Path, facts: dict) -> list[Path]:
    """The repo's own `.py` files, never a dependency or a virtual environment."""
    tracked = _cached(facts, "tracked_files", lambda: _tracked_files(root))
    if tracked is not None:
        return [root / relative for relative in sorted(tracked) if relative.endswith(".py")]
    # Sorted, so the first offending file named is the same on every run.
    return sorted(
        path
        for path in root.rglob("*.py")
        if not path.is_symlink() and not set(path.relative_to(root).parts) & set(_NON_SOURCE_DIRS)
    )


def zero_tokens_beyond_builtin_github_token(root: Path, facts: dict) -> ProbeResult:
    """Confirm no workflow references a secret beyond the built-in GITHUB_TOKEN."""
    state = _load_json(root / ".ossemble" / "state.json")
    optins = state.get("optins") if isinstance(state, dict) else None
    allowed = set(optins) if isinstance(optins, (list, dict)) else set()
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for match in re.finditer(r"secrets\.([A-Za-z0-9_]+)", text):
            name = match.group(1)
            if name == "GITHUB_TOKEN" or name in allowed:
                continue
            message = (
                f"uses secrets.{name} beyond the built-in token, "
                "unless recorded under optins in .ossemble/state.json"
            )
            return (str(path.relative_to(root)), message)
    return None


def commit_identity_is_noreply(root: Path, _facts: dict) -> ProbeResult:
    """Commit under the repo's no-reply identity, never a personal name or email."""
    result = _run_git(root, "log", "-1", "--format=%ae")
    if result is None:
        return (".", "could not read git history")
    email = result.stdout.strip()
    if result.returncode != 0 or not email:
        return (".", "no commit history found to check the author identity")
    if "noreply" not in email:
        return (".", f"the latest commit's author email is not a no-reply address: {email}")
    return None


def state_file_holds_only_allowed_keys(root: Path, _facts: dict) -> ProbeResult:
    """Confirm the state file holds only keys the repo cannot derive on its own."""
    state = _load_json(root / ".ossemble" / "state.json")
    if state is None:
        return None
    extra = sorted(set(cast("dict", state)) - ALLOWED_STATE_KEYS)
    if extra:
        return (".ossemble/state.json", f"holds keys the repo could derive on its own: {extra}")
    return None


def no_gate_lowering_left_open_at_finish_stage(root: Path, _facts: dict) -> ProbeResult:
    """Confirm no gate is still recorded as lowered once the repo reaches finish."""
    state = _load_json(root / ".ossemble" / "state.json")
    if not state:
        return None
    lowered = cast("dict", state).get("lowered")
    if lowered:
        return (".ossemble/state.json", f"a gate is still recorded as lowered: {lowered}")
    return None


def coverage_floor_at_least_seventy(root: Path, facts: dict) -> ProbeResult:
    """Confirm the coverage floor is at least 70 percent."""
    config = _cached(facts, "pyproject", lambda: _load_toml(root / "pyproject.toml"))
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    fail_under = config.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if not isinstance(fail_under, (int, float)) or fail_under < _BUILD_COVERAGE_FLOOR:
        return (
            "pyproject.toml",
            f"[tool.coverage.report] fail_under is {fail_under!r}, below {_BUILD_COVERAGE_FLOOR}",
        )
    return None


def coverage_floor_is_100_line_and_branch(root: Path, facts: dict) -> ProbeResult:
    """Enforce 100 percent line and branch coverage at the finish stage."""
    config = _cached(facts, "pyproject", lambda: _load_toml(root / "pyproject.toml"))
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    fail_under = config.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if fail_under != _FINISH_COVERAGE_FLOOR:
        return (
            "pyproject.toml",
            f"[tool.coverage.report] fail_under is {fail_under!r}, not {_FINISH_COVERAGE_FLOOR}",
        )
    if config.get("tool", {}).get("coverage", {}).get("run", {}).get("branch") is not True:
        return ("pyproject.toml", "[tool.coverage.run] branch is not true")
    return None


PRAGMA_LINE = re.compile(r"#\s*pragma:\s*no cover(?:\s*--\s*(\S.*))?")


_NON_SOURCE_DIRS = (".git", ".venv", "venv", "node_modules", "__pycache__")


def pragma_no_cover_only_on_main_guard_with_reason(root: Path, facts: dict) -> ProbeResult:
    """Confirm every no-cover pragma sits on a __main__ guard with a reason."""
    for path in _python_source_files(root, facts):
        text = _read_text(path)
        if text is None:
            continue
        for line in text.splitlines():
            match = PRAGMA_LINE.search(line)
            if not match:
                continue
            if "__main__" not in line:
                return (
                    str(path.relative_to(root)),
                    f"pragma: no cover outside a __main__ guard: {line.strip()}",
                )
            if not match.group(1):
                return (
                    str(path.relative_to(root)),
                    f"pragma: no cover has no trailing reason: {line.strip()}",
                )
    return None


# ------------------------------------------------------------------ api probes


def auto_merge_and_delete_branch_enabled(_root: Path, facts: dict) -> ProbeResult:
    """Turn on auto-merge and delete-branch-on-merge."""
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    if not settings.get("allow_auto_merge"):
        return ("gh api repos", "allow_auto_merge is off")
    if not settings.get("delete_branch_on_merge"):
        return ("gh api repos", "delete_branch_on_merge is off")
    return None


def merge_strategy_is_rebase_only(_root: Path, facts: dict) -> ProbeResult:
    """Allow rebase merges only; turn off squash merges and merge commits."""
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    if not settings.get("allow_rebase_merge"):
        return ("gh api repos", "allow_rebase_merge is off")
    if settings.get("allow_squash_merge"):
        return ("gh api repos", "allow_squash_merge is on")
    if settings.get("allow_merge_commit"):
        return ("gh api repos", "allow_merge_commit is on")
    return None


def wiki_and_projects_disabled(_root: Path, facts: dict) -> ProbeResult:
    """Turn off the wiki and the projects tab."""
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    if settings.get("has_wiki"):
        return ("gh api repos", "the wiki is on")
    if settings.get("has_projects"):
        return ("gh api repos", "the projects tab is on")
    return None


def dependabot_alerts_and_security_updates_enabled(_root: Path, facts: dict) -> ProbeResult:
    """Turn on Dependabot alerts and security updates.

    A private repo without Advanced Security omits security_and_analysis from
    the repo settings, so we fall back to the automated-security-fixes
    endpoint when the status is missing.
    """
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    analysis = settings.get("security_and_analysis") or {}
    status = analysis.get("dependabot_security_updates", {}).get("status")
    if status is None:
        fallback = facts.get("automated_security_fixes") or {}
        if fallback.get("enabled") and not fallback.get("paused"):
            return None
        return ("gh api repos", "dependabot_security_updates is not enabled")
    if status != "enabled":
        return ("gh api repos", "dependabot_security_updates is not enabled")
    return None


def topics_are_set(_root: Path, facts: dict) -> ProbeResult:
    """Set repo topics once the repo is public."""
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    if not settings.get("topics"):
        return ("gh api repos", "no topics are set")
    return None


def secret_scanning_and_push_protection_enabled(_root: Path, facts: dict) -> ProbeResult:
    """Turn on secret scanning and push protection once the repo is public."""
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    analysis = settings.get("security_and_analysis") or {}
    if analysis.get("secret_scanning", {}).get("status") != "enabled":
        return ("gh api repos", "secret_scanning is not enabled")
    if analysis.get("secret_scanning_push_protection", {}).get("status") != "enabled":
        return ("gh api repos", "secret_scanning_push_protection is not enabled")
    return None


def copilot_autofix_for_codeql_enabled(_root: Path, facts: dict) -> ProbeResult:
    """Turn on Copilot Autofix for CodeQL once the repo is public and CodeQL runs."""
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    analysis = settings.get("security_and_analysis") or {}
    status = analysis.get("copilot_autofix", {}).get("status")
    if status != "enabled":
        return ("gh api repos", "Copilot Autofix for CodeQL is not enabled")
    return None


def _security_md_path(root: Path) -> Path | None:
    for candidate in (root / "SECURITY.md", root / ".github" / "SECURITY.md"):
        if candidate.is_file():
            return candidate
    return None


def security_reporting_route_must_be_on(root: Path, facts: dict) -> ProbeResult:
    """When SECURITY.md points to private vulnerability reporting, that setting must be on.

    Never a false row: a `gh` that is missing, unauthenticated, or fails
    for any other reason leaves `facts["private_vulnerability_reporting"]`
    `None`, and that is recorded as unverified (`facts["unverified_probes"]`)
    rather than reported as a gap.
    """
    path = _security_md_path(root)
    if path is None:
        return None
    text = _read_text(path)
    if text is None:
        return None
    lowered = text.lower()
    if "security/advisories" not in lowered and "private vulnerability reporting" not in lowered:
        return None
    status = facts.get("private_vulnerability_reporting")
    if status is None:
        facts.setdefault("unverified_probes", set()).add("security_reporting_route_must_be_on")
        return None
    if not status.get("enabled"):
        return (
            str(path.relative_to(root)),
            "points reporters at private vulnerability reporting, but the setting is off",
        )
    return None


def ruleset_requires_ci_check(_root: Path, facts: dict) -> ProbeResult:
    """Confirm the branch ruleset requires the `ci` check and has auto-merge armed."""
    ruleset = facts.get("ruleset")
    if ruleset is None:
        return ("gh api rulesets", "no ruleset named main was found")
    if ruleset.get("enforcement") != "active":
        return ("gh api rulesets", "the main ruleset is not active")
    if ruleset.get("bypass_actors"):
        return ("gh api rulesets", "the main ruleset has bypass actors")
    types = {rule.get("type") for rule in ruleset.get("rules", [])}
    if "pull_request" not in types:
        return ("gh api rulesets", "the main ruleset does not require a pull request")
    contexts = set()
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "required_status_checks":
            for check in rule.get("parameters", {}).get("required_status_checks", []):
                contexts.add(check.get("context"))
    if "ci" not in contexts:
        return ("gh api rulesets", "the main ruleset does not require the ci check")
    return None


def ruleset_blocks_history_rewrites(_root: Path, facts: dict) -> ProbeResult:
    """Confirm the ruleset blocks deletion, force push and non-linear history."""
    ruleset = facts.get("ruleset")
    if ruleset is None:
        return ("gh api rulesets", "no ruleset named main was found")
    types = {rule.get("type") for rule in ruleset.get("rules", [])}
    missing = {"deletion", "non_fast_forward", "required_linear_history"} - types
    if missing:
        return ("gh api rulesets", f"the main ruleset is missing: {sorted(missing)}")
    return None


def ruleset_never_requires_reviews_or_thread_resolution(_root: Path, facts: dict) -> ProbeResult:
    """Confirm the branch ruleset never requires reviews or thread resolution."""
    ruleset = facts.get("ruleset")
    if ruleset is None:
        return ("gh api rulesets", "no ruleset named main was found")
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "pull_request":
            params = rule.get("parameters", {})
            if params.get("required_approving_review_count"):
                return ("gh api rulesets", "the main ruleset requires approving reviews")
            if params.get("required_review_thread_resolution"):
                return ("gh api rulesets", "the main ruleset requires thread resolution")
        if rule.get("type") == "required_status_checks":
            params = rule.get("parameters", {})
            if params.get("strict_required_status_checks_policy"):
                return ("gh api rulesets", "the main ruleset requires up-to-date branches")
    return None


PROBES = {
    function.__name__: function
    for function in (
        stdlib_only_runtime_dependencies,
        dev_tooling_in_dependency_group,
        docs_under_300_lines,
        leanness_tool_never_wired_into_ci,
        workflow_top_level_permissions_empty,
        job_level_permissions_declared,
        job_timeout_minutes_set,
        checkout_persist_credentials_false,
        actions_pinned_to_full_sha_with_version_comment,
        no_expression_interpolation_in_run_steps,
        secrets_scan_configured_over_full_history,
        dependabot_grouped_weekly_with_cooldown,
        ruff_select_all_with_ignores_justified,
        concurrency_keyed_by_ref_on_pr_and_sha_on_push,
        ci_gate_job_fails_closed,
        dependency_audit_workflow_separate_and_scheduled,
        diff_cover_runs_on_one_ci_leg,
        full_interpreter_matrix_everywhere,
        readme_has_no_ci_badge_code_or_workflow_link_before_content,
        readme_headings_are_only_the_fixed_set,
        readme_security_section_is_never_only,
        readme_check_exec_flag_is_true,
        pinact_verify_runs_on_pull_request,
        zizmor_runs_in_precommit_or_ci,
        no_lockfile_committed,
        only_clonometer_pushes_to_badges_branch,
        zero_tokens_beyond_builtin_github_token,
        commit_identity_is_noreply,
        state_file_holds_only_allowed_keys,
        no_gate_lowering_left_open_at_finish_stage,
        coverage_floor_at_least_seventy,
        coverage_floor_is_100_line_and_branch,
        pragma_no_cover_only_on_main_guard_with_reason,
        auto_merge_and_delete_branch_enabled,
        merge_strategy_is_rebase_only,
        wiki_and_projects_disabled,
        dependabot_alerts_and_security_updates_enabled,
        topics_are_set,
        secret_scanning_and_push_protection_enabled,
        copilot_autofix_for_codeql_enabled,
        security_reporting_route_must_be_on,
        ruleset_requires_ci_check,
        ruleset_blocks_history_rewrites,
        ruleset_never_requires_reviews_or_thread_resolution,
    )
}
