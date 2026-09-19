# Modify runbook

Brings an existing repo up to the same bar. Read `references/contract.md` and `references/build-runbook.md` first: from step 3 onward, modify runs the identical build runbook, so this file only covers the front end that replaces build's steps 1 and 2.

```
+----------+    +-----------------+    +-----------------+    +---------+
| 0 RESUME | -> | AUDIT [script]  | -> | HISTORY HYGIENE | -> | RANK    |
|          |    | gap table       |    | emails, pinned  |    | by cost |
+----------+    +-----------------+    | consumers       |    | [model] |
                                       +-----------------+    +---------+
                                                                   |
                                                                   v
                                                                 3 MAP
```

Everything from 3 MAP down is `references/build-runbook.md` unchanged: the ownership map, the parallel builder wave, the lean-and-prove pass in delete-then-test-then-audit order, tightening, the repo and CI audits at step 7, one PR per confirmed finding at step 8 (PRC-007), docs, the recommendation table at step 10, the read-only final check at step 11, the public flip, listing and stop. The verifier role stays opt-in for README rewrites (PRC-004), and the judge role resolves conflicting findings, exactly as in the build runbook; nothing about parallelisation changes because the repo already existed.

## 0 Resume

Who decides: script. Same as build step 0: `python3 scripts/ossemble resume [path] --json` reads `.ossemble/state.json` if one exists, runs `audit`, and prints stage, regressions, and the next step. (PRC-005) Most modify runs start from no state file at all; resume then reports there is nothing to resume and the run proceeds to audit.

## Audit

Who decides: script.

```
python3 scripts/ossemble audit [path] --json
```

against `rules/rules.json` on the repo as it stands, before anything is touched. This gap table is kept: it becomes the opening half of the closing report, so the change this run made can be shown as a diff rather than restated. Scope, the prior-art outcome, and the name are not re-asked; they only run again if the audit or the repo shows none is recorded (no state file, no clue in the README or `SKILL.md`). (PRC-005)

## History hygiene

Who decides: script gathers facts, model reads them, before any rewrite is proposed.

Checked before touching anything: author emails across the full log (a personal address anywhere in `git log --format='%ae'` blocks a public flip later, and finding it now is cheaper than after a rewrite) (PRV-002), the repo's merge settings (rebase-only, squash and merge off, matching the ruleset this runbook expects) (SET-002), and any known consumer that pins this repo by commit hash, because a history rewrite moves those hashes out from under them. A finding here that only a rewrite can fix is recorded, not fixed immediately; it is ranked with everything else next. (PRV-003)

## Rank by cost

Who decides: model.

Every gap from the audit and every finding from history hygiene is ranked by cost to fix, not by category. The ranked list becomes the input to 3 MAP: it is what the ownership map in the build runbook is drawn against, in place of a fresh scope. A gap a spec line or an existing test already requires is not optional just because it ranks low. (STR-006)

## Closing report

Who decides: script computes the diff, model writes the sentence.

At the point the build runbook would stop (step 14), run the same audit again (REV-001):

```
python3 scripts/ossemble audit [path] --json
```

and report only the difference between this closing table and the opening one captured at the audit step above: what closed, what is still open and why, and what was newly found along the way. The report is the closing audit minus the opening one, not a restatement of everything the repo now passes.
