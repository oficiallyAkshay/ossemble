"""Tests for the `ossemble scaffold` subcommand."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts.ossemble import scaffold

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_args(path=".", set_name="boot", variables=None, check=False) -> argparse.Namespace:
    return argparse.Namespace(
        path=path, set_name=set_name, variables=list(variables or []), check=check
    )


def _write_manifest(templates_root: Path, entries: list[dict]) -> None:
    (templates_root / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")


@pytest.fixture
def custom_templates(tmp_path, monkeypatch):
    """Point scaffold at a throwaway templates/ tree instead of the real one."""
    templates_root = tmp_path / "templates"
    templates_root.mkdir()
    monkeypatch.setattr(scaffold, "_TEMPLATES_ROOT", templates_root)
    monkeypatch.setattr(scaffold, "_MANIFEST_PATH", templates_root / "manifest.json")
    return templates_root


def test_add_parser_registers_the_scaffold_subcommand_and_wires_it_to_run() -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    scaffold.add_parser(subparsers)

    args = parser.parse_args(["scaffold", "--set", "boot"])

    assert args.subcommand == "scaffold"
    assert args.run is scaffold.run
    assert args.set_name == "boot"
    assert args.path == "."
    assert args.variables == []
    assert args.check is False


def test_add_parser_requires_the_set_flag() -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    scaffold.add_parser(subparsers)

    with pytest.raises(SystemExit):
        parser.parse_args(["scaffold"])


def test_add_parser_accepts_a_path_repeated_vars_and_check(tmp_path) -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    scaffold.add_parser(subparsers)

    args = parser.parse_args(
        ["scaffold", str(tmp_path), "--set", "boot", "--var", "NAME=widget", "--check"]
    )

    assert args.path == str(tmp_path)
    assert args.variables == ["NAME=widget"]
    assert args.check is True


def test_run_fails_one_line_on_stderr_when_the_set_name_is_unknown(
    custom_templates, tmp_path, capsys
) -> None:
    _write_manifest(custom_templates, [])

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="ghost"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "ossemble scaffold: no templates in set: ghost\n"


def test_run_fails_one_line_on_stderr_when_a_var_flag_has_no_equals_sign(
    custom_templates, tmp_path, capsys
) -> None:
    _write_manifest(custom_templates, [])

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot", variables=["NAME"]))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "ossemble scaffold: --var must be KEY=VALUE, got: NAME\n"


def test_run_fails_one_line_on_stderr_when_a_var_flag_has_an_empty_key(
    custom_templates, tmp_path, capsys
) -> None:
    _write_manifest(custom_templates, [])

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot", variables=["=widget"]))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "ossemble scaffold: --var must be KEY=VALUE, got: =widget\n"


def test_run_fails_one_line_on_stderr_when_a_needed_var_is_not_supplied(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "greeting.txt").write_text("hello {{NAME}}\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "greeting.txt",
                "dest": "greeting.txt",
                "set": "boot",
                "vars": ["NAME"],
                "rules": [],
            }
        ],
    )

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "ossemble scaffold: missing --var for NAME\n"


def test_run_fails_one_line_on_stderr_when_the_manifest_file_is_missing(
    custom_templates, tmp_path, capsys
) -> None:
    # custom_templates creates the templates/ directory but never writes a
    # manifest.json into it, so the file is missing by construction.
    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("ossemble scaffold: cannot read manifest:")


def test_run_fails_one_line_on_stderr_when_the_manifest_is_not_valid_json(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "manifest.json").write_text("{not json", encoding="utf-8")

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("ossemble scaffold: manifest is not valid json:")


def test_run_fails_one_line_on_stderr_when_a_template_source_file_is_missing(
    custom_templates, tmp_path, capsys
) -> None:
    _write_manifest(
        custom_templates,
        [
            {
                "src": "missing.txt",
                "dest": "missing.txt",
                "set": "boot",
                "vars": [],
                "rules": [],
            }
        ],
    )

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("ossemble scaffold: cannot read template missing.txt:")


def test_run_creates_a_new_file_from_a_template_and_renders_its_variable(
    custom_templates, tmp_path
) -> None:
    (custom_templates / "greeting.txt").write_text("hello {{NAME}}\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "greeting.txt",
                "dest": "greeting.txt",
                "set": "boot",
                "vars": ["NAME"],
                "rules": [],
            }
        ],
    )

    exit_code = scaffold.run(
        _make_args(path=str(tmp_path), set_name="boot", variables=["NAME=widget"])
    )

    assert exit_code == 0
    assert (tmp_path / "greeting.txt").read_text(encoding="utf-8") == "hello widget\n"


def test_run_creates_parent_directories_for_a_nested_destination(
    custom_templates, tmp_path
) -> None:
    (custom_templates / "workflow.yml").write_text("name: ci\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "workflow.yml",
                "dest": ".github/workflows/ci.yml",
                "set": "boot",
                "vars": [],
                "rules": [],
            }
        ],
    )

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    assert exit_code == 0
    assert (tmp_path / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    ) == "name: ci\n"


def test_run_is_idempotent_and_leaves_an_unchanged_file_untouched(
    custom_templates, tmp_path
) -> None:
    (custom_templates / "greeting.txt").write_text("hello {{NAME}}\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "greeting.txt",
                "dest": "greeting.txt",
                "set": "boot",
                "vars": ["NAME"],
                "rules": [],
            }
        ],
    )
    args = _make_args(path=str(tmp_path), set_name="boot", variables=["NAME=widget"])

    first = scaffold.run(args)
    written_at = (tmp_path / "greeting.txt").stat().st_mtime_ns
    second = scaffold.run(args)

    assert first == 0
    assert second == 0
    assert (tmp_path / "greeting.txt").stat().st_mtime_ns == written_at
    assert (tmp_path / "greeting.txt").read_text(encoding="utf-8") == "hello widget\n"


def test_run_upgrades_a_file_from_an_older_known_stamp_of_the_same_destination(
    custom_templates, tmp_path
) -> None:
    (custom_templates / "boot.toml").write_text('stage = "boot"\n', encoding="utf-8")
    (custom_templates / "finish.toml").write_text('stage = "finish"\n', encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {"src": "boot.toml", "dest": "config.toml", "set": "boot", "vars": [], "rules": []},
            {
                "src": "finish.toml",
                "dest": "config.toml",
                "set": "finish",
                "vars": [],
                "rules": [],
            },
        ],
    )

    first = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))
    second = scaffold.run(_make_args(path=str(tmp_path), set_name="finish"))

    assert first == 0
    assert second == 0
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == 'stage = "finish"\n'


def test_run_ignores_a_sibling_sets_version_when_its_own_var_is_not_supplied(
    custom_templates, tmp_path
) -> None:
    # config.toml has two known stamps: boot (needs NAME, supplied here) and
    # finish (needs OTHER, never supplied in this call). The finish version
    # cannot be rendered, so it is skipped rather than failing the boot
    # stamp; a hand edit is still recognised as drift because it matches
    # neither stamp.
    (custom_templates / "boot.toml").write_text('stage = "{{NAME}}"\n', encoding="utf-8")
    (custom_templates / "finish.toml").write_text('stage = "{{OTHER}}"\n', encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "boot.toml",
                "dest": "config.toml",
                "set": "boot",
                "vars": ["NAME"],
                "rules": [],
            },
            {
                "src": "finish.toml",
                "dest": "config.toml",
                "set": "finish",
                "vars": ["OTHER"],
                "rules": [],
            },
        ],
    )

    exit_code = scaffold.run(
        _make_args(path=str(tmp_path), set_name="boot", variables=["NAME=widget"])
    )

    assert exit_code == 0
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == 'stage = "widget"\n'


def test_run_refuses_to_overwrite_a_file_that_was_hand_edited(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "greeting.txt").write_text("hello there\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "greeting.txt",
                "dest": "greeting.txt",
                "set": "boot",
                "vars": [],
                "rules": [],
            }
        ],
    )
    (tmp_path / "greeting.txt").write_text("a person wrote this by hand\n", encoding="utf-8")

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "drift: greeting.txt\n"
    assert (tmp_path / "greeting.txt").read_text(
        encoding="utf-8"
    ) == "a person wrote this by hand\n"


def test_run_with_check_reports_pending_creates_and_writes_nothing(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "greeting.txt").write_text("hello\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "greeting.txt",
                "dest": "greeting.txt",
                "set": "boot",
                "vars": [],
                "rules": [],
            }
        ],
    )

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot", check=True))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == "create: greeting.txt\n"
    assert not (tmp_path / "greeting.txt").exists()


def test_run_with_check_reports_an_upgrade_without_writing_it(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "boot.toml").write_text('stage = "boot"\n', encoding="utf-8")
    (custom_templates / "finish.toml").write_text('stage = "finish"\n', encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {"src": "boot.toml", "dest": "config.toml", "set": "boot", "vars": [], "rules": []},
            {
                "src": "finish.toml",
                "dest": "config.toml",
                "set": "finish",
                "vars": [],
                "rules": [],
            },
        ],
    )
    scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="finish", check=True))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == "update: config.toml\n"
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == 'stage = "boot"\n'


def test_run_with_check_reports_drift_on_stderr_and_writes_nothing(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "greeting.txt").write_text("hello there\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "greeting.txt",
                "dest": "greeting.txt",
                "set": "boot",
                "vars": [],
                "rules": [],
            }
        ],
    )
    (tmp_path / "greeting.txt").write_text("a person wrote this by hand\n", encoding="utf-8")

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot", check=True))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "drift: greeting.txt\n"
    assert (tmp_path / "greeting.txt").read_text(
        encoding="utf-8"
    ) == "a person wrote this by hand\n"


def test_run_with_check_on_an_already_stamped_tree_reports_nothing_and_exits_zero(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "greeting.txt").write_text("hello\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "greeting.txt",
                "dest": "greeting.txt",
                "set": "boot",
                "vars": [],
                "rules": [],
            }
        ],
    )
    scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot", check=True))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_run_refuses_to_write_through_a_symlinked_destination(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "greeting.txt").write_text("hello\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "greeting.txt",
                "dest": "greeting.txt",
                "set": "boot",
                "vars": [],
                "rules": [],
            }
        ],
    )
    elsewhere = tmp_path.parent / "elsewhere.txt"
    elsewhere.write_text("not the template's business\n", encoding="utf-8")
    (tmp_path / "greeting.txt").symlink_to(elsewhere)

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == "ossemble scaffold: refuses to write through a symlink: greeting.txt\n"
    assert elsewhere.read_text(encoding="utf-8") == "not the template's business\n"


def test_run_refuses_to_write_through_a_symlinked_parent_directory(
    custom_templates, tmp_path, capsys
) -> None:
    (custom_templates / "workflow.yml").write_text("name: ci\n", encoding="utf-8")
    _write_manifest(
        custom_templates,
        [
            {
                "src": "workflow.yml",
                "dest": "workflows/ci.yml",
                "set": "boot",
                "vars": [],
                "rules": [],
            }
        ],
    )
    elsewhere = tmp_path.parent / "elsewhere_dir"
    elsewhere.mkdir()
    (tmp_path / "workflows").symlink_to(elsewhere)

    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name="boot"))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        captured.err == "ossemble scaffold: refuses to write through a symlink: workflows/ci.yml\n"
    )
    assert list(elsewhere.iterdir()) == []


class TestRealBootTemplatesMatchThisRepo:
    """The templates/ directory this builder owns, stamped against itself."""

    def test_scaffold_boot_reproduces_this_repos_own_gate_files_byte_for_byte(
        self, tmp_path
    ) -> None:
        exit_code = scaffold.run(
            _make_args(path=str(tmp_path), set_name="boot", variables=["NAME=ossemble"])
        )

        assert exit_code == 0
        for dest in (
            "pyproject.toml",
            ".pre-commit-config.yaml",
            ".gitignore",
            ".github/workflows/ci.yml",
            ".github/dependabot.yml",
            ".github/pull_request_template.md",
        ):
            stamped = (tmp_path / dest).read_bytes()
            live = (REPO_ROOT / dest).read_bytes()
            assert stamped == live, f"{dest} has drifted from the boot template"

    def test_scaffold_boot_is_idempotent_on_this_repos_own_variables(self, tmp_path) -> None:
        args = _make_args(path=str(tmp_path), set_name="boot", variables=["NAME=ossemble"])

        first = scaffold.run(args)
        second = scaffold.run(args)

        assert first == 0
        assert second == 0

    def test_scaffold_finish_upgrades_pyproject_toml_to_full_coverage_and_lint(
        self, tmp_path
    ) -> None:
        variables = ["NAME=ossemble"]
        scaffold.run(_make_args(path=str(tmp_path), set_name="boot", variables=variables))

        exit_code = scaffold.run(
            _make_args(path=str(tmp_path), set_name="finish", variables=variables)
        )

        assert exit_code == 0
        rendered = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        assert "fail_under = 100" in rendered
        assert 'select = ["ALL"]' in rendered


class TestExamplesMinimalRebuildsByteForByte:
    """examples/minimal/ is boot, stamped once and committed; scaffold must reproduce it."""

    EXAMPLE_ROOT = REPO_ROOT / "examples" / "minimal"
    EXAMPLE_DESTS = (
        "pyproject.toml",
        ".pre-commit-config.yaml",
        ".gitignore",
        ".github/workflows/ci.yml",
        ".github/dependabot.yml",
        ".github/pull_request_template.md",
    )

    def test_stamping_boot_with_name_minimal_reproduces_the_committed_example(
        self, tmp_path
    ) -> None:
        exit_code = scaffold.run(
            _make_args(path=str(tmp_path), set_name="boot", variables=["NAME=minimal"])
        )

        assert exit_code == 0
        for dest in self.EXAMPLE_DESTS:
            rebuilt = (tmp_path / dest).read_bytes()
            committed = (self.EXAMPLE_ROOT / dest).read_bytes()
            assert rebuilt == committed, f"examples/minimal/{dest} is not a byte-for-byte rebuild"

    def test_the_committed_example_has_no_extra_files(self) -> None:
        committed = {
            str(path.relative_to(self.EXAMPLE_ROOT))
            for path in self.EXAMPLE_ROOT.rglob("*")
            if path.is_file()
        }
        assert committed == set(self.EXAMPLE_DESTS)
