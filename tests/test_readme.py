"""Every count and fact the README states is checked against the tree, per the README rules."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
EXPECTED_HEADINGS = ["Features", "Badges", "Security", "How it compares", "Callouts"]


def test_the_python_floor_in_the_readme_matches_pyproject() -> None:
    floor = PYPROJECT["project"]["requires-python"].removeprefix(">=")
    assert f"python-{floor}" in README
    assert f"Python {floor} or newer" in README


def test_the_zero_dependency_badge_matches_pyproject() -> None:
    assert PYPROJECT["project"]["dependencies"] == []
    assert "dependencies-0" in README


def test_the_licence_badge_matches_the_licence_file() -> None:
    assert (REPO_ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert "license-MIT" in README


def test_the_coverage_ramp_in_the_callouts_matches_the_templates() -> None:
    manifest = json.loads((REPO_ROOT / "templates" / "manifest.json").read_text(encoding="utf-8"))
    boot = next(e for e in manifest if e["set"] == "boot" and e["dest"] == "pyproject.toml")
    finish = (REPO_ROOT / "templates" / "finish" / "pyproject.toml").read_text(encoding="utf-8")
    assert boot["defaults"]["COVERAGE_FLOOR"] == "70"
    assert "fail_under = 100" in finish
    assert "70 while building, 100 at finish" in README


def test_the_section_headings_are_the_fixed_six_in_order() -> None:
    headings = re.findall(r"^## (.+)$", README, flags=re.MULTILINE)
    assert headings == EXPECTED_HEADINGS
    assert README.startswith("# 🧩 ossemble\n")


def test_the_comparison_table_puts_ossemble_first_and_uses_no_yes_or_no_cells() -> None:
    header = next(line for line in README.splitlines() if line.startswith("| | ["))
    assert header.split("|")[2].strip().startswith("[oficiallyAkshay/ossemble]")
    rows = [line for line in README.splitlines() if line.startswith("| ") and "|" in line[2:]]
    assert not any(re.search(r"\|\s*(Yes|No)\s*\|", row) for row in rows)


def test_the_readme_has_no_code_fence_shell_snippet_em_dash_or_forbidden_heading() -> None:
    assert "```" not in README
    assert not re.search(r"^\s*(npx|python3?|curl|mkdir|sed|pip) ", README, flags=re.MULTILINE)
    assert "—" not in README
    for heading in ("Limits", "Configuration", "Quick start", "Installation", "Usage"):
        assert f"## {heading}" not in README
