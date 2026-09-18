"""The hook entry point: capture, chunk, belt, ask, report, decide.

Exit codes are semdecide's contract (cli.py:17-21) minus its uncertain state, which has no
consumer here: 0 nothing blocking, 20 a high-precision belt hit or a --strict finding, 2 a
usage error. pre-commit aborts the commit on any nonzero exit, so every API failure, every
timeout and every parse error lands on 0 with one dim line.
"""

import argparse
import json
import os
import pathlib
import sys
import time

from jev_commit import belt, chunk, git, jev
from jev_commit.questions import (FINDINGS, LABELS, MESSAGE_IS_SUBSTANTIVE,
                                  MESSAGE_MATCHES_DIFF, MODEL, QUESTIONS)
from jev_commit.report import Report, cost_of, status_of

OK, BLOCK, USAGE = 0, 20, 2

# Starting points. The sweep in measure.py writes the measured values to
# fixtures/thresholds.json, which wins when it exists.
DEFAULTS = {"substantive": 0.50, "mismatch": 0.30, "finding": 0.70, "strict": 0.85}
THRESHOLDS_FILE = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "thresholds.json"


def thresholds():
    out = dict(DEFAULTS)
    try:
        out.update({k: v for k, v in json.loads(THRESHOLDS_FILE.read_text()).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return out


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="jev-commit", add_help=True,
                                     description="Judge a commit message against its staged diff.")
    parser.add_argument("message_file", nargs="?", help="the file git wrote the message to")
    parser.add_argument("--strict", action="store_true",
                        help="block on a finding past the measured threshold, not only on a belt hit")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                        help="skip the belt on paths matching this glob, repeatable")
    parser.add_argument("--amend-base", action="store_true",
                        help="compare against HEAD^ instead of the index, for `git add` then --amend")
    return parser.parse_args(argv)


def combine_answers(acc, answers):
    """The worse answer wins: the gate as answered, the match by min, the findings by max."""
    for name, probability in answers.items():
        if name == MESSAGE_IS_SUBSTANTIVE:
            acc[name] = probability
        elif name in FINDINGS:
            acc[name] = max(acc.get(name, 0.0), probability)
        else:
            acc[name] = min(acc.get(name, 1.0), probability)
    return acc


# Splitting a state in two on every too-big response walks a binary tree, so a commit of
# thousands of hunks can cost 2n-1 requests. No commit is worth that much of the budget.
MAX_REQUESTS = 24


def judge(states, env, gate_wanted=True, deadline_s=jev.DEADLINE_S):
    """One request per chunk, split and retried on a too-big response.

    Routing: the gate question rides the first request only, the match question combines by
    min and the three findings by max. The worse answer wins in every direction.

    One deadline covers the whole call, not one per chunk: ten chunks against a slow but
    living API took ten times the budget while git held the terminal. Whatever came back
    before the deadline is returned, because a chunk already answered may already hold the
    finding, and it was already paid for.
    """
    combined, usage, requests, ms = {}, 0, 0, 0
    model = MODEL
    error = None
    gate_asked = not gate_wanted
    stop = time.monotonic() + deadline_s
    queue = [(i == 0, state) for i, state in enumerate(states)]
    while queue:
        first, state = queue.pop(0)
        asking = dict(QUESTIONS)
        if gate_asked or not first:
            asking.pop(MESSAGE_IS_SUBSTANTIVE)
        left = stop - time.monotonic()
        if requests >= MAX_REQUESTS:
            error = jev.JevError("stopped after %d requests" % requests)
            break
        if left <= 0:
            error = jev.JevError("deadline reached with %d chunks unasked" % (len(queue) + 1))
            break
        try:
            out = jev.ask(state, asking, env=env, deadline_s=left)
        except jev.TooBig as err:
            halves = chunk.bisect(state)
            if not halves:
                error = err
                break
            queue = [(first, half) for half in halves] + queue
            continue
        except jev.JevError as err:
            error = err
            break
        requests += 1
        ms += out["ms"]
        usage += out["usage"].get("input_tokens") or 0
        model = out["model"]
        if MESSAGE_IS_SUBSTANTIVE in out["answers"]:
            gate_asked = True
        combine_answers(combined, out["answers"])
    return {"answers": combined, "model": model, "ms": ms, "requests": requests,
            "usage": {"input_tokens": usage}, "error": error}


def decide(answers, hits, limits, strict=False, blocking_allowed=True):
    """(exit code, findings, rows). Jev only makes this stricter: a low noul never clears a belt hit."""
    rows, findings = [], []
    gate = answers.get(MESSAGE_IS_SUBSTANTIVE)
    substantive = gate is None or gate >= limits["substantive"]
    for name in (MESSAGE_IS_SUBSTANTIVE, MESSAGE_MATCHES_DIFF) + FINDINGS:
        if name not in answers:
            continue
        probability = answers[name]
        # The match bar reads off the mismatch cutoff, not the finding one. They are two
        # separate keys in thresholds.json, so a swept mismatch cutoff would otherwise
        # paint a red bar beside a verdict that says clean.
        healthy_high = name not in FINDINGS
        at = 1 - limits["mismatch"] if name == MESSAGE_MATCHES_DIFF else limits["finding"]
        status = status_of(probability, at, healthy_high=healthy_high)
        if name == MESSAGE_MATCHES_DIFF:
            if not substantive:
                status = "ok"
            elif probability <= limits["mismatch"]:
                status = "flag"
                findings.append(name)
        elif name in FINDINGS:
            if probability >= limits["finding"]:
                findings.append(name)
        elif name == MESSAGE_IS_SUBSTANTIVE:
            status = "ok" if substantive else "warn"
        rows.append((LABELS[name], probability, status))
    blockers = belt.blocking(hits)
    code = OK
    if blockers and blocking_allowed:
        code = BLOCK
    elif strict and blocking_allowed:
        strict_hit = (substantive and answers.get(MESSAGE_MATCHES_DIFF, 1.0) <= 1 - limits["strict"]) or any(
            answers.get(name, 0.0) >= limits["strict"] for name in FINDINGS)
        if strict_hit:
            code = BLOCK
    return code, findings, rows


def main(argv=None):
    """Never nonzero but on a usage error: pre-commit aborts the commit on any of them.

    Anything unexpected below, a malformed patch, a gateway answering `null`, a Ctrl-C
    during the call, is this tool's problem and not the committer's.
    """
    try:
        return _run(argv)
    except SystemExit:
        raise
    except BaseException as err:  # a hook that raises is a hook that blocks
        sys.stderr.write("jev-commit: skipped (%s: %s)\n" % (type(err).__name__, err))
        return OK


def _run(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = Report()
    if not args.message_file:
        report.line("usage: jev-commit <message-file>")
        return USAGE
    try:
        raw = pathlib.Path(args.message_file).read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        report.line("jev-commit: cannot read %s (%s)" % (args.message_file, err))
        return USAGE

    limits = thresholds()
    env = dict(os.environ)
    try:
        message = git.strip_message(raw, git.comment_prefix())
        captured = git.capture(amend_base=args.amend_base)
    except git.GitError as err:
        report.skipped(str(err))
        return OK
    if not captured["patch"].strip():
        report.skipped("nothing staged")
        return OK

    prep = chunk.prepare(captured["patch"], git.parse_name_status(captured["name_status"]))
    states = chunk.chunk_states(message, prep)
    # The belt reads the whole diff, never only the part that survived the token budget.
    hits = belt.scan(prep["all_hunks"], exclude=args.exclude)
    amend = captured["mode"] == "amend"

    added = sum(row["added"] for row in prep["files"])
    removed = sum(row["removed"] for row in prep["files"])
    tokens = sum(chunk.estimate_tokens(repr(state)) for state in states)
    report.header(len(prep["files"]), added, removed, tokens, len(states))
    report.asking(MODEL)
    try:
        out = judge(states, env)
    finally:
        report.stop_spinner()

    if not out["requests"]:
        report.skipped(str(out["error"]) if out["error"] else "no answers")
        return _belt_only(report, hits, amend)
    report.resolved(out["model"], out["ms"], cost_of(out["usage"]))

    code, findings, rows = decide(out["answers"], hits, limits, strict=args.strict,
                                  blocking_allowed=not amend)
    for label, probability, status in rows:
        report.check(label, probability, status)
    for hit in hits:
        if hit["precision"] == "high":
            report.blocked_line(hit["kind"], hit["path"], hit["redacted"])
        else:
            report.note("possible %s in %s (%s)"
                        % (hit["kind"].replace("_", " "), hit["path"], hit["redacted"]))
    if out["error"]:
        report.note("answered %d of %d chunks, then stopped: %s"
                    % (out["requests"], len(states), out["error"]))
    elif out["requests"] != len(states):
        report.note("split into %d requests after a too-big response" % out["requests"])
    if amend:
        report.note("nothing staged, judged against HEAD^, never blocking")
    if captured["truncated"]:
        report.note("diff truncated at %d MB, the rest was not judged"
                    % (git.MAX_BYTES // (1024 * 1024)))
    if prep["omitted"]:
        report.note(prep["omitted"])

    if code == BLOCK:
        report.verdict("blocked, a credential-shaped line is staged" if belt.blocking(hits)
                       else "blocked by --strict", "flag")
    else:
        report.verdict(_tally(findings, hits) or "clean, nothing to flag",
                       "warn" if findings or hits else "ok")
    return code


def _tally(findings, hits):
    """One clause per thing the report printed, so the count matches what is on screen."""
    parts = []
    if findings:
        parts.append("%d finding%s" % (len(findings), "" if len(findings) == 1 else "s"))
    if hits:
        parts.append("%d credential-shaped line%s" % (len(hits), "" if len(hits) == 1 else "s"))
    return " and ".join(parts) + ", commit allowed" if parts else ""


def _belt_only(report, hits, amend):
    """Jev is unreachable, so the belt is all there is. It still blocks."""
    blockers = belt.blocking(hits)
    for hit in blockers:
        report.blocked_line(hit["kind"], hit["path"], hit["redacted"])
    if blockers and not amend:
        report.verdict("blocked, a credential-shaped line is staged", "flag")
        return BLOCK
    if blockers:
        report.note("nothing staged, judged against HEAD^, never blocking")
    return OK


if __name__ == "__main__":
    sys.exit(main())
