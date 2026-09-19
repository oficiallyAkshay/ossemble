"""Tests for the ossemble CLI dispatcher: scripts/ossemble/__main__.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.ossemble import __main__ as ossemble_main

PACKAGE_DIR = str(Path(ossemble_main.__file__).resolve().parent)
SUBCOMMANDS = ["audit", "scaffold", "name", "resume", "floor"]


@pytest.fixture(autouse=True)
def _without_the_package_directory_on_sys_path():
    """Keep each test's starting sys.path free of the ossemble package directory."""
    while PACKAGE_DIR in sys.path:
        sys.path.remove(PACKAGE_DIR)
    yield
    while PACKAGE_DIR in sys.path:
        sys.path.remove(PACKAGE_DIR)


@pytest.mark.parametrize("subcommand", SUBCOMMANDS)
def test_each_subcommand_is_registered_and_answers_help_under_its_own_name(
    subcommand, capsys
) -> None:
    # The dispatcher's job ends at registration: each module owns what its
    # subcommand does, so this only proves the subcommand exists and that
    # argparse routes to it. Help exits 0 before any run() is called.
    with pytest.raises(SystemExit) as exc_info:
        ossemble_main.main([subcommand, "--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(f"usage: ossemble {subcommand}")
    assert captured.err == ""


def test_calling_main_twice_adds_the_package_directory_to_sys_path_only_once() -> None:
    assert PACKAGE_DIR not in sys.path
    with pytest.raises(SystemExit):
        ossemble_main.main(["audit", "--help"])
    assert sys.path.count(PACKAGE_DIR) == 1
    with pytest.raises(SystemExit):
        ossemble_main.main(["audit", "--help"])
    assert sys.path.count(PACKAGE_DIR) == 1


def test_running_with_no_subcommand_exits_with_status_two_and_names_the_missing_argument(
    capsys,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        ossemble_main.main([])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "subcommand" in captured.err


def test_an_unknown_subcommand_exits_with_status_two_and_names_the_invalid_choice(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        ossemble_main.main(["nonexistent"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err


def test_main_dispatches_a_real_subcommand_and_returns_its_exit_code(tmp_path, capsys) -> None:
    # This only proves dispatch reaches a subcommand's run() and returns its
    # exit code, the interface main() owns; it never asserts what resume
    # itself reports, which is resume's own behaviour to test.
    exit_code = ossemble_main.main(["resume", str(tmp_path), "--json"])
    capsys.readouterr()
    assert exit_code in (0, 1)
