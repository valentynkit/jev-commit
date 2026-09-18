import json
import pathlib
import threading

import pytest

from jev_commit import belt, chunk, cli
from jev_commit.questions import (
    DEBUG_LEFTOVERS,
    MESSAGE_IS_SUBSTANTIVE,
    MESSAGE_MATCHES_DIFF,
    SCOPE_CREEP,
    SECRET_SHAPED,
)
from conftest import commit, git, write

CORPUS = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "corpus"
LIMITS = cli.DEFAULTS


def noul(value):
    return {"type": "noul", "noul": value}


def answers(match=0.9, substantive=0.95, debug=0.02, scope=0.05, secret=0.02):
    return {
        MESSAGE_IS_SUBSTANTIVE: noul(substantive),
        MESSAGE_MATCHES_DIFF: noul(match),
        DEBUG_LEFTOVERS: noul(debug),
        SCOPE_CREEP: noul(scope),
        SECRET_SHAPED: noul(secret),
    }


@pytest.fixture
def fake():
    import fake_jev

    servers = []

    def start(fixtures=None, status=0, max_tokens=0):
        log = []
        server = fake_jev.serve(0, fixtures, status, max_tokens, log)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return "http://127.0.0.1:%d" % server.server_address[1], log

    yield start
    for server in servers:
        server.shutdown()


def flat(fixtures):
    return {name: answer["noul"] for name, answer in fixtures.items()}


def test_clean_commit_exits_zero():
    code, findings, rows = cli.decide(flat(answers()), [], LIMITS)
    assert code == cli.OK and findings == []
    assert [status for _, _, status in rows] == ["ok"] * 5


def test_a_belt_hit_blocks_and_never_prints_the_secret():
    hits = belt.scan(
        [{"path": "deploy/id_rsa", "text": "@@\n+-----BEGIN OPENSSH PRIVATE KEY-----"}]
    )
    code, _, _ = cli.decide(flat(answers()), hits, LIMITS)
    assert code == cli.BLOCK
    assert hits[0]["redacted"] == "----..."


def test_a_low_noul_never_clears_a_belt_hit():
    hits = belt.scan([{"path": ".env", "text": "@@\n+AWS_KEY=AKIA2X7QF4LMZ3VBNTYE"}])
    code, _, _ = cli.decide(flat(answers(secret=0.01)), hits, LIMITS)
    assert code == cli.BLOCK


def test_strict_blocks_on_a_finding_and_the_default_does_not():
    strong = flat(answers(match=0.1, debug=0.93))
    assert cli.decide(strong, [], LIMITS)[0] == cli.OK
    assert cli.decide(strong, [], LIMITS, strict=True)[0] == cli.BLOCK


def test_a_placeholder_message_suppresses_the_mismatch_finding():
    lying = flat(answers(match=0.05, substantive=0.92))
    code, findings, rows = cli.decide(lying, [], LIMITS)
    assert MESSAGE_MATCHES_DIFF in findings
    wip = flat(answers(match=0.05, substantive=0.11))
    code, findings, rows = cli.decide(wip, [], LIMITS)
    assert findings == []
    assert (
        dict((label, status) for label, _, status in rows)["contradicts the diff"]
        == "ok"
    )


def test_every_row_prints_risk_so_a_long_bar_is_always_a_problem():
    _, _, rows = cli.decide(
        flat(answers(match=0.05, substantive=0.92, debug=0.88)), [], LIMITS
    )
    risk = dict((label, value) for label, value, _ in rows)
    assert risk["contradicts the diff"] == pytest.approx(0.95)
    assert risk["message is filler"] == pytest.approx(0.08)
    assert risk["debug leftovers"] == pytest.approx(0.88)


def test_usage_error_is_code_two(tmp_path):
    assert cli.main([]) == cli.USAGE
    assert cli.main([str(tmp_path / "missing")]) == cli.USAGE


def test_a_five_hundred_exits_zero(repo, fake, monkeypatch):
    url, _ = fake({}, status=500)
    commit(repo, "a.py", "x = 1\n", "add a")
    write(repo, "a.py", "x = 2\n")
    git(repo, "add", "-A")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("JEV_BASE_URL", url)
    message = repo / "msg"
    message.write_text("fix: bump x\n")
    assert cli.main([str(message)]) == cli.OK


def test_an_unreachable_api_still_blocks_on_the_belt(repo, monkeypatch):
    commit(repo, "a.py", "x = 1\n", "add a")
    write(repo, "deploy/id_rsa", "-----BEGIN OPENSSH PRIVATE KEY-----\nbody\n")
    git(repo, "add", "-A")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("JEV_BASE_URL", "http://127.0.0.1:1")
    message = repo / "msg"
    message.write_text("chore: add deploy key\n")
    assert cli.main([str(message)]) == cli.BLOCK


def two_chunk_states(message):
    hunks = [
        {"path": "src/a.py", "text": "@@ -1,2 +1,3 @@\n+a = 1"},
        {"path": "src/b.py", "text": "@@ -1,2 +1,3 @@\n+b = 2"},
    ]
    prep = {
        "files": [
            {"path": "src/a.py", "status": "M", "added": 1, "removed": 0},
            {"path": "src/b.py", "status": "M", "added": 1, "removed": 0},
        ],
        "hunks": hunks,
        "omitted": "",
        "more": "",
    }
    return [chunk.build_state(message, prep, [h]) for h in hunks]


def test_routing_asks_the_gate_once_and_takes_the_worse_answer(fake):
    url, log = fake([answers(match=0.95, debug=0.10), answers(match=0.12, debug=0.80)])
    out = cli.judge(two_chunk_states("feat: a and b"), {"JEV_BASE_URL": url})
    assert out["requests"] == 2
    assert MESSAGE_IS_SUBSTANTIVE in log[0]["questions"]
    assert MESSAGE_IS_SUBSTANTIVE not in log[1]["questions"], (
        "the gate rides the first request only"
    )
    assert out["answers"][MESSAGE_MATCHES_DIFF] == 0.12, "min: the worse answer wins"
    assert out["answers"][DEBUG_LEFTOVERS] == 0.80, "max: the worse answer wins"


def test_a_too_big_response_splits_and_retries(fake):
    url, log = fake(answers(), max_tokens=500)
    states = chunk.chunk_states(
        "feat: things",
        {
            "files": [
                {"path": "src/%d.py" % i, "status": "M", "added": 1, "removed": 0}
                for i in range(8)
            ],
            "hunks": [
                {"path": "src/%d.py" % i, "text": "@@ -1,2 +1,3 @@\n+value = %d" % i}
                for i in range(8)
            ],
            "omitted": "",
            "more": "",
        },
    )
    assert len(states) == 1
    out = cli.judge(states, {"JEV_BASE_URL": url})
    assert out["requests"] > 1
    assert set(out["answers"]) >= {MESSAGE_MATCHES_DIFF, DEBUG_LEFTOVERS}


def replay(case, per_chunk):
    prep = {"files": case["files"], "hunks": case["hunks"], "omitted": "", "more": ""}
    return chunk.chunk_states(case["message"], prep), prep


@pytest.mark.skipif(
    not (CORPUS / "split_01.json").exists(), reason="corpus not recorded yet"
)
def test_split_01_reports_the_false_claim(fake):
    case = json.loads((CORPUS / "split_01.json").read_text())
    states, _ = replay(case, None)
    assert len(states) > 1, "split_01 must actually split"
    url, _ = fake([answers(match=0.95)] + [answers(match=0.08)] * len(states))
    out = cli.judge(states, {"JEV_BASE_URL": url})
    code, findings, _ = cli.decide(out["answers"], [], LIMITS)
    assert MESSAGE_MATCHES_DIFF in findings and code == cli.OK


@pytest.mark.skipif(
    not (CORPUS / "split_02.json").exists(), reason="corpus not recorded yet"
)
def test_split_02_does_not_false_mismatch(fake):
    case = json.loads((CORPUS / "split_02.json").read_text())
    states, _ = replay(case, None)
    assert len(states) > 1
    url, _ = fake(answers(match=0.93))
    out = cli.judge(states, {"JEV_BASE_URL": url})
    code, findings, _ = cli.decide(out["answers"], [], LIMITS)
    assert findings == [] and code == cli.OK


def test_main_never_exits_nonzero_when_something_blows_up(tmp_path, monkeypatch):
    """pre-commit aborts on any nonzero, so a bug here stops a stranger's commit."""
    message = tmp_path / "msg"
    message.write_text("fix: thing\n")

    def boom(*args, **kwargs):
        raise RuntimeError("the patch parser fell over")

    monkeypatch.setattr(cli.git, "capture", boom)
    assert cli.main([str(message)]) == cli.OK

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.git, "capture", interrupt)
    assert cli.main([str(message)]) == cli.OK


def test_the_match_bar_agrees_with_the_verdict_under_a_swept_cutoff():
    """The bar reads the mismatch cutoff; keying it to `finding` made them disagree."""
    limits = dict(cli.DEFAULTS, mismatch=0.10)
    for probability in (0.15, 0.20, 0.30):
        _, findings, rows = cli.decide({MESSAGE_MATCHES_DIFF: probability}, [], limits)
        status = [row[2] for row in rows][0]
        assert (status == "flag") == (MESSAGE_MATCHES_DIFF in findings), probability
