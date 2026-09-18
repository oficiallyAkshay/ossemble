# Tool reference

Read by the model at build-runbook step 6 (tighten) and step 10 (recommend) to pick tools per repo. This table is data the model reads, not code the audit runs; `audit` only checks that a picked tool is configured and sitting at its finish value.

A few rows are always on whenever their trigger exists in the repo being built, not opt-in per language: a secrets scan, and workflow lint, workflow security and pin verification whenever any workflow file exists. Everything else is a Python pick, a public-only pick, or an explicit owner recommendation from build-runbook step 10.

| Tool | Applies when | Cost | Always or conditional | Stage |
| --- | --- | --- | --- | --- |
| gitleaks | any repo, full history | free | always | build, day zero |
| pinact | any workflow file exists | free | always once a workflow exists | build, day zero |
| actionlint | any workflow file exists | free | always once a workflow exists | build, day zero |
| zizmor | any workflow file exists | free | always once a workflow exists | build, day zero |
| ruff (`select = ["ALL"]` at finish) | Python detected | free | conditional, Python pick | build (default rules), finish (full set) |
| vulture, with a name whitelist for fixtures | Python detected | free | conditional, Python pick | finish |
| deptry, with a module-name map | Python detected with declared dependencies | free | conditional, Python pick | finish |
| pip-audit, its own workflow, outside the gate | Python detected with a `pyproject.toml` | free | conditional, Python pick | finish; weekly and on PRs touching `pyproject.toml` |
| diff-cover, one CI leg | tests exist | free | conditional | finish |
| codecov, tokenless via OIDC, non-required | coverage data exists | free | conditional | finish; project and patch targets at 100, kept non-required because fork PRs cannot upload |
| CodeQL, Python and Actions | public repo with code (or private with Advanced Security) | free on public | recommendation | finish, own workflow, push, PR and weekly |
| OpenSSF Scorecard | public repo | free | recommendation | finish, own workflow, push to main and weekly, `publish_results: true` |
| CodeRabbit, 13-line `.coderabbit.yaml` | public repo with a PR flow | free on public, paid on private | recommendation, needs the owner's passkey | finish, advisory only, never a required check |
| Dependabot auto-merge (`dependabot/fetch-metadata`, `gh pr merge --auto --rebase`) | coverage 100 enforced, a required CI check, hash-pinned actions all hold | free | recommendation | finish; keeps scheduled workflows alive past GitHub's 60-day cutoff |
| deps.dev API v3 | prior-art check needs staleness facts | free, no auth | conditional, judgment step not code | step 1, define |
| ecosyste.ms | prior-art subject has no deps.dev entry | free | conditional, judgment step not code | step 1, define |
| skills.sh install badge | shape includes skill | free | conditional | step 13, list |
| uv dependency groups (PEP 735) | dev tooling needed with no package to build | free | always for ossemble-built repos with dev tooling | build |
| prek | measured first against the existing `.pre-commit-config.yaml`; same config either way | free | conditional, adopt only if the measured speed gain holds | either stage, reversible |

## Measured, not yet adopted anywhere

- **prek**: a Rust drop-in for the same `.pre-commit-config.yaml`, claimed much faster; young, compatibility "mostly". Reversal is free because the config does not change.

## Skipped, so a future scout does not re-propose them

Copier (the only real fit for `scaffold`, but it is a dependency with its own template format; a small standard-library stamper keeps the byte-for-byte example intact), cruft, cookiecutter (both stalled), projen, a Terraform provider (both too heavy for this), repolinter (archived), Probot settings, safe-settings (both superseded or org-scale), trunk, MegaLinter, super-linter (Docker or an account, no gain measured over per-language picks), a Rust drop-in for pin verification once pinact already covers it, poutine, octoscan, harden-runner (more dependencies, no measured gap over the current set). The OpenSSF Best Practices badge's modern sibling, the OSPS Baseline, stays a note only: its scanners are third-party and unverified.

## Never for a counter

Publishing a thin npm or PyPI wrapper only to get a download count is cut regardless of shape. The durable counter for something ossemble builds is an opt-in clonometer ledger plus the skills.sh page, decided at build-runbook step 1, never a package that exists only to be counted.
