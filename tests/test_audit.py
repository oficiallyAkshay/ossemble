"""Tests for the `ossemble audit` subcommand stub."""

from __future__ import annotations

import argparse

from scripts.ossemble import audit


def test_add_parser_registers_the_audit_subcommand_and_wires_it_to_run() -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    audit.add_parser(subparsers)

    args = parser.parse_args(["audit"])

    assert args.subcommand == "audit"
    assert args.run is audit.run


def test_run_prints_the_not_built_yet_message_to_stderr_and_returns_one(capsys) -> None:
    exit_code = audit.run(argparse.Namespace())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "ossemble audit: not built yet\n"
    assert captured.out == ""
