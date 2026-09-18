# Contributing

## Running the tests

```sh
make test      # pytest against tools/fake_jev.py: no network, no key, no git
make e2e       # installs the hook in a scratch repo and commits twice
make measure   # replays fixtures/answers over fixtures/corpus
```

Everything above runs offline. If a change makes a test reach the network or need a key, the
change is wrong.

Python 3.10 or newer, stdlib only. The hook ships under `language: python` with no
dependencies, so a new import from PyPI is a no. pytest comes from an ephemeral `uv` env and
is a dev tool, not a dependency.

## The fake

`tools/fake_jev.py` is a 70-line HTTP server that answers `/v1/systemone` from a JSON file
mapping question name to probability. Point the client at it with
`JEV_BASE_URL=http://127.0.0.1:<port>`; any non-empty bearer works. `tests/conftest.py`
starts one per session. To test a new answer shape, write a fixture file next to
`tools/fixtures.json` and pass it to the server.

Tests never read `fixtures/answers/`. That directory is for `make measure` only.

## Adding a corpus case

`fixtures/corpus/<id>.json` is one case:

```json
{"id": "real_042", "group": "real", "repo": "owner/name", "sha": "<full sha>",
 "license": "MIT", "message": "<the commit message>",
 "files": [{"path": "...", "status": "M", "added": 12, "removed": 3}],
 "hunks": [{"path": "...", "text": "@@ ..."}],
 "omitted": "", "more": "", "label": {"mismatch": false}}
```

Groups and their labels:

| group | label keys | what the number means |
|---|---|---|
| `real` | `mismatch` (always false) | a false alarm if we report a mismatch |
| `mismatch` | `mismatch`, `kind`, `catch_on` | caught if any finding in `catch_on` fires |
| `over_budget` | `mismatch`, `kind`, `catch_on` | must split into two or more chunks |
| `secret` | `secret`, `category` | correct if belt or noul agrees with `secret` |

`hunks` must already be `-U2`-trimmed and budget-degraded, because `make measure` rebuilds
the state from the case with no git and no network. `make fixtures` does that trimming when
it pulls a case from the GitHub API.

## The license rule for excerpts

Only MIT and Apache-2.0 sources. Both permit redistributing an excerpt with attribution, and
only hunks ship, never a whole file. Check before adding:

```sh
gh api repos/<owner>/<name> --jq .license.spdx_id
```

A `null` there means no license, which means the code cannot be redistributed at all, even as
a few lines. Every case adds a line to `fixtures/corpus/NOTICE` with repo, sha, SPDX id and
URL. If a repo relicenses, its cases come out, a replacement goes in, and the published n
changes with them.

Cases in the `secret` group are written here rather than copied, so they carry
`"repo": "jev-commit"` and no sha.

## Numbers

Every number in the README comes from `make measure`. Until an answer is recorded the slot
prints `__`, and `__` is what ships. A guessed number is worse than an empty slot.
