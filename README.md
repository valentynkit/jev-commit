# jev-commit

Your agent writes the code, then writes the commit message about the code. Nothing checks
that the two agree. This does, in one call to Jev, before the commit lands.

![jev-commit judging a commit whose message claims a null check while the diff also adds an endpoint and a print statement, then blocking a second commit that stages a private key](demo.gif)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/valentynkit/jev-commit
    rev: v0.1.0
    hooks:
      - id: jev-commit
```

```sh
pre-commit install --hook-type commit-msg
```

Four cents per thousand commits. It warns and gets out of the way. The one thing it stops is
a credential on an added line.

## What it checks

Five questions about the message and the staged diff together, in one request. A high number
is always the bad direction.

| check | flags when |
|---|---|
| message is filler | the message makes no checkable claim: `wip`, `fix`, `update`, a bare label |
| contradicts the diff | a claim in the message is not visible in the hunks it names |
| debug leftovers | a `print` added to trace execution, a commented-out block, a hardcoded localhost, a skipped test |
| unmentioned work | a path the message never names and does not imply |
| secret shaped | a credential value written out on an added line |

```
jev-commit · 2 files · +5 −0 · ~221 tokens · 1 request
jev-1.13.0 · 19 ms · $0.00001

  message is filler      █░░░░░░░░░░░  0.07
  contradicts the diff   █████████░░░  0.79  ✗
  debug leftovers        ███████████░  0.88  ✗
  unmentioned work       █████████░░░  0.76  ✗
  secret shaped          ░░░░░░░░░░░░  0.04

  3 findings, commit allowed
```

The message promised a null check. The diff added one, plus a new endpoint and a
`print("HERE")`. The commit still lands, because a warning you cannot ignore stops being a
warning and starts being an outage.

## Why Jev and not a chat model

Jev is TypeSafe's decision model. It does not write text, it answers typed questions with
calibrated probabilities, and every question in a call is judged in isolation against the
same state. That buys three things a text reviewer cannot give you: a number you can
threshold instead of a paragraph you have to parse, a cost that rounds to nothing because
output tokens are free, and an answer fast enough to sit in front of every commit rather
than a sample of them.

Code owns the thresholds, the counting, the entropy, the budget and the decision. Jev owns
five judgments and nothing else.

## What it costs

| | |
|---|---|
| per commit | $0.000044 at the median, $0.000207 at the mean |
| per thousand commits | about four cents |
| tokens | 1,048 input at the median over the 152-case corpus, 4,928 at the mean |
| requests | 1 for most commits, more when the diff does not fit one budget |
| price | $0.042 per million input tokens, output free |
| the hook itself, no model | 240 ms median, of which 21 ms is a loopback call (15 runs against the local fake, M-series Mac) |

Cost is arithmetic over the committed corpus at list price, not a billed figure. The last
row is the part people forget: a `commit-msg` hook is a fresh Python process every time, so
42 ms of interpreter, 117 ms of stdlib imports and about 60 ms of git, chunking and the belt
land before the request goes out.

The detection rate over the corpus is not published here yet. `make measure` prints it from
recorded answers, and this README carries the number once that has run against a real key.

## Install

The pre-commit snippet above, or a plain git hook:

```sh
pipx install git+https://github.com/valentynkit/jev-commit
printf '#!/bin/sh\nexec jev-commit "$1"\n' > .git/hooks/commit-msg
chmod +x .git/hooks/commit-msg
```

```sh
cp .env.example .env
```

| variable | required | purpose |
|---|---|---|
| `TYPESAFE_API_KEY` | required | the Jev key, read only by the hook, never handed to git |
| `JEV_API_KEY` | optional | alias for the same key |
| `JEV_BASE_URL` | optional | point at a local gateway shim instead of api.typesafe.ai |
| `NO_COLOR` | optional | plain text report, no color and no spinner |

## Use

```sh
git commit -m "fix: null check in parser"    # the hook runs, prints, and gets out of the way
jev-commit .git/COMMIT_EDITMSG               # run it by hand against the last message
jev-commit --strict .git/COMMIT_EDITMSG      # block on a finding, not only on a credential
jev-commit --exclude 'tests/fixtures/*' .git/COMMIT_EDITMSG
jev-commit --amend-base .git/COMMIT_EDITMSG  # compare against HEAD^ after `git add` then --amend
```

Exit codes: `0` nothing blocking, including every API failure. `20` a credential-shaped line,
or a finding past the threshold under `--strict`. `2` a usage error.

A line ending in `# jev-commit: allow` is skipped by the belt.

## How it works

1. Strip the message: comments out, everything past the scissors line out.
2. Pick the base. A clean index with a parent commit means an amend, which is judged against
   `HEAD^` and never blocks.
3. Two git calls, argv arrays under a lockdown borrowed from commit-miner: no hooks path, no
   textconv, no external diff, no credential helper, no `GIT_*` inherited, and no API key in
   the child environment, because the child reads bytes someone else wrote.
4. The belt scans added lines: thirteen high-precision credential patterns that block, two
   high-recall ones that only report.
5. Hunks are packed into states under a 24k token budget. Lockfiles, generated directories,
   minified files and binaries degrade to a row of counts. A file over its own cap keeps its
   first and last hunk.
6. One request per chunk, five nouls each, pinned to `jev-1.13.0`. A too-big response splits
   the chunk and retries. The gate question rides the first request only; the match answer
   combines by min and the three findings by max, so the worse answer always wins.
7. Every error path fails open. An API error, a timeout past 8 seconds, a missing key or a
   Ctrl-C exits 0 and lets the commit through.

## Known limits

- Needs `--hook-type commit-msg`. A plain `pre-commit install` will not run it.
- `pre-commit install` refuses while `core.hooksPath` is set, which is common on machines
  with a global hooks directory. Install the hook by hand there.
- Silent on merges, rebases, and `git commit --no-verify`. Git runs no `commit-msg` hook for
  the first two and skips hooks entirely for the third.
- `git add` then `git commit --amend` is byte-identical to a plain commit from inside the
  hook, so it judges the newly staged delta alone. `--amend-base` opts into `HEAD^`.
- `--amend-base` on a root commit has no `HEAD^` to use and falls back to the index.
- The 100-commit false-alarm set is labeled by assumption: every commit is taken to match its
  own message. The filter also picks small focused commits, so any rate measured on it is a
  floor, not a guarantee.
- A commit that does not fit one budget costs several requests, and several times the money.
- English only. Other languages are measurably weaker for the model, and untested here.
- Under the pre-commit framework the report is captured and replayed after the hook finishes,
  so there is no live spinner and no color. A plain git hook shows both.
- The belt is regex and entropy, so it blocks on credential *shapes*. A repo that commits
  real-format test keys or JWT fixtures wants `--exclude` on that path, or the trailing
  `# jev-commit: allow`.
- `git commit -a` and `git commit <path>` are judged correctly, but only because the hook
  reads the temporary index git hands it. Running `jev-commit` by hand outside a commit
  reads `.git/index` instead, which is the plain staged diff.

## Development

```sh
make test      # pytest against tools/fake_jev.py, no network, no key
make e2e       # install the hook in a scratch repo and commit twice
make measure   # replay fixtures/answers over fixtures/corpus and print the numbers
make fixtures  # rebuild the corpus from GitHub, then record answers (needs a key)
make demo      # re-record the clip, see demo/README.md
```

Python 3.10 or newer, stdlib only, no dependencies. `CONTRIBUTING.md` has the rest.

## License

MIT.
