# AGENTS.md

Run any subcommand as `python3 scripts/ossemble <subcommand>`, or add
`--help` for its authoritative flags. Exit 0 means done and clean,
exit 1 means gaps, drift, a taken name or a failure, and exit 2 is
argparse's own for a bad invocation. The full subcommand table and
what exit 1 means for each is in [references/cli.md](references/cli.md).

Reference: [CONTRIBUTING.md](CONTRIBUTING.md) holds the commands a
person runs by hand and how a change lands. The pages below are for an
agent, or for anyone wiring this repo into CI.

- **CI shape.** Three required jobs, the coverage floor ramp and the
  audit-deps workflow, in [references/ci-shape.md](references/ci-shape.md).
- **Pre-commit hooks.** What runs and why two env vars are unset, in
  [references/pre-commit.md](references/pre-commit.md).
- **Template sets.** Stamping, drift and the manifest fields, in
  [references/templates.md](references/templates.md).
- **Badge recipes.** Fill-in URLs for coverage and licence badges, in
  [references/badge-recipes.md](references/badge-recipes.md).
- **Rule schema.** The fields `rules/rules.json` expects, in
  [references/rule-schema.md](references/rule-schema.md).
- **State file.** What `.ossemble/state.json` holds and how `resume`
  uses it, in [references/state.md](references/state.md).
- **Agent roster.** The roles that run ossemble itself (orchestrator,
  builder, auditor and the rest), in [references/agents.md](references/agents.md).
