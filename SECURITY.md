# Security

## Supported versions

The current `main` branch and the latest tag. Nothing older gets a fix.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository:
https://github.com/oficiallyAkshay/ossemble/security/advisories/new

Never open a public issue for a vulnerability. Expect an acknowledgement
within seven days.

## Scope

ossemble is a skill that reads and writes files in the repo it is
pointed at, then shells out to `git`, `gh`, and `uv` on the operator's
own machine, using whatever auth those tools already have. It does not
touch any repo other than the one it was pointed at.

- ✅ reads and writes files inside the target repo: scaffolding
  templates, running the audit, updating rule-driven config
- ✅ shells out to `git`, `gh`, and `uv` using the operator's existing
  credentials
- ✅ uses `GITHUB_TOKEN`, each workflow's own built-in copy, read-only
  wherever GitHub allows it
- ✅ the `name` subcommand makes unauthenticated, read-only lookups
  against the npm registry, PyPI, and the public GitHub API to check
  whether a candidate name is taken
- ❌ does not read, store, or transmit a credential itself; it only
  invokes tools that already hold their own auth
- ❌ does not publish a package, tag a release, install an app, change
  a repository setting, or flip visibility on its own
- ❌ does not send telemetry
- ❌ does not contact any service beyond `git`, `gh`, `uv`, and the
  three public lookups the `name` subcommand makes

If you find a way for ossemble to leak a credential, act on a repo it
was not pointed at, or push a change the owner did not approve, that is
a vulnerability report, not a bug report.
