# Contributing

This file has two halves. The first is for a person making a change by
hand. The second is dense reference for an agent, or for anyone wiring
this repo into CI; skip it unless you need it.

## For people

Clone the repo, then:

```
uv sync
uv run pytest --cov
uv run pre-commit run --all-files
```

`uv sync` installs the dev dependency group (pytest, coverage, pre-commit
and friends); the runtime script itself depends on nothing beyond the
standard library. Run the two commands above before every push; CI runs
the same checks and will not tell you anything new if they already pass.

There is a third check, run separately because it clones real repos:
`python3 tests/eval/consumers.py`. It runs the audit against thirteen
pinned public repos and compares the rows it prints with the ones
stored in `tests/eval/consumers.json`, so a probe change that starts or
stops flagging something real is visible in the diff, not just in the
test suite. It clones into `$RUNNER_TEMP` on a runner, or a system
temp directory otherwise, never into the repo. If you meant to change
what fires, update the stored snapshot in the same pull request with
`python3 tests/eval/consumers.py --update`.

### How a change lands

One branch per change, one commit or a small stack you are happy to
squash by hand (rebase merge only, no squash button here). Title the
change as a plain present-tense sentence describing the state once it
lands, for example "The audit reads its own rules file instead of the
target's". Open a pull request; `.github/pull_request_template.md`
gives you four headings to fill in: What changes, What does not change,
How to undo, and Checks run locally.

Auto-merge is on and set to rebase. Once you open the PR, arm it (`gh pr
merge --auto --rebase`) and walk away. CI is the review: nothing here
waits on a human approval, and the `ci` check is the only one the branch
ruleset requires. If CI fails, push a fix to the same branch.

### What to add where

- **A new rule.** Add an object to `rules/rules.json` (see the schema
  below) and, if it is machine-checkable, a matching probe function in
  `scripts/ossemble/audit.py`.
- **A new template.** Add the file under `templates/`, then an entry in
  `templates/manifest.json` naming its destination, its set and the
  rules it satisfies.
- **A new agent role.** Add a prompt file under `agents/`. The roster is
  the directory listing; there is no separate registration step.

### Reporting a vulnerability

Open an issue. This repo has no private reporting channel, by design.

## For agents and CI

### CLI usage

Run any subcommand as `python3 scripts/ossemble <subcommand>`, or see
`python3 scripts/ossemble <subcommand> --help` for the authoritative
flags. Across every subcommand, exit 0 means done and clean, exit 1
means gaps, drift, a taken name or a failure (always one line on
stderr, never a traceback), and exit 2 is argparse's own for a bad
invocation.

| Subcommand | Arguments | Exit 1 means |
| --- | --- | --- |
| `audit [path] --json --api` | checks the repo against `rules/rules.json`, loaded from beside the script, never from the target | at least one failed default rule (a gap). `--api` also reads repo settings and the ruleset through `gh`. `--json` prints the same rows as objects |
| `scaffold [path] --set NAME --var KEY=VALUE --check` | stamps a named template set; idempotent, refuses symlinks | with `--check`, at least one file would change; without it, a file on disk differs from every version this manifest has ever stamped (drift), and nothing is written for that file |
| `name CANDIDATE... --json` | screens every candidate against every registry | at least one candidate is taken |
| `resume [path] --json` | environment check, stage, regressions, next step, from `.ossemble/state.json` and a live audit | a required tool is missing, the no-reply git identity is not set, or the state file failed to parse |
| `floor [path] --coverage-xml FILE` | raises `fail_under` in `pyproject.toml` to the achieved coverage, rounded down; never lowers it | the path is not a directory, a symlink was refused, or the coverage XML could not be read |

`audit`'s gap table is sorted by rule id, columns separated by two
spaces: `ID  KIND  STAGE  FILE  MESSAGE`. A `recommendation` rule that is
missing prints under a second heading, `Recommendations`, and never
changes the exit code. Only `name`, and `audit --api`, touch the
network; everything else is offline and deterministic (sorted output,
no timestamps, no absolute paths).

### The CI shape

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

### Pre-commit hooks

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

### Template sets and drift

`templates/manifest.json` lists every stampable file: its source path
under `templates/`, its destination in the target repo, the named set
it belongs to (`boot`, `finish`, and optional sets such as `scorecard`,
`codeql`, `coderabbit`, `dependabot-automerge`, `audit-deps`,
`ruleset`), an optional `when` condition, the `{{VAR}}` placeholders it
needs, optional defaults for those, and the rule ids it satisfies.
Stamp a set with:

```
python3 scripts/ossemble scaffold --set <name> --var KEY=VALUE
```

`scaffold` is idempotent: stamping the same set twice changes nothing.
Add `--check` first to see what would happen without writing anything.
For each destination file it reports one of: unchanged, create,
update, or drift. Drift means the file on disk does not match anything
this manifest has ever produced for that destination; `scaffold`
refuses to touch it and exits 1 rather than overwrite a hand edit.

### Badge recipes

These are recipes to fill in, not rendered images; nothing here embeds
one. Per `rules/rules.json` (`DOC-001`), a badge never appears before a
README's first heading.

```
https://img.shields.io/codecov/c/github/{owner}/{repo}
https://img.shields.io/github/license/{owner}/{repo}
```

### Rule schema

`rules/rules.json` is a list of objects sorted by `id`, each an
`ID-###` (a three-letter category prefix, a dash, three digits). The
fields: `text` (one sentence), `basis` (why the rule exists; a rule
with no basis does not ship), `category`, `kind` (`default`, which
applies without asking, or `recommendation`, which is offered with a
verdict), `stage` (`build` or `finish`, when it starts to bind),
`check` (`audit`, `api`, or `judgment`, meaning only a model or the
owner can tell), an optional `when` condition, and, when `check` is
`audit` or `api`, a `probe` naming the function in `audit.py` that
checks it. A rule already covered by a configured hook (pins, workflow
permissions, workflow syntax, secrets) gets a probe that only confirms
the hook is present and at its finish value; it does not re-implement
the hook's own check.

### State

`.ossemble/state.json`, gitignored, holds only what the repo itself
cannot answer: the scope sentence, the chosen distribution shape, opt-
ins, the prior-art outcome, owner-approved outward-facing steps,
temporarily lowered gates, the audit findings ledger, and a cache of
expensive model checks keyed to a commit and a file hash. `resume`
reads it, runs a live audit, reports the stage, any regression (a gap
absent at the recorded baseline but present now), any lowered gate
still below its finish value, and the next step; it then writes the
new baseline back. Whenever the state file and the repo disagree about
something the repo can answer for itself, the repo wins.
