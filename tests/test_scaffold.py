"""Tests for the `ossemble scaffold` subcommand stub."""

from __future__ import annotations

import argparse

from scripts.ossemble import scaffold


def test_add_parser_registers_the_scaffold_subcommand_and_wires_it_to_run() -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    scaffold.add_parser(subparsers)

    args = parser.parse_args(["scaffold"])

    assert args.subcommand == "scaffold"
    assert args.run is scaffold.run


def test_run_prints_the_not_built_yet_message_to_stderr_and_returns_one(capsys) -> None:
    exit_code = scaffold.run(argparse.Namespace())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "ossemble scaffold: not built yet\n"
    assert captured.out == ""
