# State

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
