"""Tests for the `ossemble resume` subcommand: environment, stage, regressions, next step."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types

from scripts.ossemble import resume


def _all_tools_present(monkeypatch) -> None:
    monkeypatch.setattr(resume.shutil, "which", lambda tool: f"/usr/bin/{tool}")


def _fake_git_config(monkeypatch, email: str, returncode: int = 0) -> None:
    def fake_run(cmd, **kwargs):
        assert cmd[:2] == ["git", "-C"]
        return subprocess.CompletedProcess(cmd, returncode=returncode, stdout=email, stderr="")

    monkeypatch.setattr(resume.subprocess, "run", fake_run)


def _write_pyproject(tmp_path, fail_under) -> None:
    (tmp_path / "pyproject.toml").write_text(f"[tool.coverage.report]\nfail_under = {fail_under}\n")


# --- add_parser ------------------------------------------------------------------------------


def test_add_parser_registers_the_resume_subcommand_and_wires_it_to_run() -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    resume.add_parser(subparsers)

    args = parser.parse_args(["resume"])

    assert args.subcommand == "resume"
    assert args.run is resume.run
    assert args.path == "."
    assert args.json is False


# --- _check_environment / _has_noreply_identity -----------------------------------------------


def test_check_environment_is_ok_when_every_tool_and_a_noreply_identity_are_present(
    monkeypatch, tmp_path
) -> None:
    _all_tools_present(monkeypatch)
    _fake_git_config(monkeypatch, "1+owner@users.noreply.github.com\n")

    environment = resume._check_environment(tmp_path)

    assert environment == {"git": True, "gh": True, "uv": True, "identity": True, "ok": True}


def test_check_environment_reports_missing_tools(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        resume.shutil, "which", lambda tool: None if tool == "gh" else f"/usr/bin/{tool}"
    )
    _fake_git_config(monkeypatch, "1+owner@users.noreply.github.com\n")

    environment = resume._check_environment(tmp_path)

    assert environment["gh"] is False
    assert environment["ok"] is False


def test_check_environment_never_checks_identity_when_git_itself_is_missing(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        resume.shutil, "which", lambda tool: None if tool == "git" else f"/usr/bin/{tool}"
    )

    def fail(*_args, **_kwargs):
        raise AssertionError("git config should not run when git is missing")

    monkeypatch.setattr(resume.subprocess, "run", fail)

    environment = resume._check_environment(tmp_path)

    assert environment["identity"] is False
    assert environment["ok"] is False


def test_has_noreply_identity_is_false_when_the_email_is_not_a_noreply_address(
    monkeypatch, tmp_path
) -> None:
    _fake_git_config(monkeypatch, "person@example.com\n")
    assert resume._has_noreply_identity(tmp_path) is False


def test_has_noreply_identity_is_false_when_git_config_has_no_identity_set(
    monkeypatch, tmp_path
) -> None:
    _fake_git_config(monkeypatch, "", returncode=1)
    assert resume._has_noreply_identity(tmp_path) is False


def test_has_noreply_identity_is_false_when_running_git_raises(monkeypatch, tmp_path) -> None:
    def fake_run(*_args, **_kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(resume.subprocess, "run", fake_run)
    assert resume._has_noreply_identity(tmp_path) is False


def test_has_noreply_identity_is_true_for_a_users_noreply_github_com_address(
    monkeypatch, tmp_path
) -> None:
    _fake_git_config(monkeypatch, "186180952+owner@users.noreply.github.com\n")
    assert resume._has_noreply_identity(tmp_path) is True


# --- _read_stage -------------------------------------------------------------------------------


def test_read_stage_is_unknown_when_pyproject_toml_is_missing(tmp_path) -> None:
    assert resume._read_stage(tmp_path) == ("unknown", None)


def test_read_stage_is_unknown_when_pyproject_toml_is_not_valid_toml(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("this is not [ toml")
    assert resume._read_stage(tmp_path) == ("unknown", None)


def test_read_stage_is_unknown_when_fail_under_is_missing(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert resume._read_stage(tmp_path) == ("unknown", None)


def test_read_stage_is_unknown_when_fail_under_is_not_a_number(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.coverage.report]\nfail_under = "high"\n')
    assert resume._read_stage(tmp_path) == ("unknown", None)


def test_read_stage_is_build_below_a_hundred_percent(tmp_path) -> None:
    _write_pyproject(tmp_path, 70)
    assert resume._read_stage(tmp_path) == ("build", 70)


def test_read_stage_is_finish_at_a_hundred_percent(tmp_path) -> None:
    _write_pyproject(tmp_path, 100)
    assert resume._read_stage(tmp_path) == ("finish", 100)


# --- _read_state ---------------------------------------------------------------------------------


def test_read_state_defaults_to_empty_when_no_state_file_exists(tmp_path) -> None:
    assert resume._read_state(tmp_path) == ({}, None)


def test_read_state_refuses_a_symlinked_state_file(tmp_path) -> None:
    real_target = tmp_path / "elsewhere.json"
    real_target.write_text("{}")
    state_dir = tmp_path / ".ossemble"
    state_dir.mkdir()
    (state_dir / "state.json").symlink_to(real_target)

    state, error = resume._read_state(tmp_path)

    assert state == {}
    assert "symlink" in error


def test_read_state_reports_invalid_json(tmp_path) -> None:
    state_dir = tmp_path / ".ossemble"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("{not json")

    state, error = resume._read_state(tmp_path)

    assert state == {}
    assert "could not be read" in error


def test_read_state_reports_a_json_value_that_is_not_an_object(tmp_path) -> None:
    state_dir = tmp_path / ".ossemble"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("[]")

    state, error = resume._read_state(tmp_path)

    assert state == {}
    assert "must hold a JSON object" in error


def test_read_state_reports_fields_with_the_wrong_shape(tmp_path) -> None:
    state_dir = tmp_path / ".ossemble"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps({"lowered": {"not": "a list"}, "scope": ["not", "a", "dict"]})
    )

    state, error = resume._read_state(tmp_path)

    assert state == {}
    assert "lowered" in error
    assert "scope" in error


def test_read_state_accepts_a_correctly_shaped_state_file(tmp_path) -> None:
    payload = {
        "lowered": [{"gate": "coverage", "from": 100, "to": 70, "why": "still building"}],
        "scope": {},
    }
    state_dir = tmp_path / ".ossemble"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(json.dumps(payload))

    state, error = resume._read_state(tmp_path)

    assert state == payload
    assert error is None


# --- _regressions ----------------------------------------------------------------------------------


def test_regressions_reports_not_available_when_audit_cannot_be_imported(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setitem(sys.modules, "audit", None)
    assert resume._regressions(tmp_path) == "audit not available"


def test_regressions_reports_not_available_when_audit_has_no_regressions_probe(
    monkeypatch, tmp_path
) -> None:
    stub = types.ModuleType("audit")
    monkeypatch.setitem(sys.modules, "audit", stub)
    assert resume._regressions(tmp_path) == "audit not available"


def test_regressions_reports_not_available_when_the_probe_raises(monkeypatch, tmp_path) -> None:
    stub = types.ModuleType("audit")
    stub.regressions = lambda path: (_ for _ in ()).throw(RuntimeError("not finished"))
    monkeypatch.setitem(sys.modules, "audit", stub)
    assert resume._regressions(tmp_path) == "audit not available"


def test_regressions_returns_the_probes_result_when_it_succeeds(monkeypatch, tmp_path) -> None:
    stub = types.ModuleType("audit")
    stub.regressions = lambda path: ["CI-001"]
    monkeypatch.setitem(sys.modules, "audit", stub)
    assert resume._regressions(tmp_path) == ["CI-001"]


# --- _next_step -------------------------------------------------------------------------------------


def test_next_step_asks_to_fix_the_environment_first(monkeypatch) -> None:
    environment = {"git": True, "gh": False, "uv": True, "identity": False, "ok": False}
    step = resume._next_step(environment, "build", [])
    assert step == "fix the environment: install gh; set a no-reply git identity"


def test_next_step_names_only_the_identity_problem_when_every_tool_is_present() -> None:
    environment = {"git": True, "gh": True, "uv": True, "identity": False, "ok": False}
    step = resume._next_step(environment, "build", [])
    assert step == "fix the environment: set a no-reply git identity"


def test_next_step_names_only_the_missing_tools_when_the_identity_is_fine() -> None:
    environment = {"git": True, "gh": True, "uv": False, "identity": True, "ok": False}
    step = resume._next_step(environment, "build", [])
    assert step == "fix the environment: install uv"


def test_next_step_points_at_the_runbooks_when_the_repo_has_no_ossemble_scaffolding() -> None:
    environment = {"git": True, "gh": True, "uv": True, "identity": True, "ok": True}
    step = resume._next_step(environment, "unknown", [])
    assert "build-runbook.md" in step
    assert "modify-runbook.md" in step


def test_next_step_asks_to_raise_a_lowered_gate() -> None:
    environment = {"git": True, "gh": True, "uv": True, "identity": True, "ok": True}
    step = resume._next_step(
        environment, "build", [{"gate": "coverage", "from": 100, "to": 70, "why": "x"}]
    )
    assert step == "raise the lowered gate(s) (coverage) back to their finish value"


def test_next_step_at_the_finish_stage_with_nothing_lowered() -> None:
    environment = {"git": True, "gh": True, "uv": True, "identity": True, "ok": True}
    step = resume._next_step(environment, "finish", [])
    assert "review step" in step


def test_next_step_at_the_build_stage_with_nothing_lowered() -> None:
    environment = {"git": True, "gh": True, "uv": True, "identity": True, "ok": True}
    step = resume._next_step(environment, "build", [])
    assert step == "continue the build stage; read references/build-runbook.md"


# --- _format_report ---------------------------------------------------------------------------------


def test_format_report_lists_the_missing_tools_and_identity_problem_when_not_ok() -> None:
    report = {
        "environment": {"git": True, "gh": False, "uv": True, "identity": False, "ok": False},
        "stage": "unknown",
        "coverage_floor": None,
        "regressions": "audit not available",
        "lowered": [],
        "next_step": "fix the environment",
    }

    lines = resume._format_report(report)

    assert lines[0] == "environment: not ok"
    assert "  missing: gh" in lines
    assert "  identity: not a no-reply git identity" in lines
    assert "stage: unknown" in lines
    assert "lowered: none" in lines


def test_format_report_shows_only_the_identity_line_when_every_tool_is_present() -> None:
    report = {
        "environment": {"git": True, "gh": True, "uv": True, "identity": False, "ok": False},
        "stage": "unknown",
        "coverage_floor": None,
        "regressions": "audit not available",
        "lowered": [],
        "next_step": "fix the environment",
    }

    lines = resume._format_report(report)

    assert not any(line.startswith("  missing:") for line in lines)
    assert "  identity: not a no-reply git identity" in lines


def test_format_report_shows_only_the_missing_line_when_the_identity_is_fine() -> None:
    report = {
        "environment": {"git": True, "gh": True, "uv": False, "identity": True, "ok": False},
        "stage": "unknown",
        "coverage_floor": None,
        "regressions": "audit not available",
        "lowered": [],
        "next_step": "fix the environment",
    }

    lines = resume._format_report(report)

    assert "  missing: uv" in lines
    assert not any(line.startswith("  identity:") for line in lines)


def test_format_report_shows_the_coverage_floor_and_lowered_entries_when_present() -> None:
    report = {
        "environment": {"git": True, "gh": True, "uv": True, "identity": True, "ok": True},
        "stage": "build",
        "coverage_floor": 70,
        "regressions": "audit not available",
        "lowered": [{"gate": "coverage", "from": 100, "to": 70, "why": "still building"}],
        "next_step": "continue",
    }

    lines = resume._format_report(report)

    assert "stage: build (coverage floor 70)" in lines
    assert any("coverage (100 -> 70): still building" in line for line in lines)


# --- run(): end to end ------------------------------------------------------------------------------


def test_run_returns_zero_and_prints_text_lines_for_a_clean_repo(
    monkeypatch, tmp_path, capsys
) -> None:
    _all_tools_present(monkeypatch)
    _fake_git_config(monkeypatch, "1+owner@users.noreply.github.com\n")
    _write_pyproject(tmp_path, 70)
    monkeypatch.setitem(sys.modules, "audit", None)

    exit_code = resume.run(argparse.Namespace(path=str(tmp_path), json=False))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "environment: ok" in captured.out
    assert "stage: build (coverage floor 70)" in captured.out
    assert "regressions: audit not available" in captured.out
    assert captured.err == ""


def test_run_prints_json_when_asked(monkeypatch, tmp_path, capsys) -> None:
    _all_tools_present(monkeypatch)
    _fake_git_config(monkeypatch, "1+owner@users.noreply.github.com\n")
    _write_pyproject(tmp_path, 100)
    monkeypatch.setitem(sys.modules, "audit", None)

    exit_code = resume.run(argparse.Namespace(path=str(tmp_path), json=True))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["stage"] == "finish"
    assert payload["coverage_floor"] == 100
    assert payload["lowered"] == []


def test_run_returns_one_and_reports_the_state_error_on_stderr_when_the_state_file_is_invalid(
    monkeypatch, tmp_path, capsys
) -> None:
    _all_tools_present(monkeypatch)
    _fake_git_config(monkeypatch, "1+owner@users.noreply.github.com\n")
    _write_pyproject(tmp_path, 70)
    monkeypatch.setitem(sys.modules, "audit", None)
    state_dir = tmp_path / ".ossemble"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("not json")

    exit_code = resume.run(argparse.Namespace(path=str(tmp_path), json=False))

    assert exit_code == 1
    assert "could not be read" in capsys.readouterr().err


def test_run_returns_one_when_the_environment_is_not_ok(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(resume.shutil, "which", lambda _tool: None)
    _write_pyproject(tmp_path, 70)
    monkeypatch.setitem(sys.modules, "audit", None)

    exit_code = resume.run(argparse.Namespace(path=str(tmp_path), json=False))

    assert exit_code == 1
