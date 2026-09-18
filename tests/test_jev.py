import http.server
import threading

import pytest

from jev_commit import jev, questions


@pytest.fixture
def fake():
    """tools/fake_jev.py, in process. Returns (env, log) with JEV_BASE_URL pointed at it."""
    import fake_jev

    def start(fixtures=None, status=0, max_tokens=0):
        log = []
        server = fake_jev.serve(0, fixtures, status, max_tokens, log)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        env = {"JEV_BASE_URL": "http://127.0.0.1:%d" % server.server_address[1]}
        return env, log

    started = []
    yield start
    for server in started:
        server.shutdown()


def test_five_answers_come_back(fake):
    env, log = fake({name: {"type": "noul", "noul": 0.42} for name in questions.QUESTIONS})
    out = jev.ask({"message": "fix: thing"}, questions.QUESTIONS, env=env)
    assert set(out["answers"]) == set(questions.QUESTIONS)
    assert out["answers"]["scope_creep"] == 0.42
    assert out["usage"]["input_tokens"] > 0 and out["ms"] >= 0
    assert log[0]["model"] == "jev-1.13.0", "the model is pinned, never an alias"


def test_a_local_base_url_needs_no_key(fake):
    env, _ = fake({"secret_shaped": {"type": "noul", "noul": 0.1}})
    assert jev.api_key(env) == "local-shim"
    assert jev.api_key({}) is None


def test_server_error_raises_after_retries_inside_the_deadline(fake):
    env, log = fake({}, status=500)
    with pytest.raises(jev.JevError):
        jev.ask({"message": "m"}, questions.QUESTIONS, env=env, deadline_s=2.0)
    assert len(log) > 1, "5xx retries"


def test_client_error_does_not_retry(fake):
    env, log = fake({}, status=403)
    with pytest.raises(jev.JevError):
        jev.ask({"message": "m"}, questions.QUESTIONS, env=env)
    assert len(log) == 1


def test_too_big_is_its_own_error(fake):
    env, _ = fake({}, max_tokens=10)
    with pytest.raises(jev.TooBig):
        jev.ask({"message": "x " * 200}, questions.QUESTIONS, env=env)


def test_an_answer_without_a_probability_is_an_error(fake):
    env, _ = fake({"scope_creep": {"type": "noul"}})
    with pytest.raises(jev.JevError):
        jev.ask({"message": "m"}, {"scope_creep": questions.QUESTIONS["scope_creep"]}, env=env)


def test_every_question_has_both_criteria_and_no_counting_words():
    banned = ("how many", "count", "number of", "at least two", "more than")
    for name, question in questions.QUESTIONS.items():
        assert question["type"] == "noul"
        assert set(question["criteria"]) == {"true", "false"}
        blob = repr(question).lower()
        assert not any(word in blob for word in banned), name


class _Odd(http.server.BaseHTTPRequestHandler):
    """Answers 200 with whatever BODY holds, however malformed."""

    BODY = b"null"

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.BODY)))
        self.end_headers()
        self.wfile.write(self.BODY)

    def log_message(self, *args):
        pass


@pytest.fixture
def odd():
    def start(body):
        handler = type("H", (_Odd,), {"BODY": body})
        server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        return {"JEV_BASE_URL": "http://127.0.0.1:%d" % server.server_address[1]}

    started = []
    yield start
    for server in started:
        server.shutdown()


@pytest.mark.parametrize("body", [b"null", b"[1, 2, 3]", b'{"answers": null}',
                                  b'{"answers": [1]}', b'{"error": "nope"}'])
def test_a_body_that_is_not_an_answer_map_is_a_jev_error(odd, body):
    """A 200 shaped like anything else used to raise AttributeError and block the commit."""
    with pytest.raises(jev.JevError):
        jev.ask({"message": "m"}, questions.QUESTIONS, env=odd(body))


def test_a_true_is_not_a_probability(odd):
    body = b'{"answers": {"%s": true}}' % questions.MESSAGE_IS_SUBSTANTIVE.encode()
    with pytest.raises(jev.JevError):
        jev.ask({"message": "m"}, {questions.MESSAGE_IS_SUBSTANTIVE: {}}, env=odd(body))
