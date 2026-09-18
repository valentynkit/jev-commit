import http.server
import socket
import threading
import time

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


def test_a_slow_body_cannot_outrun_the_deadline():
    """urlopen's timeout is per recv, so a dripping body used to sail past the budget."""
    body = b'{"answers": {"%s": {"noul": 0.9}}}' % questions.MESSAGE_IS_SUBSTANTIVE.encode()

    def serve(sock):
        conn, _ = sock.accept()
        conn.recv(65536)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                     b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(body))
        try:
            for i in range(0, len(body), 4):
                conn.sendall(body[i:i + 4])
                time.sleep(0.4)
        except OSError:
            pass
        conn.close()

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    threading.Thread(target=serve, args=(sock,), daemon=True).start()
    env = {"JEV_BASE_URL": "http://127.0.0.1:%d" % sock.getsockname()[1]}

    started = time.monotonic()
    with pytest.raises(jev.JevError):
        jev.ask({"message": "m"}, {questions.MESSAGE_IS_SUBSTANTIVE: {}}, env=env, deadline_s=1.0)
    elapsed = time.monotonic() - started
    assert elapsed < 3.0, "gave up after %.2fs against a 1s deadline" % elapsed
    sock.close()


def test_a_real_key_to_a_plain_http_host_warns_but_does_not_block(fake, capsys, monkeypatch):
    monkeypatch.setattr(jev, "_warned", False)
    env, _ = fake({name: {"type": "noul", "noul": 0.5} for name in questions.QUESTIONS})
    env["TYPESAFE_API_KEY"] = "sk-real-secret"
    jev.ask({"message": "m"}, questions.QUESTIONS, env=env)
    assert "not https or loopback" not in capsys.readouterr().err, "loopback is fine"

    monkeypatch.setattr(jev, "_warned", False)
    jev.warn_if_insecure("http://gateway.example.com/v1/systemone", "sk-real-secret")
    assert "not https or loopback" in capsys.readouterr().err
