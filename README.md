# jev-commit

Catches __ of 20 commit messages that do not match their diff, for four cents per thousand
commits and one Jev call each.

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

![demo](demo.gif)

## Why

A commit message is the only part of a change nothing checks. Linters read the code, CI runs
the tests, and the sentence claiming what you did goes straight into the history unread. Six
months later that sentence is the only thing anyone reads.

jev-commit reads the message and the staged diff together and asks five questions about the
pair in one call to Jev, TypeSafe's decision model: is this message substantive, does it
match the diff, are there debug leftovers, is there work the message never mentions, and is
a credential written out on an added line. Answers come back as probabilities, priced at
$0.042 per million input tokens with output free. What that works out to per commit, and how
long it takes, is what `make measure` prints; the slots above stay `__` until it has run.

It warns, it does not stand in your way. The only thing that stops a commit by default is a
regex belt hit on a credential shaped like a real one, because that is the mistake you
cannot take back. Everything else prints a bar and lets the commit land.

The honest limit, up front: the false-alarm number comes from 100 real commits labeled as
matching their own messages, and the filter that picked them favors small focused commits.
That makes the rate a floor, not a guarantee.

## Cost

| | |
|---|---|
| per commit | $0.000044 at the median, $0.000207 at the mean (1,048 and 4,928 input tokens over the 152-case corpus, priced at list, not billed) |
| per thousand commits | about four cents |
| p50 latency, the Jev call | __ ms |
| the hook itself, no model | 240 ms median, of which 21 ms is a loopback call (15 runs against the local fake, M-series Mac) |
| requests | 1 for most commits, more when the diff does not fit one budget |
| price | $0.042 per million input tokens, output free |

The second row is the honest half of the first: a commit-msg hook is a fresh Python process
every time, so 42 ms of interpreter, 117 ms of stdlib imports and about 60 ms of git,
chunking and the belt land before the request goes out. Expect roughly half a second per
commit end to end, most of it not the model.

## Install

With the pre-commit framework, using the snippet above, or as a plain git hook:

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
7. Code owns the thresholds, the counting, the entropy, the budget and the decision. Jev owns
   the five judgments and nothing else.

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
  own message. The filter also picks small focused commits, so the rate is a floor.
- A commit that does not fit one budget costs several requests, and several times the money.
- English only. Other languages are measurably weaker for the model, and untested here.
- The config-shaped secret set is written in this repo, not the incumbent's, because theirs
  carries no license. The comparison against their 15/20 is indicative, not like for like.
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
make demo      # re-record demo.gif with asciinema and agg
```

## License

MIT.
