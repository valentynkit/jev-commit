"""make fixtures: build the corpus from GitHub, then record answers for it.

Two phases, neither ever runs in CI. The corpus phase needs GitHub and no key, and writes
fixtures/corpus/*.json plus NOTICE. The answer phase needs a key or the local shim, and
writes fixtures/answers/<sha256(state+questions)>.json, which is what make measure replays.

The corpus ships states, not repos: each case holds the message, the file table and the
already trimmed hunks, so measure rebuilds byte-identical requests with no git and no
network.
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

from jev_commit import chunk, jev
from jev_commit.config_cases import CASES as CONFIG_CASES
from jev_commit.questions import QUESTIONS

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "fixtures" / "corpus"
ANSWERS = ROOT / "fixtures" / "answers"
SIZE_CAP = 4 * 1024 * 1024
OVER_BUDGET_HUNK_CAP = 200 * 1024

REPOS = [
    "pre-commit/pre-commit", "pytest-dev/pytest", "astral-sh/ruff", "tokio-rs/axum",
    "charmbracelet/vhs", "junegunn/fzf", "sindresorhus/execa", "vuejs/core",
    "nlohmann/json", "rails/rails",
]
SINCE = "2024-01-01T00:00:00Z"
WINDOW = 300  # the most recent commits since SINCE that the selection rule runs over
REAL_PER_REPO = 10
OVER_BUDGET = 12
STATUS = {"added": "A", "removed": "D", "modified": "M", "renamed": "R", "copied": "C",
          "changed": "M", "unchanged": "M"}

HISTORY = """
query($owner:String!,$name:String!,$cursor:String){
  repository(owner:$owner,name:$name){
    licenseInfo{ spdxId }
    defaultBranchRef{ target{ ... on Commit {
      history(first:100, since:"%s", after:$cursor){
        pageInfo{ hasNextPage endCursor }
        nodes{ oid additions deletions changedFilesIfAvailable parents(first:2){ totalCount } }
      }
    }}}
  }
}
""" % SINCE


def gh(*args):
    proc = subprocess.run(["gh"] + list(args), capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("gh %s failed: %s" % (" ".join(args[:2]), proc.stderr.strip()[:300]))
    return json.loads(proc.stdout)


def history(repo):
    owner, name = repo.split("/")
    nodes, cursor, spdx = [], None, None
    while len(nodes) < WINDOW:
        args = ["api", "graphql", "-f", "query=" + HISTORY, "-F", "owner=" + owner, "-F", "name=" + name]
        if cursor:
            args += ["-F", "cursor=" + cursor]
        data = gh(*args)["data"]["repository"]
        spdx = data["licenseInfo"]["spdxId"]
        page = data["defaultBranchRef"]["target"]["history"]
        nodes += [n for n in page["nodes"] if n["parents"]["totalCount"] == 1]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    if spdx not in ("MIT", "Apache-2.0"):
        raise SystemExit("%s is %s, not redistributable" % (repo, spdx))
    return nodes[:WINDOW], spdx


def every_nth(shas, want):
    """Sort by SHA, take every Nth. Deterministic and independent of commit order."""
    ordered = sorted(shas)
    if not ordered:
        return []
    step = max(1, len(ordered) // want)
    return ordered[::step][:want]


def pick_real(nodes):
    keep = [n["oid"] for n in nodes
            if 1 <= (n["changedFilesIfAvailable"] or 0) <= 8
            and 5 <= n["additions"] + n["deletions"] <= 400]
    return every_nth(keep, REAL_PER_REPO)


def pick_over_budget(nodes):
    return [n["oid"] for n in nodes
            if (n["changedFilesIfAvailable"] or 0) >= 20 or n["additions"] + n["deletions"] >= 3000]


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def trim_context(patch, keep=2):
    """The API hands out three context lines; the hook asks git for two."""
    out = []
    for block in re.split(r"(?m)^(?=@@ )", patch):
        match = HUNK_HEADER.match(block.split("\n", 1)[0]) if block.startswith("@@") else None
        if not match:
            out.append(block)
            continue
        head, body = block.split("\n", 1)
        lines = body.split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        lead = 0
        while lead < len(lines) and lines[lead].startswith(" "):
            lead += 1
        tail = 0
        while tail < len(lines) - lead and lines[len(lines) - 1 - tail].startswith(" "):
            tail += 1
        cut_lead = max(0, min(lead - keep, lead))
        cut_tail = max(0, min(tail - keep, tail))
        lines = lines[cut_lead:len(lines) - cut_tail] if cut_tail else lines[cut_lead:]
        old_start, old_count, new_start, new_count, rest = match.groups()
        old_count = int(old_count if old_count is not None else 1)
        new_count = int(new_count if new_count is not None else 1)
        head = "@@ -%d,%d +%d,%d @@%s" % (
            int(old_start) + cut_lead, old_count - cut_lead - cut_tail,
            int(new_start) + cut_lead, new_count - cut_lead - cut_tail, rest)
        out.append("\n".join([head] + lines) + "\n")
    return "".join(out)


def patch_from_api(files):
    """Rebuild a unified patch so the corpus runs through the same prepare() as a real hook."""
    parts = []
    for entry in files:
        path = entry["filename"]
        old = entry.get("previous_filename", path)
        parts.append("diff --git a/%s b/%s\n" % (old, path))
        status = entry.get("status")
        parts.append("--- %s\n" % ("/dev/null" if status == "added" else "a/" + old))
        parts.append("+++ %s\n" % ("/dev/null" if status == "removed" else "b/" + path))
        if entry.get("patch"):
            body = trim_context(entry["patch"])
            parts.append(body if body.endswith("\n") else body + "\n")
        else:
            parts.append("Binary files a/%s and b/%s differ\n" % (old, path))
    return "".join(parts)


def commit_case(repo, sha, spdx, case_id, group, message=None, label=None, hunk_cap=None):
    data = gh("api", "repos/%s/commits/%s" % (repo, sha))
    files = data.get("files") or []
    patch = patch_from_api(files)
    name_status = {f["filename"]: STATUS.get(f.get("status"), "M") for f in files}
    prep = chunk.prepare(patch, name_status)
    counts = {f["filename"]: (f.get("additions", 0), f.get("deletions", 0)) for f in files}
    for row in prep["files"]:
        if row["path"] in counts:
            row["added"], row["removed"] = counts[row["path"]]
    hunks, size = [], 0
    for hunk in prep["hunks"]:
        size += len(hunk["text"])
        if hunk_cap and size > hunk_cap:
            break
        hunks.append(hunk)
    text = data["commit"]["message"].strip()
    return {
        "id": case_id,
        "group": group,
        "repo": repo,
        "sha": sha,
        "license": spdx,
        "message": message if message is not None else text,
        "files": prep["files"],
        "hunks": hunks,
        "omitted": prep["omitted"],
        "more": prep["more"],
        "label": label or {},
    }


VERSION_BUMP = [
    ("package.json", '@@ -3,3 +3,3 @@\n   "name": "app",\n-  "version": "4.2.1",\n+  "version": "4.3.0",\n   "type": "module"'),
    ("pyproject.toml", '@@ -2,3 +2,3 @@\n name = "app"\n-version = "4.2.1"\n+version = "4.3.0"\n description = "x"'),
    ("Cargo.toml", '@@ -2,3 +2,3 @@\n name = "app"\n-version = "4.2.1"\n+version = "4.3.0"\n edition = "2021"'),
]


def build_corpus():
    CORPUS.mkdir(parents=True, exist_ok=True)
    for stale in CORPUS.glob("*.json"):
        stale.unlink()
    cases, per_repo, over_pool = [], {}, []
    for repo in REPOS:
        nodes, spdx = history(repo)
        per_repo[repo] = (pick_real(nodes), spdx)
        over_pool += [(repo, sha, spdx) for sha in pick_over_budget(nodes)]
        print("%-26s %d commits, %d real candidates" % (repo, len(nodes), len(per_repo[repo][0])), file=sys.stderr)

    # Real 100: the false-alarm set. Every case is assumed to match its own message.
    index = 0
    for repo in REPOS:
        shas, spdx = per_repo[repo]
        for sha in shas:
            index += 1
            case = commit_case(repo, sha, spdx, "real_%03d" % index, "real",
                               label={"mismatch": False})
            cases.append(case)
            print("real_%03d %s %s" % (index, repo, sha[:8]), file=sys.stderr)

    # 20 mismatches: 14 diffs wearing another commit's message, 6 with a version bump added.
    real_by_repo = {}
    for case in cases:
        real_by_repo.setdefault(case["repo"], []).append(case)
    pairs = [(repo, 0, 1) for repo in REPOS] + [(repo, 2, 3) for repo in REPOS[:4]]
    for number, (repo, left, right) in enumerate(pairs, start=1):
        donor, source = real_by_repo[repo][left], real_by_repo[repo][right]
        case = commit_case(repo, donor["sha"], donor["license"], "mm_%02d" % number, "mismatch",
                           message=source["message"],
                           label={"mismatch": True, "kind": "paired",
                                  "catch_on": ["message_matches_diff"]})
        cases.append(case)
    for number, repo in enumerate(REPOS[4:], start=len(pairs) + 1):
        base = real_by_repo[repo][4]
        path, text = VERSION_BUMP[number % len(VERSION_BUMP)]
        case = dict(base)
        case["id"] = "mm_%02d" % number
        case["group"] = "mismatch"
        case["files"] = base["files"] + [{"path": path, "status": "M", "added": 1, "removed": 1}]
        case["hunks"] = base["hunks"] + [{"path": path, "text": text}]
        case["label"] = {"mismatch": True, "kind": "version_bump",
                         "catch_on": ["message_matches_diff", "scope_creep"]}
        cases.append(case)

    # 12 over-budget commits, two of them the crafted split cases. The inverted filter
    # (20+ files or 3,000+ lines) does not by itself guarantee a split: -U2, degrade to
    # counts and the per-file cap shrink most big commits back under one budget. So the
    # candidates are walked round robin across repos and only the ones that really split
    # are kept, which also keeps one repo from owning the group.
    by_repo = {}
    for repo, sha, spdx in over_pool:
        by_repo.setdefault(repo, []).append((sha, spdx))
    queues = [sorted(by_repo[repo]) for repo in REPOS if repo in by_repo]
    over = []
    round_index = 0
    while len(over) < OVER_BUDGET and any(round_index < len(q) for q in queues):
        for repo, queue in zip([r for r in REPOS if r in by_repo], queues):
            if len(over) >= OVER_BUDGET or round_index >= len(queue):
                continue
            sha, spdx = queue[round_index]
            case = commit_case(repo, sha, spdx, "pending", "over_budget",
                               label={"mismatch": False}, hunk_cap=OVER_BUDGET_HUNK_CAP)
            if len(states_for(case)) < 2:
                continue
            over.append(case)
            print("over-budget %s %s %d chunks" % (repo, sha[:8], len(states_for(case))), file=sys.stderr)
        round_index += 1

    first, second = over[0], over[1]
    first["id"] = "split_01"
    first["message"] = ("refactor: update %s\n\nAlso deletes the legacy src/dead_code_path.py helper, "
                        "which nothing imports any more." % first["hunks"][0]["path"])
    first["label"] = {"mismatch": True, "kind": "two_claims_one_false",
                      "catch_on": ["message_matches_diff"]}
    chunks = states_for(second)
    second["id"] = "split_02"
    second["message"] = "refactor: update %s and %s" % (
        chunks[0]["hunks"][0]["path"], chunks[-1]["hunks"][-1]["path"])
    second["label"] = {"mismatch": False, "kind": "two_claims_both_true"}
    for number, case in enumerate(over[2:], start=1):
        case["id"] = "over_%02d" % number
    cases += over

    cases += config_cases()
    for case in cases:
        write_case(case)
    write_notice(cases)
    check_size()
    print("%d cases, %d bytes" % (len(cases), corpus_size()), file=sys.stderr)
    return cases


def write_case(case):
    path = CORPUS / (case["id"] + ".json")
    path.write_text(json.dumps(case, indent=1, sort_keys=True) + "\n")
    return path


def config_cases():
    """The config-shaped secret group, authored in this repo (see config_cases.py)."""
    out = []
    for case_id, path, is_secret, category, content in CONFIG_CASES:
        lines = content.splitlines()
        text = "@@ -0,0 +1,%d @@\n" % len(lines) + "\n".join("+" + line for line in lines)
        out.append({
            "id": case_id,
            "group": "secret",
            "repo": "jev-commit",
            "sha": "",
            "license": "MIT",
            "message": "chore: add %s" % path.rsplit("/", 1)[-1],
            "files": [{"path": path, "status": "A", "added": len(lines), "removed": 0}],
            "hunks": [{"path": path, "text": text}],
            "omitted": "",
            "more": "",
            "label": {"secret": is_secret, "category": category},
        })
    return out


def write_notice(cases):
    lines = [
        "Corpus attribution",
        "",
        "Every case below is an excerpt of a commit from a repository under the license named,",
        "which permits redistribution with attribution. Only hunks ship, never whole files.",
        "If a repository relicenses we drop its cases, re-record from a replacement, and",
        "republish with the new n.",
        "",
        "The cfg_* cases are not excerpts. They were written for this repository (MIT, see",
        "jev_commit/config_cases.py) because the incumbent's config-shaped set carries no",
        "license at all and cannot be redistributed.",
        "",
        "%-12s %-26s %-42s %s" % ("case", "repo", "commit", "license"),
    ]
    for case in cases:
        if not case["sha"]:
            continue
        lines.append("%-12s %-26s %-42s %s" % (case["id"], case["repo"], case["sha"], case["license"]))
    lines += ["", "Commit URLs: https://github.com/<repo>/commit/<sha>", ""]
    (CORPUS / "NOTICE").write_text("\n".join(lines))


def corpus_size():
    return sum(path.stat().st_size for path in CORPUS.iterdir())


def check_size():
    size = corpus_size()
    if size > SIZE_CAP:
        raise SystemExit("corpus is %d bytes, over the %d cap" % (size, SIZE_CAP))
    return size


def load_corpus(group=None):
    cases = []
    for path in sorted(CORPUS.glob("*.json")):
        case = json.loads(path.read_text())
        if group is None or case["group"] == group:
            cases.append(case)
    return cases


def states_for(case):
    prep = {"files": case["files"], "hunks": case["hunks"],
            "omitted": case.get("omitted", ""), "more": case.get("more", "")}
    return chunk.chunk_states(case["message"], prep)


def answer_key(state, questions):
    blob = json.dumps({"state": state, "questions": questions}, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


RECORD_DEADLINE_S = 90.0   # the client's own retry budget, generous because this is offline work
GIVE_UP_S = 120.0          # stop after this long with nothing but errors, never busy loop


def record_answers(env=None, limit=None):
    """One request per chunk over the whole corpus, written to fixtures/answers/.

    Resumable and serial: a key already on disk is skipped, so a run that dies partway
    through picks up where it stopped, and only one request is ever in flight.
    """
    env = dict(os.environ if env is None else env)
    ANSWERS.mkdir(parents=True, exist_ok=True)
    cases = load_corpus()
    if limit:
        cases = cases[:limit]
    wanted = written = spent = 0
    failing_since = None
    for case in cases:
        for index, state in enumerate(states_for(case)):
            questions = dict(QUESTIONS)
            if index > 0:
                questions.pop("message_is_substantive")
            key = answer_key(state, questions)
            path = ANSWERS / (key + ".json")
            wanted += 1
            if path.exists():
                continue
            try:
                out = jev.ask(state, questions, env=env, deadline_s=RECORD_DEADLINE_S)
            except jev.JevError as err:
                now = time.monotonic()
                failing_since = failing_since or now
                print("%s chunk %d: %s" % (case["id"], index, err), file=sys.stderr)
                if now - failing_since > GIVE_UP_S:
                    print("giving up: recorded %d of %d" % (written, wanted), file=sys.stderr)
                    return written
                time.sleep(3)
                continue
            failing_since = None
            path.write_text(json.dumps({
                "case": case["id"], "chunk": index, "answers": out["answers"],
                "model": out["model"], "ms": out["ms"], "usage": out["usage"],
            }, indent=1, sort_keys=True) + "\n")
            written += 1
            spent += (out["usage"].get("input_tokens") or 0) * 0.042 / 1_000_000
            print("%s chunk %d %s" % (case["id"], index, out["answers"]), file=sys.stderr)
    print("wrote %d of %d answers, about $%.4f" % (written, wanted, spent), file=sys.stderr)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(prog="make fixtures")
    parser.add_argument("--corpus", action="store_true", help="rebuild fixtures/corpus from GitHub")
    parser.add_argument("--answers", action="store_true", help="record fixtures/answers against Jev")
    parser.add_argument("--limit", type=int, default=0, help="record only the first N cases")
    args = parser.parse_args(argv)
    if not args.corpus and not args.answers:
        args.corpus = args.answers = True
    if args.corpus:
        build_corpus()
    if args.answers:
        if not jev.api_key(os.environ):
            print("no key and no JEV_BASE_URL, skipping fixtures/answers", file=sys.stderr)
            return 0
        record_answers(limit=args.limit or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
