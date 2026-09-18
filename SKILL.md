---
name: ossemble
description: Assembles a finished, trustworthy open-source repo from a need or an existing repo. Use when starting a new open-source skill, agent, action or library and want tests, gates, an honest README and clean history from the start, or when hardening, auditing or resuming work on a repo ossemble already started.
license: MIT
compatibility: Requires git, gh and uv on PATH, and Python 3.11 or newer. No runtime dependencies.
metadata:
  emoji: 🧩
  tagline: Assembles a finished open-source repo.
---

# ossemble

Takes a need, or an existing repo, and leaves behind a public repo a stranger can trust: tests, gates, an honest README, clean history, nothing personal. The model judges what a repo needs; the script only gathers facts and checks whether a thing is done; the owner approves anything outward-facing.

## Two entry points

- **A need.** No repo exists yet. Read `references/build-runbook.md` and start at scope.
- **An existing repo.** A repo already exists and needs hardening, review or finishing. Read `references/modify-runbook.md` and start at audit.

## Every sitting, start here

Run this before anything else, in the repo being built or hardened:

```
python3 scripts/ossemble resume
```

It checks the environment, reads the stage from the repo, lists any gate the agent lowered, and names the next step. It never redoes work the repo already proves is done.

## Where to look next

| Situation | Open |
|---|---|
| Starting from a need | `references/build-runbook.md` |
| Hardening, auditing or finishing an existing repo | `references/modify-runbook.md` |
| Who does what: scouts, builders, verifiers, judges, auditors | `references/agents.md` |
| Picking security or hygiene tools for this repo | `references/tools.md` |
| Host-specific facts and quirks | `references/hosts.md` |
| Coining and screening a name | `python3 scripts/ossemble name CANDIDATE...` |

Each reference file is a runbook in its own right, not repeated here. Open the one the situation calls for.
