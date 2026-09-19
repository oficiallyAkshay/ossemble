# Template sets and drift

`templates/manifest.json` lists every stampable file: its source path
under `templates/`, its destination in the target repo, the named set
it belongs to (`boot`, `finish`, and optional sets such as `scorecard`,
`codeql`, `coderabbit`, `dependabot-automerge`, `audit-deps`,
`ruleset`), an optional `when` condition, the `{{VAR}}` placeholders it
needs, optional defaults for those, and the rule ids it satisfies.
Stamp a set with:

```
python3 scripts/ossemble scaffold --set <name> --var KEY=VALUE
```

`scaffold` is idempotent: stamping the same set twice changes nothing.
Add `--check` first to see what would happen without writing anything.
For each destination file it reports one of: unchanged, create,
update, or drift. Drift means the file on disk does not match anything
this manifest has ever produced for that destination; `scaffold`
refuses to touch it and exits 1 rather than overwrite a hand edit.
