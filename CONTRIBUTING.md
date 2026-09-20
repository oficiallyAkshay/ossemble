# Contributing

This file is for a person making a change by hand. Dense reference for
an agent, or for anyone wiring this repo into CI, lives in
[AGENTS.md](AGENTS.md) at the repo root: the subcommand contract, exit
codes, CI shape, pre-commit hooks, template sets, badge recipes, the
rule schema and the state file.

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

A Dependabot pull request arms itself: `dependabot-auto-merge.yml`
(`.github/workflows/dependabot-auto-merge.yml`) runs `gh pr merge
--auto --rebase` for every pull request opened by `dependabot[bot]`, so
nobody has to click it by hand. The same `ci` check still gates the
merge either way.

### What to add where

- **A new rule.** Add an object to `rules/rules.json` (see the schema
  in [references/rule-schema.md](references/rule-schema.md)) and, if it
  is machine-checkable, a matching probe function in
  `scripts/ossemble/audit.py`.
- **A new template.** Add the file under `templates/`, then an entry in
  `templates/manifest.json` naming its destination, its set and the
  rules it satisfies.
- **A new agent role.** Add a prompt file under `agents/`. The roster is
  the directory listing; there is no separate registration step.

### Reporting a vulnerability

Open an issue. This repo has no private reporting channel, by design.
