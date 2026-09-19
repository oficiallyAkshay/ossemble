# Pre-commit hooks

`.pre-commit-config.yaml` runs `ruff-check --fix`, `ruff-format`,
`gitleaks`, `actionlint` and `zizmor`, pinned by tag. Run it as:

```
env -u GH_TOKEN -u GITHUB_TOKEN uv run pre-commit run --all-files
```

The two env vars are unset on purpose. An ambient `GH_TOKEN` or
`GITHUB_TOKEN` in a cloud session can be a placeholder; zizmor forwards
whatever it finds to github.com and fails with a 401 and a Rust
backtrace instead of a clean rule finding. Unsetting both first keeps a
placeholder token from ever reaching it, locally and in CI alike.
