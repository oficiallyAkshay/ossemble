# Tool reference

Read by the model at build-runbook step 6 (tighten) and step 10 (recommend) to pick tools per repo. This table is data the model reads, not code the audit runs; `audit` only checks that a picked tool is configured and sitting at its finish value.

A few rows are always on whenever their trigger exists in the repo being built, not opt-in per language: a secrets scan, and workflow lint, workflow security and pin verification whenever any workflow file exists. (HRD-007, HRD-005) Everything else is a Python pick, a public-only pick, or an explicit owner recommendation from build-runbook step 10.

| Tool | Applies when | Cost | Always or conditional | Stage |
| --- | --- | --- | --- | --- |
| gitleaks | any repo, full history (HRD-007) | free | always | build, day zero |
| pinact | any workflow file exists (HRD-005) | free | always once a workflow exists | build, day zero |
| actionlint | any workflow file exists | free | always once a workflow exists | build, day zero |
| zizmor | any workflow file exists | free | always once a workflow exists | build, day zero |
| ruff (`select = ["ALL"]` at finish) (HRD-009) | Python detected | free | conditional, Python pick | build (default rules), finish (full set) |
| ty (Astral's type checker) | Python detected | free | conditional, Python pick, adopt | finish |
| vulture, with a name whitelist for fixtures | Python detected | free | conditional, Python pick | finish |
| deptry, with a module-name map | Python detected with declared dependencies | free | conditional, Python pick | finish |
| pip-audit, its own workflow, outside the gate (CI-005) | Python detected with a `pyproject.toml` | free | conditional, Python pick | finish; weekly and on PRs touching `pyproject.toml` |
| diff-cover, one CI leg (CI-006) | tests exist | free | conditional | finish |
| codecov, tokenless via OIDC, non-required (CI-006) | coverage data exists | free | conditional | finish; project and patch targets at 100, kept non-required because fork PRs cannot upload |
| actions/dependency-review-action, on pull requests | public repo with any declared dependencies (dev groups count) | free, GITHUB_TOKEN only | recommendation | finish, on pull requests, complements the weekly pip-audit |
| re-actors/alls-green, as the gate job | any repo with a required `ci` gate job (CI-004) | free | recommendation, equivalent to the hand-rolled gate | finish |
| PyPI trusted publishing with build attestations (OIDC, `id-token: write`, no stored secret) | packaging is recommended at all | free | always, the only publishing mechanism ossemble recommends | finish |
| AGENTS.md, one file, with `CLAUDE.md` a one-line pointer to it (never a symlink; scaffold refuses symlinks) | any repo agents will work on | free | recommendation | finish, docs |
| CodeQL, Python and Actions (CI-009) | public repo with code (or private with Advanced Security) | free on public | recommendation | finish, own workflow, push, PR and weekly |
| OpenSSF Scorecard (CI-008) | public repo | free | recommendation | finish, own workflow, push to main and weekly, `publish_results: true` |
| CodeRabbit, 13-line `.coderabbit.yaml` (REV-004) | public repo with a PR flow | free on public, paid on private | recommendation, needs the owner's passkey | finish, advisory only, never a required check |
| Dependabot auto-merge (`dependabot/fetch-metadata`, `gh pr merge --auto --rebase`) (CI-010) | coverage 100 enforced, a required CI check, hash-pinned actions all hold | free | recommendation | finish; keeps scheduled workflows alive past GitHub's 60-day cutoff |
| deps.dev API v3 | prior-art check needs staleness facts (SCP-003) | free, no auth | conditional, judgment step not code | step 1, define |
| ecosyste.ms | prior-art subject has no deps.dev entry (SCP-003) | free | conditional, judgment step not code | step 1, define |
| skills.sh install badge | shape includes skill | free | conditional | step 13, list |
| uv dependency groups (PEP 735) (STR-002) | dev tooling needed with no package to build | free | always for ossemble-built repos with dev tooling | build |
| prek | any repo using pre-commit; re-measure only if pre-commit becomes the slow step | free | conditional, measured and not adopted | either stage, reversible |

## `.git-blame-ignore-revs`

Adopt as a runbook line, not a template file: when the full formatter first runs repo-wide at tighten, record that commit in `.git-blame-ignore-revs` (`references/build-runbook.md` step 6 has the exact line). Seen at zizmor.

## Measured against ossemble, 2026-09-19 community survey

Ten community repos surveyed: anthropics/skills, vercel-labs/agent-skills, pypa/pipx, python-attrs/attrs, hynek/structlog, pyca/cryptography, ossf/scorecard-action, zizmorcore/zizmor, step-security/harden-runner, github/ruleset-recipes, plus quick audits of astral-sh/setup-uv, actions/checkout and sethvargo/ratchet.

- **ty**: adopt, conditional Python pick at finish. 13 diagnostics on ossemble, 8 fixed by one config line (the flat import layout under `scripts/ossemble` needs the source root declared), 5 real type findings in about 1,700 lines, about one second to run. Production use: pypa/pipx.
- **prek**: measured, not adopted. On ossemble's own hooks it ran 0.65s against pre-commit's 0.36 to 0.73s warm, no gain, and all four hooks failed under it in the cloud container. Production use: attrs, structlog. Re-measure only if pre-commit becomes the slow step.
- **codespell**: measured, not adopted. 9 hits on ossemble, all the deliberate key `optins`, zero real typos.

## Skipped, so a future scout does not re-propose them

Copier (the only real fit for `scaffold`, but it is a dependency with its own template format; a small standard-library stamper keeps the byte-for-byte example intact), cruft, cookiecutter (both stalled), projen, a Terraform provider (both too heavy for this), repolinter (archived), Probot settings, safe-settings (both superseded or org-scale), trunk, MegaLinter, super-linter (Docker or an account, no gain measured over per-language picks), a Rust drop-in for pin verification once pinact already covers it, poutine, octoscan, harden-runner (more dependencies, no measured gap over the current set). The OpenSSF Best Practices badge's modern sibling, the OSPS Baseline, stays a note only: its scanners are third-party and unverified.

From the 2026-09-19 survey:

- CODEOWNERS: skip, solo maintainer.
- Issue templates: skip until a repo is public and has issue traffic; cheap then.
- towncrier and changelog fragments: skip, no releases.
- workflow_call reuse for release gates: skip, no releases.
- Path-filtered workflow triggers: skip, single-product repos.
- GitHub App tokens for bots: skip, zero tokens.
- An osv-scanner ignore file: skip until a false CVE appears.
- Per-skill LICENSE files and THIRD_PARTY_NOTICES: skip, bundle scale.
- An OS matrix: skip, no cross-platform target.
- Container attestations and immutable action releases: skip, not published that way.
- SECURITY.md with private reporting: skip, owner decision.

## Never for a counter

Publishing a thin npm or PyPI wrapper only to get a download count is cut regardless of shape. (NO-005) The durable counter for something ossemble builds is an opt-in clonometer ledger plus the skills.sh page, decided at build-runbook step 1, never a package that exists only to be counted. (DST-001)
