"""Tests for the `ossemble audit` subcommand.

Each probe gets one repo where the rule holds and one where it does not.
Filesystem probes are called directly against a small temp-dir repo;
`gh api` probes are called against a `facts` dict built by hand, since
`audit._gh_api` is the only network-shaped call and tests never touch it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts.ossemble import audit

BASE_FACTS = {
    "has_workflows": False,
    "language": None,
    "shape": None,
    "public": None,
    "stage": "build",
    "repo_settings": None,
    "ruleset": None,
    "automated_security_fixes": None,
    "private_vulnerability_reporting": None,
}


def facts(**overrides) -> dict:
    return {**BASE_FACTS, **overrides}


def write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def workflow(root: Path, content: str, name: str = "ci.yml") -> Path:
    return write(root, f".github/workflows/{name}", content)


def stub_rules(monkeypatch, tmp_path: Path, rules: list[dict]) -> Path:
    """Point `audit` at a rules.json of our own instead of ossemble's real one.

    The stub lives outside the target repo, under a directory named for
    the target so several stubs in one test never collide.
    """
    rules_path = write(tmp_path.parent, f"{tmp_path.name}-rules/rules.json", json.dumps(rules))
    monkeypatch.setattr(audit, "rules_path", lambda: rules_path)
    return rules_path


def init_git_repo(
    root: Path, author_email: str = "154273+octocat@users.noreply.github.com"
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", author_email], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "octocat"], cwd=root, check=True)
    write(root, "README.md", "# repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Add the README"], cwd=root, check=True)


# --------------------------------------------------------- add_parser / run


def test_add_parser_registers_the_audit_subcommand_and_wires_it_to_run() -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    audit.add_parser(subparsers)

    args = parser.parse_args(["audit"])

    assert args.subcommand == "audit"
    assert args.run is audit.run
    assert args.path == "."
    assert args.as_json is False
    assert args.api is False


def test_run_returns_one_and_prints_one_line_when_the_path_is_not_a_directory(capsys) -> None:
    exit_code = audit.run(argparse.Namespace(path="/no/such/path", as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.strip() == "ossemble audit: /no/such/path is not a directory"


def test_run_refuses_to_follow_a_symlink_as_the_target_path(tmp_path, capsys) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_dir)

    exit_code = audit.run(argparse.Namespace(path=str(link), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "symlink" in captured.err


def test_run_returns_one_when_rules_json_is_missing(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(audit, "rules_path", lambda: tmp_path / "missing" / "rules.json")

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "no rules/rules.json" in captured.err


def test_run_returns_one_when_rules_json_is_not_valid_json(tmp_path, capsys, monkeypatch) -> None:
    bad_rules = write(tmp_path.parent, f"{tmp_path.name}-rules/rules.json", "not json")
    monkeypatch.setattr(audit, "rules_path", lambda: bad_rules)

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "cannot read rules/rules.json" in captured.err


def test_run_returns_one_and_names_the_rule_when_a_probe_is_unknown(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(
        monkeypatch,
        tmp_path,
        [
            {
                "id": "ZZ-001",
                "text": "made up",
                "basis": "test",
                "category": "made up",
                "kind": "default",
                "stage": "build",
                "check": "audit",
                "probe": "nonexistent_probe",
            }
        ],
    )

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ZZ-001" in captured.err
    assert "nonexistent_probe" in captured.err


def test_run_returns_one_and_names_the_rule_when_a_required_field_is_missing(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule(kind=None)])

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "STR-001" in captured.err
    assert "kind" in captured.err


def test_run_names_a_rule_by_its_position_when_even_its_id_is_missing(
    tmp_path, capsys, monkeypatch
) -> None:
    broken = _rule()
    del broken["id"]
    stub_rules(monkeypatch, tmp_path, [broken])

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "#0" in captured.err
    assert "'id'" in captured.err


def test_run_returns_one_when_a_rules_text_field_is_an_empty_string(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule(text="")])

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "'text'" in captured.err


def test_run_returns_one_when_a_rules_stage_is_not_build_or_finish(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule(stage="someday")])

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "'stage'" in captured.err


def test_run_returns_one_when_a_rules_check_is_not_a_known_value(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule(check="vibes")])

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "'check'" in captured.err


def test_run_returns_one_when_an_audit_rule_names_no_probe(tmp_path, capsys, monkeypatch) -> None:
    broken = _rule()
    del broken["probe"]
    stub_rules(monkeypatch, tmp_path, [broken])

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "'probe'" in captured.err


def test_run_scores_a_judgment_rule_with_no_probe_without_a_traceback(
    tmp_path, monkeypatch
) -> None:
    """A `check: judgment` rule needs no probe and never reaches the probe check."""
    stub_rules(
        monkeypatch,
        tmp_path,
        [
            {
                "id": "REV-001",
                "text": "a human reviews this",
                "basis": "test",
                "category": "review",
                "kind": "recommendation",
                "stage": "build",
                "check": "judgment",
            }
        ],
    )

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    assert exit_code == 0


def test_run_turns_a_probes_os_error_into_a_gap_row_instead_of_a_traceback(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(
        monkeypatch, tmp_path, [_rule(id="STR-001", probe="stdlib_only_runtime_dependencies")]
    )

    def failing_probe(root, facts):
        raise OSError("permission denied")

    monkeypatch.setitem(audit.PROBES, "stdlib_only_runtime_dependencies", failing_probe)

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "the probe could not read the repo" in captured.out


def _rule(**overrides) -> dict:
    rule = {
        "id": "STR-001",
        "text": "stdlib only",
        "basis": "test",
        "category": "structure and leanness",
        "kind": "default",
        "stage": "build",
        "check": "audit",
        "probe": "stdlib_only_runtime_dependencies",
    }
    rule.update(overrides)
    return rule


def test_run_prints_a_gap_row_and_returns_one_when_a_default_rule_fails(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule()])
    write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests"]\n')

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out.strip() == (
        "STR-001  default  build  pyproject.toml  [project] dependencies is not empty: ['requests']"
    )


def test_run_prints_nothing_and_returns_zero_when_every_rule_passes(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule()])
    write(tmp_path, "pyproject.toml", "[project]\ndependencies = []\n")

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_run_json_prints_a_sorted_list_of_gap_objects(tmp_path, capsys, monkeypatch) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule()])
    write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests"]\n')

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=True, api=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    rows = json.loads(captured.out)
    assert rows == [
        {
            "id": "STR-001",
            "kind": "default",
            "stage": "build",
            "file": "pyproject.toml",
            "message": "[project] dependencies is not empty: ['requests']",
        }
    ]


def test_run_prints_a_failing_recommendation_under_its_own_heading_without_changing_the_exit_code(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule(id="DST-777", kind="recommendation")])
    write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests"]\n')

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 0
    lines = captured.out.strip().splitlines()
    assert lines[0] == "Recommendations"
    assert lines[1].startswith("DST-777  recommendation")


def test_run_skips_a_rule_whose_when_condition_is_not_met(tmp_path, capsys, monkeypatch) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule(when={"has_workflows": True})])
    write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests"]\n')

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_run_skips_a_finish_stage_rule_while_the_repo_is_still_at_the_build_stage(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule(stage="finish")])
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\ndependencies = ["requests"]\n\n[tool.coverage.report]\nfail_under = 70\n',
    )

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_run_evaluates_a_finish_stage_rule_once_the_coverage_floor_reaches_100(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule(stage="finish")])
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\ndependencies = ["requests"]\n\n[tool.coverage.report]\nfail_under = 100\n',
    )

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    assert exit_code == 1


def test_run_skips_an_api_rule_when_the_api_flag_is_not_given(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(
        monkeypatch, tmp_path, [_rule(check="api", probe="auto_merge_and_delete_branch_enabled")]
    )

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_run_evaluates_an_api_rule_when_the_api_flag_is_given(
    tmp_path, capsys, monkeypatch
) -> None:
    stub_rules(
        monkeypatch, tmp_path, [_rule(check="api", probe="auto_merge_and_delete_branch_enabled")]
    )
    monkeypatch.setattr(
        audit,
        "_gh_api",
        lambda path: (
            {"allow_auto_merge": False}
            if path.startswith("repos/") and "rulesets" not in path
            else []
        ),
    )

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=True))

    assert exit_code == 1


def test_run_json_with_api_nests_gaps_and_names_an_unverified_rule_id(
    tmp_path, capsys, monkeypatch
) -> None:
    """A probe that records itself unverified never becomes a gap row; `--api --json` names it."""
    stub_rules(
        monkeypatch,
        tmp_path,
        [_rule(id="NO-011", check="api", probe="security_reporting_route_must_be_on")],
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )
    write(
        tmp_path,
        "SECURITY.md",
        "Use https://github.com/an-owner/a-repo/security/advisories/new\n",
    )

    def fake_gh_api(path):
        raise RuntimeError("gh: not authenticated")

    monkeypatch.setattr(audit, "_gh_api", fake_gh_api)

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=True, api=True))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {"gaps": [], "unverified": ["NO-011"]}


def test_run_json_without_api_stays_a_plain_list_even_with_a_stubbed_api_rule(
    tmp_path, capsys, monkeypatch
) -> None:
    """`--json` alone never nests: an api-check rule cannot run, so nothing is ever unverified."""
    stub_rules(
        monkeypatch,
        tmp_path,
        [_rule(id="NO-011", check="api", probe="security_reporting_route_must_be_on")],
    )

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=True, api=False))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == []


def test_run_prints_an_unverified_line_in_text_mode(tmp_path, capsys, monkeypatch) -> None:
    stub_rules(
        monkeypatch,
        tmp_path,
        [_rule(id="NO-011", check="api", probe="security_reporting_route_must_be_on")],
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )
    write(
        tmp_path,
        "SECURITY.md",
        "Use https://github.com/an-owner/a-repo/security/advisories/new\n",
    )
    monkeypatch.setattr(
        audit, "_gh_api", lambda path: (_ for _ in ()).throw(RuntimeError("gh: not authenticated"))
    )

    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=True))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "Unverified: NO-011"


def test_gaps_never_includes_an_unverified_probes_marker(tmp_path, monkeypatch) -> None:
    """The public `gaps()` helper (used by `resume`) only ever returns gap rows."""
    stub_rules(
        monkeypatch,
        tmp_path,
        [_rule(id="NO-011", check="api", probe="security_reporting_route_must_be_on")],
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )
    write(
        tmp_path,
        "SECURITY.md",
        "Use https://github.com/an-owner/a-repo/security/advisories/new\n",
    )
    monkeypatch.setattr(
        audit, "_gh_api", lambda path: (_ for _ in ()).throw(RuntimeError("gh: not authenticated"))
    )

    rows = audit.gaps(tmp_path, use_api=True)

    assert rows == []


def test_run_reads_rules_from_ossemble_not_the_target_even_without_a_rules_dir(
    tmp_path, capsys
) -> None:
    """A target repo with no rules/ directory of its own still audits fine."""
    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    captured = capsys.readouterr()
    assert "no rules/rules.json" not in captured.err
    assert exit_code in (0, 1)


def test_gaps_returns_the_same_rows_run_prints(tmp_path, capsys, monkeypatch) -> None:
    stub_rules(
        monkeypatch,
        tmp_path,
        [_rule(), _rule(id="STR-002", stage="finish")],
    )
    write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests"]\n')

    rows = audit.gaps(tmp_path)
    exit_code = audit.run(argparse.Namespace(path=str(tmp_path), as_json=True, api=False))

    printed_rows = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert rows == printed_rows
    assert rows == [
        {
            "id": "STR-001",
            "kind": "default",
            "stage": "build",
            "file": "pyproject.toml",
            "message": "[project] dependencies is not empty: ['requests']",
        }
    ]


def test_gaps_resolves_a_relative_path(tmp_path, monkeypatch) -> None:
    stub_rules(monkeypatch, tmp_path, [_rule()])
    write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests"]\n')
    monkeypatch.chdir(tmp_path)

    rows = audit.gaps(Path())

    assert [row["id"] for row in rows] == ["STR-001"]


# ------------------------------------------------------------------- facts


def test_applies_returns_true_when_no_when_conditions_are_given() -> None:
    assert audit._applies({}, facts()) is True


def test_applies_returns_false_when_a_when_condition_does_not_match_the_facts() -> None:
    assert audit._applies({"public": True}, facts(public=False)) is False


def test_has_workflows_is_false_when_the_workflows_directory_is_absent(tmp_path) -> None:
    assert audit._has_workflows(tmp_path) is False


def test_has_workflows_is_true_when_a_workflow_file_exists(tmp_path) -> None:
    workflow(tmp_path, "name: ci\n")
    assert audit._has_workflows(tmp_path) is True


def test_workflow_files_is_empty_when_the_workflows_directory_is_absent(tmp_path) -> None:
    assert audit._workflow_files(tmp_path) == []


def test_workflow_files_skips_a_symlinked_workflow(tmp_path) -> None:
    real = workflow(tmp_path, "name: ci\n")
    link = tmp_path / ".github" / "workflows" / "link.yml"
    link.symlink_to(real)

    files = audit._workflow_files(tmp_path)

    assert files == [real]


def test_stage_is_build_when_pyproject_toml_is_missing(tmp_path) -> None:
    assert audit._stage(tmp_path) == "build"


def test_stage_is_finish_once_the_coverage_floor_reaches_100(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.coverage.report]\nfail_under = 100\n")
    assert audit._stage(tmp_path) == "finish"


def test_stage_is_build_below_the_coverage_floor_of_100(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.coverage.report]\nfail_under = 99\n")
    assert audit._stage(tmp_path) == "build"


def test_load_toml_returns_none_for_a_symlink(tmp_path) -> None:
    real = write(tmp_path, "real.toml", "a = 1\n")
    link = tmp_path / "link.toml"
    link.symlink_to(real)
    assert audit._load_toml(link) is None


def test_load_toml_returns_none_for_invalid_toml(tmp_path) -> None:
    path = write(tmp_path, "bad.toml", "not = [valid")
    assert audit._load_toml(path) is None


def test_load_json_returns_none_when_the_file_is_missing(tmp_path) -> None:
    assert audit._load_json(tmp_path / "missing.json") is None


def test_load_json_returns_none_for_invalid_json(tmp_path) -> None:
    path = write(tmp_path, "bad.json", "not json")
    assert audit._load_json(path) is None


def test_read_text_returns_none_when_the_file_is_missing(tmp_path) -> None:
    assert audit._read_text(tmp_path / "missing.txt") is None


def test_read_text_returns_none_when_reading_raises_an_os_error(tmp_path, monkeypatch) -> None:
    path = write(tmp_path, "file.txt", "content\n")

    def raise_os_error(self, encoding=None):
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", raise_os_error)

    assert audit._read_text(path) is None


def test_run_git_returns_none_when_git_itself_cannot_run(tmp_path, monkeypatch) -> None:
    def raise_os_error(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(audit.subprocess, "run", raise_os_error)

    assert audit._run_git(tmp_path, "status") is None


def test_git_run_git_is_the_one_wrapper_audit_and_resume_both_share(tmp_path) -> None:
    """`audit._run_git` is `_git.run_git` itself, the one place this is tested."""
    init_git_repo(tmp_path)

    assert audit._run_git is audit._git.run_git
    result = audit._git.run_git(tmp_path, "rev-parse", "--is-inside-work-tree")

    assert result is not None
    assert result.returncode == 0
    assert result.stdout.strip() == "true"


def test_steps_splits_multiple_list_items_by_dedent() -> None:
    text = "steps:\n  - one\n    detail one\n  - two\n    detail two\n  - three\n"

    chunks = audit._steps(text)

    assert len(chunks) == 3
    assert chunks[0] == "  - one\n    detail one\n"
    assert chunks[1] == "  - two\n    detail two\n"
    assert chunks[2] == "  - three\n"


def test_steps_keeps_a_more_indented_nested_item_inside_its_own_step(tmp_path) -> None:
    """A step's own nested `- ` (a `with:` list, say) is not a step of its own."""
    text = "steps:\n  - one\n    - nested\n  - two\n"

    chunks = audit._steps(text)

    assert chunks == ["  - one\n    - nested\n", "  - two\n"]


def test_steps_stops_at_the_next_job_and_ignores_shallower_dashes_elsewhere() -> None:
    """A matrix entry or a later job's own `steps:` never fragments or extends this one."""
    text = (
        "jobs:\n"
        "  build:\n"
        "    strategy:\n"
        "      matrix:\n"
        "        os: [ubuntu-latest, windows-latest]\n"
        "    steps:\n"
        "      - run: echo hi\n"
        "  other:\n"
        "    steps:\n"
        "      - run: echo bye\n"
    )

    chunks = audit._steps(text)

    assert chunks == ["      - run: echo hi\n", "      - run: echo bye\n"]


def test_steps_returns_nothing_for_text_with_no_steps_key() -> None:
    assert audit._steps("- one\n  detail one\n- two\n") == []


def test_run_value_returns_none_for_a_step_with_no_run_key() -> None:
    assert audit._run_value("- uses: actions/checkout@v4\n") is None


def test_run_value_stops_at_a_sibling_key_after_an_inline_run(tmp_path) -> None:
    step = "      - run: echo hi\n        shell: bash\n"
    assert audit._run_value(step) == "echo hi\n"


def test_run_value_keeps_a_block_scalar_body_and_stops_at_the_next_step() -> None:
    step = "  - run: |\n      echo one\n      echo two\n  - run: echo three\n"
    assert audit._run_value(step) == "\n      echo one\n      echo two\n"


def test_jobs_returns_an_empty_mapping_when_there_is_no_jobs_key() -> None:
    assert audit._jobs("name: ci\n") == {}


def test_jobs_splits_the_text_by_top_level_job_name() -> None:
    text = "jobs:\n  a:\n    runs-on: ubuntu-latest\n  b:\n    runs-on: ubuntu-latest\n"
    jobs = audit._jobs(text)
    assert set(jobs) == {"a", "b"}
    assert "runs-on: ubuntu-latest" in jobs["a"]


def test_remote_owner_repo_returns_none_when_there_is_no_git_remote(tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert audit._remote_owner_repo(tmp_path) is None


def test_remote_owner_repo_parses_a_github_https_remote(tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )
    assert audit._remote_owner_repo(tmp_path) == "an-owner/a-repo"


def test_remote_owner_repo_returns_none_for_a_non_github_remote(tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )
    assert audit._remote_owner_repo(tmp_path) is None


def test_gh_api_returns_the_parsed_json_on_success(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)

    assert audit._gh_api("repos/an-owner/a-repo") == {"ok": True}


def test_gh_api_raises_runtime_error_with_stderr_on_a_non_zero_exit(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="not found"):
        audit._gh_api("repos/an-owner/a-repo")


def test_gather_facts_leaves_public_and_settings_unset_without_the_api_flag(tmp_path) -> None:
    result = audit._gather_facts(tmp_path, use_api=False)
    assert result["public"] is None
    assert result["repo_settings"] is None
    assert result["ruleset"] is None
    assert result["automated_security_fixes"] is None
    assert result["private_vulnerability_reporting"] is None


def test_gather_facts_reads_repo_settings_the_main_ruleset_and_security_fixes_with_the_api_flag(
    tmp_path, monkeypatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )

    def fake_gh_api(path):
        if path == "repos/an-owner/a-repo":
            return {"private": False}
        if path == "repos/an-owner/a-repo/rulesets":
            return [{"id": 1, "name": "main"}]
        if path == "repos/an-owner/a-repo/rulesets/1":
            return {"enforcement": "active"}
        if path == "repos/an-owner/a-repo/automated-security-fixes":
            return {"enabled": True, "paused": False}
        if path == "repos/an-owner/a-repo/private-vulnerability-reporting":
            return {"enabled": True}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(audit, "_gh_api", fake_gh_api)

    result = audit._gather_facts(tmp_path, use_api=True)

    assert result["public"] is True
    assert result["repo_settings"] == {"private": False}
    assert result["ruleset"] == {"enforcement": "active"}
    assert result["automated_security_fixes"] == {"enabled": True, "paused": False}
    assert result["private_vulnerability_reporting"] == {"enabled": True}


def test_gather_facts_skips_a_non_main_ruleset_before_finding_the_main_one(
    tmp_path, monkeypatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )

    def fake_gh_api(path):
        if path == "repos/an-owner/a-repo":
            return {"private": False}
        if path == "repos/an-owner/a-repo/rulesets":
            return [{"id": 1, "name": "other"}, {"id": 2, "name": "main"}]
        if path == "repos/an-owner/a-repo/rulesets/2":
            return {"enforcement": "active"}
        if path == "repos/an-owner/a-repo/automated-security-fixes":
            return {"enabled": True, "paused": False}
        if path == "repos/an-owner/a-repo/private-vulnerability-reporting":
            return {"enabled": True}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(audit, "_gh_api", fake_gh_api)

    result = audit._gather_facts(tmp_path, use_api=True)

    assert result["ruleset"] == {"enforcement": "active"}


def test_gather_facts_leaves_the_ruleset_unset_when_none_is_named_main(
    tmp_path, monkeypatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )

    def fake_gh_api(path):
        if path == "repos/an-owner/a-repo":
            return {"private": False}
        if path == "repos/an-owner/a-repo/rulesets":
            return [{"id": 1, "name": "other"}]
        if path == "repos/an-owner/a-repo/automated-security-fixes":
            return {"enabled": True, "paused": False}
        if path == "repos/an-owner/a-repo/private-vulnerability-reporting":
            return {"enabled": True}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(audit, "_gh_api", fake_gh_api)

    result = audit._gather_facts(tmp_path, use_api=True)

    assert result["ruleset"] is None


def test_gather_facts_tolerates_a_failing_gh_api_call(tmp_path, monkeypatch) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )

    def fake_gh_api(path):
        raise RuntimeError("gh: not authenticated")

    monkeypatch.setattr(audit, "_gh_api", fake_gh_api)

    result = audit._gather_facts(tmp_path, use_api=True)

    assert result["repo_settings"] is None
    assert result["ruleset"] is None
    assert result["automated_security_fixes"] is None
    assert result["private_vulnerability_reporting"] is None


def test_gather_facts_tolerates_a_failing_automated_security_fixes_call(
    tmp_path, monkeypatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )

    def fake_gh_api(path):
        if path == "repos/an-owner/a-repo":
            return {"private": True}
        if path == "repos/an-owner/a-repo/rulesets":
            return []
        if path == "repos/an-owner/a-repo/automated-security-fixes":
            raise RuntimeError("gh: not found")
        if path == "repos/an-owner/a-repo/private-vulnerability-reporting":
            return {"enabled": True}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(audit, "_gh_api", fake_gh_api)

    result = audit._gather_facts(tmp_path, use_api=True)

    assert result["repo_settings"] == {"private": True}
    assert result["automated_security_fixes"] is None
    assert result["private_vulnerability_reporting"] == {"enabled": True}


def test_gather_facts_tolerates_a_failing_private_vulnerability_reporting_call_alone(
    tmp_path, monkeypatch
) -> None:
    """A failure on this one endpoint never blanks the repo settings or ruleset calls."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/an-owner/a-repo.git"],
        cwd=tmp_path,
        check=True,
    )

    def fake_gh_api(path):
        if path == "repos/an-owner/a-repo":
            return {"private": True}
        if path == "repos/an-owner/a-repo/rulesets":
            return [{"id": 1, "name": "main"}]
        if path == "repos/an-owner/a-repo/rulesets/1":
            return {"enforcement": "active"}
        if path == "repos/an-owner/a-repo/automated-security-fixes":
            return {"enabled": True, "paused": False}
        if path == "repos/an-owner/a-repo/private-vulnerability-reporting":
            raise RuntimeError("gh: 403")
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(audit, "_gh_api", fake_gh_api)

    result = audit._gather_facts(tmp_path, use_api=True)

    assert result["repo_settings"] == {"private": True}
    assert result["ruleset"] == {"enforcement": "active"}
    assert result["automated_security_fixes"] == {"enabled": True, "paused": False}
    assert result["private_vulnerability_reporting"] is None


def test_gather_facts_reads_each_workflow_file_pyproject_and_tracked_files_exactly_once(
    tmp_path, monkeypatch
) -> None:
    workflow(tmp_path, "on:\n  push:\njobs:\n  build:\n    steps: []\n")
    workflow(tmp_path, "on:\n  push:\njobs:\n  build:\n    steps: []\n", name="other.yml")
    write(tmp_path, "pyproject.toml", "[project]\ndependencies = []\n")
    init_git_repo(tmp_path)

    read_calls: list[Path] = []
    original_read_text = audit._read_text

    def counting_read_text(path: Path) -> str | None:
        read_calls.append(path)
        return original_read_text(path)

    monkeypatch.setattr(audit, "_read_text", counting_read_text)

    load_toml_calls: list[Path] = []
    original_load_toml = audit._load_toml

    def counting_load_toml(path: Path) -> dict | None:
        load_toml_calls.append(path)
        return original_load_toml(path)

    monkeypatch.setattr(audit, "_load_toml", counting_load_toml)

    tracked_files_calls: list[Path] = []
    original_tracked_files = audit._tracked_files

    def counting_tracked_files(root: Path) -> set[str] | None:
        tracked_files_calls.append(root)
        return original_tracked_files(root)

    monkeypatch.setattr(audit, "_tracked_files", counting_tracked_files)

    facts = audit._gather_facts(tmp_path, use_api=False)

    workflow_reads = [path for path in read_calls if path.parent.name == "workflows"]
    assert sorted(workflow_reads) == sorted(path for path, _text in facts["workflow_items"])
    assert len(workflow_reads) == 2
    assert load_toml_calls == [tmp_path / "pyproject.toml"]
    assert tracked_files_calls == [tmp_path]


def test_run_reads_each_workflow_file_and_parses_pyproject_exactly_once_per_run(
    tmp_path, monkeypatch
) -> None:
    """Several probes need workflow text or pyproject; each reads its input once, not once each."""
    workflow(
        tmp_path,
        "permissions: {}\n"
        "on:\n  push:\njobs:\n  build:\n    permissions: {}\n"
        "    timeout-minutes: 5\n"
        "    steps:\n"
        "      - uses: actions/checkout@"
        + "a" * 40
        + " # v4\n"
        + "        with:\n          persist-credentials: false\n",
    )
    write(tmp_path, "pyproject.toml", "[project]\ndependencies = []\n")
    init_git_repo(tmp_path)

    read_calls: list[Path] = []
    original_read_text = audit._read_text

    def counting_read_text(path: Path) -> str | None:
        read_calls.append(path)
        return original_read_text(path)

    monkeypatch.setattr(audit, "_read_text", counting_read_text)

    load_toml_calls: list[Path] = []
    original_load_toml = audit._load_toml

    def counting_load_toml(path: Path) -> dict | None:
        load_toml_calls.append(path)
        return original_load_toml(path)

    monkeypatch.setattr(audit, "_load_toml", counting_load_toml)

    stub_rules(
        monkeypatch,
        tmp_path,
        [
            _rule(id="CI-001", probe="workflow_top_level_permissions_empty"),
            _rule(id="CI-002", probe="job_level_permissions_declared"),
            _rule(id="CI-003", probe="job_timeout_minutes_set"),
            _rule(id="CI-004", probe="checkout_persist_credentials_false"),
            _rule(id="CI-005", probe="actions_pinned_to_full_sha_with_version_comment"),
            _rule(id="CI-006", probe="concurrency_keyed_by_ref_on_pr_and_sha_on_push"),
            _rule(id="STR-005", probe="stdlib_only_runtime_dependencies"),
            _rule(id="STR-006", probe="coverage_floor_at_least_seventy"),
        ],
    )

    audit.run(argparse.Namespace(path=str(tmp_path), as_json=False, api=False))

    workflow_reads = [path for path in read_calls if path.parent.name == "workflows"]
    assert len(workflow_reads) == 1
    assert load_toml_calls == [tmp_path / "pyproject.toml"]


# ------------------------------------------------------------------- probes


def test_stdlib_only_runtime_dependencies_passes_when_the_dependency_list_is_empty(
    tmp_path,
) -> None:
    write(tmp_path, "pyproject.toml", "[project]\ndependencies = []\n")
    assert audit.stdlib_only_runtime_dependencies(tmp_path, facts()) is None


def test_stdlib_only_runtime_dependencies_fails_when_a_dependency_is_listed(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["requests"]\n')
    assert audit.stdlib_only_runtime_dependencies(tmp_path, facts()) is not None


def test_dev_tooling_in_dependency_group_passes_with_a_dev_group_and_no_build_backend(
    tmp_path,
) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[dependency-groups]\ndev = ["pytest"]\n\n[tool.uv]\npackage = false\n',
    )
    assert audit.dev_tooling_in_dependency_group(tmp_path, facts()) is None


def test_dev_tooling_in_dependency_group_fails_without_a_dev_group(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.uv]\npackage = false\n")
    assert audit.dev_tooling_in_dependency_group(tmp_path, facts()) is not None


def test_dev_tooling_in_dependency_group_fails_when_package_is_not_false(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", '[dependency-groups]\ndev = ["pytest"]\n')
    assert audit.dev_tooling_in_dependency_group(tmp_path, facts()) is not None


def test_docs_under_300_lines_passes_for_a_short_readme(tmp_path) -> None:
    write(tmp_path, "README.md", "one line\n")
    assert audit.docs_under_300_lines(tmp_path, facts()) is None


def test_docs_under_300_lines_fails_for_a_long_readme(tmp_path) -> None:
    write(tmp_path, "README.md", "\n".join(f"line {n}" for n in range(400)))
    assert audit.docs_under_300_lines(tmp_path, facts()) is not None


def test_docs_under_300_lines_ignores_a_long_file_under_references(tmp_path) -> None:
    write(tmp_path, "README.md", "one line\n")
    write(tmp_path, "references/long.md", "\n".join(f"line {n}" for n in range(400)))
    assert audit.docs_under_300_lines(tmp_path, facts()) is None


def test_docs_under_300_lines_ignores_a_long_file_under_agents(tmp_path) -> None:
    write(tmp_path, "README.md", "one line\n")
    write(tmp_path, "agents/long.md", "\n".join(f"line {n}" for n in range(400)))
    assert audit.docs_under_300_lines(tmp_path, facts()) is None


def test_leanness_tool_never_wired_into_ci_passes_without_ponytail(tmp_path) -> None:
    workflow(tmp_path, "name: ci\njobs:\n  test:\n    runs-on: ubuntu-latest\n")
    assert audit.leanness_tool_never_wired_into_ci(tmp_path, facts()) is None


def test_leanness_tool_never_wired_into_ci_fails_when_a_workflow_mentions_ponytail(
    tmp_path,
) -> None:
    workflow(tmp_path, "name: ci\njobs:\n  lean:\n    steps:\n      - run: ponytail --check\n")
    assert audit.leanness_tool_never_wired_into_ci(tmp_path, facts()) is not None


def test_workflow_top_level_permissions_empty_passes_when_declared(tmp_path) -> None:
    workflow(tmp_path, "name: ci\npermissions: {}\njobs: {}\n")
    assert audit.workflow_top_level_permissions_empty(tmp_path, facts()) is None


def test_workflow_top_level_permissions_empty_fails_when_missing(tmp_path) -> None:
    workflow(tmp_path, "name: ci\njobs: {}\n")
    assert audit.workflow_top_level_permissions_empty(tmp_path, facts()) is not None


GOOD_JOB = (
    "jobs:\n  build:\n    runs-on: ubuntu-latest\n    timeout-minutes: 10\n"
    "    permissions:\n      contents: read\n"
)


def test_job_level_permissions_declared_passes_when_every_job_has_one(tmp_path) -> None:
    workflow(tmp_path, GOOD_JOB)
    assert audit.job_level_permissions_declared(tmp_path, facts()) is None


def test_job_level_permissions_declared_fails_when_a_job_has_none(tmp_path) -> None:
    workflow(tmp_path, "jobs:\n  build:\n    runs-on: ubuntu-latest\n    timeout-minutes: 10\n")
    assert audit.job_level_permissions_declared(tmp_path, facts()) is not None


def test_job_timeout_minutes_set_passes_when_every_job_has_one(tmp_path) -> None:
    workflow(tmp_path, GOOD_JOB)
    assert audit.job_timeout_minutes_set(tmp_path, facts()) is None


def test_job_timeout_minutes_set_fails_when_a_job_has_none(tmp_path) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    runs-on: ubuntu-latest\n    permissions:\n      contents: read\n",
    )
    assert audit.job_timeout_minutes_set(tmp_path, facts()) is not None


CHECKOUT_GOOD = (
    "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@"
    "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
    "        with:\n          persist-credentials: false\n"
)
CHECKOUT_BAD = (
    "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@"
    "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
)


def test_checkout_persist_credentials_false_passes_when_set(tmp_path) -> None:
    workflow(tmp_path, CHECKOUT_GOOD)
    assert audit.checkout_persist_credentials_false(tmp_path, facts()) is None


def test_checkout_persist_credentials_false_fails_when_missing(tmp_path) -> None:
    workflow(tmp_path, CHECKOUT_BAD)
    assert audit.checkout_persist_credentials_false(tmp_path, facts()) is not None


def test_actions_pinned_to_full_sha_with_version_comment_passes_for_a_pinned_action(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@"
        "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n",
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is None


def test_actions_pinned_to_full_sha_with_version_comment_fails_for_a_tag_pin(tmp_path) -> None:
    workflow(tmp_path, "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n")
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is not None


def test_actions_pinned_to_full_sha_with_version_comment_ignores_uses_mentioned_in_a_comment(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "# every `uses:` must be a full commit SHA\n"
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@"
        "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n",
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is None


def test_actions_pinned_to_full_sha_with_version_comment_passes_for_a_justified_self_reference(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n"
        "      - uses: acme/acme@main # zizmor: ignore[unpinned-uses] this repo is acme\n",
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is None


def test_actions_pinned_to_full_sha_with_version_comment_fails_for_an_ignore_with_no_reason(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n"
        "      - uses: acme/acme@main # zizmor: ignore[unpinned-uses]\n",
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is not None


def test_actions_pinned_to_full_sha_with_version_comment_skips_a_local_path_reference(
    tmp_path,
) -> None:
    """A local path cannot carry a commit-SHA pin, so it is exempt, not a gap."""
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - uses: ./.github/workflows/update-docs.yml\n",
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is None


def test_actions_pinned_to_full_sha_with_version_comment_skips_a_docker_reference(
    tmp_path,
) -> None:
    workflow(tmp_path, "jobs:\n  build:\n    steps:\n      - uses: docker://alpine:3.18\n")
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is None


def test_actions_pinned_to_full_sha_with_version_comment_still_fails_with_no_pin_at_all(
    tmp_path,
) -> None:
    """Exempting local paths and docker refs must not exempt a bare third-party reference."""
    workflow(tmp_path, "jobs:\n  build:\n    steps:\n      - uses: actions/checkout\n")
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is not None


def test_actions_pinned_to_full_sha_with_version_comment_passes_for_a_quoted_ratchet_pin(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n"
        "      - uses: 'docker/setup-qemu-action@"
        "96fe6ef7f33517b61c61be40b68a1882f3264fb8' # ratchet:docker/setup-qemu-action@v4\n",
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is None


def test_actions_pinned_to_full_sha_with_version_comment_fails_for_a_quoted_pin_with_no_comment(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n"
        '      - uses: "docker/setup-qemu-action@'
        '96fe6ef7f33517b61c61be40b68a1882f3264fb8"\n',
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is not None


def test_actions_pinned_to_full_sha_with_version_comment_ignores_a_key_ending_in_uses(
    tmp_path,
) -> None:
    """`statuses: write` must never be mistaken for a `uses:` key."""
    workflow(
        tmp_path,
        "jobs:\n  build:\n    permissions:\n      statuses: write\n    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n",
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is None


def test_actions_pinned_to_full_sha_with_version_comment_ignores_uses_inside_prose(
    tmp_path,
) -> None:
    """`uses:` written inside a body/run block scalar is text, not a YAML key."""
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
        "      - run: |\n"
        "          echo 'Update `uses: astral-sh/setup-uv@...` in the docs.'\n",
    )
    assert audit.actions_pinned_to_full_sha_with_version_comment(tmp_path, facts()) is None


# --- pinact_verify_runs_on_pull_request -----------------------------------------------------


def test_pinact_verify_runs_on_pull_request_passes_when_a_pull_request_workflow_verifies(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "on:\n  pull_request:\njobs:\n  checks:\n    steps:\n"
        "      - uses: suzuki-shunsuke/pinact-action@896d595f299e71d65b9d28349d6956abe144390a"
        " # v3.0.0\n"
        "        with:\n"
        '          verify: "true"\n',
    )
    assert audit.pinact_verify_runs_on_pull_request(tmp_path, facts()) is None


def test_pinact_verify_runs_on_pull_request_fails_when_no_workflow_triggers_on_pull_request(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "on:\n  push:\njobs:\n  checks:\n    steps:\n"
        "      - uses: suzuki-shunsuke/pinact-action@896d595f299e71d65b9d28349d6956abe144390a"
        " # v3.0.0\n"
        "        with:\n"
        '          verify: "true"\n',
    )
    assert audit.pinact_verify_runs_on_pull_request(tmp_path, facts()) is not None


def test_pinact_verify_runs_on_pull_request_fails_when_the_step_is_missing(tmp_path) -> None:
    workflow(
        tmp_path,
        "on:\n  pull_request:\njobs:\n  checks:\n    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n",
    )
    assert audit.pinact_verify_runs_on_pull_request(tmp_path, facts()) is not None


def test_pinact_verify_runs_on_pull_request_fails_when_verify_is_not_true(tmp_path) -> None:
    workflow(
        tmp_path,
        "on:\n  pull_request:\njobs:\n  checks:\n    steps:\n"
        "      - uses: suzuki-shunsuke/pinact-action@896d595f299e71d65b9d28349d6956abe144390a"
        " # v3.0.0\n"
        "        with:\n"
        '          fix: "true"\n'
        '          verify: "false"\n',
    )
    assert audit.pinact_verify_runs_on_pull_request(tmp_path, facts()) is not None


# --- zizmor_runs_in_precommit_or_ci ----------------------------------------------------------


def test_zizmor_runs_in_precommit_or_ci_passes_with_the_pre_commit_hook(tmp_path) -> None:
    write(
        tmp_path,
        ".pre-commit-config.yaml",
        "repos:\n  - repo: https://github.com/woodruffw/zizmor-pre-commit\n"
        "    rev: v1.30.1\n    hooks:\n      - id: zizmor\n",
    )
    assert audit.zizmor_runs_in_precommit_or_ci(tmp_path, facts()) is None


def test_zizmor_runs_in_precommit_or_ci_passes_with_a_ci_step(tmp_path) -> None:
    workflow(
        tmp_path,
        "jobs:\n  checks:\n    steps:\n      - run: uvx zizmor .\n",
    )
    assert audit.zizmor_runs_in_precommit_or_ci(tmp_path, facts()) is None


def test_zizmor_runs_in_precommit_or_ci_fails_when_neither_is_configured(tmp_path) -> None:
    write(tmp_path, ".pre-commit-config.yaml", "repos:\n  - repo: https://example.com/ruff\n")
    workflow(tmp_path, "jobs:\n  checks:\n    steps:\n      - run: echo hi\n")
    assert audit.zizmor_runs_in_precommit_or_ci(tmp_path, facts()) is not None


def test_zizmor_runs_in_precommit_or_ci_ignores_a_mention_that_is_not_the_hook_id(
    tmp_path,
) -> None:
    """A comment that merely mentions zizmor is not the `- id: zizmor` hook itself."""
    write(
        tmp_path,
        ".pre-commit-config.yaml",
        "# zizmor runs in CI instead of here\nrepos:\n  - repo: https://example.com/ruff\n",
    )
    assert audit.zizmor_runs_in_precommit_or_ci(tmp_path, facts()) is not None


def test_no_expression_interpolation_in_run_steps_passes_when_env_carries_the_value(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - env:\n          VALUE: ${{ github.sha }}\n"
        '        run: echo "$VALUE"\n',
    )
    assert audit.no_expression_interpolation_in_run_steps(tmp_path, facts()) is None


def test_no_expression_interpolation_in_run_steps_fails_when_run_interpolates_directly(
    tmp_path,
) -> None:
    workflow(tmp_path, 'jobs:\n  build:\n    steps:\n      - run: echo "${{ github.sha }}"\n')
    assert audit.no_expression_interpolation_in_run_steps(tmp_path, facts()) is not None


def test_no_expression_interpolation_in_run_steps_passes_for_a_step_with_no_run_key(
    tmp_path,
) -> None:
    workflow(tmp_path, "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n")
    assert audit.no_expression_interpolation_in_run_steps(tmp_path, facts()) is None


def test_no_expression_interpolation_in_run_steps_ignores_a_shallow_dash_before_the_jobs(
    tmp_path,
) -> None:
    """A schedule cron or a matrix list, shallower than `steps:`, must never widen a step.

    A later step's own `${{ }}` in `with:`, not `run:`, must not be swept
    into an earlier step's run block either.
    """
    workflow(
        tmp_path,
        "on:\n  schedule:\n    - cron: '0 0 * * *'\n"
        "jobs:\n"
        "  build:\n"
        "    strategy:\n"
        "      matrix:\n"
        "        os: [ubuntu-latest, windows-latest]\n"
        "    steps:\n"
        "      - run: echo hi\n"
        "      - name: use a secret\n"
        "        if: ${{ failure() }}\n"
        "        with:\n"
        "          token: ${{ secrets.TOKEN }}\n",
    )
    assert audit.no_expression_interpolation_in_run_steps(tmp_path, facts()) is None


def test_no_expression_interpolation_in_run_steps_still_fails_inside_a_real_run_block(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "on:\n  schedule:\n    - cron: '0 0 * * *'\n"
        "jobs:\n  build:\n    steps:\n"
        '      - run: echo "${{ github.sha }}"\n',
    )
    assert audit.no_expression_interpolation_in_run_steps(tmp_path, facts()) is not None


def test_secrets_scan_configured_over_full_history_fails_when_no_workflow_runs_it(
    tmp_path,
) -> None:
    write(
        tmp_path,
        ".pre-commit-config.yaml",
        "repos:\n  - repo: https://github.com/gitleaks/gitleaks\n",
    )
    workflow(tmp_path, "jobs:\n  build:\n    steps:\n      - run: pytest\n")
    assert audit.secrets_scan_configured_over_full_history(tmp_path, facts()) is not None


def test_secrets_scan_configured_over_full_history_passes_with_gitleaks_and_full_history(
    tmp_path,
) -> None:
    write(
        tmp_path,
        ".pre-commit-config.yaml",
        "repos:\n  - repo: https://github.com/gitleaks/gitleaks\n",
    )
    workflow(
        tmp_path,
        "jobs:\n  checks:\n    steps:\n      - uses: gitleaks/gitleaks-action@x\n"
        "        with:\n          fetch-depth: 0\n",
    )
    assert audit.secrets_scan_configured_over_full_history(tmp_path, facts()) is None


def test_secrets_scan_configured_over_full_history_fails_without_a_gitleaks_hook(tmp_path) -> None:
    write(
        tmp_path,
        ".pre-commit-config.yaml",
        "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n",
    )
    assert audit.secrets_scan_configured_over_full_history(tmp_path, facts()) is not None


DEPENDABOT_GOOD = (
    "version: 2\nupdates:\n"
    '  - package-ecosystem: "github-actions"\n    schedule:\n      interval: "weekly"\n'
    '    cooldown:\n      default-days: 7\n    groups:\n      actions:\n        patterns: ["*"]\n'
    '  - package-ecosystem: "pip"\n    schedule:\n      interval: "weekly"\n'
    '    cooldown:\n      default-days: 7\n    groups:\n      python:\n        patterns: ["*"]\n'
)


def test_dependabot_grouped_weekly_with_cooldown_passes_for_a_well_formed_config(tmp_path) -> None:
    write(tmp_path, ".github/dependabot.yml", DEPENDABOT_GOOD)
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is None


def test_dependabot_grouped_weekly_with_cooldown_fails_when_the_file_is_missing(tmp_path) -> None:
    """A workflow exists, so Dependabot would have something to update."""
    assert (
        audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts(has_workflows=True))
        is not None
    )


def test_dependabot_grouped_weekly_with_cooldown_passes_with_no_workflow_and_no_manifest(
    tmp_path,
) -> None:
    """No workflow and no dependency manifest: a dependabot file would configure nothing."""
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is None


def test_dependabot_grouped_weekly_with_cooldown_fails_when_a_manifest_exists(tmp_path) -> None:
    """A tracked manifest means Dependabot has something to update, even with no workflow."""
    init_git_repo(tmp_path)
    write(tmp_path, "pyproject.toml", '[project]\nname = "x"\n')
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path, check=True)
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is not None


def test_dependabot_grouped_weekly_with_cooldown_finds_a_manifest_nested_under_a_subdirectory(
    tmp_path,
) -> None:
    """A manifest need not sit at the root: a monorepo package's own manifest counts too."""
    init_git_repo(tmp_path)
    write(tmp_path, "packages/widget/requirements-dev.txt", "requests\n")
    subprocess.run(["git", "add", "packages"], cwd=tmp_path, check=True)
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is not None


def test_dependabot_grouped_weekly_with_cooldown_passes_with_tracked_files_but_no_manifest(
    tmp_path,
) -> None:
    """A git repo with tracked files that match no manifest pattern still gets a pass."""
    init_git_repo(tmp_path)
    write(tmp_path, "README.md", "hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is None


def test_dependabot_grouped_weekly_with_cooldown_fails_without_a_weekly_interval(
    tmp_path,
) -> None:
    write(tmp_path, ".github/dependabot.yml", DEPENDABOT_GOOD.replace('"weekly"', '"daily"'))
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is not None


def test_dependabot_grouped_weekly_with_cooldown_fails_without_a_cooldown(tmp_path) -> None:
    write(tmp_path, ".github/dependabot.yml", DEPENDABOT_GOOD.replace("cooldown:", "chill:"))
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is not None


def test_dependabot_grouped_weekly_with_cooldown_fails_without_groups(tmp_path) -> None:
    write(tmp_path, ".github/dependabot.yml", DEPENDABOT_GOOD.replace("groups:", "bunches:"))
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is not None


def test_dependabot_grouped_weekly_with_cooldown_passes_for_any_well_configured_ecosystem(
    tmp_path,
) -> None:
    """Not only github-actions and pip: any ecosystem that is grouped weekly with a cooldown."""
    write(
        tmp_path,
        ".github/dependabot.yml",
        DEPENDABOT_GOOD.replace('package-ecosystem: "pip"', 'package-ecosystem: "npm"'),
    )
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is None


def test_dependabot_grouped_weekly_with_cooldown_fails_for_a_cooldown_under_seven_days(
    tmp_path,
) -> None:
    write(
        tmp_path,
        ".github/dependabot.yml",
        DEPENDABOT_GOOD.replace("default-days: 7", "default-days: 3"),
    )
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is not None


def test_dependabot_grouped_weekly_with_cooldown_reads_the_yaml_spelling_too(tmp_path) -> None:
    write(tmp_path, ".github/dependabot.yaml", DEPENDABOT_GOOD)
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is None


def test_dependabot_grouped_weekly_with_cooldown_fails_when_no_updates_are_configured(
    tmp_path,
) -> None:
    write(tmp_path, ".github/dependabot.yml", "version: 2\nupdates:\n")
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is not None


def test_dependabot_grouped_weekly_with_cooldown_prefers_yml_when_both_exist(tmp_path) -> None:
    write(tmp_path, ".github/dependabot.yml", DEPENDABOT_GOOD)
    write(tmp_path, ".github/dependabot.yaml", DEPENDABOT_GOOD.replace('"weekly"', '"daily"'))
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is None


def test_dependabot_grouped_weekly_with_cooldown_reads_entries_flush_with_updates(
    tmp_path,
) -> None:
    """YAML allows `- ` at the same indent as its own key, not only more indented."""
    write(
        tmp_path,
        ".github/dependabot.yml",
        "version: 2\nupdates:\n"
        '- package-ecosystem: "npm"\n  schedule:\n    interval: "weekly"\n'
        '  cooldown:\n    default-days: 7\n  groups:\n    npm:\n      patterns: ["*"]\n',
    )
    assert audit.dependabot_grouped_weekly_with_cooldown(tmp_path, facts()) is None


RUFF_GOOD = (
    "[tool.ruff.lint]\n"
    'select = ["ALL"]\n'
    'ignore = [\n    "COM812",  # formatter owns trailing commas\n]\n\n'
    "[tool.ruff.lint.per-file-ignores]\n"
    '"tests/*" = ["S101"]\n'
)


def test_ruff_select_all_with_ignores_justified_passes_for_a_well_commented_config(
    tmp_path,
) -> None:
    write(tmp_path, "pyproject.toml", RUFF_GOOD)
    assert audit.ruff_select_all_with_ignores_justified(tmp_path, facts()) is None


def test_ruff_select_all_with_ignores_justified_fails_when_pyproject_toml_is_missing(
    tmp_path,
) -> None:
    assert audit.ruff_select_all_with_ignores_justified(tmp_path, facts()) is not None


def test_ruff_select_all_with_ignores_justified_passes_for_a_non_security_per_file_ignore(
    tmp_path,
) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff.lint]\nselect = ["ALL"]\n\n[tool.ruff.lint.per-file-ignores]\n'
        '"scripts/*" = ["D103", "ANN001"]\n',
    )
    assert audit.ruff_select_all_with_ignores_justified(tmp_path, facts()) is None


def test_ruff_select_all_with_ignores_justified_fails_when_select_is_not_all(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.ruff.lint]\nselect = ["E"]\n')
    assert audit.ruff_select_all_with_ignores_justified(tmp_path, facts()) is not None


def test_ruff_select_all_with_ignores_justified_fails_for_an_uncommented_ignore(tmp_path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff.lint]\nselect = ["ALL"]\nignore = [\n    "COM812",\n]\n',
    )
    assert audit.ruff_select_all_with_ignores_justified(tmp_path, facts()) is not None


def test_ruff_select_all_with_ignores_justified_fails_for_a_security_ignore_outside_tests(
    tmp_path,
) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff.lint]\nselect = ["ALL"]\n\n[tool.ruff.lint.per-file-ignores]\n'
        '"scripts/*" = ["S101"]\n',
    )
    assert audit.ruff_select_all_with_ignores_justified(tmp_path, facts()) is not None


def test_on_triggers_returns_empty_when_there_is_no_on_line() -> None:
    assert audit._on_triggers("jobs: {}\n") == set()


def test_on_triggers_reads_a_single_inline_trigger() -> None:
    assert audit._on_triggers("on: push\njobs: {}\n") == {"push"}


def test_on_triggers_reads_an_inline_list_of_triggers() -> None:
    assert audit._on_triggers("on: [push, pull_request]\njobs: {}\n") == {"push", "pull_request"}


def test_on_triggers_reads_a_block_of_triggers() -> None:
    text = 'on:\n  schedule:\n    - cron: "0 0 * * 1"\n  workflow_dispatch:\njobs: {}\n'
    assert audit._on_triggers(text) == {"schedule", "workflow_dispatch"}


def test_on_triggers_returns_empty_when_the_on_block_ends_the_file_with_no_newline() -> None:
    assert audit._on_triggers("jobs: {}\non:") == set()


ON_PULL_REQUEST_AND_PUSH = "on:\n  pull_request:\n  push:\n    branches: [main]\n"

CONCURRENCY_GOOD = (
    ON_PULL_REQUEST_AND_PUSH + "concurrency:\n"
    "  group: ci-${{ github.event_name == 'pull_request' && github.ref || github.sha }}\n"
    "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
    "jobs: {}\n"
)


def test_concurrency_keyed_by_ref_on_pr_and_sha_on_push_passes_for_the_standard_shape(
    tmp_path,
) -> None:
    workflow(tmp_path, CONCURRENCY_GOOD)
    assert audit.concurrency_keyed_by_ref_on_pr_and_sha_on_push(tmp_path, facts()) is None


def test_concurrency_keyed_by_ref_on_pr_and_sha_on_push_fails_when_missing(tmp_path) -> None:
    workflow(tmp_path, ON_PULL_REQUEST_AND_PUSH + "jobs: {}\n")
    assert audit.concurrency_keyed_by_ref_on_pr_and_sha_on_push(tmp_path, facts()) is not None


def test_concurrency_keyed_by_ref_on_pr_and_sha_on_push_fails_when_not_keyed_by_both(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        ON_PULL_REQUEST_AND_PUSH + "concurrency:\n  group: ci-${{ github.ref }}\njobs: {}\n",
    )
    assert audit.concurrency_keyed_by_ref_on_pr_and_sha_on_push(tmp_path, facts()) is not None


def test_concurrency_keyed_by_ref_on_pr_and_sha_on_push_fails_without_cancel_in_progress(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        ON_PULL_REQUEST_AND_PUSH + "concurrency:\n"
        "  group: ci-${{ github.event_name == 'pull_request' && github.ref || github.sha }}\n"
        "jobs: {}\n",
    )
    assert audit.concurrency_keyed_by_ref_on_pr_and_sha_on_push(tmp_path, facts()) is not None


def test_concurrency_keyed_by_ref_on_pr_and_sha_on_push_passes_for_pull_request_only_keyed_by_ref(
    tmp_path,
) -> None:
    """A pull_request-only workflow, such as a dependency audit, needs no sha key: no push."""
    workflow(
        tmp_path,
        "on:\n"
        '  schedule:\n    - cron: "51 6 * * 2"\n'
        "  pull_request:\n    paths:\n      - pyproject.toml\n"
        "concurrency:\n"
        "  group: audit-${{ github.event_name == 'pull_request' && github.ref || 'schedule' }}\n"
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
        "jobs: {}\n",
    )
    assert audit.concurrency_keyed_by_ref_on_pr_and_sha_on_push(tmp_path, facts()) is None


def test_concurrency_keyed_by_ref_on_pr_and_sha_on_push_exempts_a_schedule_only_workflow(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        'on:\n  schedule:\n    - cron: "0 0 * * 1"\n  workflow_dispatch:\njobs: {}\n',
    )
    assert audit.concurrency_keyed_by_ref_on_pr_and_sha_on_push(tmp_path, facts()) is None


def test_concurrency_keyed_by_ref_on_pr_and_sha_on_push_does_not_exempt_pull_request_plus_schedule(
    tmp_path,
) -> None:
    """Adding schedule alongside pull_request does not exempt the workflow."""
    workflow(
        tmp_path,
        'on:\n  schedule:\n    - cron: "0 0 * * 1"\n  pull_request:\njobs: {}\n',
    )
    assert audit.concurrency_keyed_by_ref_on_pr_and_sha_on_push(tmp_path, facts()) is not None


def test_concurrency_keyed_by_ref_on_pr_and_sha_on_push_fails_when_pull_request_lacks_a_ref_key(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "on:\n  pull_request:\n"
        "concurrency:\n  group: audit\n  cancel-in-progress: true\njobs: {}\n",
    )
    assert audit.concurrency_keyed_by_ref_on_pr_and_sha_on_push(tmp_path, facts()) is not None


CI_GATE_GOOD = (
    "on:\n  pull_request:\njobs:\n"
    "  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    "  ci:\n    needs: [test]\n    if: always()\n"
    '    steps:\n      - run: |\n          if [ "${R}" != "success" ]; then exit 1; fi\n'
)


def test_ci_gate_job_fails_closed_passes_for_the_standard_gate_job(tmp_path) -> None:
    workflow(tmp_path, CI_GATE_GOOD)
    assert audit.ci_gate_job_fails_closed(tmp_path, facts()) is None


def test_ci_gate_job_fails_closed_passes_when_the_workflow_has_a_single_job(tmp_path) -> None:
    """A workflow with exactly one job is itself the one required context; no gate needed."""
    workflow(tmp_path, "on:\n  pull_request:\njobs:\n  test:\n    runs-on: ubuntu-latest\n")
    assert audit.ci_gate_job_fails_closed(tmp_path, facts()) is None


def test_ci_gate_job_fails_closed_fails_when_there_is_no_always_gate_job(tmp_path) -> None:
    workflow(
        tmp_path,
        "on:\n  pull_request:\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "  build:\n    runs-on: ubuntu-latest\n",
    )
    assert audit.ci_gate_job_fails_closed(tmp_path, facts()) is not None


def test_ci_gate_job_fails_closed_fails_when_the_gate_job_never_checks_the_result(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "on:\n  pull_request:\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "  ci:\n    needs: [test]\n    if: always()\n"
        "    steps:\n      - run: echo done\n",
    )
    assert audit.ci_gate_job_fails_closed(tmp_path, facts()) is not None


def test_ci_gate_job_fails_closed_passes_for_the_alls_green_gate_job(tmp_path) -> None:
    """Job name does not matter, and neither does the shape of the if: guard."""
    workflow(
        tmp_path,
        "on:\n  pull_request:\njobs:\n"
        "  lint:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo lint\n"
        "  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo test\n"
        "  all-tests-pass:\n    needs: [lint, test]\n"
        "    if: ${{ !cancelled() }}\n    steps:\n"
        "      - uses: re-actors/alls-green@b5b5b37504aa4183270bd3d855c52a67f212be35 # v1.3.0\n"
        "        with:\n          jobs: ${{ toJSON(needs) }}\n",
    )
    assert audit.ci_gate_job_fails_closed(tmp_path, facts()) is None


def test_ci_gate_job_fails_closed_fails_when_the_gate_job_skips_a_dependency(tmp_path) -> None:
    """Delegating to alls-green is not enough if the gate job does not need every job."""
    workflow(
        tmp_path,
        "on:\n  pull_request:\njobs:\n"
        "  lint:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo lint\n"
        "  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo test\n"
        "  all-tests-pass:\n    needs: [lint]\n    if: always()\n    steps:\n"
        "      - uses: re-actors/alls-green@b5b5b37504aa4183270bd3d855c52a67f212be35 # v1.3.0\n",
    )
    assert audit.ci_gate_job_fails_closed(tmp_path, facts()) is not None


def test_needs_parses_a_block_style_list() -> None:
    body = "    needs:\n      - lint\n      - test\n    if: always()\n"
    assert audit._needs(body) == {"lint", "test"}


def test_needs_returns_an_empty_set_with_no_needs_key() -> None:
    assert audit._needs("    if: always()\n") == set()


def test_ci_gate_job_fails_closed_passes_with_a_block_style_needs_list(tmp_path) -> None:
    workflow(
        tmp_path,
        "on:\n  pull_request:\njobs:\n"
        "  lint:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo lint\n"
        "  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo test\n"
        "  ci:\n    needs:\n      - lint\n      - test\n    if: always()\n"
        "    steps:\n      - uses: re-actors/alls-green@abcdef\n",
    )
    assert audit.ci_gate_job_fails_closed(tmp_path, facts()) is None


def test_ci_gate_job_fails_closed_ignores_a_workflow_with_no_pull_request_trigger(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "on:\n  schedule:\n    - cron: '0 0 * * *'\njobs:\n"
        "  a:\n    runs-on: ubuntu-latest\n  b:\n    runs-on: ubuntu-latest\n",
    )
    assert audit.ci_gate_job_fails_closed(tmp_path, facts()) is None


def test_dependency_audit_workflow_separate_and_scheduled_passes_for_a_scheduled_pip_audit(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "on:\n  schedule:\n    - cron: '0 0 * * 1'\n"
        "  pull_request:\n    paths: ['pyproject.toml']\n"
        "jobs:\n  audit:\n    steps:\n      - run: pip-audit\n",
        name="pip-audit.yml",
    )
    assert audit.dependency_audit_workflow_separate_and_scheduled(tmp_path, facts()) is None


def test_dependency_audit_workflow_separate_and_scheduled_fails_when_absent(tmp_path) -> None:
    workflow(tmp_path, "jobs:\n  test:\n    runs-on: ubuntu-latest\n")
    assert audit.dependency_audit_workflow_separate_and_scheduled(tmp_path, facts()) is not None


def test_dependency_audit_workflow_separate_and_scheduled_keeps_looking_past_an_unscheduled_one(
    tmp_path,
) -> None:
    workflow(tmp_path, "jobs:\n  audit:\n    steps:\n      - run: pip-audit\n", name="a.yml")
    workflow(tmp_path, "jobs:\n  test:\n    runs-on: ubuntu-latest\n", name="ci.yml")
    assert audit.dependency_audit_workflow_separate_and_scheduled(tmp_path, facts()) is not None


def test_diff_cover_runs_on_one_ci_leg_passes_when_a_step_runs_it(tmp_path) -> None:
    workflow(tmp_path, "jobs:\n  test:\n    steps:\n      - run: diff-cover coverage.xml\n")
    assert audit.diff_cover_runs_on_one_ci_leg(tmp_path, facts()) is None


def test_diff_cover_runs_on_one_ci_leg_fails_when_no_step_runs_it(tmp_path) -> None:
    workflow(tmp_path, "jobs:\n  test:\n    steps:\n      - run: pytest\n")
    assert audit.diff_cover_runs_on_one_ci_leg(tmp_path, facts()) is not None


def test_full_interpreter_matrix_everywhere_passes_for_an_unconditional_matrix(tmp_path) -> None:
    workflow(
        tmp_path,
        "jobs:\n  test:\n    strategy:\n      matrix:\n"
        '        python-version: ["3.11", "3.12", "3.14"]\n',
    )
    assert audit.full_interpreter_matrix_everywhere(tmp_path, facts()) is None


def test_full_interpreter_matrix_everywhere_fails_when_still_narrowed_on_pull_requests(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  test:\n    strategy:\n      matrix:\n"
        "        python-version: ${{ github.event_name == 'pull_request' && "
        "fromJson('[\"3.12\"]') || fromJson('[\"3.11\"]') }}\n",
    )
    assert audit.full_interpreter_matrix_everywhere(tmp_path, facts()) is not None


def test_readme_has_no_ci_badge_code_or_workflow_link_before_content_passes_for_a_clean_hero(
    tmp_path,
) -> None:
    write(
        tmp_path,
        "README.md",
        "# ossemble\n\nAssembles a finished open-source repo.\n\n## Features\n\nstuff\n",
    )
    assert (
        audit.readme_has_no_ci_badge_code_or_workflow_link_before_content(tmp_path, facts()) is None
    )


def test_readme_has_no_ci_badge_code_or_workflow_link_before_content_fails_for_a_leading_code_block(
    tmp_path,
) -> None:
    write(tmp_path, "README.md", "# ossemble\n\n```\npip install\n```\n\n## Features\n")
    assert (
        audit.readme_has_no_ci_badge_code_or_workflow_link_before_content(tmp_path, facts())
        is not None
    )


def test_readme_has_no_ci_badge_code_or_workflow_link_before_content_fails_when_missing(
    tmp_path,
) -> None:
    assert (
        audit.readme_has_no_ci_badge_code_or_workflow_link_before_content(tmp_path, facts())
        is not None
    )


def test_readme_has_no_ci_badge_code_or_workflow_link_before_content_fails_for_a_workflow_link(
    tmp_path,
) -> None:
    write(
        tmp_path,
        "README.md",
        "# ossemble\n\nSee .github/workflows/ci.yml for the gate.\n\n## Features\n",
    )
    assert (
        audit.readme_has_no_ci_badge_code_or_workflow_link_before_content(tmp_path, facts())
        is not None
    )


def test_readme_headings_are_only_the_fixed_set_passes_for_allowed_headings(tmp_path) -> None:
    write(tmp_path, "README.md", "# ossemble\n\n## Features\n\n## Security and limits\n")
    assert audit.readme_headings_are_only_the_fixed_set(tmp_path, facts()) is None


def test_readme_headings_are_only_the_fixed_set_fails_for_a_forbidden_heading(tmp_path) -> None:
    write(tmp_path, "README.md", "# ossemble\n\n## Quick start\n")
    assert audit.readme_headings_are_only_the_fixed_set(tmp_path, facts()) is not None


def test_readme_headings_are_only_the_fixed_set_fails_for_the_old_bare_security_heading(
    tmp_path,
) -> None:
    write(tmp_path, "README.md", "# ossemble\n\n## Security\n")
    assert audit.readme_headings_are_only_the_fixed_set(tmp_path, facts()) is not None


def test_readme_headings_are_only_the_fixed_set_fails_when_missing(tmp_path) -> None:
    assert audit.readme_headings_are_only_the_fixed_set(tmp_path, facts()) is not None


def test_readme_headings_are_only_the_fixed_set_passes_for_all_six_headings_in_order(
    tmp_path,
) -> None:
    write(
        tmp_path,
        "README.md",
        "# ossemble\n\n"
        "## Features\n\n## In action\n\n## Fit\n\n## How it compares\n\n"
        "## Security and limits\n\n## Badges\n",
    )
    assert audit.readme_headings_are_only_the_fixed_set(tmp_path, facts()) is None


def test_readme_headings_are_only_the_fixed_set_passes_for_a_subset_in_order(tmp_path) -> None:
    write(
        tmp_path,
        "README.md",
        "# ossemble\n\n## Features\n\n## How it compares\n\n## Badges\n",
    )
    assert audit.readme_headings_are_only_the_fixed_set(tmp_path, facts()) is None


def test_readme_headings_are_only_the_fixed_set_fails_when_out_of_order(tmp_path) -> None:
    write(tmp_path, "README.md", "# ossemble\n\n## Badges\n\n## Features\n")
    assert audit.readme_headings_are_only_the_fixed_set(tmp_path, facts()) is not None


def test_readme_security_section_is_never_only_fails_when_missing(tmp_path) -> None:
    assert audit.readme_security_section_is_never_only(tmp_path, facts()) is not None


def test_readme_security_section_is_never_only_passes_without_a_security_section(
    tmp_path,
) -> None:
    write(tmp_path, "README.md", "# ossemble\n\n## Features\n\nstuff\n")
    assert audit.readme_security_section_is_never_only(tmp_path, facts()) is None


def test_readme_security_section_is_never_only_passes_for_the_old_bare_security_heading(
    tmp_path,
) -> None:
    write(tmp_path, "README.md", "## Security\n\n- Uses a token\n")
    assert audit.readme_security_section_is_never_only(tmp_path, facts()) is None


def test_readme_security_section_is_never_only_fails_with_no_never_items(tmp_path) -> None:
    write(tmp_path, "README.md", "## Security and limits\n\nNothing to see here.\n")
    assert audit.readme_security_section_is_never_only(tmp_path, facts()) is not None


def test_readme_security_section_is_never_only_passes_for_a_never_only_checklist(tmp_path) -> None:
    write(
        tmp_path,
        "README.md",
        "## Security and limits\n\n- Never sends a token to a URL\n- ❌ Never phones home\n",
    )
    assert audit.readme_security_section_is_never_only(tmp_path, facts()) is None


def test_readme_security_section_is_never_only_fails_when_a_checked_item_appears(tmp_path) -> None:
    write(
        tmp_path,
        "README.md",
        "## Security and limits\n\n- ✅ Uses a token\n- ❌ Never phones home\n",
    )
    assert audit.readme_security_section_is_never_only(tmp_path, facts()) is not None


# --- readme_check_exec_flag_is_true ----------------------------------------------------------


def test_readme_check_exec_flag_is_true_passes_when_the_workflow_is_missing(tmp_path) -> None:
    assert audit.readme_check_exec_flag_is_true(tmp_path, facts()) is None


def test_readme_check_exec_flag_is_true_passes_when_readmerlin_is_not_used(tmp_path) -> None:
    write(
        tmp_path,
        ".github/workflows/readme-check.yml",
        "jobs:\n  readmerlin:\n    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n",
    )
    assert audit.readme_check_exec_flag_is_true(tmp_path, facts()) is None


def test_readme_check_exec_flag_is_true_passes_when_exec_is_true(tmp_path) -> None:
    write(
        tmp_path,
        ".github/workflows/readme-check.yml",
        "jobs:\n  readmerlin:\n    steps:\n"
        "      - uses: oficiallyAkshay/readmerlin@63f78b5379bcdeff23a443ecf165ceb43544eebb"
        " # v1.0.2\n"
        "        with:\n"
        '          exec: "true"\n',
    )
    assert audit.readme_check_exec_flag_is_true(tmp_path, facts()) is None


def test_readme_check_exec_flag_is_true_fails_when_exec_is_missing(tmp_path) -> None:
    write(
        tmp_path,
        ".github/workflows/readme-check.yml",
        "jobs:\n  readmerlin:\n    steps:\n"
        "      - uses: oficiallyAkshay/readmerlin@63f78b5379bcdeff23a443ecf165ceb43544eebb"
        " # v1.0.2\n",
    )
    assert audit.readme_check_exec_flag_is_true(tmp_path, facts()) is not None


def test_readme_check_exec_flag_is_true_fails_when_exec_is_false(tmp_path) -> None:
    write(
        tmp_path,
        ".github/workflows/readme-check.yml",
        "jobs:\n  readmerlin:\n    steps:\n"
        "      - uses: oficiallyAkshay/readmerlin@63f78b5379bcdeff23a443ecf165ceb43544eebb"
        " # v1.0.2\n"
        "        with:\n"
        '          exec: "false"\n',
    )
    assert audit.readme_check_exec_flag_is_true(tmp_path, facts()) is not None


def test_no_lockfile_committed_passes_without_a_lockfile(tmp_path) -> None:
    assert audit.no_lockfile_committed(tmp_path, facts()) is None


def test_no_lockfile_committed_fails_when_uv_lock_is_present_outside_a_git_repo(tmp_path) -> None:
    write(tmp_path, "uv.lock", "")
    assert audit.no_lockfile_committed(tmp_path, facts()) is not None


def test_no_lockfile_committed_passes_when_a_lockfile_exists_but_is_gitignored_and_untracked(
    tmp_path,
) -> None:
    init_git_repo(tmp_path)
    write(tmp_path, ".gitignore", "uv.lock\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Ignore uv.lock"], cwd=tmp_path, check=True)
    write(tmp_path, "uv.lock", "# untracked, local only\n")

    assert audit.no_lockfile_committed(tmp_path, facts()) is None


def test_no_lockfile_committed_fails_when_a_lockfile_is_tracked_by_git(tmp_path) -> None:
    init_git_repo(tmp_path)
    write(tmp_path, "uv.lock", "# tracked\n")
    subprocess.run(["git", "add", "uv.lock"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Add uv.lock"], cwd=tmp_path, check=True)

    assert audit.no_lockfile_committed(tmp_path, facts()) is not None


# --- only_clonometer_pushes_to_badges_branch --------------------------------------------------


def test_only_clonometer_pushes_to_badges_branch_passes_with_no_badges_push_at_all(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
        "      - run: uv run pytest\n",
    )
    assert audit.only_clonometer_pushes_to_badges_branch(tmp_path, facts()) is None


def test_only_clonometer_pushes_to_badges_branch_exempts_a_workflow_that_uses_clonometer(
    tmp_path,
) -> None:
    """Exempt by file, per the rule text: this workflow's own git commands never matter."""
    workflow(
        tmp_path,
        "jobs:\n  badges:\n    steps:\n"
        "      - uses: oficiallyAkshay/clonometer@2c82a8779a68d2babb1e5e856d2ae69253dcd611"
        " # v1\n"
        "      - run: git push origin HEAD:badges\n",
    )
    assert audit.only_clonometer_pushes_to_badges_branch(tmp_path, facts()) is None


def test_only_clonometer_pushes_to_badges_branch_fails_on_a_head_colon_badges_push(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
        "      - run: git push origin HEAD:badges\n",
    )
    result = audit.only_clonometer_pushes_to_badges_branch(tmp_path, facts())
    assert result is not None
    file_, _message = result
    assert file_ == ".github/workflows/ci.yml"


def test_only_clonometer_pushes_to_badges_branch_fails_on_git_init_dash_b_badges(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - run: git init -b badges\n",
    )
    assert audit.only_clonometer_pushes_to_badges_branch(tmp_path, facts()) is not None


def test_only_clonometer_pushes_to_badges_branch_fails_on_a_forced_push_to_badges(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - run: git push --force origin badges\n",
    )
    assert audit.only_clonometer_pushes_to_badges_branch(tmp_path, facts()) is not None


def test_no_001_does_not_fire_on_a_javascript_repo_with_a_committed_package_lock(
    tmp_path,
) -> None:
    """NO-001's basis is uv resolving a Python dev group; it must not bind a JS action."""
    init_git_repo(tmp_path)
    write(tmp_path, "action.yml", "runs:\n  using: node20\n  main: dist/index.js\n")
    write(tmp_path, "package-lock.json", "{}\n")
    subprocess.run(["git", "add", "action.yml", "package-lock.json"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Add the action"], cwd=tmp_path, check=True)

    rows = audit.gaps(tmp_path)

    assert "NO-001" not in {row["id"] for row in rows}


def test_no_001_still_fires_on_a_python_repo_with_a_committed_lockfile(tmp_path) -> None:
    init_git_repo(tmp_path)
    write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\nversion = '0'\n")
    write(tmp_path, "uv.lock", "# tracked\n")
    subprocess.run(["git", "add", "pyproject.toml", "uv.lock"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Add uv.lock"], cwd=tmp_path, check=True)

    rows = audit.gaps(tmp_path)

    assert "NO-001" in {row["id"] for row in rows}


def test_tracked_files_returns_none_outside_a_git_repo(tmp_path) -> None:
    assert audit._tracked_files(tmp_path) is None


def test_tracked_files_returns_none_when_git_ls_files_fails(tmp_path, monkeypatch) -> None:
    init_git_repo(tmp_path)

    def failing_run_git(root, *args):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="fatal: error")

    monkeypatch.setattr(audit, "_run_git", failing_run_git)

    assert audit._tracked_files(tmp_path) is None


def test_zero_tokens_beyond_builtin_github_token_passes_with_only_the_built_in_token(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - env:\n          T: ${{ secrets.GITHUB_TOKEN }}\n",
    )
    assert audit.zero_tokens_beyond_builtin_github_token(tmp_path, facts()) is None


def test_zero_tokens_beyond_builtin_github_token_fails_for_another_secret(tmp_path) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - env:\n          T: ${{ secrets.NPM_TOKEN }}\n",
    )
    result = audit.zero_tokens_beyond_builtin_github_token(tmp_path, facts())
    assert result is not None
    assert "unless recorded under optins in .ossemble/state.json" in result[1]


def test_zero_tokens_beyond_builtin_github_token_passes_for_a_secret_listed_under_optins_as_a_list(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - env:\n          T: ${{ secrets.NPM_TOKEN }}\n",
    )
    write(tmp_path, ".ossemble/state.json", json.dumps({"optins": ["NPM_TOKEN"]}))
    assert audit.zero_tokens_beyond_builtin_github_token(tmp_path, facts()) is None


def test_zero_tokens_beyond_builtin_github_token_passes_for_a_secret_listed_under_optins_object(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - env:\n          T: ${{ secrets.NPM_TOKEN }}\n",
    )
    write(
        tmp_path,
        ".ossemble/state.json",
        json.dumps({"optins": {"NPM_TOKEN": "needed to publish"}}),
    )
    assert audit.zero_tokens_beyond_builtin_github_token(tmp_path, facts()) is None


def test_zero_tokens_beyond_builtin_github_token_fails_for_a_secret_not_listed_under_optins(
    tmp_path,
) -> None:
    workflow(
        tmp_path,
        "jobs:\n  build:\n    steps:\n      - env:\n          T: ${{ secrets.NPM_TOKEN }}\n",
    )
    write(tmp_path, ".ossemble/state.json", json.dumps({"optins": ["OTHER_TOKEN"]}))
    assert audit.zero_tokens_beyond_builtin_github_token(tmp_path, facts()) is not None


def test_commit_identity_is_noreply_passes_for_a_noreply_author(tmp_path) -> None:
    init_git_repo(tmp_path)
    assert audit.commit_identity_is_noreply(tmp_path, facts()) is None


def test_commit_identity_is_noreply_fails_for_a_personal_looking_email(tmp_path) -> None:
    init_git_repo(tmp_path, author_email="person@example.com")
    assert audit.commit_identity_is_noreply(tmp_path, facts()) is not None


def test_commit_identity_is_noreply_fails_when_git_cannot_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "_run_git", lambda root, *args: None)
    assert audit.commit_identity_is_noreply(tmp_path, facts()) is not None


def test_state_file_holds_only_allowed_keys_passes_without_a_state_file(tmp_path) -> None:
    assert audit.state_file_holds_only_allowed_keys(tmp_path, facts()) is None


def test_state_file_holds_only_allowed_keys_passes_with_only_allowed_keys(tmp_path) -> None:
    write(tmp_path, ".ossemble/state.json", json.dumps({"scope": {}, "lowered": []}))
    assert audit.state_file_holds_only_allowed_keys(tmp_path, facts()) is None


def test_state_file_holds_only_allowed_keys_fails_for_an_undeclared_key(tmp_path) -> None:
    write(tmp_path, ".ossemble/state.json", json.dumps({"scope": {}, "mystery": 1}))
    assert audit.state_file_holds_only_allowed_keys(tmp_path, facts()) is not None


def test_no_gate_lowering_left_open_at_finish_stage_passes_with_an_empty_state_file(
    tmp_path,
) -> None:
    write(tmp_path, ".ossemble/state.json", "{}")
    assert audit.no_gate_lowering_left_open_at_finish_stage(tmp_path, facts()) is None


def test_no_gate_lowering_left_open_at_finish_stage_passes_without_a_lowered_entry(
    tmp_path,
) -> None:
    write(tmp_path, ".ossemble/state.json", json.dumps({"lowered": []}))
    assert audit.no_gate_lowering_left_open_at_finish_stage(tmp_path, facts()) is None


def test_no_gate_lowering_left_open_at_finish_stage_fails_when_a_gate_is_still_lowered(
    tmp_path,
) -> None:
    write(tmp_path, ".ossemble/state.json", json.dumps({"lowered": [{"gate": "coverage"}]}))
    assert audit.no_gate_lowering_left_open_at_finish_stage(tmp_path, facts()) is not None


def test_coverage_floor_at_least_seventy_passes_at_the_floor(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
    assert audit.coverage_floor_at_least_seventy(tmp_path, facts()) is None


def test_coverage_floor_at_least_seventy_fails_when_pyproject_toml_is_missing(tmp_path) -> None:
    assert audit.coverage_floor_at_least_seventy(tmp_path, facts()) is not None


def test_coverage_floor_at_least_seventy_fails_below_the_floor(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.coverage.report]\nfail_under = 50\n")
    assert audit.coverage_floor_at_least_seventy(tmp_path, facts()) is not None


def test_coverage_floor_is_100_line_and_branch_passes_at_100_with_branch_on(tmp_path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        "[tool.coverage.report]\nfail_under = 100\n\n[tool.coverage.run]\nbranch = true\n",
    )
    assert audit.coverage_floor_is_100_line_and_branch(tmp_path, facts()) is None


def test_coverage_floor_is_100_line_and_branch_fails_when_pyproject_toml_is_missing(
    tmp_path,
) -> None:
    assert audit.coverage_floor_is_100_line_and_branch(tmp_path, facts()) is not None


def test_coverage_floor_is_100_line_and_branch_fails_below_100(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", "[tool.coverage.report]\nfail_under = 91\n")
    assert audit.coverage_floor_is_100_line_and_branch(tmp_path, facts()) is not None


def test_coverage_floor_is_100_line_and_branch_fails_when_branch_coverage_is_off(tmp_path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        "[tool.coverage.report]\nfail_under = 100\n\n[tool.coverage.run]\nbranch = false\n",
    )
    assert audit.coverage_floor_is_100_line_and_branch(tmp_path, facts()) is not None


def test_pragma_no_cover_only_on_main_guard_with_reason_passes_on_a_main_guard(tmp_path) -> None:
    write(
        tmp_path,
        "m.py",
        'if __name__ == "__main__":  # pragma: no cover -- exercised'
        " by running the script\n    pass\n",
    )
    assert audit.pragma_no_cover_only_on_main_guard_with_reason(tmp_path, facts()) is None


def test_pragma_no_cover_only_on_main_guard_with_reason_fails_outside_a_main_guard(
    tmp_path,
) -> None:
    # Built by concatenation, not one literal, so this repo's own audit does
    # not read the marker below as a pragma comment in this test file.
    marker = "# pragma" + ": no cover -- unreachable"
    write(tmp_path, "m.py", f"def f():  {marker}\n    pass\n")
    assert audit.pragma_no_cover_only_on_main_guard_with_reason(tmp_path, facts()) is not None


def test_pragma_no_cover_only_on_main_guard_with_reason_fails_without_a_trailing_reason(
    tmp_path,
) -> None:
    marker = "# pragma" + ": no cover"
    write(tmp_path, "m.py", f'if __name__ == "__main__":  {marker}\n    pass\n')
    assert audit.pragma_no_cover_only_on_main_guard_with_reason(tmp_path, facts()) is not None


def test_pragma_no_cover_only_on_main_guard_with_reason_skips_a_symlinked_py_file(
    tmp_path,
) -> None:
    marker = "# pragma" + ": no cover"
    outside = write(
        tmp_path.parent, f"{tmp_path.name}-outside.py", f"def f():  {marker}\n    pass\n"
    )
    link = tmp_path / "link.py"
    link.symlink_to(outside)
    assert audit.pragma_no_cover_only_on_main_guard_with_reason(tmp_path, facts()) is None


def test_pragma_no_cover_only_on_main_guard_with_reason_skips_a_directory_named_like_a_py_file(
    tmp_path,
) -> None:
    (tmp_path / "weird.py").mkdir()
    assert audit.pragma_no_cover_only_on_main_guard_with_reason(tmp_path, facts()) is None


def test_pragma_no_cover_only_on_main_guard_with_reason_scans_only_git_tracked_py_files(
    tmp_path,
) -> None:
    # A dependency under .venv/ is never tracked, so a git-tracked repo must
    # never see it, even though a plain filesystem walk would.
    init_git_repo(tmp_path)
    marker = "# pragma" + ": no cover -- unreachable"
    write(tmp_path, ".venv/lib/dep.py", f"def f():  {marker}\n    pass\n")
    write(tmp_path, "real.py", "def f():\n    pass\n")
    subprocess.run(["git", "add", "real.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Add real.py"], cwd=tmp_path, check=True)

    assert audit.pragma_no_cover_only_on_main_guard_with_reason(tmp_path, facts()) is None


# --------------------------------------------------------------- api probes


def test_auto_merge_and_delete_branch_enabled_passes_when_both_are_on(tmp_path) -> None:
    settings = {"allow_auto_merge": True, "delete_branch_on_merge": True}
    assert (
        audit.auto_merge_and_delete_branch_enabled(tmp_path, facts(repo_settings=settings)) is None
    )


def test_auto_merge_and_delete_branch_enabled_fails_when_repo_settings_are_unavailable(
    tmp_path,
) -> None:
    assert audit.auto_merge_and_delete_branch_enabled(tmp_path, facts()) is not None


def test_auto_merge_and_delete_branch_enabled_fails_when_auto_merge_is_off(tmp_path) -> None:
    settings = {"allow_auto_merge": False, "delete_branch_on_merge": True}
    assert (
        audit.auto_merge_and_delete_branch_enabled(tmp_path, facts(repo_settings=settings))
        is not None
    )


def test_auto_merge_and_delete_branch_enabled_fails_when_delete_branch_is_off(tmp_path) -> None:
    settings = {"allow_auto_merge": True, "delete_branch_on_merge": False}
    assert (
        audit.auto_merge_and_delete_branch_enabled(tmp_path, facts(repo_settings=settings))
        is not None
    )


def test_merge_strategy_is_rebase_only_passes_for_rebase_only(tmp_path) -> None:
    settings = {
        "allow_rebase_merge": True,
        "allow_squash_merge": False,
        "allow_merge_commit": False,
    }
    assert audit.merge_strategy_is_rebase_only(tmp_path, facts(repo_settings=settings)) is None


def test_merge_strategy_is_rebase_only_fails_when_repo_settings_are_unavailable(tmp_path) -> None:
    assert audit.merge_strategy_is_rebase_only(tmp_path, facts()) is not None


def test_merge_strategy_is_rebase_only_fails_when_rebase_merge_is_off(tmp_path) -> None:
    settings = {
        "allow_rebase_merge": False,
        "allow_squash_merge": False,
        "allow_merge_commit": False,
    }
    assert audit.merge_strategy_is_rebase_only(tmp_path, facts(repo_settings=settings)) is not None


def test_merge_strategy_is_rebase_only_fails_when_squash_is_also_allowed(tmp_path) -> None:
    settings = {"allow_rebase_merge": True, "allow_squash_merge": True, "allow_merge_commit": False}
    assert audit.merge_strategy_is_rebase_only(tmp_path, facts(repo_settings=settings)) is not None


def test_merge_strategy_is_rebase_only_fails_when_merge_commit_is_also_allowed(tmp_path) -> None:
    settings = {"allow_rebase_merge": True, "allow_squash_merge": False, "allow_merge_commit": True}
    assert audit.merge_strategy_is_rebase_only(tmp_path, facts(repo_settings=settings)) is not None


def test_wiki_and_projects_disabled_passes_when_both_are_off(tmp_path) -> None:
    settings = {"has_wiki": False, "has_projects": False}
    assert audit.wiki_and_projects_disabled(tmp_path, facts(repo_settings=settings)) is None


def test_wiki_and_projects_disabled_fails_when_repo_settings_are_unavailable(tmp_path) -> None:
    assert audit.wiki_and_projects_disabled(tmp_path, facts()) is not None


def test_wiki_and_projects_disabled_fails_when_the_wiki_is_on(tmp_path) -> None:
    settings = {"has_wiki": True, "has_projects": False}
    assert audit.wiki_and_projects_disabled(tmp_path, facts(repo_settings=settings)) is not None


def test_wiki_and_projects_disabled_fails_when_the_projects_tab_is_on(tmp_path) -> None:
    settings = {"has_wiki": False, "has_projects": True}
    assert audit.wiki_and_projects_disabled(tmp_path, facts(repo_settings=settings)) is not None


def test_dependabot_alerts_and_security_updates_enabled_passes_when_enabled(tmp_path) -> None:
    settings = {"security_and_analysis": {"dependabot_security_updates": {"status": "enabled"}}}
    assert (
        audit.dependabot_alerts_and_security_updates_enabled(
            tmp_path, facts(repo_settings=settings)
        )
        is None
    )


def test_dependabot_alerts_and_security_updates_enabled_fails_when_repo_settings_are_unavailable(
    tmp_path,
) -> None:
    assert audit.dependabot_alerts_and_security_updates_enabled(tmp_path, facts()) is not None


def test_dependabot_alerts_and_security_updates_enabled_fails_when_disabled(tmp_path) -> None:
    settings = {"security_and_analysis": {"dependabot_security_updates": {"status": "disabled"}}}
    assert (
        audit.dependabot_alerts_and_security_updates_enabled(
            tmp_path, facts(repo_settings=settings)
        )
        is not None
    )


def test_dependabot_alerts_and_security_updates_enabled_passes_via_the_private_repo_fallback(
    tmp_path,
) -> None:
    """A private repo without Advanced Security omits security_and_analysis entirely."""
    settings: dict = {}
    fallback = {"enabled": True, "paused": False}
    assert (
        audit.dependabot_alerts_and_security_updates_enabled(
            tmp_path, facts(repo_settings=settings, automated_security_fixes=fallback)
        )
        is None
    )


def test_dependabot_alerts_and_security_updates_enabled_fails_when_the_fallback_is_disabled(
    tmp_path,
) -> None:
    settings: dict = {}
    fallback = {"enabled": False, "paused": False}
    assert (
        audit.dependabot_alerts_and_security_updates_enabled(
            tmp_path, facts(repo_settings=settings, automated_security_fixes=fallback)
        )
        is not None
    )


def test_dependabot_alerts_and_security_updates_enabled_fails_when_the_fallback_is_paused(
    tmp_path,
) -> None:
    settings: dict = {}
    fallback = {"enabled": True, "paused": True}
    assert (
        audit.dependabot_alerts_and_security_updates_enabled(
            tmp_path, facts(repo_settings=settings, automated_security_fixes=fallback)
        )
        is not None
    )


def test_dependabot_alerts_and_security_updates_enabled_fails_when_the_fallback_is_unreadable(
    tmp_path,
) -> None:
    settings: dict = {}
    assert (
        audit.dependabot_alerts_and_security_updates_enabled(
            tmp_path, facts(repo_settings=settings, automated_security_fixes=None)
        )
        is not None
    )


def test_dependabot_alerts_and_security_updates_enabled_treats_null_analysis_as_missing(
    tmp_path,
) -> None:
    settings = {"security_and_analysis": None}
    fallback = {"enabled": True, "paused": False}
    assert (
        audit.dependabot_alerts_and_security_updates_enabled(
            tmp_path, facts(repo_settings=settings, automated_security_fixes=fallback)
        )
        is None
    )


def test_topics_are_set_passes_with_topics(tmp_path) -> None:
    settings = {"topics": ["skill", "agent"]}
    assert audit.topics_are_set(tmp_path, facts(repo_settings=settings)) is None


def test_topics_are_set_fails_without_topics(tmp_path) -> None:
    settings = {"topics": []}
    assert audit.topics_are_set(tmp_path, facts(repo_settings=settings)) is not None


def test_topics_are_set_fails_when_repo_settings_are_unavailable(tmp_path) -> None:
    assert audit.topics_are_set(tmp_path, facts()) is not None


def test_secret_scanning_and_push_protection_enabled_passes_when_both_are_on(tmp_path) -> None:
    settings = {
        "security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        }
    }
    assert (
        audit.secret_scanning_and_push_protection_enabled(tmp_path, facts(repo_settings=settings))
        is None
    )


def test_secret_scanning_and_push_protection_enabled_fails_when_repo_settings_are_unavailable(
    tmp_path,
) -> None:
    assert audit.secret_scanning_and_push_protection_enabled(tmp_path, facts()) is not None


def test_secret_scanning_and_push_protection_enabled_fails_when_secret_scanning_is_off(
    tmp_path,
) -> None:
    settings = {
        "security_and_analysis": {
            "secret_scanning": {"status": "disabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        }
    }
    assert (
        audit.secret_scanning_and_push_protection_enabled(tmp_path, facts(repo_settings=settings))
        is not None
    )


def test_secret_scanning_and_push_protection_enabled_fails_when_push_protection_is_off(
    tmp_path,
) -> None:
    settings = {
        "security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "disabled"},
        }
    }
    assert (
        audit.secret_scanning_and_push_protection_enabled(tmp_path, facts(repo_settings=settings))
        is not None
    )


def test_secret_scanning_and_push_protection_enabled_fails_when_security_and_analysis_is_null(
    tmp_path,
) -> None:
    settings = {"security_and_analysis": None}
    assert (
        audit.secret_scanning_and_push_protection_enabled(tmp_path, facts(repo_settings=settings))
        is not None
    )


def test_copilot_autofix_for_codeql_enabled_passes_when_enabled(tmp_path) -> None:
    settings = {"security_and_analysis": {"copilot_autofix": {"status": "enabled"}}}
    assert audit.copilot_autofix_for_codeql_enabled(tmp_path, facts(repo_settings=settings)) is None


def test_copilot_autofix_for_codeql_enabled_fails_when_repo_settings_are_unavailable(
    tmp_path,
) -> None:
    assert audit.copilot_autofix_for_codeql_enabled(tmp_path, facts()) is not None


def test_copilot_autofix_for_codeql_enabled_fails_when_disabled(tmp_path) -> None:
    settings = {"security_and_analysis": {"copilot_autofix": {"status": "disabled"}}}
    assert (
        audit.copilot_autofix_for_codeql_enabled(tmp_path, facts(repo_settings=settings))
        is not None
    )


def test_copilot_autofix_for_codeql_enabled_fails_when_security_and_analysis_is_null(
    tmp_path,
) -> None:
    settings = {"security_and_analysis": None}
    assert (
        audit.copilot_autofix_for_codeql_enabled(tmp_path, facts(repo_settings=settings))
        is not None
    )


def test_security_reporting_route_passes_with_no_security_md_at_all(tmp_path) -> None:
    assert audit.security_reporting_route_must_be_on(tmp_path, facts()) is None


def test_security_reporting_route_passes_when_security_md_is_a_symlink(tmp_path) -> None:
    """`_read_text` refuses a symlink, the same as every other probe that reads a doc file."""
    target = write(tmp_path, "elsewhere.md", "security/advisories\n")
    (tmp_path / "SECURITY.md").symlink_to(target)
    assert audit.security_reporting_route_must_be_on(tmp_path, facts()) is None


def test_security_reporting_route_passes_when_security_md_never_mentions_the_route(
    tmp_path,
) -> None:
    write(tmp_path, "SECURITY.md", "# Security\n\nEmail us at security@example.com.\n")
    assert audit.security_reporting_route_must_be_on(tmp_path, facts()) is None


def test_security_reporting_route_passes_when_the_route_is_on(tmp_path) -> None:
    write(
        tmp_path,
        "SECURITY.md",
        "Use https://github.com/an-owner/a-repo/security/advisories/new\n",
    )
    result_facts = facts(private_vulnerability_reporting={"enabled": True})
    assert audit.security_reporting_route_must_be_on(tmp_path, result_facts) is None


def test_security_reporting_route_matches_the_phrase_private_vulnerability_reporting_too(
    tmp_path,
) -> None:
    write(tmp_path, "SECURITY.md", "Use GitHub's Private Vulnerability Reporting.\n")
    result_facts = facts(private_vulnerability_reporting={"enabled": True})
    assert audit.security_reporting_route_must_be_on(tmp_path, result_facts) is None


def test_security_reporting_route_fails_when_the_route_is_off(tmp_path) -> None:
    write(
        tmp_path,
        "SECURITY.md",
        "Use https://github.com/an-owner/a-repo/security/advisories/new\n",
    )
    result_facts = facts(private_vulnerability_reporting={"enabled": False})

    result = audit.security_reporting_route_must_be_on(tmp_path, result_facts)

    assert result is not None
    file_, message = result
    assert file_ == "SECURITY.md"
    assert "off" in message


def test_security_reporting_route_checks_github_slash_security_md_too(tmp_path) -> None:
    write(
        tmp_path,
        ".github/SECURITY.md",
        "Use https://github.com/an-owner/a-repo/security/advisories/new\n",
    )
    result_facts = facts(private_vulnerability_reporting={"enabled": False})

    result = audit.security_reporting_route_must_be_on(tmp_path, result_facts)

    assert result is not None
    file_, _message = result
    assert file_ == ".github/SECURITY.md"


def test_security_reporting_route_records_itself_unverified_when_the_api_call_failed(
    tmp_path,
) -> None:
    write(
        tmp_path,
        "SECURITY.md",
        "Use https://github.com/an-owner/a-repo/security/advisories/new\n",
    )
    result_facts = facts()

    result = audit.security_reporting_route_must_be_on(tmp_path, result_facts)

    assert result is None
    assert result_facts["unverified_probes"] == {"security_reporting_route_must_be_on"}


GOOD_RULESET = {
    "enforcement": "active",
    "bypass_actors": [],
    "rules": [
        {"type": "pull_request", "parameters": {}},
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "ci"}]},
        },
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "required_linear_history"},
    ],
}


def test_ruleset_requires_ci_check_passes_for_the_standard_ruleset(tmp_path) -> None:
    assert audit.ruleset_requires_ci_check(tmp_path, facts(ruleset=GOOD_RULESET)) is None


def test_ruleset_requires_ci_check_fails_when_no_ruleset_was_found(tmp_path) -> None:
    assert audit.ruleset_requires_ci_check(tmp_path, facts()) is not None


def test_ruleset_requires_ci_check_fails_when_the_ci_context_is_missing(tmp_path) -> None:
    broken = {**GOOD_RULESET, "rules": [{"type": "pull_request", "parameters": {}}]}
    assert audit.ruleset_requires_ci_check(tmp_path, facts(ruleset=broken)) is not None


def test_ruleset_requires_ci_check_fails_when_not_active(tmp_path) -> None:
    broken = {**GOOD_RULESET, "enforcement": "disabled"}
    assert audit.ruleset_requires_ci_check(tmp_path, facts(ruleset=broken)) is not None


def test_ruleset_requires_ci_check_fails_when_it_has_bypass_actors(tmp_path) -> None:
    broken = {**GOOD_RULESET, "bypass_actors": [{"actor_id": 1}]}
    assert audit.ruleset_requires_ci_check(tmp_path, facts(ruleset=broken)) is not None


def test_ruleset_requires_ci_check_fails_when_it_does_not_require_a_pull_request(tmp_path) -> None:
    broken = {
        **GOOD_RULESET,
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "ci"}]},
            }
        ],
    }
    assert audit.ruleset_requires_ci_check(tmp_path, facts(ruleset=broken)) is not None


def test_ruleset_blocks_history_rewrites_passes_for_the_standard_ruleset(tmp_path) -> None:
    assert audit.ruleset_blocks_history_rewrites(tmp_path, facts(ruleset=GOOD_RULESET)) is None


def test_ruleset_blocks_history_rewrites_fails_when_deletion_is_not_blocked(tmp_path) -> None:
    broken = {
        **GOOD_RULESET,
        "rules": [{"type": "non_fast_forward"}, {"type": "required_linear_history"}],
    }
    assert audit.ruleset_blocks_history_rewrites(tmp_path, facts(ruleset=broken)) is not None


def test_ruleset_blocks_history_rewrites_fails_when_no_ruleset_was_found(tmp_path) -> None:
    assert audit.ruleset_blocks_history_rewrites(tmp_path, facts()) is not None


def test_ruleset_never_requires_reviews_or_thread_resolution_passes_for_the_standard_ruleset(
    tmp_path,
) -> None:
    assert (
        audit.ruleset_never_requires_reviews_or_thread_resolution(
            tmp_path, facts(ruleset=GOOD_RULESET)
        )
        is None
    )


def test_ruleset_never_requires_reviews_or_thread_resolution_fails_when_no_ruleset_was_found(
    tmp_path,
) -> None:
    assert audit.ruleset_never_requires_reviews_or_thread_resolution(tmp_path, facts()) is not None


def test_ruleset_never_requires_reviews_or_thread_resolution_fails_when_threads_must_resolve(
    tmp_path,
) -> None:
    broken = {
        "rules": [
            {"type": "pull_request", "parameters": {"required_review_thread_resolution": True}},
        ]
    }
    assert (
        audit.ruleset_never_requires_reviews_or_thread_resolution(tmp_path, facts(ruleset=broken))
        is not None
    )


def test_ruleset_never_requires_reviews_or_thread_resolution_fails_when_reviews_are_required(
    tmp_path,
) -> None:
    broken = {
        "rules": [
            {"type": "pull_request", "parameters": {"required_approving_review_count": 1}},
        ]
    }
    assert (
        audit.ruleset_never_requires_reviews_or_thread_resolution(tmp_path, facts(ruleset=broken))
        is not None
    )


def test_ruleset_never_requires_reviews_or_thread_resolution_fails_when_branches_must_be_up_to_date(
    tmp_path,
) -> None:
    broken = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {"strict_required_status_checks_policy": True},
            },
        ]
    }
    assert (
        audit.ruleset_never_requires_reviews_or_thread_resolution(tmp_path, facts(ruleset=broken))
        is not None
    )


# --------------------------------------------------------- language scoping


def test_gather_facts_sets_language_to_python_when_pyproject_toml_exists(tmp_path) -> None:
    write(tmp_path, "pyproject.toml", "[project]\ndependencies = []\n")

    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "python"


def test_gather_facts_sets_language_to_other_without_pyproject_or_git(tmp_path) -> None:
    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "other"


def test_gather_facts_sets_language_to_python_from_a_tracked_py_file_outside_tests(
    tmp_path,
) -> None:
    init_git_repo(tmp_path)
    write(tmp_path, "scripts/tool.py", "print('hi')\n")
    subprocess.run(["git", "add", "scripts/tool.py"], cwd=tmp_path, check=True)

    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "python"


def test_gather_facts_sets_language_to_other_when_the_only_py_file_is_under_tests(
    tmp_path,
) -> None:
    init_git_repo(tmp_path)
    write(tmp_path, "tests/test_thing.py", "def test_it(): pass\n")
    write(tmp_path, "notes.txt", "not python\n")
    subprocess.run(["git", "add", "tests/test_thing.py", "notes.txt"], cwd=tmp_path, check=True)

    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "other"


def test_gather_facts_sets_language_to_other_when_the_only_py_file_is_under_a_dot_dir(
    tmp_path,
) -> None:
    """A `.py` file under a dot-prefixed directory, a plugin shim say, is not the repo's source."""
    init_git_repo(tmp_path)
    write(tmp_path, ".hermes-plugin/__init__.py", "print('hi')\n")
    subprocess.run(["git", "add", ".hermes-plugin/__init__.py"], cwd=tmp_path, check=True)

    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "other"


def test_audit_of_a_non_python_repo_has_no_pyproject_rows(tmp_path) -> None:
    init_git_repo(tmp_path)
    write(tmp_path, "README.md", "# a markdown-only repo\n")

    rows = audit.gaps(tmp_path)

    assert {row["id"] for row in rows}.isdisjoint({"STR-001", "STR-002", "TST-001", "TST-002"})


def test_gather_facts_sets_language_to_other_when_py_files_are_a_typescript_actions_helpers(
    tmp_path,
) -> None:
    """A TypeScript action with a handful of helper `.py` scripts is not a Python repo."""
    init_git_repo(tmp_path)
    write(tmp_path, "src/main.ts", "export {}\n")
    write(tmp_path, "src/other.ts", "export {}\n")
    write(tmp_path, "src/setup.ts", "export {}\n")
    write(tmp_path, "__tests__/helpers/one.py", "print('one')\n")
    write(tmp_path, "__tests__/helpers/two.py", "print('two')\n")
    subprocess.run(
        [
            "git",
            "add",
            "src/main.ts",
            "src/other.ts",
            "src/setup.ts",
            "__tests__/helpers/one.py",
            "__tests__/helpers/two.py",
        ],
        cwd=tmp_path,
        check=True,
    )

    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "other"


def test_gather_facts_sets_language_to_python_when_py_is_the_majority_extension(
    tmp_path,
) -> None:
    init_git_repo(tmp_path)
    write(tmp_path, "src/a.py", "print('a')\n")
    write(tmp_path, "src/b.py", "print('b')\n")
    write(tmp_path, "src/c.sh", "echo c\n")
    subprocess.run(["git", "add", "src/a.py", "src/b.py", "src/c.sh"], cwd=tmp_path, check=True)

    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "python"


def test_gather_facts_sets_language_to_python_from_a_top_level_requirements_file(
    tmp_path,
) -> None:
    write(tmp_path, "requirements-dev.txt", "pytest\n")

    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "python"


def test_gather_facts_sets_language_to_python_from_setup_py(tmp_path) -> None:
    write(tmp_path, "setup.py", "from setuptools import setup\nsetup()\n")

    result = audit._gather_facts(tmp_path, use_api=False)

    assert result["language"] == "python"


def test_audit_of_a_python_repo_without_pyproject_still_flags_str_001(tmp_path) -> None:
    init_git_repo(tmp_path)
    write(tmp_path, "app.py", "print('hi')\n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)

    rows = audit.gaps(tmp_path)

    assert "STR-001" in {row["id"] for row in rows}
