"""The `ossemble name` subcommand.

Screens each candidate name against npm, PyPI (and its normalised twins),
a GitHub user or org, and an exact-name GitHub repository search. A
candidate is free only when every check comes back free. Registries are
checked before GitHub, and GitHub calls go through `gh api` when it is on
PATH, falling back to a plain unauthenticated request otherwise.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable
    from typing import NoReturn

_CANDIDATE_RE = re.compile(r"^[a-z][a-z0-9]*$")
_TIMEOUT_SECONDS = 10
_USER_AGENT = "ossemble-name-check"
_CHECK_ORDER = ("npm", "pypi", "github_user", "github_repo")
_HTTP_OK = 200
_HTTP_NOT_FOUND = 404

# Anything that means "the check could not be completed", never "it is
# taken" or "it is free". Caught in one place so every network path fails
# the same graceful way: one stderr line, never a traceback.
_CHECK_ERRORS = (
    OSError,
    RuntimeError,
    ValueError,
    subprocess.SubprocessError,
    json.JSONDecodeError,
)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `name` subcommand and wire it to `run`."""
    parser = subparsers.add_parser(
        "name", help="screen candidate repo names on npm, PyPI and GitHub"
    )
    parser.add_argument(
        "candidates", metavar="CANDIDATE", nargs="+", help="a candidate name to screen"
    )
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON instead of rows"
    )
    parser.set_defaults(run=run)
    return parser


def run(args: argparse.Namespace) -> int:
    """Validate every candidate, screen each one, and print the results."""
    for candidate in args.candidates:
        if not _CANDIDATE_RE.match(candidate):
            print(
                f"ossemble name: '{candidate}' is not one lowercase word of letters and digits",
                file=sys.stderr,
            )
            return 1

    use_gh = shutil.which("gh") is not None
    results = sorted(
        (_screen(candidate, use_gh=use_gh) for candidate in args.candidates),
        key=lambda r: r["candidate"],
    )

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        for result in results:
            print(_format_row(result))

    return 0 if all(result["free"] for result in results) else 1


def _screen(candidate: str, *, use_gh: bool) -> dict:
    """Run every check for one candidate and combine them into one result."""
    checks = {
        "npm": _check_npm(candidate),
        "pypi": _check_pypi(candidate),
        "github_user": _check_github_user(candidate, use_gh=use_gh),
        "github_repo": _check_github_repo(candidate, use_gh=use_gh),
    }
    if any(checks[name] == "taken" for name in _CHECK_ORDER):
        status = "taken"
    elif any(checks[name] == "error" for name in _CHECK_ORDER):
        status = "error"
    else:
        status = "free"
    return {"candidate": candidate, "status": status, "free": status == "free", "checks": checks}


def _format_row(result: dict) -> str:
    """Format one candidate's result as a plain two- or three-column row."""
    if result["free"]:
        return f"{result['candidate']}  FREE"
    detail = ",".join(
        f"{name}:{result['checks'][name]}"
        for name in _CHECK_ORDER
        if result["checks"][name] != "free"
    )
    return f"{result['candidate']}  {result['status'].upper()}  {detail}"


def _run_check(candidate: str, check_name: str, probe: Callable[[], str]) -> str:
    """Run one probe, turning any failure into a single stderr line."""
    try:
        return probe()
    except _CHECK_ERRORS as error:
        print(
            f"ossemble name: {check_name} check failed for '{candidate}': {error}", file=sys.stderr
        )
        return "error"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect instead of following it."""

    def redirect_request(
        self,
        _req: urllib.request.Request,
        _fp: object,
        _code: int,
        _msg: str,
        _headers: object,
        newurl: str,
    ) -> NoReturn:
        raise urllib.error.URLError(f"refusing to follow a redirect to {newurl}")


def _fetch(url: str) -> tuple[int, bytes]:
    """GET an https URL with no redirects, returning its status and body."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-https URL: {url}")
    opener = urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(  # noqa: S310 -- https is checked just above
        url, headers={"User-Agent": _USER_AGENT}
    )
    try:
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


def _status_from_code(code: int) -> str:
    """Map an HTTP status code to taken, free or error for an existence check."""
    if code == _HTTP_OK:
        return "taken"
    if code == _HTTP_NOT_FOUND:
        return "free"
    return "error"


def _check_npm(candidate: str) -> str:
    """Check whether a package of this name is registered on npm."""

    def probe() -> str:
        url = f"https://registry.npmjs.org/{urllib.parse.quote(candidate, safe='')}"
        status, _ = _fetch(url)
        return _status_from_code(status)

    return _run_check(candidate, "npm", probe)


def _pypi_names(candidate: str) -> list[str]:
    """List the names to check on PyPI: the candidate and its plural twin.

    A validated candidate never contains a hyphen or underscore, so PyPI's
    own hyphen/underscore normalisation has nothing to fold together here;
    the transforms are kept so the function still does the right thing if
    that validation is ever relaxed.
    """
    variants = [
        candidate,
        candidate.replace("-", "_"),
        candidate.replace("_", "-"),
        f"{candidate}s",
    ]
    return list(dict.fromkeys(variants))


def _check_pypi(candidate: str) -> str:
    """Check the candidate and its normalised twins (hyphen, underscore, plural) on PyPI."""

    def probe() -> str:
        statuses = []
        for variant in _pypi_names(candidate):
            url = f"https://pypi.org/pypi/{urllib.parse.quote(variant, safe='')}/json"
            status, _ = _fetch(url)
            statuses.append(_status_from_code(status))
        if "taken" in statuses:
            return "taken"
        if "error" in statuses:
            return "error"
        return "free"

    return _run_check(candidate, "pypi", probe)


def _run_gh(path_and_query: str) -> subprocess.CompletedProcess:
    """Run `gh api <path>`, never raising for a non-zero exit."""
    return subprocess.run(  # noqa: S603 -- fixed argv, never a shell
        ["gh", "api", path_and_query],  # noqa: S607 -- gh is a trusted binary name
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _check_github_user(candidate: str, *, use_gh: bool) -> str:
    """Check whether a GitHub user or org owns this exact login."""

    def probe() -> str:
        encoded = urllib.parse.quote(candidate, safe="")
        if use_gh:
            result = _run_gh(f"users/{encoded}")
            if result.returncode == 0:
                return "taken"
            if "404" in result.stderr:
                return "free"
            raise RuntimeError(result.stderr.strip() or "gh api users failed")
        status, _ = _fetch(f"https://api.github.com/users/{encoded}")
        return _status_from_code(status)

    return _run_check(candidate, "github_user", probe)


def _check_github_repo(candidate: str, *, use_gh: bool) -> str:
    """Check GitHub for a repository whose name matches the candidate exactly."""

    def probe() -> str:
        query = urllib.parse.quote(f"{candidate} in:name", safe="")
        if use_gh:
            result = _run_gh(f"search/repositories?q={query}")
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "gh api search failed")
            payload = json.loads(result.stdout)
        else:
            status, body = _fetch(f"https://api.github.com/search/repositories?q={query}")
            if status != _HTTP_OK:
                return "error"
            payload = json.loads(body.decode("utf-8"))
        names = {item["name"].lower() for item in payload.get("items", [])}
        return "taken" if candidate in names else "free"

    return _run_check(candidate, "github_repo", probe)
