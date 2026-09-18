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


def add_parser(subparsers):
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


def run(args) -> int:
    """Audit `args.path` and print the gap table (and, with a `--json` twin, JSON)."""
    root = Path(args.path)
    if root.is_symlink():
        print("ossemble audit: refusing to follow a symlink as the target path", file=sys.stderr)
        return 1
    if not root.is_dir():
        print(f"ossemble audit: {args.path} is not a directory", file=sys.stderr)
        return 1
    root = root.resolve()

    rules_path = root / "rules" / "rules.json"
    if not rules_path.is_file():
        print("ossemble audit: no rules/rules.json found under the target repo", file=sys.stderr)
        return 1
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ossemble audit: cannot read rules/rules.json: {exc}", file=sys.stderr)
        return 1

    facts = _gather_facts(root, use_api=args.api)

    gaps: list[dict[str, str]] = []
    recommendations: list[dict[str, str]] = []
    for rule in rules:
        check = rule.get("check")
        if check not in ("audit", "api"):
            continue
        if check == "api" and not args.api:
            continue
        if not _applies(rule.get("when") or {}, facts):
            continue
        if rule.get("stage") == "finish" and facts["stage"] != "finish":
            continue

        probe_name = rule.get("probe")
        probe = PROBES.get(probe_name)
        if probe is None:
            print(
                f"ossemble audit: rule {rule.get('id')} names an unknown probe {probe_name!r}",
                file=sys.stderr,
            )
            return 1

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

    if args.as_json:
        print(json.dumps(gaps, indent=2, sort_keys=True))
    else:
        for row in gaps:
            print(f"{row['id']}  {row['kind']}  {row['stage']}  {row['file']}  {row['message']}")
        if recommendations:
            print("Recommendations")
            for row in recommendations:
                print(
                    f"{row['id']}  {row['kind']}  {row['stage']}  {row['file']}  {row['message']}"
                )

    return 1 if gaps else 0


# --------------------------------------------------------------------- facts


def _gather_facts(root: Path, *, use_api: bool) -> dict:
    facts: dict = {
        "has_workflows": _has_workflows(root),
        "language": "python" if (root / "pyproject.toml").is_file() else None,
        "shape": None,
        "public": None,
        "stage": _stage(root),
        "repo_settings": None,
        "ruleset": None,
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


def _applies(when: dict, facts: dict) -> bool:
    for key, expected in when.items():
        if facts.get(key) != expected:
            return False
    return True


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
        for path in sorted(workflows_dir.glob(pattern)):
            if not path.is_symlink():
                files.append(path)
    return files


def _stage(root: Path) -> str:
    config = _load_toml(root / "pyproject.toml")
    if config is None:
        return "build"
    fail_under = config.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if isinstance(fail_under, (int, float)) and fail_under >= 100:
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
    result = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh api {path} failed")
    return json.loads(result.stdout)


def _remote_owner_repo(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", result.stdout.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


# --------------------------------------------------------------------- probes
#
# Each probe takes (root, facts) and returns None (rule holds) or an
# (file, message) pair naming the gap.


def stdlib_only_runtime_dependencies(root: Path, facts: dict):
    config = _load_toml(root / "pyproject.toml")
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    deps = config.get("project", {}).get("dependencies", [])
    if deps:
        return ("pyproject.toml", f"[project] dependencies is not empty: {deps}")
    return None


def dev_tooling_in_dependency_group(root: Path, facts: dict):
    config = _load_toml(root / "pyproject.toml")
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    dev_group = config.get("dependency-groups", {}).get("dev")
    if not dev_group:
        return ("pyproject.toml", "no [dependency-groups] dev entry")
    if config.get("tool", {}).get("uv", {}).get("package") is not False:
        return ("pyproject.toml", "[tool.uv] package is not set to false")
    return None


def docs_under_300_lines(root: Path, facts: dict):
    for name in ("README.md", "CONTRIBUTING.md"):
        text = _read_text(root / name)
        if text is None:
            continue
        line_count = len(text.splitlines())
        if line_count > 300:
            return (name, f"{line_count} lines, over the 300-line limit")
    return None


def repo_under_250kb(root: Path, facts: dict):
    limit = 250_000
    total = 0
    for path in root.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    if total > limit:
        return (".", f"tracked tree is {total} bytes, over the {limit}-byte limit")
    return None


def leanness_tool_never_wired_into_ci(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        if "ponytail" in text.lower():
            return (
                str(path.relative_to(root)),
                "ponytail is referenced in a workflow, but it must stay dev-only",
            )
    return None


def workflow_top_level_permissions_empty(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        if not re.search(r"^permissions:\s*\{\}\s*$", text, re.MULTILINE):
            return (str(path.relative_to(root)), "no top-level `permissions: {}`")
    return None


def job_level_permissions_declared(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        for name, body in _jobs(text).items():
            if not re.search(r"^\s+permissions:", body, re.MULTILINE):
                return (str(path.relative_to(root)), f"job {name!r} has no permissions of its own")
    return None


def job_timeout_minutes_set(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        for name, body in _jobs(text).items():
            if "timeout-minutes:" not in body:
                return (str(path.relative_to(root)), f"job {name!r} has no timeout-minutes")
    return None


def checkout_persist_credentials_false(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        for step in _steps(text):
            if "actions/checkout@" in step and "persist-credentials: false" not in step:
                return (
                    str(path.relative_to(root)),
                    "a checkout step does not set persist-credentials: false",
                )
    return None


def actions_pinned_to_full_sha_with_version_comment(root: Path, facts: dict):
    pin_pattern = re.compile(r"uses:\s*([^\s#]+)@([0-9a-fA-F]{40})(\s*#\s*(\S.*))?")
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            uses_match = re.search(r"uses:\s*(\S+)", line)
            if not uses_match or uses_match.group(1).startswith("./"):
                continue
            pinned = pin_pattern.search(line)
            if not pinned or not pinned.group(4):
                return (
                    str(path.relative_to(root)),
                    f"not pinned to a full SHA with a version comment: {line.strip()}",
                )
    return None


def no_expression_interpolation_in_run_steps(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
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


def secrets_scan_configured_over_full_history(root: Path, facts: dict):
    pre_commit = _read_text(root / ".pre-commit-config.yaml") or ""
    if "gitleaks" not in pre_commit.lower():
        return (".pre-commit-config.yaml", "no gitleaks hook configured")
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        if "gitleaks" in text.lower() and "fetch-depth: 0" in text:
            return None
    return (
        ".github/workflows",
        "no workflow runs a full-history secrets scan (gitleaks with fetch-depth: 0)",
    )


def dependabot_grouped_weekly_with_cooldown(root: Path, facts: dict):
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


def ruff_select_all_with_ignores_justified(root: Path, facts: dict):
    config = _load_toml(root / "pyproject.toml")
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


def concurrency_keyed_by_ref_on_pr_and_sha_on_push(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        match = re.search(r"^concurrency:\s*$(.*?)(^\S|\Z)", text, re.MULTILINE | re.DOTALL)
        if not match:
            return (str(path.relative_to(root)), "no concurrency block")
        block = match.group(1)
        if "github.ref" not in block or "github.sha" not in block:
            return (
                str(path.relative_to(root)),
                "concurrency is not keyed by ref on pull requests and sha on pushes",
            )
        if "cancel-in-progress" not in block:
            return (str(path.relative_to(root)), "concurrency has no cancel-in-progress")
    return None


def ci_gate_job_fails_closed(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
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


def dependency_audit_workflow_separate_and_scheduled(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        if "pip-audit" not in text:
            continue
        if "cron" in text and "pyproject.toml" in text:
            return None
    return (".github/workflows", "no separate, weekly, pyproject.toml-triggered pip-audit workflow")


def diff_cover_runs_on_one_ci_leg(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        if "diff-cover" in text:
            return None
    return (".github/workflows", "no workflow runs diff-cover")


def full_interpreter_matrix_everywhere(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        for name, body in _jobs(text).items():
            match = re.search(r"python-version:.*", body)
            if match and "pull_request" in match.group(0):
                return (
                    str(path.relative_to(root)),
                    f"job {name!r} still narrows its matrix on pull requests",
                )
    return None


def readme_has_no_ci_badge_code_or_workflow_link_before_content(root: Path, facts: dict):
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


def readme_headings_are_only_the_fixed_set(root: Path, facts: dict):
    text = _read_text(root / "README.md")
    if text is None:
        return ("README.md", "file is missing")
    for match in re.finditer(r"^##\s+(.+)$", text, re.MULTILINE):
        normalized = match.group(1).strip().lower()
        if normalized not in README_ALLOWED_HEADINGS:
            return ("README.md", f"heading {match.group(1)!r} is not in the fixed set")
    return None


def readme_security_section_is_never_only(root: Path, facts: dict):
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


def no_lockfile_committed(root: Path, facts: dict):
    tracked = _tracked_files(root)
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
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return set(result.stdout.splitlines())


def zero_tokens_beyond_builtin_github_token(root: Path, facts: dict):
    for path in _workflow_files(root):
        text = _read_text(path) or ""
        for match in re.finditer(r"secrets\.([A-Za-z0-9_]+)", text):
            if match.group(1) != "GITHUB_TOKEN":
                return (
                    str(path.relative_to(root)),
                    f"uses secrets.{match.group(1)} beyond the built-in token",
                )
    return None


def commit_identity_is_noreply(root: Path, facts: dict):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%ae"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return (".", f"could not read git history: {exc}")
    email = result.stdout.strip()
    if result.returncode != 0 or not email:
        return (".", "no commit history found to check the author identity")
    if "noreply" not in email:
        return (".", f"the latest commit's author email is not a no-reply address: {email}")
    return None


def state_file_holds_only_allowed_keys(root: Path, facts: dict):
    state = _load_json(root / ".ossemble" / "state.json")
    if state is None:
        return None
    extra = sorted(set(state) - ALLOWED_STATE_KEYS)
    if extra:
        return (".ossemble/state.json", f"holds keys the repo could derive on its own: {extra}")
    return None


def no_gate_lowering_left_open_at_finish_stage(root: Path, facts: dict):
    state = _load_json(root / ".ossemble" / "state.json")
    if not state:
        return None
    lowered = state.get("lowered")
    if lowered:
        return (".ossemble/state.json", f"a gate is still recorded as lowered: {lowered}")
    return None


def no_security_md(root: Path, facts: dict):
    for candidate in ("SECURITY.md", ".github/SECURITY.md"):
        if (root / candidate).exists():
            return (candidate, "SECURITY.md exists, but ossemble never stamps one")
    return None


def coverage_floor_at_least_seventy(root: Path, facts: dict):
    config = _load_toml(root / "pyproject.toml")
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    fail_under = config.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if not isinstance(fail_under, (int, float)) or fail_under < 70:
        return ("pyproject.toml", f"[tool.coverage.report] fail_under is {fail_under!r}, below 70")
    return None


def coverage_floor_is_100_line_and_branch(root: Path, facts: dict):
    config = _load_toml(root / "pyproject.toml")
    if config is None:
        return ("pyproject.toml", "cannot read pyproject.toml")
    fail_under = config.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if fail_under != 100:
        return ("pyproject.toml", f"[tool.coverage.report] fail_under is {fail_under!r}, not 100")
    if config.get("tool", {}).get("coverage", {}).get("run", {}).get("branch") is not True:
        return ("pyproject.toml", "[tool.coverage.run] branch is not true")
    return None


PRAGMA_LINE = re.compile(r"#\s*pragma:\s*no cover(?:\s*--\s*(\S.*))?")


def pragma_no_cover_only_on_main_guard_with_reason(root: Path, facts: dict):
    for path in root.rglob("*.py"):
        if ".git" in path.parts or path.is_symlink():
            continue
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


def auto_merge_and_delete_branch_enabled(root: Path, facts: dict):
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    if not settings.get("allow_auto_merge"):
        return ("gh api repos", "allow_auto_merge is off")
    if not settings.get("delete_branch_on_merge"):
        return ("gh api repos", "delete_branch_on_merge is off")
    return None


def merge_strategy_is_rebase_only(root: Path, facts: dict):
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


def wiki_and_projects_disabled(root: Path, facts: dict):
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    if settings.get("has_wiki"):
        return ("gh api repos", "the wiki is on")
    if settings.get("has_projects"):
        return ("gh api repos", "the projects tab is on")
    return None


def dependabot_alerts_and_security_updates_enabled(root: Path, facts: dict):
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


def topics_are_set(root: Path, facts: dict):
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    if not settings.get("topics"):
        return ("gh api repos", "no topics are set")
    return None


def secret_scanning_and_push_protection_enabled(root: Path, facts: dict):
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    analysis = settings.get("security_and_analysis", {})
    if analysis.get("secret_scanning", {}).get("status") != "enabled":
        return ("gh api repos", "secret_scanning is not enabled")
    if analysis.get("secret_scanning_push_protection", {}).get("status") != "enabled":
        return ("gh api repos", "secret_scanning_push_protection is not enabled")
    return None


def copilot_autofix_for_codeql_enabled(root: Path, facts: dict):
    settings = facts.get("repo_settings")
    if settings is None:
        return ("gh api repos", "could not read repo settings")
    status = settings.get("security_and_analysis", {}).get("copilot_autofix", {}).get("status")
    if status != "enabled":
        return ("gh api repos", "Copilot Autofix for CodeQL is not enabled")
    return None


def no_private_vulnerability_reporting(root: Path, facts: dict):
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


def ruleset_requires_ci_check(root: Path, facts: dict):
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


def ruleset_blocks_history_rewrites(root: Path, facts: dict):
    ruleset = facts.get("ruleset")
    if ruleset is None:
        return ("gh api rulesets", "no ruleset named main was found")
    types = {rule.get("type") for rule in ruleset.get("rules", [])}
    missing = {"deletion", "non_fast_forward", "required_linear_history"} - types
    if missing:
        return ("gh api rulesets", f"the main ruleset is missing: {sorted(missing)}")
    return None


def ruleset_never_requires_reviews_or_thread_resolution(root: Path, facts: dict):
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
        no_security_md,
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
