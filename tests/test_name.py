"""Tests for the `ossemble name` subcommand: screening candidates on npm, PyPI and GitHub."""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.error
from typing import Self

import pytest

from scripts.ossemble import name


class _FakeResponse:
    """A stand-in for the object `urllib.request.OpenerDirector.open` returns."""

    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _FakeOpener:
    """Replaces `build_opener(...)`'s result with a scripted `.open`."""

    def __init__(self, open_fn) -> None:
        self._open_fn = open_fn

    def open(self, request, timeout):
        return self._open_fn(request.full_url, timeout)


def _patch_opener(monkeypatch, open_fn) -> None:
    monkeypatch.setattr(
        name.urllib.request, "build_opener", lambda *_handlers: _FakeOpener(open_fn)
    )


def _by_url(table: dict[str, _FakeResponse | Exception]):
    """Build an `.open` function that dispatches on the exact request URL."""

    def open_fn(url, timeout):
        outcome = table[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return open_fn


# --- add_parser and run wiring -----------------------------------------------------------


def test_add_parser_registers_the_name_subcommand_and_wires_it_to_run() -> None:
    parser = argparse.ArgumentParser(prog="ossemble")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    name.add_parser(subparsers)

    args = parser.parse_args(["name", "ossemble"])

    assert args.subcommand == "name"
    assert args.run is name.run
    assert args.candidates == ["ossemble"]
    assert args.json is False


# --- candidate validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate", ["Ossemble", "os-semble", "os_semble", "1ossemble", "", "os semble"]
)
def test_run_rejects_a_candidate_that_is_not_one_lowercase_word_of_letters_and_digits(
    candidate, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(name.shutil, "which", lambda _tool: None)
    exit_code = name.run(argparse.Namespace(candidates=[candidate], json=False))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "is not one lowercase word of letters and digits" in captured.err
    assert captured.out == ""


def test_run_validates_every_candidate_before_making_any_network_request(
    monkeypatch, capsys
) -> None:
    called = []
    monkeypatch.setattr(name, "_screen", lambda candidate, use_gh: called.append(candidate))
    monkeypatch.setattr(name.shutil, "which", lambda _tool: None)

    exit_code = name.run(argparse.Namespace(candidates=["good", "Bad"], json=False))

    assert exit_code == 1
    assert called == []
    assert "'Bad'" in capsys.readouterr().err


# --- run(): dispatch, sorting, exit code, output mode ------------------------------------


def test_run_sorts_results_by_candidate_and_prints_one_row_each(monkeypatch, capsys) -> None:
    monkeypatch.setattr(name.shutil, "which", lambda _tool: None)
    monkeypatch.setattr(
        name,
        "_screen",
        lambda candidate, use_gh: {
            "candidate": candidate,
            "status": "free",
            "free": True,
            "checks": dict.fromkeys(name._CHECK_ORDER, "free"),
        },
    )

    exit_code = name.run(argparse.Namespace(candidates=["zeta", "alpha"], json=False))

    out_lines = capsys.readouterr().out.splitlines()
    assert exit_code == 0
    assert out_lines == ["alpha  FREE", "zeta  FREE"]


def test_run_prints_json_when_asked(monkeypatch, capsys) -> None:
    monkeypatch.setattr(name.shutil, "which", lambda _tool: None)
    monkeypatch.setattr(
        name,
        "_screen",
        lambda candidate, use_gh: {
            "candidate": candidate,
            "status": "free",
            "free": True,
            "checks": dict.fromkeys(name._CHECK_ORDER, "free"),
        },
    )

    exit_code = name.run(argparse.Namespace(candidates=["ossemble"], json=True))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == [
        {
            "candidate": "ossemble",
            "status": "free",
            "free": True,
            "checks": dict.fromkeys(name._CHECK_ORDER, "free"),
        }
    ]


def test_run_returns_one_when_any_candidate_is_not_free(monkeypatch, capsys) -> None:
    monkeypatch.setattr(name.shutil, "which", lambda _tool: None)
    monkeypatch.setattr(
        name,
        "_screen",
        lambda candidate, use_gh: {
            "candidate": candidate,
            "status": "taken",
            "free": False,
            "checks": {**dict.fromkeys(name._CHECK_ORDER, "free"), "npm": "taken"},
        },
    )

    exit_code = name.run(argparse.Namespace(candidates=["taken"], json=False))

    assert exit_code == 1
    assert capsys.readouterr().out.splitlines() == ["taken  TAKEN  npm:taken"]


def test_run_returns_one_when_a_candidate_is_errored_rather_than_taken(monkeypatch, capsys) -> None:
    monkeypatch.setattr(name.shutil, "which", lambda _tool: None)
    monkeypatch.setattr(
        name,
        "_screen",
        lambda candidate, use_gh: {
            "candidate": candidate,
            "status": "error",
            "free": False,
            "checks": {**dict.fromkeys(name._CHECK_ORDER, "free"), "github_user": "error"},
        },
    )

    exit_code = name.run(argparse.Namespace(candidates=["errored"], json=False))

    assert exit_code == 1
    assert capsys.readouterr().out.splitlines() == ["errored  ERROR  github_user:error"]


def test_run_uses_gh_when_it_is_on_path(monkeypatch) -> None:
    monkeypatch.setattr(name.shutil, "which", lambda tool: "/usr/bin/gh" if tool == "gh" else None)
    seen = {}

    def fake_screen(candidate, use_gh):
        seen["use_gh"] = use_gh
        return {"candidate": candidate, "status": "free", "free": True, "checks": {}}

    monkeypatch.setattr(name, "_screen", fake_screen)

    name.run(argparse.Namespace(candidates=["ossemble"], json=False))

    assert seen["use_gh"] is True


# --- _screen: combining four checks into one status --------------------------------------


def test_screen_reports_taken_when_any_check_is_taken(monkeypatch) -> None:
    monkeypatch.setattr(name, "_check_npm", lambda candidate: "taken")
    monkeypatch.setattr(name, "_check_pypi", lambda candidate: "free")
    monkeypatch.setattr(name, "_check_github_user", lambda candidate, use_gh: "free")
    monkeypatch.setattr(name, "_check_github_repo", lambda candidate, use_gh: "error")

    result = name._screen("ossemble", use_gh=False)

    assert result["status"] == "taken"
    assert result["free"] is False


def test_screen_reports_error_when_nothing_is_taken_but_something_errored(monkeypatch) -> None:
    monkeypatch.setattr(name, "_check_npm", lambda candidate: "free")
    monkeypatch.setattr(name, "_check_pypi", lambda candidate: "error")
    monkeypatch.setattr(name, "_check_github_user", lambda candidate, use_gh: "free")
    monkeypatch.setattr(name, "_check_github_repo", lambda candidate, use_gh: "free")

    result = name._screen("ossemble", use_gh=False)

    assert result["status"] == "error"
    assert result["free"] is False


def test_screen_reports_free_when_every_check_is_free(monkeypatch) -> None:
    for attr in ("_check_npm", "_check_pypi"):
        monkeypatch.setattr(name, attr, lambda candidate: "free")
    for attr in ("_check_github_user", "_check_github_repo"):
        monkeypatch.setattr(name, attr, lambda candidate, use_gh: "free")

    result = name._screen("ossemble", use_gh=False)

    assert result["status"] == "free"
    assert result["free"] is True


# --- _format_row --------------------------------------------------------------------------


def test_format_row_lists_every_non_free_check_in_a_fixed_order() -> None:
    result = {
        "candidate": "ossemble",
        "status": "error",
        "free": False,
        "checks": {"npm": "free", "pypi": "error", "github_user": "taken", "github_repo": "free"},
    }

    assert name._format_row(result) == "ossemble  ERROR  pypi:error,github_user:taken"


# --- _run_check ----------------------------------------------------------------------------


def test_run_check_returns_the_probes_result_when_it_succeeds() -> None:
    assert name._run_check("ossemble", "npm", lambda: "free") == "free"


def test_run_check_prints_one_stderr_line_and_returns_error_on_failure(capsys) -> None:
    def probe():
        raise ValueError("boom")

    result = name._run_check("ossemble", "npm", probe)

    assert result == "error"
    assert capsys.readouterr().err == "ossemble name: npm check failed for 'ossemble': boom\n"


# --- _NoRedirect ----------------------------------------------------------------------------


def test_no_redirect_handler_refuses_every_redirect_instead_of_following_it() -> None:
    handler = name._NoRedirect()
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://example.com/elsewhere")


# --- _fetch --------------------------------------------------------------------------------


def test_fetch_refuses_a_non_https_url() -> None:
    with pytest.raises(ValueError, match="non-https"):
        name._fetch("http://registry.npmjs.org/ossemble")


def test_fetch_returns_the_status_and_body_on_success(monkeypatch) -> None:
    _patch_opener(monkeypatch, lambda url, timeout: _FakeResponse(200, b"{}"))

    status, body = name._fetch("https://registry.npmjs.org/ossemble")

    assert (status, body) == (200, b"{}")


def test_fetch_turns_an_http_error_into_its_status_code_with_no_body(monkeypatch) -> None:
    def open_fn(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    _patch_opener(monkeypatch, open_fn)

    status, body = name._fetch("https://registry.npmjs.org/ossemble")

    assert (status, body) == (404, b"")


# --- _status_from_code ----------------------------------------------------------------------


@pytest.mark.parametrize(("code", "expected"), [(200, "taken"), (404, "free"), (500, "error")])
def test_status_from_code_maps_http_codes_to_a_check_result(code, expected) -> None:
    assert name._status_from_code(code) == expected


# --- _check_npm ------------------------------------------------------------------------------


def test_check_npm_reports_taken_when_the_registry_has_the_package(monkeypatch) -> None:
    monkeypatch.setattr(name, "_fetch", lambda url: (200, b""))
    assert name._check_npm("ossemble") == "taken"


def test_check_npm_reports_free_when_the_registry_returns_not_found(monkeypatch) -> None:
    monkeypatch.setattr(name, "_fetch", lambda url: (404, b""))
    assert name._check_npm("ossemble") == "free"


def test_check_npm_reports_error_on_a_network_failure(monkeypatch, capsys) -> None:
    def fetch(url):
        raise OSError("connection reset")

    monkeypatch.setattr(name, "_fetch", fetch)
    assert name._check_npm("ossemble") == "error"
    assert "npm check failed" in capsys.readouterr().err


# --- _pypi_names -----------------------------------------------------------------------------


def test_pypi_names_deduplicates_the_hyphen_and_underscore_twins_of_a_plain_word() -> None:
    assert name._pypi_names("ossemble") == ["ossemble", "ossembles"]


# --- _check_pypi -----------------------------------------------------------------------------


def test_check_pypi_is_free_when_the_word_and_its_plural_are_both_unregistered(monkeypatch) -> None:
    monkeypatch.setattr(name, "_fetch", lambda url: (404, b""))
    assert name._check_pypi("ossemble") == "free"


def test_check_pypi_is_taken_when_the_plural_twin_is_registered(monkeypatch) -> None:
    table = {
        "https://pypi.org/pypi/ossemble/json": (404, b""),
        "https://pypi.org/pypi/ossembles/json": (200, b""),
    }
    monkeypatch.setattr(name, "_fetch", lambda url: table[url])
    assert name._check_pypi("ossemble") == "taken"


def test_check_pypi_is_error_when_nothing_is_taken_but_a_lookup_misbehaves(monkeypatch) -> None:
    table = {
        "https://pypi.org/pypi/ossemble/json": (404, b""),
        "https://pypi.org/pypi/ossembles/json": (503, b""),
    }
    monkeypatch.setattr(name, "_fetch", lambda url: table[url])
    assert name._check_pypi("ossemble") == "error"


# --- _run_gh --------------------------------------------------------------------------------


def test_run_gh_runs_gh_api_with_the_given_path_and_never_raises_on_failure(monkeypatch) -> None:
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)"
        )

    monkeypatch.setattr(name.subprocess, "run", fake_run)

    result = name._run_gh("users/ossemble")

    assert seen["cmd"] == ["gh", "api", "users/ossemble"]
    assert result.returncode == 1


# --- _check_github_user -----------------------------------------------------------------------


def test_check_github_user_is_taken_when_gh_api_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(
        name,
        "_run_gh",
        lambda path: subprocess.CompletedProcess([], returncode=0, stdout="{}", stderr=""),
    )
    assert name._check_github_user("ossemble", use_gh=True) == "taken"


def test_check_github_user_is_free_when_gh_api_reports_a_404(monkeypatch) -> None:
    monkeypatch.setattr(
        name,
        "_run_gh",
        lambda path: subprocess.CompletedProcess(
            [], returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)"
        ),
    )
    assert name._check_github_user("ossemble", use_gh=True) == "free"


def test_check_github_user_falls_back_and_is_honoured_when_gh_api_is_refused(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        name,
        "_run_gh",
        lambda path: subprocess.CompletedProcess(
            [], returncode=1, stdout="", stderr="HTTP 403: Forbidden"
        ),
    )
    monkeypatch.setattr(name, "_fetch", lambda url: (404, b""))

    result = name._check_github_user("ossemble", use_gh=True)

    err = capsys.readouterr().err
    assert result == "free"
    assert "github_user check for 'ossemble': gh api refused" in err
    assert "falling back to the public GitHub API" in err


def test_check_github_user_fallback_failing_stays_an_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        name,
        "_run_gh",
        lambda path: subprocess.CompletedProcess(
            [], returncode=1, stdout="", stderr="rate limited"
        ),
    )

    def fetch(url):
        raise OSError("connection reset")

    monkeypatch.setattr(name, "_fetch", fetch)

    assert name._check_github_user("ossemble", use_gh=True) == "error"
    assert "github_user check failed" in capsys.readouterr().err


def test_check_github_user_falls_back_to_a_plain_request_when_gh_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(name, "_fetch", lambda url: (404, b""))
    assert name._check_github_user("ossemble", use_gh=False) == "free"


# --- _check_github_repo -----------------------------------------------------------------------


def test_check_github_repo_is_taken_when_gh_api_finds_an_exact_name_match(monkeypatch) -> None:
    payload = json.dumps({"items": [{"name": "Ossemble"}, {"name": "ossemble-other"}]})
    monkeypatch.setattr(
        name,
        "_run_gh",
        lambda path: subprocess.CompletedProcess([], returncode=0, stdout=payload, stderr=""),
    )
    assert name._check_github_repo("ossemble", use_gh=True) == "taken"


def test_check_github_repo_is_free_when_gh_api_finds_no_exact_name_match(monkeypatch) -> None:
    payload = json.dumps({"items": [{"name": "ossemble-other"}]})
    monkeypatch.setattr(
        name,
        "_run_gh",
        lambda path: subprocess.CompletedProcess([], returncode=0, stdout=payload, stderr=""),
    )
    assert name._check_github_repo("ossemble", use_gh=True) == "free"


def test_check_github_repo_falls_back_and_is_honoured_when_gh_api_is_refused(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        name,
        "_run_gh",
        lambda path: subprocess.CompletedProcess(
            [], returncode=1, stdout="", stderr="HTTP 403: Forbidden"
        ),
    )
    payload = json.dumps({"items": [{"name": "ossemble-other"}]}).encode("utf-8")
    monkeypatch.setattr(name, "_fetch", lambda url: (200, payload))

    result = name._check_github_repo("ossemble", use_gh=True)

    err = capsys.readouterr().err
    assert result == "free"
    assert "github_repo check for 'ossemble': gh api refused" in err
    assert "falling back to the public GitHub API" in err


def test_check_github_repo_fallback_failing_stays_an_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        name,
        "_run_gh",
        lambda path: subprocess.CompletedProcess(
            [], returncode=1, stdout="", stderr="rate limited"
        ),
    )
    monkeypatch.setattr(name, "_fetch", lambda url: (503, b""))

    assert name._check_github_repo("ossemble", use_gh=True) == "error"


def test_check_github_repo_falls_back_to_a_plain_request_when_gh_is_unavailable(
    monkeypatch,
) -> None:
    payload = json.dumps({"items": []}).encode("utf-8")
    monkeypatch.setattr(name, "_fetch", lambda url: (200, payload))
    assert name._check_github_repo("ossemble", use_gh=False) == "free"


def test_check_github_repo_without_gh_reports_error_on_a_non_200_response(monkeypatch) -> None:
    monkeypatch.setattr(name, "_fetch", lambda url: (503, b""))
    assert name._check_github_repo("ossemble", use_gh=False) == "error"
