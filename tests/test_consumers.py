"""Tests for `tests/eval/consumers.py`: the consumers eval's cloning, auditing and diffing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.eval import consumers


def _git_call_kind(cmd: list[str]) -> str:
    """Label a faked git argv by which of the eval's git steps it is."""
    if "init" in cmd:
        return "init"
    if "remote" in cmd:
        return "remote"
    if "fetch" in cmd:
        return "fetch"
    if "checkout" in cmd:
        return "checkout"
    if "rev-parse" in cmd:
        return "rev-parse"
    return "other"


def _install_fake_run(
    monkeypatch,
    calls: list[list[str]],
    *,
    rev_parse_stdout: str = "",
    git_failures: frozenset[str] = frozenset(),
    audit: tuple[int, str] = (0, "[]"),
):
    """Fake `subprocess.run`: records every call and answers git and audit argv.

    `audit` is `(returncode, stdout)` for the one audit subprocess call.
    """
    audit_returncode, audit_stdout = audit

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if cmd[0] == "git":
            kind = _git_call_kind(cmd)
            if kind in git_failures:
                return subprocess.CompletedProcess(
                    cmd, returncode=1, stdout="", stderr=f"{kind} failed"
                )
            if kind == "rev-parse":
                return subprocess.CompletedProcess(
                    cmd, returncode=0, stdout=rev_parse_stdout, stderr=""
                )
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            cmd, returncode=audit_returncode, stdout=audit_stdout, stderr=""
        )

    monkeypatch.setattr(consumers.subprocess, "run", fake_run)


def _prepare_repo_root(tmp_path, entries=None):
    """A fake ossemble repo root with a `tests/eval/` dir, optionally seeded with a snapshot."""
    eval_dir = tmp_path / "tests" / "eval"
    eval_dir.mkdir(parents=True)
    if entries is not None:
        (eval_dir / "consumers.json").write_text(json.dumps(entries), encoding="utf-8")
    return tmp_path


_CHECKOUT = "actions/checkout"
_CHECKOUT_COMMIT = "f548e57e544e1ff5a4c46bf1e1b8685f8e4a348a"


# --- _repo_root ----------------------------------------------------------------------------------


def test_repo_root_is_three_levels_above_this_file() -> None:
    assert consumers._repo_root() == Path(consumers.__file__).resolve().parent.parent.parent


# --- _ensure_clone -----------------------------------------------------------------------------


def test_ensure_clone_clones_a_missing_repo_with_init_remote_add_fetch_and_checkout(
    monkeypatch, tmp_path
) -> None:
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls)
    clone_dir = tmp_path / "clones"

    path = consumers._ensure_clone(clone_dir, _CHECKOUT, _CHECKOUT_COMMIT)

    assert path == clone_dir / "actions-checkout"
    assert path.is_dir()
    assert calls == [
        ["git", "init", "-q"],
        ["git", "remote", "add", "origin", "https://github.com/actions/checkout.git"],
        [
            "git",
            "-c",
            "protocol.version=2",
            "fetch",
            "-q",
            "--depth",
            "1",
            "origin",
            _CHECKOUT_COMMIT,
        ],
        ["git", "checkout", "-q", "--detach", "FETCH_HEAD"],
    ]


def test_ensure_clone_refetches_a_repo_present_at_the_wrong_commit(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, rev_parse_stdout="0" * 40 + "\n")
    clone_dir = tmp_path / "clones"
    (clone_dir / "actions-checkout").mkdir(parents=True)

    consumers._ensure_clone(clone_dir, _CHECKOUT, _CHECKOUT_COMMIT)

    assert calls == [
        ["git", "rev-parse", "HEAD"],
        [
            "git",
            "-c",
            "protocol.version=2",
            "fetch",
            "-q",
            "--depth",
            "1",
            "origin",
            _CHECKOUT_COMMIT,
        ],
        ["git", "checkout", "-q", "--detach", "FETCH_HEAD"],
    ]


def test_ensure_clone_does_nothing_for_a_repo_already_at_the_right_commit(
    monkeypatch, tmp_path
) -> None:
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, rev_parse_stdout=_CHECKOUT_COMMIT + "\n")
    clone_dir = tmp_path / "clones"
    (clone_dir / "actions-checkout").mkdir(parents=True)

    consumers._ensure_clone(clone_dir, _CHECKOUT, _CHECKOUT_COMMIT)

    assert calls == [["git", "rev-parse", "HEAD"]]


def test_current_commit_returns_none_when_rev_parse_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        consumers.subprocess,
        "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(
            cmd, returncode=1, stdout="", stderr="not a repo"
        ),
    )

    assert consumers._current_commit(tmp_path) is None


def test_ensure_clone_raises_when_a_git_step_fails(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, git_failures=frozenset({"init"}))
    clone_dir = tmp_path / "clones"

    with pytest.raises(
        consumers._EvalError, match="git init failed for actions/checkout: init failed"
    ):
        consumers._ensure_clone(clone_dir, _CHECKOUT, _CHECKOUT_COMMIT)


# --- _audit_rows ---------------------------------------------------------------------------------


def test_audit_rows_returns_sorted_id_file_pairs_and_runs_with_the_repo_root_as_cwd(
    monkeypatch, tmp_path
) -> None:
    clone_path = tmp_path / "clone"
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["cwd"] = kwargs.get("cwd")
        payload = json.dumps([{"id": "CI-002", "file": "b"}, {"id": "CI-001", "file": "a"}])
        return subprocess.CompletedProcess(cmd, returncode=1, stdout=payload, stderr="")

    monkeypatch.setattr(consumers.subprocess, "run", fake_run)

    rows = consumers._audit_rows(tmp_path, clone_path, "owner/name")

    assert rows == ["CI-001  a", "CI-002  b"]
    assert recorded["cmd"] == [
        sys.executable,
        "scripts/ossemble",
        "audit",
        "--json",
        str(clone_path),
    ]
    assert recorded["cwd"] == tmp_path


def test_audit_rows_raises_when_the_audit_exits_with_an_unexpected_code(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        consumers.subprocess,
        "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, returncode=2, stdout="", stderr="boom"),
    )

    with pytest.raises(consumers._EvalError, match="audit crashed on owner/name: exit 2"):
        consumers._audit_rows(tmp_path, tmp_path / "clone", "owner/name")


def test_audit_rows_raises_when_the_audit_output_is_not_valid_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        consumers.subprocess,
        "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(
            cmd, returncode=0, stdout="not json", stderr=""
        ),
    )

    with pytest.raises(consumers._EvalError, match="audit produced invalid JSON for owner/name"):
        consumers._audit_rows(tmp_path, tmp_path / "clone", "owner/name")


# --- _load_snapshot / _write_snapshot ------------------------------------------------------------


def test_load_snapshot_returns_an_empty_dict_when_the_file_is_missing(tmp_path) -> None:
    assert consumers._load_snapshot(tmp_path / "consumers.json") == {}


def test_load_snapshot_raises_on_invalid_json(tmp_path) -> None:
    path = tmp_path / "consumers.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(consumers._EvalError, match=r"could not parse consumers\.json"):
        consumers._load_snapshot(path)


def test_load_snapshot_keys_entries_by_repo(tmp_path) -> None:
    path = tmp_path / "consumers.json"
    entries = [
        {"repo": "a/b", "commit": "1" * 40, "rows": ["CI-001  x"]},
        {"repo": "c/d", "commit": "2" * 40, "rows": []},
    ]
    path.write_text(json.dumps(entries), encoding="utf-8")

    loaded = consumers._load_snapshot(path)

    assert loaded == {"a/b": entries[0], "c/d": entries[1]}


def test_write_snapshot_writes_sorted_two_space_indent_with_ordered_keys_and_trailing_newline(
    tmp_path,
) -> None:
    path = tmp_path / "consumers.json"
    entries_by_repo = {
        "z/last": {"repo": "z/last", "commit": "9" * 40, "rows": []},
        "a/first": {"repo": "a/first", "commit": "1" * 40, "rows": ["CI-001  x"]},
    }

    consumers._write_snapshot(path, entries_by_repo)

    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    parsed = json.loads(text)
    assert [entry["repo"] for entry in parsed] == ["a/first", "z/last"]
    assert list(parsed[0].keys()) == ["repo", "commit", "rows"]
    assert '\n    "repo"' in text  # two-space indent, one level deep inside the list


# --- _diff -----------------------------------------------------------------------------------


def test_diff_reports_ok_when_rows_match_exactly_including_duplicates() -> None:
    lines, differs = consumers._diff("a/b", ["CI-001  x", "CI-001  x"], ["CI-001  x", "CI-001  x"])

    assert lines == ["a/b  ok"]
    assert differs is False


def test_diff_reports_added_rows_when_new_gaps_appear() -> None:
    lines, differs = consumers._diff("a/b", [], ["CI-001  x"])

    assert lines == ["a/b  +1 -0", "+ CI-001  x"]
    assert differs is True


def test_diff_reports_vanished_rows_when_gaps_disappear() -> None:
    lines, differs = consumers._diff("a/b", ["CI-001  x"], [])

    assert lines == ["a/b  +0 -1", "- CI-001  x"]
    assert differs is True


# --- _default_clone_dir --------------------------------------------------------------------------


def test_default_clone_dir_uses_runner_temp_when_set(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner-temp"))

    assert consumers._default_clone_dir() == tmp_path / "runner-temp" / "consumers"


def test_default_clone_dir_falls_back_to_a_system_temp_directory_when_runner_temp_is_unset(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.setattr(consumers.tempfile, "gettempdir", lambda: str(tmp_path))

    assert consumers._default_clone_dir() == tmp_path / "ossemble-consumers"


# --- main / _run -----------------------------------------------------------------------------


def test_main_prints_ok_and_exits_0_when_the_audit_matches_the_snapshot(
    monkeypatch, tmp_path, capsys
) -> None:
    repo_root = _prepare_repo_root(
        tmp_path,
        entries=[{"repo": _CHECKOUT, "commit": _CHECKOUT_COMMIT, "rows": ["CI-001  a"]}],
    )
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, audit=(0, json.dumps([{"id": "CI-001", "file": "a"}])))

    exit_code = consumers.main(["--clone-dir", str(tmp_path / "clones"), "--only", _CHECKOUT])

    assert exit_code == 0
    assert capsys.readouterr().out == "actions/checkout  ok\n"


def test_main_prints_added_rows_and_exits_1_for_a_new_gap(monkeypatch, tmp_path, capsys) -> None:
    repo_root = _prepare_repo_root(tmp_path, entries=[])
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, audit=(0, json.dumps([{"id": "CI-001", "file": "a"}])))

    exit_code = consumers.main(["--clone-dir", str(tmp_path / "clones"), "--only", _CHECKOUT])

    assert exit_code == 1
    assert capsys.readouterr().out == "actions/checkout  +1 -0\n+ CI-001  a\n"


def test_main_prints_vanished_rows_and_exits_1_for_a_fixed_gap(
    monkeypatch, tmp_path, capsys
) -> None:
    repo_root = _prepare_repo_root(
        tmp_path,
        entries=[{"repo": _CHECKOUT, "commit": _CHECKOUT_COMMIT, "rows": ["CI-001  a"]}],
    )
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, audit=(0, "[]"))

    exit_code = consumers.main(["--clone-dir", str(tmp_path / "clones"), "--only", _CHECKOUT])

    assert exit_code == 1
    assert capsys.readouterr().out == "actions/checkout  +0 -1\n- CI-001  a\n"


def test_main_with_update_rewrites_the_snapshot_and_exits_0_even_when_rows_differ(
    monkeypatch, tmp_path
) -> None:
    other_repo = "hynek/structlog"
    other_commit = "7" * 40
    repo_root = _prepare_repo_root(
        tmp_path,
        entries=[
            {"repo": _CHECKOUT, "commit": _CHECKOUT_COMMIT, "rows": ["CI-001  old"]},
            {"repo": other_repo, "commit": other_commit, "rows": ["CI-002  b"]},
        ],
    )
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, audit=(0, json.dumps([{"id": "CI-001", "file": "new"}])))

    exit_code = consumers.main(
        ["--clone-dir", str(tmp_path / "clones"), "--only", _CHECKOUT, "--update"]
    )

    assert exit_code == 0
    written = json.loads(
        (repo_root / "tests" / "eval" / "consumers.json").read_text(encoding="utf-8")
    )
    assert written == [
        {"repo": _CHECKOUT, "commit": _CHECKOUT_COMMIT, "rows": ["CI-001  new"]},
        {"repo": other_repo, "commit": other_commit, "rows": ["CI-002  b"]},
    ]


def test_main_with_only_checks_a_single_repo_and_clones_nothing_else(
    monkeypatch, tmp_path, capsys
) -> None:
    repo_root = _prepare_repo_root(tmp_path, entries=[])
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, audit=(0, "[]"))
    clone_dir = tmp_path / "clones"

    exit_code = consumers.main(["--clone-dir", str(clone_dir), "--only", _CHECKOUT])

    assert exit_code == 0
    assert capsys.readouterr().out == "actions/checkout  ok\n"
    assert [entry.name for entry in clone_dir.iterdir()] == ["actions-checkout"]


def test_main_exits_1_with_one_stderr_line_for_an_unknown_only_repo(
    monkeypatch, tmp_path, capsys
) -> None:
    repo_root = _prepare_repo_root(tmp_path, entries=[])
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls)

    exit_code = consumers.main(["--clone-dir", str(tmp_path / "clones"), "--only", "no/such"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.err == "tests/eval/consumers.py: unknown repo: no/such\n"
    assert captured.out == ""
    assert calls == []


def test_main_exits_1_with_one_stderr_line_when_a_git_step_fails(
    monkeypatch, tmp_path, capsys
) -> None:
    repo_root = _prepare_repo_root(tmp_path, entries=[])
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, git_failures=frozenset({"fetch"}))

    exit_code = consumers.main(["--clone-dir", str(tmp_path / "clones"), "--only", _CHECKOUT])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert (
        captured.err
        == "tests/eval/consumers.py: git fetch failed for actions/checkout: fetch failed\n"
    )
    assert captured.out == ""


def test_main_exits_1_with_one_stderr_line_when_the_audit_exits_with_an_unexpected_code(
    monkeypatch, tmp_path, capsys
) -> None:
    repo_root = _prepare_repo_root(tmp_path, entries=[])
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, audit=(3, "[]"))

    exit_code = consumers.main(["--clone-dir", str(tmp_path / "clones"), "--only", _CHECKOUT])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.err == "tests/eval/consumers.py: audit crashed on actions/checkout: exit 3\n"
    assert captured.out == ""


def test_main_exits_1_with_one_stderr_line_when_the_audit_output_is_not_valid_json(
    monkeypatch, tmp_path, capsys
) -> None:
    repo_root = _prepare_repo_root(tmp_path, entries=[])
    monkeypatch.setattr(consumers, "_repo_root", lambda: repo_root)
    calls: list[list[str]] = []
    _install_fake_run(monkeypatch, calls, audit=(0, "not json"))

    exit_code = consumers.main(["--clone-dir", str(tmp_path / "clones"), "--only", _CHECKOUT])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith(
        "tests/eval/consumers.py: audit produced invalid JSON for actions/checkout"
    )
    assert captured.out == ""
