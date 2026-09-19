"""make measure: replay the recorded answers over the committed corpus.

Everything it reads is committed: fixtures/corpus/*.json holds the states, and
fixtures/answers/ holds one file per recorded request, keyed by sha256(state+questions).
No git, no network, no key. Until answers exist every number prints as __, because a
guessed number is worse than an empty slot.

Calibration is vendored from the API notes: Brier score, reliability bins and a
threshold sweep. The published thresholds come from that sweep, never from a guess.
"""

import argparse
import json
import pathlib
import statistics
import sys

from jev_commit import belt, cli
from jev_commit.questions import MESSAGE_MATCHES_DIFF, SCOPE_CREEP, SECRET_SHAPED
from jev_commit.record import ANSWERS, answer_key, load_corpus, states_for
from jev_commit.questions import QUESTIONS

ROOT = pathlib.Path(__file__).resolve().parent.parent
THRESHOLDS = ROOT / "fixtures" / "thresholds.json"
MEASURE_JSON = ROOT / "measure.json"
SLOT = "__"
FOOTNOTE = "via Vercel AI Gateway shim, re-measure on the direct API before pinning jev-1.13.0"


def brier(probabilities, labels):
    return sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / len(probabilities)


def reliability_bins(probabilities, labels, n=10):
    bins = [[] for _ in range(n)]
    for p, y in zip(probabilities, labels):
        bins[min(int(p * n), n - 1)].append((p, y))
    return [{"predicted": sum(p for p, _ in b) / len(b), "actual": sum(y for _, y in b) / len(b),
             "count": len(b)} for b in bins if b]


def threshold_sweep(probabilities, labels, cutoffs=(0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)):
    """For the mismatch cutoff: how many mismatches a cutoff catches, and what it costs."""
    rows = []
    for cutoff in cutoffs:
        caught = sum(1 for p, y in zip(probabilities, labels) if y and p <= cutoff)
        false = sum(1 for p, y in zip(probabilities, labels) if not y and p <= cutoff)
        positives = sum(labels)
        negatives = len(labels) - positives
        rows.append({"cutoff": cutoff, "caught": caught, "of": positives, "false_alarms": false,
                     "of_clean": negatives,
                     "precision": caught / (caught + false) if caught + false else 0.0})
    return rows


def replay(case):
    """Combined answers for one case, or None when a chunk was never recorded."""
    combined, ms, tokens = {}, 0, 0
    model = ""
    for index, state in enumerate(states_for(case)):
        questions = dict(QUESTIONS)
        if index > 0:
            questions.pop("message_is_substantive")
        path = ANSWERS / (answer_key(state, questions) + ".json")
        if not path.exists():
            return None
        recorded = json.loads(path.read_text())
        cli.combine_answers(combined, recorded["answers"])
        ms += recorded.get("ms") or 0
        tokens += (recorded.get("usage") or {}).get("input_tokens") or 0
        model = recorded.get("model") or model
    return {"answers": combined, "ms": ms, "tokens": tokens, "model": model,
            "chunks": len(states_for(case))}


def evaluate(limits):
    """Only the cases that were actually recorded. A rate-limited recorder leaves gaps, and
    one gap erasing all 152 numbers is worse than publishing the n that was measured."""
    cases = load_corpus()
    results = {}
    for case in cases:
        played = replay(case)
        if played is None:
            continue
        hits = belt.scan(case["hunks"])
        code, findings, _ = cli.decide(played["answers"], hits, limits)
        results[case["id"]] = {"case": case, "played": played, "findings": findings,
                               "code": code, "belt": belt.blocking(hits)}
    return (results or None), cases


def numbers(results, limits):
    mismatch = [r for r in results.values() if r["case"]["group"] == "mismatch"]
    caught = sum(1 for r in mismatch
                 if set(r["findings"]) & set(r["case"]["label"].get("catch_on", [])))
    real = [r for r in results.values() if r["case"]["group"] == "real"]
    false_alarms = sum(1 for r in real if MESSAGE_MATCHES_DIFF in r["findings"])
    over = [r for r in results.values() if r["case"]["group"] == "over_budget"]
    split_false = sum(1 for r in over
                      if not r["case"]["label"].get("mismatch") and MESSAGE_MATCHES_DIFF in r["findings"])
    secret = [r for r in results.values() if r["case"]["group"] == "secret"]
    correct = 0
    for r in secret:
        predicted = bool(r["belt"]) or r["played"]["answers"].get(SECRET_SHAPED, 0.0) >= limits["finding"]
        correct += int(predicted == bool(r["case"]["label"]["secret"]))
    latencies = sorted(r["played"]["ms"] for r in results.values())
    costs = [r["played"]["tokens"] * 0.042 / 1_000_000 for r in results.values()]
    return {
        "mismatches_caught": caught, "mismatches": len(mismatch),
        "false_alarms": false_alarms, "real": len(real),
        "split_false_alarms": split_false, "over_budget": len(over),
        "secret_correct": correct, "secret": len(secret),
        "p50_ms": int(statistics.median(latencies)) if latencies else 0,
        "cost_per_commit": sum(costs) / len(costs) if costs else 0.0,
        "n": len(results),
    }


def lines(stats, model):
    if stats is None:
        return [
            "%s/20 message/diff mismatches caught (n=20 crafted mismatches, %s)" % (SLOT, model),
            "%s false alarms (n=100 real MIT commits), %s on the split path (n=12 over-budget)" % (SLOT, SLOT),
            "config-shaped secrets %s/20 correct (n=20, belt + noul; noul-only incumbent 15/20 on its own set)" % SLOT,
            "%s ms p50, $%s per commit (n=152)" % (SLOT, SLOT),
        ]
    return [
        "%d/%d message/diff mismatches caught (n=%d crafted mismatches, %s)" % (
            stats["mismatches_caught"], stats["mismatches"], stats["mismatches"], model),
        "%d false alarms (n=%d real MIT commits), %d on the split path (n=%d over-budget)" % (
            stats["false_alarms"], stats["real"], stats["split_false_alarms"], stats["over_budget"]),
        "config-shaped secrets %d/%d correct (n=%d, belt + noul; noul-only incumbent 15/20 on its own set)" % (
            stats["secret_correct"], stats["secret"], stats["secret"]),
        "%d ms p50, $%.5f per commit (n=%d)" % (stats["p50_ms"], stats["cost_per_commit"], stats["n"]),
    ]


def sweep_inputs(results):
    probabilities, labels = [], []
    for r in results.values():
        if r["case"]["group"] not in ("mismatch", "real", "over_budget"):
            continue
        probabilities.append(r["played"]["answers"].get(MESSAGE_MATCHES_DIFF, 1.0))
        labels.append(1 if r["case"]["label"].get("mismatch") else 0)
    return probabilities, labels


def pick_cutoff(sweep):
    """The widest cutoff whose precision holds at 0.9, else the tightest one measured."""
    good = [row for row in sweep if row["precision"] >= 0.9 and row["caught"]]
    return max(good, key=lambda row: row["cutoff"])["cutoff"] if good else sweep[0]["cutoff"]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="make measure")
    parser.add_argument("--lock", action="store_true", help="write the measured numbers as the gate")
    args = parser.parse_args(argv)

    limits = cli.thresholds()
    results, cases = evaluate(limits)
    model = "jev-1.13.0"
    if results is None:
        for line in lines(None, model):
            print(line)
        print("no recorded answers, unlocked, no gate")
        MEASURE_JSON.write_text(json.dumps({"recorded": False, "cases": len(cases)}, indent=1) + "\n")
        return 0

    probabilities, labels = sweep_inputs(results)
    sweep = threshold_sweep(probabilities, labels)
    cutoff = pick_cutoff(sweep)
    if args.lock:
        limits = dict(limits, mismatch=cutoff)
        results, _ = evaluate(limits)
    stats = numbers(results, limits)
    model = next(iter(results.values()))["played"].get("model") or model
    if len(results) != len(cases):
        print("measured %d of %d cases, the rest were never recorded"
              % (len(results), len(cases)), file=sys.stderr)
    out = lines(stats, model)
    for line in out:
        print(line)
    print(FOOTNOTE)

    locked = {}
    if THRESHOLDS.exists():
        try:
            locked = json.loads(THRESHOLDS.read_text())
        except ValueError as err:
            # cli.thresholds() silently falls back to defaults on the same file, so the
            # gate is the only place a half-written lock can still be caught.
            print("corrupt threshold lock: %s" % err, file=sys.stderr)
            return 1
    report = {
        "recorded": True, "lines": out, "numbers": stats, "thresholds": limits,
        "sweep": sweep, "brier": brier(probabilities, labels),
        "reliability": reliability_bins(probabilities, labels), "footnote": FOOTNOTE,
    }
    MEASURE_JSON.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")

    if args.lock:
        THRESHOLDS.write_text(json.dumps(dict(limits, locked=stats), indent=1, sort_keys=True) + "\n")
        print("locked: %s" % THRESHOLDS.relative_to(ROOT))
        return 0
    gate = locked.get("locked")
    if gate:
        regressions = []
        if stats["mismatches_caught"] < gate["mismatches_caught"]:
            regressions.append("mismatches caught")
        if stats["false_alarms"] > gate["false_alarms"]:
            regressions.append("false alarms")
        if stats["secret_correct"] < gate["secret_correct"]:
            regressions.append("config-shaped secrets")
        if regressions:
            print("regressed: %s" % ", ".join(regressions), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
