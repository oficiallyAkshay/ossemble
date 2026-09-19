# Build runbook

Builds a repo from a need. Read `references/contract.md` first: it names every path, subcommand and output shape this runbook uses. Rule ids are not cited here where the rules file does not exist yet; describe the rule in words and let a later pass wire the id.

```
+------------------------------------------------------------+
| 0 RESUME  (every sitting)  [script]                        |
|   environment check, stage read from the repo,             |
|   regressions, next step                                   |
+------------------------------------------------------------+
                               |
                               v
+------------------------------------------------------------+
| 1 DEFINE  [model]                                          |
|   scope: one job, one user, one output, refusal list,      |
|   shape(s), opt-ins: tokens, clonometer                    |
+------------------------------------------------------------+
                               |  scouts and name coining run together
       +---------------+-------+-------+---------------+
       |               |               |               |
+------------+  +------------+  +------------+  +------------+
|   haiku    |  |   haiku    |  |   haiku    |  | coin names |
|   GitHub   |  | npm, PyPI  |  |  skills,   |  |   script   |
|            |  |            |  |  actions   |  |  screens   |
+------------+  +------------+  +------------+  +------------+
       |               |               |               |
       +---------------+-------+-------+---------------+
                               |
                               v
+------------------------------------------------------------+
|   one question  [YOU confirm and pick]                     |
|   scope, prior-art outcome (use it | upstream the gap |    |
|   build the gap | build), the free names                   |
+------------------------------------------------------------+
                               |
                               v
+------------------------------------------------------------+
| 2 BOOT  [orchestrator alone]                               |
|   repo, identity, ruleset, auto-merge, contract file,      |
|   state file                                                |
+------------------------------------------------------------+
                               |
== BUILD GATES ON: secrets, pins, formatter, coverage 70 =====
                               |
                               v
+------------------------------------------------------------+
| 3 MAP  [model draws, script checks overlap]                |
|   who owns which files                                     |
+------------------------------------------------------------+
                               |  4 BUILD: count = the map
       +-----------+-----------+-----------+-----------+
       |           |           |           |           |
  +--------+  +--------+  +--------+  +--------+  +--------+
  | bldr A |  | bldr B |  | bldr C |  | bldr D |  |  ...   |
  |worktree|  |worktree|  |worktree|  |worktree|  |        |
  |   PR   |  |   PR   |  |   PR   |  |   PR   |  |        |
  +--------+  +--------+  +--------+  +--------+  +--------+
       |           |           |           |           |
       +-----------+-----------+-----------+-----------+
                               |
                               v
+------------------------------------------------------------+
|   after each wave  [CI, script]                             |
|   auto-merge on open, CI decides, tidy worktrees,           |
|   check main is green, raise coverage floor to achieved     |
+------------------------------------------------------------+
                               |  5 LEAN + PROVE: read-only, before tightening
          +--------------------+--------------------+
          |                    |                    |
 +-----------------+  +-----------------+  +-----------------+
 |     ponytail    |  |     live run    |  |   2nd consumer  |
 |      (code)     |  |                 |  |  if one exists  |
 +-----------------+  +-----------------+  +-----------------+
          |                    |                    |
          +--------------------+--------------------+
                               |
                               v
+------------------------------------------------------------+
|   cut  [model]                                              |
|   one PR per accepted cut; never test what is about to go   |
+------------------------------------------------------------+
                               |
                               v
+------------------------------------------------------------+
| 6 TIGHTEN  [model picks, script sets]                       |
|   pick tools from the reference table, thresholds to        |
|   finish values, parallel by owner from the same map        |
+------------------------------------------------------------+
                               |
== FINISH GATES ON: coverage 100, full lint, picked tools ====
                               |  7 REVIEW: read-only, on final code
               +---------------+---------------+
               |                               |
+----------------------------+  +----------------------------+
|         repo audit         |  |          CI audit           |
+----------------------------+  +----------------------------+
               |                               |
               +---------------+---------------+
                               |
                               v
+------------------------------------------------------------+
|   findings  [model]                                          |
|   confirmed or plausible, most severe first                  |
+------------------------------------------------------------+
                               |  8 FIX: one PR per confirmed finding
       +---------------+-------+-------+---------------+
       |               |               |               |
+------------+  +------------+  +------------+  +------------+
|   fix 1    |  |   fix 2    |  |   fix 3    |  |    ...     |
+------------+  +------------+  +------------+  +------------+
       |               |               |               |
       +---------------+-------+-------+---------------+
                               |
                               v
+------------------------------------------------------------+
| 9 DOCS  [YOU read the README]                                |
|   README by readmerlin, CONTRIBUTING, ponytail (docs)        |
+------------------------------------------------------------+
                               |
                               v
+------------------------------------------------------------+
| 10 RECOMMEND  [YOUR go, per item]                             |
|   optional parts, verdict first; never a version tag         |
+------------------------------------------------------------+
                               |  approved ones, parallel PRs
       +---------------+-------+-------+---------------+
       |               |               |               |
+------------+  +------------+  +------------+  +------------+
| Scorecard  |  |   CodeQL   |  | CodeRabbit |  |   badge,   |
|            |  |            |  |            |  |  preview   |
+------------+  +------------+  +------------+  +------------+
       |               |               |               |
       +---------------+-------+-------+---------------+
                               |
                               v
+------------------------------------------------------------+
| 11 FINAL CHECK  [model]                                      |
|   read-only, in parallel; audits read only what changed      |
|   since step 7; every gate back at its finish value           |
+------------------------------------------------------------+
                               |
       +---------------+-------+-------+---------------+
       |               |               |               |
+------------+  +------------+  +------------+  +------------+
| repo audit |  |  CI audit  |  |  live run  |  |  privacy   |
|            |  |            |  |            |  |   sweep    |
+------------+  +------------+  +------------+  +------------+
       |               |               |               |
       +---------------+-------+-------+---------------+
                               |
                               v
+------------------------------------------------------------+
|   done?  [model]                                              |
|   confirmed findings go back to 8; the agent judges           |
|   when it is done                                              |
+------------------------------------------------------------+
                               |
                               v
+------------------------------------------------------------+
| 12 PUBLIC  [YOUR go]                                          |
|   flip if private, switch on approved public-only parts       |
+------------------------------------------------------------+
                               |  13 LIST: by shape, one go for the batch
       +---------------+-------+-------+---------------+
       |               |               |               |
+------------+  +------------+  +------------+  +------------+
|   GitHub   |  |  awesome   |  |   plugin   |  | Context7,  |
|   topics   |  |  list PRs  |  |marketplace |  |MCP registry|
+------------+  +------------+  +------------+  +------------+
       |               |               |               |
       +---------------+-------+-------+---------------+
                               |
                               v
+------------------------------------------------------------+
| 14 STOP  [YOU]                                                |
|   one owner checklist (Marketplace tick, agreements,          |
|   passkeys), learnings, no-list, delete state, leave           |
+------------------------------------------------------------+
```

Nothing in this flow is a fixed count. The number of builders comes from the ownership map at step 3. The number of fix PRs comes from confirmed findings at step 7 and 11. (PRC-007) The loop from 11 back to 8 has no cap: the agent judges when the repo is done.

## Gate stages and temporary lowering

Every gate is wired at step 2 so it exists from day zero, then its threshold rises by stage. The stage is read from the repo, never stored: a repo is in the finish stage once its coverage floor reads 100. (PRC-005)

| Gate | Build stage, from step 2 | Finish stage, from step 6 |
| --- | --- | --- |
| Coverage floor | 70, raised to the achieved number after each wave (`python3 scripts/ossemble floor --coverage-xml coverage.xml`) (TST-001) | 100, line and branch (TST-002) |
| Changed-line coverage | off | 100 (CI-006) |
| Lint | formatter and the default rule set | every rule set, each ignore justified in a comment (HRD-009) |
| Secrets scan, action pins, workflow lint | on (HRD-007, HRD-005) | on |
| Selected tools from `references/tools.md` | off | on |
| CI interpreters | one on pull requests, the matrix on main | the matrix everywhere (CI-007) |

Day zero keeps only what is ruinous to add late: the no-reply identity, the secrets scan (late means a history rewrite), hash pins and empty top-level permissions (free from the boot template), the ruleset with the required `ci` check and auto-merge, and the formatter (late means a repo-wide diff that conflicts with every open PR). (PRV-001, HRD-007, HRD-005, HRD-001, CI-001)

The agent may lower a gate temporarily when that is the fastest honest path (for example, dropping the floor to land a builder PR that a later wave completes). It records the lowering in `.ossemble/state.json` under `lowered`: which gate, from what value, to what value, why. `resume` and the final check at step 11 both refuse to report the repo done until every entry in `lowered` is back at its finish value. (PRC-011)

## 0 Resume, every sitting

Who decides: script. A build spans sittings; nothing should redo checks unless something undid its work. (PRC-005)

Run `python3 scripts/ossemble resume [path] --json`. It reads `.ossemble/state.json` for what cannot be derived (scope, shapes, opt-ins, prior art, owner gos, lowered gates, the findings ledger), runs `audit` itself for everything the repo already shows, and prints three things: the stage, any regression (a rule that passed at the commit and file hashes recorded in `state.checks` but fails now), and the next runbook step. (PRC-006) Expensive model checks are keyed to a commit and a hash of the files they read; skip them again if both still match. When the state file and the repo disagree about anything derivable, the repo wins. (PRC-005)

The environment check inside `resume` includes the repo-local no-reply git identity: boot sets it once (step 2), and every later sitting must confirm it still holds before anything commits, because a cloud clone can carry a generic identity back in. (PRV-001)

## 1 Define, then the parallel scouts

Who decides: model, for the scope and shape; script, for the scout facts and the name screen.

The model writes one sentence of value, names the one user and the one output, and writes the refusal list before any file exists. (SCP-001, SCP-002) It also proposes the distribution shape (see the table below) and asks whether the owner opts in to a counting token or to clonometer.

While that draft sits, four things run together: three Haiku scouts (GitHub prior art, npm and PyPI registry facts, comparable skills and actions) and the name-coining pass. The model coins a batch of candidate names, then the script screens the whole batch in one call: `python3 scripts/ossemble name CANDIDATE_ONE CANDIDATE_TWO ... --json`. (SCP-006) Registries are checked first with no rate limit, then GitHub user, org, exact repo and Marketplace slug at 30 calls a minute. The owner only sees the names that came back free.

### Distribution-shape judgment

A judgment call, not a lookup, and sometimes the answer is more than one shape. (SCP-004)

| Trigger | Shape | clonometer fit |
| --- | --- | --- |
| A person in an agent chat | skill | good: `npx skills add` does a real git clone for any repo outside its four-owner allow list, verified in its own source | 
| Unattended with secrets or a schedule | action | weak: `uses:` fetches a tarball that traffic never counts, unless the action fetches itself by git the way clonometer does |
| A named person or program that installs and runs it | package | skip: the registry already publishes downloads |
| One consumer, or git-consumed | clone and pin a commit | best fit: the clone is the install |

readmerlin is a default at docs time regardless of shape. clonometer is never a fit for a counter and is only ever opt-in, asked here at scope, because its value depends on the shape above and counting only starts once something is installed. (SCP-004)

### Naming rules

- Coin a word, never pick an existing common one; a screened common word fails more often than a coined one. (SCP-006)
- Pun the domain word into the job, so the name is fun and understood at once.
- One lowercase word, no hyphen or underscore: a twin with one collides on npm and PyPI.
- Check every registry even when the current shape needs only one, in case the shape grows later. (SCP-006)
- Keep clear of the owner's other project names.
- Never rename after the first commit. (SCP-006)

## One question, before boot

Who decides: the owner, from a single message.

Everything from step 1 collapses into one ask: confirm the scope, pick a prior-art outcome (use the existing thing and stop, contribute the gap upstream, build only the gap, or build), and pick a name from the free list. (SCP-003) Nothing after this point revisits any of the three.

## 2 Boot

Who decides: orchestrator alone, no subagents.

Create the repo, set the repo-local no-reply git identity (before any commit, including the orchestrator's own) (PRV-001), write `references/contract.md` (the rules schema, template manifest and agent output shapes, fixed before any builder starts), write `.ossemble/state.json` (gitignored) with the scope, shape, opt-ins and prior-art outcome from the one question, and stamp the boot template set:

```
python3 scripts/ossemble scaffold --set boot --var NAME=<name> --var OWNER=<owner>
```

Write the ruleset as committed JSON and diff it against the live one with `gh api repos/{owner}/{repo}/rulesets`. Attempt the write through the API once; if a permission classifier blocks it (see `references/hosts.md`), do it in the browser instead and verify the result by reading the ruleset back, never by trusting the click. Turn on auto-merge and delete-branch-on-merge with `gh repo edit {owner}/{repo} --enable-auto-merge --enable-rebase-merge --delete-branch-on-merge`; squash and merge commits stay off. (SET-001, SET-002)

Once boot lands, the build-stage gates are on: identity, secrets scan, hash pins, empty top-level permissions, the ruleset with its required `ci` check, and the formatter. (PRV-001, HRD-007, HRD-005, HRD-001, CI-001)

The dispatcher test the orchestrator owns (`tests/test_main.py`, shared) asserts only the interface: every subcommand registers, `--help` works, exit codes are right. It never asserts a subcommand's behaviour. A behaviour assertion here fails every builder's first real implementation at once, because each stub started out passing it; a builder replacing a stub is expected to satisfy this test unchanged, not fight it.

## 3 Map

Who decides: model draws it, script checks it.

The model draws a table of path to owner, the same shape as `references/contract.md` section 1: one owner per path, disjoint owners run in parallel, shared files stay with the orchestrator. There is no dedicated subcommand for the overlap check yet; until one exists, the orchestrator reads the drawn table by hand and confirms no path appears under two owners before dispatch. The number of owners is whatever the map says, never a fixed count.

## 4 Build, one wave

Who decides: each builder, inside its own worktree; CI decides whether the PR is right.

Every disjoint owner from the map gets a worktree and a brief (see `references/agents.md` for the brief template). (PRC-001) Each builder:

```
git -C "$MAIN" worktree add "$MAIN/.claude/worktrees/<name>" -b claude/<name> origin/main
cd "$MAIN/.claude/worktrees/<name>" && uv sync
# edit only the owned paths
uv run pytest --cov --cov-report=term-missing
env -u GH_TOKEN -u GITHUB_TOKEN uv run pre-commit run --all-files
git add <path> <path>
git commit -m "<plain present-tense sentence>"
git push -u origin claude/<name>
gh pr create --title "<same sentence>" --body-file pr-body.md
gh pr merge --auto --rebase
```

Auto-merge is armed the moment the PR opens. (PRC-003) CI is the verification; there is no separate verifier pass at this step unless the owner asked to read one first, which they do for README rewrites at step 9. (PRC-004)

When GitHub GraphQL is unavailable for the session (`references/hosts.md` has the REST replacements), `gh pr create` and `gh pr merge --auto` fail: the orchestrator opens the PR and arms auto-merge by REST instead, and the builder pushes and writes the PR body to a file rather than opening the PR itself. A builder also cannot watch CI itself in that state; the orchestrator reads CI by REST and relays a failure to the builder by message. The builder amends the fix, rebases if the message asks for it, and force-pushes with `--force-with-lease`.

After the wave: CI decides each PR, worktrees for merged branches are tidied (`git worktree remove`, delete the local branch), main is checked green, and the coverage floor is raised to the number actually achieved with `python3 scripts/ossemble floor --coverage-xml coverage.xml`. (PRC-001, TST-001) Parallel PRs that touch the same file rebase; the brief for the later one says so. A PR whose base merged under it gets `--base main` by message, not a relaunch. A dropped builder is relaunched with the recoverer role in `references/agents.md`, instructed to check the leftovers first: `git status --short` in the worktree, an existing branch, an existing PR; continue rather than duplicate. A container restart kills every background builder, but worktrees and pushed branches survive it, which is why this check comes before any relaunch.

## 5 Lean, prove, cut

Who decides: model, from read-only evidence; the owner only if a cut needs saying twice.

The order here is fixed: delete, then test, then audit. Ponytail and the live run happen now, before step 6 tightens anything, so nobody writes a test for code that is about to be cut, and the two audits at step 7 read only the final, already-lean code. (STR-005)

Three things run in parallel, all read-only: the ponytail skill in report-only mode over the code (never wired into CI) (STR-005); a live run of the built thing end to end, because a claim is proved by a run, not by tests that can pass while the live path fails (REV-003); and, if a second consumer already exists, a check that it still works against this build.

A cut needs a measured number: no measured gain, it goes, even if it was asked for, with the number reported and an offer to reverse. (PRC-010) A cut that a spec line or a test import requires is rejected. (STR-006) Each accepted cut is its own PR, and nothing is tested that is about to be removed.

## 6 Tighten

Who decides: model picks which tools apply, script sets the thresholds.

The model reads `references/tools.md`, picks the tools that apply to what this repo actually contains (languages, workflows, shell files, dependencies detected), and the script raises every gate to its finish value in parallel, dispatched by the same ownership map used at step 4:

```
python3 scripts/ossemble scaffold --set finish
python3 scripts/ossemble scaffold --set <picked-tool> --check   # drift check first
python3 scripts/ossemble scaffold --set <picked-tool>
```

Once this lands, the finish-stage gates are on: coverage and changed-line coverage at 100, the full lint rule set with every ignore justified in a comment, and every picked tool enforced. (TST-002, CI-006, HRD-009)

## 7 Review

Who decides: auditor role, read-only, on final code; see `references/agents.md` for the output shape.

Two audits, always: a repo audit (efficiency, bugs, potential bugs, hygiene, structure, self-consistency across the README, contributing guide, code and tests, security, graceful failure) and a CI audit (efficiency, parallelism, consolidation, hygiene, structure, graceful failure). (REV-001) Each returns at most fifteen findings, most severe first, each marked confirmed or plausible. (REV-002)

```
python3 scripts/ossemble audit [path] --json
```

gives the machine-checkable half; the two audits add what only a model can judge.

## 8 Fix

Who decides: judge role resolves any conflicting findings; then one builder wave per confirmed finding.

Every confirmed finding gets its own PR, following the exact build-wave mechanics in step 4: worktree, tests that fail before the fix and pass after, the same verification commands, auto-merge on open. (PRC-007, TST-004) Plausible findings wait; they are not fixed until confirmed. A finding the judge cannot confirm from the diff alone stays plausible and is not fixed on that basis.

## 9 Docs

Who decides: readmerlin drafts and checks; the owner reads before merging.

The readmerlin skill drafts the README against the rendered repo as a stranger would see it, `readmerlin check` gates it in CI (already stamped at boot), and rounds converge over about three passes of numbered instructions before the owner merges on their word; this is the one place a verifier pass runs by default, because the owner said so for README rewrites. (PRC-004) CONTRIBUTING is written two-audience (short for people, dense for agents) at this step, and ponytail runs report-only a second time, now over docs. (STR-005)

## 10 Recommend

Who decides: the owner, item by item; the model states the case, never the mechanics, until the owner says go.

For every optional part, the model states a verdict first in one line, do it or skip it, then under 120 words: what it costs, what it gives (named or measured, never "best practice"), which steps only the owner can do, and what would flip the answer, plus the assumption the verdict rests on. (PRC-008) If the owner asked "should we X", the yes or no comes before anything else.

| Part | Do it when | Skip when |
| --- | --- | --- |
| Packaging (PyPI, npm) | someone names who runs `pip install` or `npx` and why (DST-001) | the product is consumed as a script, action or skill through git |
| Tagged release | anyone outside the repo pins it, or the owner asks (DST-002) | a single consumer pins commits instead |
| Marketplace listing | a GitHub action meant for other people (DST-003) | internal, single-consumer or experimental |
| OpenSSF Best Practices badge | public, meant for others, and Passing is honest today: tests, CI, licence, contribution guide, a one-line reporting process in the contributing guide (DST-004) | private, internal, experimental, or that one line is missing |
| OpenSSF Scorecard | any public repo, one workflow, expect a plateau near 8 and a 90-day wait for Maintained (CI-008) | staying private |
| CodeQL | public repo with code, free there (CI-009) | staying private, where it needs Advanced Security |
| CodeRabbit | public repo with a PR flow, advisory only, needs the owner's passkey (REV-004) | staying private, where it is paid |
| Dependabot auto-merge | coverage enforced at 100, a required CI check, and hash-pinned actions all hold (CI-010) | any of the three is missing; the owner merges Dependabot PRs by hand instead |
| Hero and social preview | the repo is meant to be found (DOC-007) | private or single-consumer; skip motion unless the owner asks for it |

No outward-facing step, meaning publish, accept an agreement, install an app, change a repo setting, or tag, starts without the owner's explicit go for that item. (PRC-009) Approved items become parallel PRs, one worktree each, using the mechanics named for each part in `references/tools.md`.

## 11 Final check

Who decides: model, read-only, in parallel.

Four things run at once: the repo audit and the CI audit, both reading only what changed since step 7, not the whole tree again (REV-001); a live run, proving the claims the README now makes (REV-003); and a privacy sweep of the tree, images, metadata and full history. The check does not pass while any gate in `.ossemble/state.json.lowered` is below its finish value. (PRC-011)

Confirmed findings from this pass go back to step 8. There is no fixed number of loops; the agent judges when the repo is done, not a counter.

## 12 Public

Who decides: the owner's go, one message, covering the flip and every approved public-only part together.

Flip visibility if the repo was private, then switch on whichever public-only optional parts were approved at step 10 and were waiting on this flip (Scorecard, CodeQL, CodeRabbit, the Best Practices badge). (SCP-005)

## 13 List

Who decides: script does the mechanical part, the owner's one go covers the whole batch, by shape.

ossemble registers the repo itself rather than only handing over a list. Always: GitHub topics and a pull request to a live awesome list if a scout has verified one fits. By shape: a plugin marketplace file for a Claude Code plugin marketplace, GitHub Marketplace for an action, an MCP registry entry for an MCP server, Context7 for anything with docs; skills.sh needs nothing submitted. (DST-005) `references/hosts.md` has the exact mechanics and verification status for every channel above; do not list on one it still marks `not verified`. What only the owner can do (a Marketplace developer agreement, a passkey) goes onto the step 14 checklist, not into this step. (PRC-009)

## 14 Stop

Who decides: the owner.

One checklist of every owner-only step deferred from steps 10, 12 and 13. (PRC-009) Record what was learned and what was refused, so neither is re-proposed next time. Delete `.ossemble/state.json` and leave the repo; a repo is done, not maintained.
