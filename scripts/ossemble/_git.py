"""The one git subprocess wrapper `audit` and `resume` both run commands through.

Both modules need to run a handful of git subcommands against a target
path and treat "git itself could not run" the same way; this is that one
place, so the timeout, the captured output and the error handling match
everywhere a git command is run.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    """Run `git -C root <args>`, or None when git itself could not be run."""
    try:
        return subprocess.run(  # noqa: S603 -- fixed argv, never a shell
            ["git", "-C", str(root), *args],  # noqa: S607 -- git is a trusted binary name
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return None
