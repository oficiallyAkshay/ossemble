# {{NAME}}

One line: what {{NAME}} is and who it is for.

## Checks

Run these before committing:

```
uv run pytest --cov --cov-report=term-missing
uv run pre-commit run --all-files
```

Both must pass. Coverage stays at the floor recorded in `pyproject.toml`.

## Rules that bind agents here

- Keep this file, `AGENTS.md`, as the single agent-instructions file; `CLAUDE.md` only points to it.
- Follow `CONTRIBUTING.md` for how changes are made, reviewed and merged.
- Never bypass a hook, and never edit a gate's own configuration to make it pass.

See `CONTRIBUTING.md` for the full contribution process.
