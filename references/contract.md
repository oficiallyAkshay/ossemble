# Contract

The interfaces every part of ossemble shares. Fixed before parallel builders start. A builder that needs a change here asks the orchestrator; nobody else edits this file.

## 1. Layout and ownership

One owner per path. Disjoint owners build in parallel.

| Path | Holds | Owner |
|---|---|---|
| `references/contract.md`, `pyproject.toml`, `.github/`, `.pre-commit-config.yaml`, `scripts/ossemble/__main__.py`, `tests/test_main.py` | shared interfaces and gates | orchestrator |
| `rules/rules.json`, `scripts/ossemble/audit.py`, `scripts/ossemble/floor.py`, `tests/test_audit.py`, `tests/test_floor.py`, `tests/test_rules.py` | rules and the audit | builder A |
| `templates/`, `scripts/ossemble/scaffold.py`, `tests/test_scaffold.py`, `examples/` | templates, the stamper, the synthetic example | builder B |
| `references/build-runbook.md`, `references/modify-runbook.md`, `references/agents.md`, `references/tools.md`, `references/hosts.md`, `agents/` | runbooks, roster, role prompts, tool table, host notes | builder C |
| `SKILL.md`, `scripts/ossemble/name.py`, `scripts/ossemble/resume.py`, `tests/test_name.py`, `tests/test_resume.py` | the skill entry, the name screen, resume | builder D |
| `README.md`, `CONTRIBUTING.md` | human docs, written at docs time | docs builder |
| `tests/eval/`, `tests/test_consumers.py`, `.github/workflows/consumers.yml` | the consumers eval: pinned public repos and their expected gap rows | eval builder |

A test the orchestrator owns asserts only the interface: that a subcommand is registered, answers `--help` under its own name and exits with the documented codes. It never asserts what a stub does, because the first real implementation replaces the stub and must not fail a shared test. (Found on the first self-build: three builders failed CI at once on one such assertion.)

## 2. The script

Run as `python3 scripts/ossemble <subcommand>`. Python 3.11 or newer, standard library only. Each subcommand is one module exposing `add_parser(subparsers)` and `run(args) -> int`.

| Subcommand | Arguments | Does |
|---|---|---|
| `audit` | `[path]` `--json` `--api` | checks the repo at `path` against ossemble's own `rules/rules.json`, loaded from beside the script and never from the target, and prints the gap table. Exposes `gaps(root, *, use_api=False) -> list[dict]` for `resume` |
| `floor` | `[path]` `--coverage-xml FILE` | raises `fail_under` to the achieved coverage, rounded down; never lowers it |
| `scaffold` | `[path]` `--set NAME` `--var KEY=VALUE` `--check` | stamps a template set; `--check` reports drift and writes nothing |
| `name` | `CANDIDATE...` `--json` | screens every candidate on every registry |
| `resume` | `[path]` `--json` | environment check, stage, regressions, next step |

Rules for every subcommand:
- Exit 0 means done and clean. Exit 1 means gaps, drift, a taken name, or a failure. Exit 2 is argparse's.
- A failure is one line on stderr and exit 1, never a traceback.
- Output is deterministic: sorted, no timestamps, no absolute paths.
- The network is touched only by `name`, and by `audit --api` through the `gh` CLI. Tests fake both.
- Nothing writes outside `path`. Symlinks are refused, not followed.

### Gap table

`audit` prints one row per failed rule, sorted by id, columns separated by two spaces: `ID  KIND  STAGE  FILE  MESSAGE`. With `--json` it prints a list of objects with the keys `id`, `kind`, `stage`, `file`, `message`; with `--json --api` it instead prints one object, `{"gaps": [...], "unverified": [...]}`, since only `--api` can leave an api-check rule's probe unable to reach a verdict (a `gh` that is missing, unauthenticated, or otherwise fails), and that rule's id then goes in `unverified` rather than becoming a false gap. A missing default is a gap and sets exit 1. A missing recommendation is printed under a second heading, `Recommendations`, and never changes the exit code.

## 3. Rules

`rules/rules.json` is a list of objects, sorted by `id`.

| Field | Type | Meaning |
|---|---|---|
| `id` | string | category prefix, a dash, three digits: `CI-001` |
| `text` | string | the rule in one sentence, as an agent should read it |
| `basis` | string | why: a measured fact, an incident, or a named source. A rule with no basis is a preference and does not ship |
| `category` | string | one of the prefixes below, spelled out |
| `kind` | `default` or `recommendation` | defaults apply without asking; recommendations are offered with a verdict |
| `stage` | `build` or `finish` | when the rule starts to bind |
| `check` | `audit`, `api` or `judgment` | read from files, read through the GitHub API, or only a model or the owner can tell |
| `when` | object, optional | conditions that make the rule apply: `public`, `shape`, `language`, `has_workflows` |
| `probe` | string, required when `check` is `audit` or `api` | the name of the function in `audit.py` that checks it |

Category prefixes: `SCP` scope, `PRC` process, `STR` structure and leanness, `TST` tests and failure, `HRD` hardening, `SET` repo settings, `CI` gates and CI, `REV` review, `DOC` README and brand, `PRV` privacy and history, `DST` distribution, `NO` the no-list.

Tests prove: ids are unique and sorted, every field validates, every `probe` exists in `audit.py`, every probe in `audit.py` is named by a rule, every rule id cited anywhere under `references/`, `agents/` or `SKILL.md` exists.

The audit does not redo what the gates already check. For anything a selected hook enforces (pins, workflow permissions, workflow syntax, secrets), the probe confirms the hook is configured and at its finish value, and stops there.

## 4. Gate stages

| Gate | Build stage, from boot | Finish stage, from tighten |
|---|---|---|
| Coverage floor | 70, raised to the achieved number after each wave | 100, line and branch |
| Changed-line coverage | off | 100 |
| Lint | formatter and the default rule set | every rule set, each ignore justified in a comment |
| Secrets scan, action pins, workflow lint | on | on |
| Selected tools from `references/tools.md` | off | on |
| CI interpreters | one on pull requests, the matrix on main | the matrix everywhere |

The stage is read from the repo, never stored: a repo is in the finish stage when its coverage floor is 100. The agent may lower a gate temporarily. It records the lowering in the state file, and `resume` reports the repo as not done until the gate is back at its finish value.

## 5. Templates

`templates/manifest.json` is a list of objects, sorted by `dest`.

| Field | Meaning |
|---|---|
| `src` | path under `templates/` |
| `dest` | path in the target repo |
| `set` | `boot`, `finish`, or the name of an optional part such as `scorecard` |
| `when` | same condition object as a rule |
| `vars` | names the template needs, filled as `{{NAME}}` and nothing else. No logic in templates |
| `defaults` | optional object: the value a var takes when `--var` does not supply it. Data, not logic. The boot `pyproject.toml` takes `COVERAGE_FLOOR` with default `70`, because the floor rises after every wave and a raised floor is not drift |
| `rules` | the rule ids this template satisfies |

`scaffold` is idempotent: stamping twice changes nothing. It never overwrites a file that differs from every version it has stamped; it reports drift and exits 1. Every template must pass its own gate once stamped, and `examples/` holds a synthetic repo that CI rebuilds byte for byte.

## 6. State

One file in the target repo, `.ossemble/state.json`, ignored by git. It holds only what cannot be read back from the repo. When state and repo disagree, the repo wins.

| Key | Holds |
|---|---|
| `scope` | the value sentence, the one user, the one output, the refusal list |
| `shapes` | the distribution shapes chosen, with the reason |
| `optins` | tokens and counters the owner opted into |
| `prior_art` | the outcome and the evidence links |
| `gos` | each outward-facing step the owner approved, with the date |
| `lowered` | gates lowered temporarily: gate, from, to, why |
| `findings` | the audit ledger: id, severity, confirmed or plausible, the fixing pull request |
| `checks` | for each expensive model check: the commit it ran at and a hash of the files it read. `checks.audit` also holds `gaps`, the rule ids that failed at that commit; a regression is a gap present now and absent there |

An expensive check is skipped when its commit and hash still match. `resume` reads this file, runs `audit.gaps`, and prints: the stage, the current gap count, every regression (a gap absent from `checks.audit.gaps` at the recorded commit and present now), any entry in `lowered`, and the next runbook step. It then writes the new baseline into `checks.audit`, the one write `resume` makes.

## 7. Agent outputs

Every role returns plain text in a fixed shape, so the orchestrator reads it without parsing prose.

- **Builder**, at most 300 words: the pull request link, files changed, counts before and after (tests, coverage, words where docs changed), the verification commands run with their last line, anything not done and why.
- **Scout**: one fact per line, each with a link and the date read, or the words `not verified`.
- **Auditor**, at most fifteen findings, most severe first. Each: `severity`, `confirmed` or `plausible`, `file:line`, the rule id if one applies, one sentence of what breaks, one sentence of the fix.
- **Recommendation**: the verdict first in one line, do it or skip it. Then at most 120 words: what it costs, what it gives, which steps only the owner can do, what would flip the answer, the assumption the verdict rests on.

### Builder brief

Every brief carries, in this order: the worktree command, the files to read first, the files the builder owns and must not step outside, the hard rules, the exact verification commands, the commit title and the trailer, the push command with its fallback, the pull request body headings, the auto-merge command, the instruction to rebase when main moves, and the word limit on the report.
