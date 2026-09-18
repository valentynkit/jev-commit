# Changelog

Format from [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), versions follow SemVer.

## [Unreleased]

### Changed

- The report prints risk instead of the raw noul, so a long bar means a problem on every row.
  The two healthy-high checks are labeled and printed as their complement: "message is filler"
  and "contradicts the diff". A flagged row ends in `✗`, a dead-band row in `?`.
- Bars fill a cell at a time, 0.36 s for the five of them, `JEV_COMMIT_DEMO_PACE` to slow it
  down for a screen capture.

### Added

- `demo.mp4` for X and `demo/README.md` with the recording recipe. `make demo` records once
  and renders both sizes, Kanagawa palette, 72 columns so it stays legible on a phone.
- `docs/launch.md`: the X thread, the Show HN title and first comment, the r/git version and
  the awesome-list line, each with the measured numbers still unfilled.

### Fixed

- `git commit -a`, `--only`, `-p` and `git commit <path>` were judged against the wrong diff.
  The lockdown stripped `GIT_INDEX_FILE`, so the hook read `.git/index` rather than the
  temporary index git was committing, and took the amend path where the belt cannot block.
- The secret belt scanned only the hunks that survived the token budget, so a credential in a
  lockfile, a generated directory or a capped file's middle hunk was never checked.
- High-precision patterns matched mid-token (`risk-...` read as an OpenAI key) and ignored the
  rest of the line, so a documented example token blocked a commit.
- `strip_message` hardcoded `#`, mangling messages under `core.commentChar`.
- Non-ASCII paths were decoded as mojibake and kept their `a/`/`b/` prefix.
- Renames, mode changes and new empty files were dropped from the file table entirely.
- The per-file cap skipped files under three hunks and measured its fallback in characters
  against a token budget; the commit message was never capped.
- A `null` or truncated response body, and Ctrl-C during the call, exited nonzero and blocked
  the commit.
- Chunked commits had no request ceiling and one deadline each rather than one between them.
- `make measure` reported nothing at all when any single chunk was unrecorded.

## [0.1.0] - 2026-09-18

### Added

- `commit-msg` hook entry for the pre-commit framework, zero dependencies, Python stdlib only.
- Five pinned `jev-1.13.0` nouls over the message and the staged diff: message is substantive,
  message matches diff, debug leftovers, scope creep, secret shaped.
- Regex and entropy belt in front of the secret noul. The thirteen high-precision patterns
  block by default, the two high-recall ones only report.
- Git capture under the commit-miner lockdown: argv arrays, stripped `GIT_*`, no hooks path,
  no textconv, no external diff, no credential helper, no API key in the child environment.
- Per-file hunk chunking with a token budget, degrade-to-counts for lockfiles and generated
  files, and split-and-retry when the API says a request is too big.
- Animated stderr report with per-check bars, plain text under `NO_COLOR` or a non-TTY.
- `make measure` over the committed corpus, `make fixtures` to rebuild it.

[Unreleased]: https://github.com/valentynkit/jev-commit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/valentynkit/jev-commit/releases/tag/v0.1.0
