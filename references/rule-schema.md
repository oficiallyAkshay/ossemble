# Rule schema

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
