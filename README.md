# 🧩 ossemble

Assembles a finished open-source repo.

<!-- hero image: still image, 1280 by 640, added at the social preview step -->

<a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/license-MIT-2f6f4e"></a>
<a href="pyproject.toml"><img alt="Python 3.11 or newer" src="https://img.shields.io/badge/python-3.11%2B-3776AB"></a>
<a href="pyproject.toml"><img alt="zero runtime dependencies" src="https://img.shields.io/badge/dependencies-0-2f6f4e"></a>

ossemble builds a repo from a need, when none exists yet, and it hardens or finishes an existing repo, when one already does. Add this repository as a skill with the skills CLI. See [CONTRIBUTING](CONTRIBUTING.md) for the workflow YAML and command reference.

## Features

- 🚧 **Gates from day zero.** Secrets scanning, pinned actions and a coverage floor start at boot, not at the end.
- 📋 **Rules as data.** Every rule carries a basis: a measured fact, an incident or a named source.
- 🔍 **Audit by rule id.** Prints exactly which rule failed, where and why, sorted and machine readable.
- 🧵 **Parallel builders.** Work splits across an ownership map, so builders never touch the same file.
- ⏸️ **Resumable across sittings.** Reads the stage, any regression and the next step back from the repo itself.
- ✅ **Recommendations with a verdict.** Every optional part gets a do-it-or-skip-it answer before the cost and the catch.
- 📣 **Listing for discovery.** Registers a finished repo on the channels that fit its shape.
- 🛠️ **Your rules, your tools.** The rule set and the tool table are data you edit, not code you fork.

## Badges

This section will hold ossemble's own audit result and coverage as live badges, once a run against this repo gives a real endpoint to read.

<table width="100%">
  <tr>
    <th></th>
    <th align="center">this repo</th>
  </tr>
  <tr>
    <th align="left">Coverage</th>
    <td align="center">pending</td>
  </tr>
  <tr>
    <th align="left">Audit gaps</th>
    <td align="center">pending</td>
  </tr>
</table>

## Security

ossemble's own workflows use only the built-in `GITHUB_TOKEN` of the workflow they run in, read-only wherever GitHub allows it, and the skill itself uses no token unless the owner opts in.

ossemble never does any of the following without the owner's explicit go, where a go is possible at all:

- ❌ publishes a package
- ❌ tags a release
- ❌ installs an app
- ❌ changes a repository setting
- ❌ flips visibility
- ❌ sends telemetry
- ❌ stores a token
- ❌ rewrites history

## How it compares

| | [oficiallyAkshay/ossemble](https://github.com/oficiallyAkshay/ossemble) | [AnayDhawan/oss-launch](https://github.com/AnayDhawan/oss-launch) | [zeyuzhangzyz/open-source-hardening-skills](https://github.com/zeyuzhangzyz/open-source-hardening-skills) | [obra/superpowers](https://github.com/obra/superpowers) |
| --- | --- | --- | --- | --- |
| Shape | skill | skill | skill | skill |
| Gates from day zero | ✅ | ❌ | ❌ | unknown |
| Rules as data | ✅ | ✅ | ❌ | unknown |
| Audit by rule id | ✅ | ❌ | ❌ | unknown |
| Parallel builders | ✅ | ❌ | ❌ | ✅ |
| Resumable | ✅ | ❌ | ❌ | ❌ |
| Recommendations | ✅ | ✅ | ✅ | unknown |
| Hardening review | ✅ | ✅ | ✅ | ❌ |
| Auto-merge on open | ✅ | unknown | ❌ | ❌ |

## Callouts

- The coverage gate ramps: 70 while building, 100 at finish.
- The owner is stopped once before boot, at this README, at each recommendation and at the flip to public.
- A private repository is a legitimate outcome, and several recommendations hang on it.
- ossemble never tags a version unless asked.
- Needs Python 3.11 or newer, git, gh and uv on PATH; the script itself has no dependencies.
