"""Shared fixtures: no test, in any file, ever runs a real zizmor or inherits a git identity."""

from __future__ import annotations

import pytest

from scripts.ossemble import audit


@pytest.fixture(autouse=True)
def zizmor_absent_unless_faked(monkeypatch) -> None:
    monkeypatch.setattr(audit, "_ZIZMOR_COMMAND", "zizmor-absent-for-tests")


@pytest.fixture(autouse=True)
def git_identity_from_repo_config_only(monkeypatch) -> None:
    """A GIT_AUTHOR_* or GIT_COMMITTER_* variable outranks the test repo's own config."""
    for role in ("AUTHOR", "COMMITTER"):
        for field in ("NAME", "EMAIL"):
            monkeypatch.delenv(f"GIT_{role}_{field}", raising=False)
