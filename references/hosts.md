# Host notes

GitHub facts and tooling quirks the model reads before touching a repo setting or a workflow. Every fact here was verified against a real repo; nothing in this file is a guess.

## GitHub facts

- Traffic rows (clones, views) arrive a day late; do not expect same-day numbers.
- Every CI job checkout counts as a clone. A day with about 20 merges produced 53 runs, 185 jobs and 528 clones with 153 uniques on one measured repo. If that count matters, offer one interpreter on pull requests and the full matrix only on main.
- View counts read zero while a repo is private.
- Uniques are reported per day and cannot be summed; no lifetime unique count exists from the traffic API.
- A newly public repo gets bot clones within a day; do not read early clone activity as real usage.
- A `uses:` reference in a workflow fetches the action as a tarball, which GitHub's traffic counter never sees. A depth-one git fetch of a public repo is counted and needs no token; an action that wants to be counted has to fetch itself by git, the way clonometer does.
- Inside a composite action, `github.action_repository` and `github.action_ref` on a nested step name the nested action, not the caller; read them through a bash step's `env:`, not by interpolating them into `run:` directly.
- Scheduled workflows are disabled after 60 days without a commit to the repo. A counter with a 14-day source window loses rows after a 13-day gap in commits. Dependabot auto-merge, once its gate conditions hold, keeps a repo's schedules alive past the 60-day cutoff; document that either way in the repo's own README.

## Tooling quirks

- Push workflow files with a header-auth fallback when the ambient token lacks the workflow scope:
  ```
  git -c credential.helper= -c "http.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "$(gh auth token)" | base64 | tr -d '\n')" push ...
  ```
  The gh OAuth token and a keychain credential do not always both carry the workflow scope; try the plain push first, fall back to this form on a scope error.
- A permission classifier blocks some ruleset and code-scanning writes made through `gh api`, and is not deterministic: retry the same API call once on the owner's explicit go, then fall back to the browser.
- GitHub's React settings pages (release, security, ruleset) accept `form_input` for checkboxes and selects, and a DOM `click()` for buttons; a browser tool driving them must verify the result by reading state back, never by trusting the click. An alert-dialog confirmation accepts neither form and needs a different path.
- A browser automation tool can go dark while any tab in its group sits on a site it cannot classify; close that tab and retry. The same tool can also disconnect transiently mid-batch; retry the same batch once before treating it as broken.
- A `language: system` pre-commit hook that names a virtualenv executable breaks a plain `git commit` outside that venv; wrap the hook in `uv run --no-sync` so a plain commit still works.

## Verified about install and listing channels

- `npx skills add` does a real `git clone` for any repository outside a four-owner allow list built into the skills CLI (read from its own source, `add.ts`, `git.ts`, `blob.ts`). This is why the skill row of the distribution-shape table in `references/build-runbook.md` counts as a good clonometer fit, not a guess.
- skills.sh auto-indexes public skill repos and ranks them by install count; nothing needs submitting for a skill to appear there.
- A Claude Code plugin marketplace is any repository that carries a `.claude-plugin/marketplace.json` file; the official and community marketplace listings additionally need review from the platform owner.
- SkillsMP and Skills Directory both auto-index public repositories on their own.
- Not yet verified by a scout: whether Context7, the various awesome lists, and the MCP registries are each free, reliable and actually used as listing channels. Do not list on any of these until a scout reports a citation for it; treat an unconfirmed channel the same as `not verified` in a scout's own output.

## Multi-sitting state

There is no single canonical pattern for resuming a multi-sitting build across the ecosystem. A local, git-ignored state file is the common shape; a tracking issue with a checklist is the alternative some projects use instead. ossemble uses the state file (`.ossemble/state.json`, described in `references/contract.md` section 6) because it can be read back by a script without hitting the network, which a tracking issue cannot.
