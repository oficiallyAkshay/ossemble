"""Tests for the `ossemble floor` subcommand."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.ossemble import floor

COVERAGE_XML = """<?xml version="1.0" ?>
<coverage line-rate="0.9" branch-rate="0.8" lines-covered="90" lines-valid="100"
          branches-covered="40" branches-valid="50">
</coverage>
"""


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_add_parser_registers_the_floor_subcommand_and_wires_it_to_run() -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    floor.add_parser(subparsers)

    args = parser.parse_args(["floor", "--coverage-xml", "coverage.xml"])

    assert args.subcommand == "floor"
    assert args.run is floor.run
    assert args.path == "."
    assert args.coverage_xml == "coverage.xml"


def test_achieved_percent_computes_the_combined_line_and_branch_percentage(tmp_path) -> None:
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)
    # (90 + 40) / (100 + 50) * 100 = 86.67, floored to 86.
    assert floor._achieved_percent(xml_path) == 86


def test_achieved_percent_returns_none_for_invalid_xml(tmp_path) -> None:
    xml_path = write(tmp_path / "coverage.xml", "not xml")
    assert floor._achieved_percent(xml_path) is None


def test_achieved_percent_returns_none_when_the_file_is_missing(tmp_path) -> None:
    assert floor._achieved_percent(tmp_path / "missing.xml") is None


def test_achieved_percent_returns_none_for_a_non_numeric_attribute(tmp_path) -> None:
    xml_path = write(
        tmp_path / "coverage.xml",
        '<coverage lines-covered="not-a-number" lines-valid="100"'
        ' branches-covered="40" branches-valid="50"></coverage>',
    )
    assert floor._achieved_percent(xml_path) is None


def test_achieved_percent_returns_none_when_no_lines_or_branches_are_valid(tmp_path) -> None:
    xml_path = write(
        tmp_path / "coverage.xml",
        '<coverage line-rate="0" lines-covered="0" lines-valid="0"'
        ' branches-covered="0" branches-valid="0"></coverage>',
    )
    assert floor._achieved_percent(xml_path) is None


def test_run_raises_fail_under_to_the_achieved_whole_number(tmp_path, capsys) -> None:
    write(tmp_path / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)

    exit_code = floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(xml_path)))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "fail_under raised from 70 to 86" in captured.out
    assert "fail_under = 86" in (tmp_path / "pyproject.toml").read_text()


def test_run_preserves_a_trailing_newline_when_the_file_had_one(tmp_path, capsys) -> None:
    write(tmp_path / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)

    floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(xml_path)))

    updated = (tmp_path / "pyproject.toml").read_text()
    assert updated == "[tool.coverage.report]\nfail_under = 86\n"


def test_run_preserves_no_trailing_newline_when_the_file_had_none(tmp_path, capsys) -> None:
    write(tmp_path / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70")
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)

    floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(xml_path)))

    updated = (tmp_path / "pyproject.toml").read_text()
    assert updated == "[tool.coverage.report]\nfail_under = 86"


def test_run_never_lowers_fail_under_below_its_current_value(tmp_path, capsys) -> None:
    write(tmp_path / "pyproject.toml", "[tool.coverage.report]\nfail_under = 95\n")
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)

    exit_code = floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(xml_path)))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "stays at 95" in captured.out
    assert "fail_under = 95" in (tmp_path / "pyproject.toml").read_text()


def test_run_returns_one_when_the_path_is_not_a_directory(capsys) -> None:
    exit_code = floor.run(argparse.Namespace(path="/no/such/path", coverage_xml="coverage.xml"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.strip() == "ossemble floor: /no/such/path is not a directory"


def test_run_refuses_to_follow_a_symlink_as_the_target_path(tmp_path, capsys) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_dir)

    exit_code = floor.run(argparse.Namespace(path=str(link), coverage_xml="coverage.xml"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "symlink" in captured.err


def test_run_refuses_to_follow_a_symlinked_coverage_xml(tmp_path, capsys) -> None:
    write(tmp_path / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
    real_xml = write(tmp_path / "real.xml", COVERAGE_XML)
    link = tmp_path / "link.xml"
    link.symlink_to(real_xml)

    exit_code = floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(link)))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "symlink" in captured.err


def test_run_returns_one_when_the_coverage_xml_cannot_be_read(tmp_path, capsys) -> None:
    write(tmp_path / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")

    exit_code = floor.run(
        argparse.Namespace(path=str(tmp_path), coverage_xml=str(tmp_path / "missing.xml"))
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "cannot read achieved coverage" in captured.err


def test_run_refuses_to_follow_a_symlinked_pyproject_toml(tmp_path, capsys) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    write(real_dir / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
    (tmp_path / "pyproject.toml").symlink_to(real_dir / "pyproject.toml")
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)

    exit_code = floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(xml_path)))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "symlink" in captured.err


def test_run_returns_one_when_pyproject_toml_is_missing(tmp_path, capsys) -> None:
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)

    exit_code = floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(xml_path)))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "cannot read" in captured.err


def test_run_returns_one_when_pyproject_toml_has_no_fail_under_line(tmp_path, capsys) -> None:
    write(tmp_path / "pyproject.toml", "[tool.coverage.report]\n")
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)

    exit_code = floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(xml_path)))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "no fail_under line" in captured.err


def test_run_returns_one_when_pyproject_toml_cannot_be_written(
    tmp_path, capsys, monkeypatch
) -> None:
    write(tmp_path / "pyproject.toml", "[tool.coverage.report]\nfail_under = 70\n")
    xml_path = write(tmp_path / "coverage.xml", COVERAGE_XML)

    def raise_os_error(self, data, encoding=None):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", raise_os_error)

    exit_code = floor.run(argparse.Namespace(path=str(tmp_path), coverage_xml=str(xml_path)))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "cannot write" in captured.err
