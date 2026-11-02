"""Shared fixtures: no test, in any file, ever runs a real zizmor."""

from __future__ import annotations

import pytest

from scripts.ossemble import audit


@pytest.fixture(autouse=True)
def zizmor_absent_unless_faked(monkeypatch) -> None:
    monkeypatch.setattr(audit, "_ZIZMOR_COMMAND", "zizmor-absent-for-tests")
