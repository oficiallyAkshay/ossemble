# The CI shape

`templates/finish/.github/workflows/ci.yml` is the shape this repo is
adopting for itself and stamps into every repo it finishes; the current
`.github/workflows/ci.yml` here is still the lighter build-stage
version from `templates/boot/`. Three jobs, every time:

- **`checks`.** Runs the same hooks from `.pre-commit-config.yaml`
  (ruff, actionlint, zizmor) over the whole tree, then `pinact` to
  confirm every `uses:` is a full commit SHA whose version comment
  names that same commit, then a gitleaks secrets scan over full
  history (not just the working tree).
- **`test`.** Runs `pytest --cov` on a matrix of Python versions. At
  the finish stage the full matrix (3.11, 3.12, 3.14) runs on every
  push and pull request; at the build stage a pull request runs one
  interpreter and only a push to `main` runs the full matrix, to keep
  the checkout-triggered clone count down (see
  `references/hosts.md`). At finish, one leg (3.14) also uploads
  `coverage.xml` to Codecov over OIDC, tokenless and non-required
  because a fork's pull request cannot carry the OIDC token, and runs
  `diff-cover` against `origin/main` at `--fail-under=100` so changed
  lines are covered even before the whole file is.
- **`ci`.** Depends on both jobs above, sets `if: always()`, and fails
  if either dependency's result was anything but `success`, including
  `skipped` or `cancelled`. This is deliberate: a matrix job or a
  workflow syntax change could otherwise skip a check silently and
  still report green. This job's name never changes shape with the
  matrix, which is why the branch ruleset requires only `ci` and
  nothing else; requiring every matrix leg by name would break the
  moment the matrix changes.

A separate `audit.yml` (from the `audit-deps` template set) runs
`pip-audit` weekly and on any pull request touching `pyproject.toml`,
outside the required gate, so a dependency finding never blocks a
merge on its own.

`dependabot-auto-merge.yml` (from the `dependabot-automerge` template
set, CI-010) arms `gh pr merge --auto --rebase` on every pull request
opened by `dependabot[bot]`; the branch ruleset's required `ci` check
still has to pass before GitHub merges anything, so this only removes
the manual click. It is only added once coverage is enforced at 100
percent, `ci` is the required check, and every action is hash-pinned —
true here, so the workflow is in.

The coverage floor itself lives in `pyproject.toml`'s
`[tool.coverage.report] fail_under`, and is how `resume` and `audit`
tell the build stage from the finish stage: 100 means finish, anything
lower means build. During the build stage it starts at 70
(`templates/boot/pyproject.toml`'s default) and is raised, wave by
wave, to whatever was actually achieved:

```
python3 scripts/ossemble floor --coverage-xml coverage.xml
```

It never drops. The finish template
(`templates/finish/pyproject.toml`) fixes it at 100, line and branch,
and turns on `select = ["ALL"]` for ruff with every ignored rule family
justified by a comment.
