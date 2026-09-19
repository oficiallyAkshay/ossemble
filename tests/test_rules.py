"""Tests proving rules/rules.json holds a well-formed, self-consistent rule set."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.ossemble import audit

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = REPO_ROOT / "rules" / "rules.json"

CATEGORY_BY_PREFIX = {
    "SCP": "scope",
    "PRC": "process",
    "STR": "structure and leanness",
    "TST": "tests and failure",
    "HRD": "hardening",
    "SET": "repo settings",
    "CI": "gates and CI",
    "REV": "review",
    "DOC": "readme and brand",
    "PRV": "privacy and history",
    "DST": "distribution",
    "NO": "the no-list",
}
KNOWN_IDS = re.compile(r"\b(?:" + "|".join(CATEGORY_BY_PREFIX) + r")-\d{3}\b")
ID_PATTERN = re.compile(r"^(?:" + "|".join(CATEGORY_BY_PREFIX) + r")-\d{3}$")
ALLOWED_WHEN_KEYS = {"public", "shape", "language", "has_workflows"}


def _load_rules() -> list[dict]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def test_rules_json_is_a_list_of_at_least_one_rule() -> None:
    rules = _load_rules()
    assert isinstance(rules, list)
    assert len(rules) > 0


def test_every_rule_id_matches_a_known_category_prefix_and_three_digits() -> None:
    for rule in _load_rules():
        assert ID_PATTERN.match(rule["id"]), f"{rule['id']!r} does not match PREFIX-000"


def test_every_rule_id_is_unique() -> None:
    rules = _load_rules()
    ids = [rule["id"] for rule in rules]
    assert len(ids) == len(set(ids)), "duplicate rule ids found"


def test_the_rule_list_is_sorted_by_id() -> None:
    rules = _load_rules()
    ids = [rule["id"] for rule in rules]
    assert ids == sorted(ids)


@pytest.mark.parametrize("rule", _load_rules(), ids=lambda rule: rule["id"])
def test_every_rule_has_the_required_fields_with_the_right_types(rule: dict) -> None:
    assert isinstance(rule["id"], str)
    assert rule["id"]
    assert isinstance(rule["text"], str)
    assert rule["text"]
    assert isinstance(rule["basis"], str)
    assert rule["basis"]
    assert isinstance(rule["category"], str)
    assert rule["category"]
    assert rule["kind"] in ("default", "recommendation")
    assert rule["stage"] in ("build", "finish")
    assert rule["check"] in ("audit", "api", "judgment")


@pytest.mark.parametrize("rule", _load_rules(), ids=lambda rule: rule["id"])
def test_every_rule_category_matches_the_spelled_out_word_for_its_id_prefix(rule: dict) -> None:
    prefix = rule["id"].split("-")[0]
    assert rule["category"] == CATEGORY_BY_PREFIX[prefix]


@pytest.mark.parametrize("rule", _load_rules(), ids=lambda rule: rule["id"])
def test_a_rule_names_a_probe_exactly_when_its_check_is_audit_or_api(rule: dict) -> None:
    has_probe = bool(rule.get("probe"))
    needs_probe = rule["check"] in ("audit", "api")
    assert has_probe == needs_probe, (
        f"{rule['id']}: check={rule['check']!r} probe={rule.get('probe')!r}"
    )


@pytest.mark.parametrize("rule", _load_rules(), ids=lambda rule: rule["id"])
def test_a_rules_when_conditions_use_only_the_documented_keys(rule: dict) -> None:
    when = rule.get("when")
    if when is None:
        return
    assert isinstance(when, dict)
    assert when
    assert set(when).issubset(ALLOWED_WHEN_KEYS)


EM_DASH = chr(0x2014)


@pytest.mark.parametrize("rule", _load_rules(), ids=lambda rule: rule["id"])
def test_no_rule_text_or_basis_contains_an_em_dash(rule: dict) -> None:
    assert EM_DASH not in rule["text"]
    assert EM_DASH not in rule["basis"]


def _rule_by_id(rule_id: str) -> dict:
    for rule in _load_rules():
        if rule["id"] == rule_id:
            return rule
    raise AssertionError(f"no rule {rule_id!r} found")


def test_str_003_states_it_covers_only_human_docs_not_references_or_agents() -> None:
    rule = _rule_by_id("STR-003")
    assert "README.md" in rule["text"]
    assert "CONTRIBUTING.md" in rule["text"]
    assert "references" in rule["basis"]
    assert "agents" in rule["basis"]


def test_str_004_states_it_counts_git_tracked_bytes_outside_tests_and_examples() -> None:
    rule = _rule_by_id("STR-004")
    assert "git-tracked" in rule["text"]
    assert "tests/" in rule["text"]
    assert "examples/" in rule["text"]
    assert "test" in rule["basis"]
    assert "example" in rule["basis"]


def test_every_probe_named_by_a_rule_exists_as_a_function_in_audit_py() -> None:
    named_probes = {rule["probe"] for rule in _load_rules() if "probe" in rule}
    for probe_name in named_probes:
        assert probe_name in audit.PROBES, (
            f"rule names probe {probe_name!r}, missing from audit.PROBES"
        )


def test_every_probe_in_audit_py_is_named_by_at_least_one_rule() -> None:
    named_probes = {rule["probe"] for rule in _load_rules() if "probe" in rule}
    for probe_name in audit.PROBES:
        assert probe_name in named_probes, (
            f"audit.py defines probe {probe_name!r}, named by no rule"
        )


def test_every_rule_id_cited_under_references_agents_or_skill_md_exists_in_rules_json() -> None:
    known_ids = {rule["id"] for rule in _load_rules()}
    citing_paths = (
        list((REPO_ROOT / "references").rglob("*.md"))
        if (REPO_ROOT / "references").is_dir()
        else []
    )
    citing_paths += (
        list((REPO_ROOT / "agents").rglob("*.md")) if (REPO_ROOT / "agents").is_dir() else []
    )
    skill_md = REPO_ROOT / "SKILL.md"
    if skill_md.is_file():
        citing_paths.append(skill_md)

    cited = set()
    for path in citing_paths:
        cited.update(KNOWN_IDS.findall(path.read_text(encoding="utf-8")))

    missing = cited - known_ids
    assert not missing, f"cited rule ids that do not exist in rules.json: {sorted(missing)}"


def test_every_manifest_rule_id_exists_in_rules_json() -> None:
    known_ids = {rule["id"] for rule in _load_rules()}
    manifest = json.loads((REPO_ROOT / "templates" / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        missing = set(entry.get("rules", [])) - known_ids
        assert not missing, (
            f"{entry['src']!r} (set {entry['set']!r}) names rule ids missing from "
            f"rules.json: {sorted(missing)}"
        )
