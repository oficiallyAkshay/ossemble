"""Tests for the readme-check and clonometer template sets and the figurehead runbook step."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts.ossemble import scaffold

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ".github/workflows"
SET_FILES = {
    "readme-check": f"{WORKFLOWS}/readme-check.yml",
    "clonometer": f"{WORKFLOWS}/clonometer.yml",
}


def _make_args(*, path: str, set_name: str) -> argparse.Namespace:
    return argparse.Namespace(path=path, set_name=set_name, variables=[], check=False)


@pytest.mark.parametrize(("set_name", "dest"), SET_FILES.items())
def test_stamping_the_set_writes_the_workflow_this_repo_runs_itself(
    set_name, dest, tmp_path
) -> None:
    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name=set_name))

    assert exit_code == 0
    stamped = (tmp_path / dest).read_bytes()
    assert stamped == (REPO_ROOT / dest).read_bytes()
    assert [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()] == [
        dest
    ]


@pytest.mark.parametrize("set_name", ["boot", "finish"])
def test_the_default_sets_never_stamp_clonometer(set_name, tmp_path) -> None:
    exit_code = scaffold.run(_make_args(path=str(tmp_path), set_name=set_name))

    assert exit_code == 0
    assert not (tmp_path / SET_FILES["clonometer"]).exists()


def test_the_clonometer_template_names_the_secret_an_owner_must_add() -> None:
    manifest = json.loads((REPO_ROOT / "templates" / "manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest if e["set"] == "clonometer")
    template = (REPO_ROOT / "templates" / entry["src"]).read_text(encoding="utf-8")

    assert "secrets.TRAFFIC_TOKEN" in template
    assert "schedule:" in template
    assert "workflow_dispatch:" in template


def test_the_runbook_runs_figurehead_to_render_and_check_the_hero() -> None:
    runbook = (REPO_ROOT / "references" / "build-runbook.md").read_text(encoding="utf-8")
    spec = "assets/readme/hero.hero.json"
    svg = "assets/readme/hero.svg"

    assert f"figurehead.mjs render {spec} --out {svg}" in runbook
    assert f"figurehead.mjs check {spec} {svg} --repo ." in runbook
    assert (REPO_ROOT / spec).is_file()
    assert (REPO_ROOT / svg).is_file()
