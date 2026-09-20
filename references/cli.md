# CLI usage

Run any subcommand as `python3 scripts/ossemble <subcommand>`, or see
`python3 scripts/ossemble <subcommand> --help` for the authoritative
flags. Across every subcommand, exit 0 means done and clean, exit 1
means gaps, drift, a taken name or a failure (always one line on
stderr, never a traceback), and exit 2 is argparse's own for a bad
invocation.

| Subcommand | Arguments | Exit 1 means |
| --- | --- | --- |
| `audit [path] --json --api` | checks the repo against `rules/rules.json`, loaded from beside the script, never from the target | at least one failed default rule (a gap). `--api` also reads repo settings, the ruleset and private vulnerability reporting through `gh`. `--json` prints the same rows as objects; with `--api` it nests them under `gaps`, alongside an `unverified` list naming any api-check rule id `gh` could not reach a verdict for |
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
