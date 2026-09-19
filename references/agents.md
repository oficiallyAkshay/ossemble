# Agent roster

Every role below has a prompt file under `agents/`; a role is added to the roster by adding a file, not by editing code. Output shapes for scout, builder and auditor are `references/contract.md` section 7, the source of truth; nothing here or in a role's own prompt file restates them. Judge, verifier and recoverer are not in the contract, since the script never parses their output; their shapes live only in their own prompt files under `agents/`.

| Role | Model | Tools | Input | Output |
| --- | --- | --- | --- | --- |
| Orchestrator | main session, one-line commands only | all, but runs almost none of them itself | the plan and `rules/rules.json` | owns the shared files, dispatches from the ownership map, arms auto-merge, records state |
| Scout | small fast model | read-only, web | one question | shape at contract.md section 7 |
| Builder | Sonnet | edit, own worktree only | the file ownership list, `references/contract.md`, the tests it must pass | shape at contract.md section 7 (see Builder brief below for what goes into its brief) |
| Verifier | Sonnet | read-only | the diff and the builder's claims | each claim marked confirmed, refuted, or untestable, with line references |
| Judge | Sonnet | read-only | contradicting findings, or several name or design candidates, plus `rules/rules.json` | a decision that cites rule ids and states its measured basis |
| Auditor | Sonnet | read-only | the tree, and which audit (repo or CI) | shape at contract.md section 7 |
| Recoverer | small fast model | read-only | a dead agent's worktree | what was left behind, and the next step |

Model choice is the cheapest reliable one for the job: Sonnet for anything that writes code or prose a stranger will read, a small fast model for lookups, one-line edits and reading a leftover worktree. The orchestrator itself never edits a file; it only dispatches, merges and records.

The verifier is opt-in, not run on every builder PR. It runs only when the owner asks to read a pass before it merges, which is the default for README rewrites (`references/build-runbook.md` step 9) and otherwise only on explicit request. Everywhere else, CI is the verification and auto-merge is armed the moment the PR opens.

## Builder brief template

Every builder brief carries these parts, in this order. Every path in it is absolute: subagents share one filesystem, and a relative path can resolve against the wrong subagent's working directory.

1. The worktree command: `git -C "$MAIN" worktree add "$MAIN/.claude/worktrees/<name>" -b claude/<name> origin/main`, then `cd` into it and `uv sync`.
2. The files to read first: `references/contract.md`, the plan, and any prior-art notes the builder needs.
3. The files this builder owns and must not step outside, taken verbatim from the ownership map drawn at step 3.
4. The hard rules: public-clean history, no em dashes, standard library only, one commit, never `git add -A`, never bypass a hook, never edit a file it does not own, never `git stash` (the container's stash stack is shared across every subagent in it). A shared test the orchestrator owns, such as `tests/test_main.py`, asserts only the interface (registration, help, exit codes); the builder should expect it to pass unchanged once a stub is replaced, never treat it as something to fight.
5. The exact verification commands: `uv run pytest --cov --cov-report=term-missing` and `env -u GH_TOKEN -u GITHUB_TOKEN uv run pre-commit run --all-files`, both must pass before pushing.
6. The commit title (a plain present-tense sentence stating the resulting state) and the fixed co-author trailer.
7. The push command, plus the header-auth fallback for when the ambient token lacks the workflow scope (`references/hosts.md` has the exact form).
8. The pull request body headings: What changes, What does not change, How to undo, Checks run locally.
9. The auto-merge command: `gh pr merge --auto --rebase`, run the moment the PR opens. When GitHub GraphQL is unavailable for the session (`references/hosts.md` has the REST replacements), the orchestrator opens the PR and arms auto-merge by REST instead; the brief then tells the builder to push and write the PR body to a file rather than open the PR itself.
10. The rebase-on-conflict instruction: when a shared file moved under this builder, `git fetch origin main && git rebase origin/main`, then force-push with `--force-with-lease`. The same two commands apply when the orchestrator relays a CI failure by message instead of the builder watching CI itself (GraphQL unavailable): amend the fix, rebase if asked, force-push with lease.
11. The word limit on the report: 300 words, matching the builder shape at contract.md section 7.

A brief that leaves any of these eleven parts out is incomplete; the orchestrator fills the gap before dispatch, not the builder after the fact.
