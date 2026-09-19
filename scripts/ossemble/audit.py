"""The `ossemble audit` subcommand: scores a repo against `rules/rules.json`.

Each machine-checkable rule names a probe function in this module. A probe
reads facts from the target repo (and, with `--api`, from `gh api`) and
returns `None` when the rule holds, or an `(file, message)` pair when it
does not. `run` reads the rules, works out the repo's stage, filters rules
by their `when` conditions, calls each probe, and prints the gap table.

The audit does not redo what a selected hook already checks (pins,
permissions, workflow syntax, secrets): for those it only confirms the
hook is configured and at its stage's value.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

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

README_ALLOWED_HEADINGS = {"features", "badges", "security", "how it compares", "callouts"}

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
    """The path to ossemble's own rules/rules.json, kept beside this package.

    The rules describe how ossemble judges a repo; they are never read from
    the repo being audited.
    """
    return Path(__file__).resolve().parents[2] / "rules" / "rules.json"


def _load_rules() -> list[dict]:
    """Load and parse ossemble's own rules.json.

    Raises FileNotFoundError when it is missing, or OSError/JSONDecodeError
    when it cannot be read or parsed.
    """
    path = rules_path()
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


_RULE_KIND_VALUES = ("default", "recommendation")
_RULE_STAGE_VALUES = ("build", "finish")
_RULE_CHECK_VALUES = ("audit", "api", "judgment")
_RULE_REQUIRED_TEXT_FIELDS = ("id", "text", "basis", "category")


def _validate_rules(rules: list[dict]) -> None:
    """Confirm every rule has its required fields, correctly typed, before any is scored.

    Per the contract: id, text, basis and category are non-empty strings;
    kind is `default` or `recommendation`; stage is `build` or `finish`;
    check is `audit`, `api` or `judgment`; and a rule whose check is
    `audit` or `api` names a probe. Raises `_RuleError` naming the rule,
    by id when it has one, else by its position in the list.
    """
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
) -> tuple[list[dict], list[dict]]:
    """Evaluate `rules` against `root`/`facts`, returning (gaps, recommendations).

    Raises `_RuleError` when a rule fails validation or names a probe this
    module does not define.
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
    return gaps, recommendations


def gaps(root: Path, *, use_api: bool = False) -> list[dict]:
    """Score `root` against ossemble's own rules.json and return the sorted gap rows.

    These are the same default-rule rows `run` prints in the gap table and
    with `--json`. Used by `resume` to compute regressions against a
    recorded baseline.
    """
    root = Path(root).resolve()
    rules = _load_rules()
    facts = _gather_facts(root, use_api=use_api)
    gap_rows, _recommendations = _score(root, facts, rules, use_api=use_api)
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
        gap_rows, recommendation_rows = _score(root, facts, rules, use_api=args.api)
    except _RuleError as exc:
        print(f"ossemble audit: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(gap_rows, indent=2, sort_keys=True))
    else:
        for row in gap_rows:
            print(f"{row['id']}  {row['kind']}  {row['stage']}  {row['file']}  {row['message']}")
        if recommendation_rows:
            print("Recommendations")
            for row in recommendation_rows:
                print(
                    f"{row['id']}  {row['kind']}  {row['stage']}  {row['file']}  {row['message']}"
                )

    return 1 if gap_rows else 0


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
        "workflow_items": workflow_items,
        "pyproject": pyproject,
        "tracked_files": tracked_files,
    }
    if use_api:
        owner_repo = _remote_owner_repo(root)
        if owner_repo:
            try:
                repo_settings = _gh_api(f"repos/{owner_repo}")
                facts["repo_settings"] = repo_settings
                facts["public"] = not bool(repo_settings.get("private", True))
                rulesets = _gh_api(f"repos/{owner_repo}/rulesets") or []
                for candidate in rulesets:
                    if candidate.get("name") == "main":
                        facts["ruleset"] = _gh_api(f"repos/{owner_repo}/rulesets/{candidate['id']}")
                        break
            except (RuntimeError, OSError, json.JSONDecodeError, KeyError):
                pass
    return facts


def _detect_language(root: Path, tracked_files: set[str] | None) -> str:
    """`python` when the repo has a pyproject.toml or a tracked `.py` file of its own.

    A rule whose probe reads pyproject.toml applies only to a Python repo,
    so a repo that is neither gets none of those rows. A `.py` file under
    tests/ or under a dot-prefixed top-level directory (a plugin shim, a
    tool's own config) does not by itself make the repo a Python project.
    `tracked_files` is None when `root` is not a git repository, in which
    case only the pyproject.toml check can decide.
    """
    if (root / "pyproject.toml").is_file():
        return "python"
    if tracked_files is not None:
        for relative in tracked_files:
            if not relative.endswith(".py"):
                continue
            top = relative.split("/", 1)[0]
            if top == "tests" or top.startswith("."):
                continue
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
    """Return `facts[key]` when `_gather_facts` already put it there, else compute it now.

    Lets a probe run standalone, against a hand-built `facts` dict that
    has no such key, exactly as it did before `_gather_facts` started
    caching; `run` and `gaps` pay the read or parse behind `compute` only
    once per audit, since their `facts` already carries the key.
    """
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


def _steps(text: str) -> list[str]:
    """Split a workflow's raw text into one chunk per `- ` list item."""
    matches = list(STEP_START.finditer(text))
    chunks = []
    for index, match in enumerate(matches):
        indent = len(match.group(1))
        end = len(text)
        for later in matches[index + 1 :]:
            if len(later.group(1)) <= indent:
                end = later.start()
                break
        chunks.append(text[match.start() : end])
    return chunks


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


_LEANNESS_EXCLUDED_DIRS = ("tests", "examples")


def repo_under_250kb(root: Path, facts: dict) -> ProbeResult:
    """Keep the repo under 250 KB, counting git-tracked bytes outside tests/ and examples/."""
    limit = 250_000
    tracked = _cached(facts, "tracked_files", lambda: _tracked_files(root))
    total = _tracked_bytes(root, tracked) if tracked is not None else _walked_bytes(root)
    if total > limit:
        return (".", f"tracked tree is {total} bytes, over the {limit}-byte limit")
    return None


def _tracked_bytes(root: Path, tracked: set[str]) -> int:
    """Sum the size of every git-tracked file outside tests/ and examples/."""
    total = 0
    for relative in tracked:
        if relative.split("/", 1)[0] in _LEANNESS_EXCLUDED_DIRS:
            continue
        path = root / relative
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total


def _walked_bytes(root: Path) -> int:
    """Sum file sizes by walking the tree, for a target with no git history to read."""
    total = 0
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if ".git" in path.parts or (parts and parts[0] in _LEANNESS_EXCLUDED_DIRS):
            continue
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total


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


def actions_pinned_to_full_sha_with_version_comment(root: Path, facts: dict) -> ProbeResult:
    """Confirm every `uses:` is pinned to a full commit SHA with a version comment.

    A deliberate unpinned self-reference passes when the same line carries
    `zizmor: ignore[unpinned-uses]` followed by at least one word of
    reason; an ignore with no reason still fails.
    """
    pin_pattern = re.compile(r"uses:\s*([^\s#]+)@([0-9a-fA-F]{40})(\s*#\s*(\S.*))?")
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            uses_match = re.search(r"uses:\s*(\S+)", line)
            if not uses_match or uses_match.group(1).startswith("./"):
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


def no_expression_interpolation_in_run_steps(root: Path, facts: dict) -> ProbeResult:
    """Never put `${{ }}` inside a `run:` step; pass the value through `env:` instead."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        for step in _steps(text):
            run_match = re.search(r"run:\s*(\||>)?\s*(.*)", step)
            if not run_match:
                continue
            run_index = step.index("run:")
            if "${{" in step[run_index:]:
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


def dependabot_grouped_weekly_with_cooldown(root: Path, _facts: dict) -> ProbeResult:
    """Confirm Dependabot updates are grouped weekly with a cooldown."""
    text = _read_text(root / ".github" / "dependabot.yml")
    if text is None:
        return (".github/dependabot.yml", "file is missing")
    if not re.search(r"interval:\s*[\"']?weekly[\"']?", text):
        return (".github/dependabot.yml", "no weekly schedule interval")
    if "cooldown:" not in text:
        return (".github/dependabot.yml", "no cooldown configured")
    if "groups:" not in text:
        return (".github/dependabot.yml", "updates are not grouped")
    ecosystems = set(re.findall(r"package-ecosystem:\s*[\"']?([\w-]+)[\"']?", text))
    if not ecosystems or not ecosystems.issubset({"github-actions", "pip"}):
        return (
            ".github/dependabot.yml",
            f"ecosystems {sorted(ecosystems)} are not limited to github-actions and pip",
        )
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
    """Confirm concurrency is keyed by ref on pull requests and sha on pushes.

    Only the triggers a workflow actually declares bind: a workflow with no
    pull_request and no push trigger, such as one run only by schedule,
    workflow_dispatch or workflow_call, has no such run to key and is
    exempt.
    """
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


def ci_gate_job_fails_closed(root: Path, facts: dict) -> ProbeResult:
    """Confirm the required `ci` job has empty permissions, runs always, and fails closed."""
    for path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        gate_jobs = [
            body
            for body in _jobs(text).values()
            if "if: always()" in body and re.search(r"permissions:\s*\{\}", body)
        ]
        if not gate_jobs:
            continue
        for body in gate_jobs:
            if '!= "success"' not in body and "!= 'success'" not in body:
                return (
                    str(path.relative_to(root)),
                    "the always() gate job does not fail on a non-success result",
                )
        return None
    return (".github/workflows", "no gate job with permissions: {} and if: always() was found")


def dependency_audit_workflow_separate_and_scheduled(root: Path, facts: dict) -> ProbeResult:
    """Confirm pip-audit runs in its own scheduled workflow, outside the main gate."""
    for _path, text in _cached(facts, "workflow_items", lambda: _workflow_item_list(root)):
        if "pip-audit" not in text:
            continue
        if "cron" in text and "pyproject.toml" in text:
            return None
    return (".github/workflows", "no separate, weekly, pyproject.toml-triggered pip-audit workflow")


def diff_cover_runs_on_one_ci_leg(root: Path, facts: dict) -> ProbeResult:
    """Confirm diff-cover runs on one CI leg once the repo reaches the finish stage."""
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
    """Confirm every README heading is in the fixed, allowed set."""
    text = _read_text(root / "README.md")
    if text is None:
        return ("README.md", "file is missing")
    for match in re.finditer(r"^##\s+(.+)$", text, re.MULTILINE):
        normalized = match.group(1).strip().lower()
        if normalized not in README_ALLOWED_HEADINGS:
            return ("README.md", f"heading {match.group(1)!r} is not in the fixed set")
    return None


def readme_security_section_is_never_only(root: Path, _facts: dict) -> ProbeResult:
    """Write the README's Security section as a never-only checklist, with no checked items."""
    text = _read_text(root / "README.md")
    if text is None:
        return ("README.md", "file is missing")
    match = re.search(r"^##\s+Security\s*$(.*?)(^##\s|\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return None
    body = match.group(1)
    if "✅" in body:
        return ("README.md", "the Security section has a checked (✅) item; it must be never-only")
    if "❌" not in body:
        return ("README.md", "the Security section has no never (❌) items")
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


def _tracked_files(root: Path) -> set[str] | None:
    """The repo's git-tracked paths, or None when `root` is not a git repo."""
    if not (root / ".git").exists():
        return None
    result = _run_git(root, "ls-files")
    if result is None or result.returncode != 0:
        return None
    return set(result.stdout.splitlines())


def _python_source_files(root: Path, facts: dict) -> list[Path]:
    """The repo's own `.py` files, never a dependency or a virtual environment.

    Prefers git-tracked paths, since that is the sure way to tell a
    dependency installed into `.venv/` from the repo's own source; a
    directory walk is the fallback for a target with no git history to
    read, still skipping the directories nothing here ever wants scanned.
    """
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
    """Confirm no workflow references a secret beyond the built-in GITHUB_TOKEN.

    A secret name the owner recorded under `optins` in `.ossemble/state.json`
    (a list of names, or an object keyed by name) is not a gap.
    """
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
    extra = sorted(set(state) - ALLOWED_STATE_KEYS)
    if extra:
        return (".ossemble/state.json", f"holds keys the repo could derive on its own: {extra}")
    return None


def no_gate_lowering_left_open_at_finish_stage(root: Path, _facts: dict) -> ProbeResult:
    """Confirm no gate is still recorded as lowered once the repo reaches finish."""
    state = _load_json(root / ".ossemble" / "state.json")
    if not state:
        return None
    lowered = state.get("lowered")
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
    """Enforce 100 percent line and branch coverage once the repo reaches the finish stage."""
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
    """Turn on Dependabot alerts and security updates."""
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    status = (
        settings.get("security_and_analysis", {})
        .get("dependabot_security_updates", {})
        .get("status")
    )
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
    analysis = settings.get("security_and_analysis", {})
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
    status = settings.get("security_and_analysis", {}).get("copilot_autofix", {}).get("status")
    if status != "enabled":
        return ("gh api repos", "Copilot Autofix for CodeQL is not enabled")
    return None


def no_private_vulnerability_reporting(_root: Path, facts: dict) -> ProbeResult:
    """Never turn on private vulnerability reporting."""
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    status = (
        settings.get("security_and_analysis", {})
        .get("private_vulnerability_reporting", {})
        .get("status")
    )
    if status == "enabled":
        return ("gh api repos", "private vulnerability reporting is enabled")
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
    """Confirm the branch ruleset blocks deletion, force push and non-linear history."""
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
        repo_under_250kb,
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
        no_lockfile_committed,
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
        no_private_vulnerability_reporting,
        ruleset_requires_ci_check,
        ruleset_blocks_history_rewrites,
        ruleset_never_requires_reviews_or_thread_resolution,
    )
}
