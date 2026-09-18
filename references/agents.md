# Agent roster

Every role below has a prompt file under `agents/`; a role is added to the roster by adding a file, not by editing code. Output shapes here restate `references/contract.md` section 7 exactly; that file is the source of truth if the two ever drift.

| Role | Model | Tools | Input | Output |
| --- | --- | --- | --- | --- |
| Orchestrator | main session, one-line commands only | all, but runs almost none of them itself | the plan and `rules/rules.json` | owns the shared files, dispatches from the ownership map, arms auto-merge, records state |
| Scout | small fast model | read-only, web | one question | one fact per line, each with a link and the date read, or the words `not verified` |
| Builder | Sonnet | edit, own worktree only | the file ownership list, `references/contract.md`, the tests it must pass | a pull request plus a claim table (see Builder brief below) |
| Verifier | Sonnet | read-only | the diff and the builder's claims | each claim marked confirmed, refuted, or untestable, with line references |
| Judge | Sonnet | read-only | contradicting findings, or several name or design candidates, plus `rules/rules.json` | a decision that cites rule ids and states its measured basis |
| Auditor | Sonnet | read-only | the tree, and which audit (repo or CI) | at most fifteen findings, most severe first |
| Recoverer | small fast model | read-only | a dead agent's worktree | what was left behind, and the next step |

Model choice is the cheapest reliable one for the job: Sonnet for anything that writes code or prose a stranger will read, a small fast model for lookups, one-line edits and reading a leftover worktree. The orchestrator itself never edits a file; it only dispatches, merges and records.

The verifier is opt-in, not run on every builder PR. It runs only when the owner asks to read a pass before it merges, which is the default for README rewrites (`references/build-runbook.md` step 9) and otherwise only on explicit request. Everywhere else, CI is the verification and auto-merge is armed the moment the PR opens.

## Output shapes, in full

- **Builder**, at most 300 words: the pull request link, the files changed, counts before and after (tests, coverage, and words where docs changed), the exact verification commands run with each one's last line, and anything not done and why.
- **Scout**: one fact per line, each with a link and the date read, or the words `not verified`. A scout never states an opinion, only a cited fact or its absence.
- **Auditor**, at most fifteen findings, most severe first. Each finding is one line with these parts: severity, `confirmed` or `plausible`, `file:line`, the rule id if one applies, one sentence of what breaks, one sentence of the fix. `confirmed` means the auditor read the exact lines and can point to the break; `plausible` means the shape looks wrong but the auditor could not confirm it from the diff alone.
- **Judge**: a decision that names which finding or candidate wins, cites the rule id it turned on, and states the measured basis (a number, a citation, or the exact text of the rule), never "best practice" alone.
- **Recommendation** (used by the model at build-runbook step 10, not a separate agent role): the verdict first, one line, do it or skip it. Then at most 120 words: what it costs, what it gives, which steps only the owner can do, what would flip the answer, and the assumption the verdict rests on.

## Builder brief template

Every builder brief carries these parts, in this order:

1. The worktree command: `git -C "$MAIN" worktree add "$MAIN/.claude/worktrees/<name>" -b claude/<name> origin/main`, then `cd` into it and `uv sync`.
2. The files to read first: `references/contract.md`, the plan, and any prior-art notes the builder needs.
3. The files this builder owns and must not step outside, taken verbatim from the ownership map drawn at step 3.
4. The hard rules: public-clean history, no em dashes, standard library only, one commit, never `git add -A`, never bypass a hook, never edit a file it does not own.
5. The exact verification commands: `uv run pytest --cov --cov-report=term-missing` and `env -u GH_TOKEN -u GITHUB_TOKEN uv run pre-commit run --all-files`, both must pass before pushing.
6. The commit title (a plain present-tense sentence stating the resulting state) and the fixed co-author trailer.
7. The push command, plus the header-auth fallback for when the ambient token lacks the workflow scope (`references/hosts.md` has the exact form).
8. The pull request body headings: What changes, What does not change, How to undo, Checks run locally.
9. The auto-merge command: `gh pr merge --auto --rebase`, run the moment the PR opens.
10. The rebase-on-conflict instruction: when a shared file moved under this builder, `git fetch origin main && git rebase origin/main`, then force-push with `--force-with-lease`.
11. The word limit on the report: 300 words, matching the Builder output shape above.

A brief that leaves any of these eleven parts out is incomplete; the orchestrator fills the gap before dispatch, not the builder after the fact.
