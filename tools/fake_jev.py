"""Fake Jev: the offline backend for the tests and the demo.

Answers come from a flat fixture file, question name to answer object, exactly the shape
research/01 section 3 describes. Env knobs, all for tests: FAKE_JEV_FIXTURES picks the
file, FAKE_JEV_STATUS forces an HTTP status, FAKE_JEV_MAX_TOKENS makes an oversized state
answer 400 too big so the split-and-retry path has something to hit.
"""

import itertools
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

DEFAULT = {"type": "noul", "noul": 0.5}
TOKEN_PIECES = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")


def estimate(text):
    return len(TOKEN_PIECES.findall(text))


def handler_for(fixtures, status=0, max_tokens=0, log=None):
    """fixtures is one answer map, or a list of them to hand out one per request."""

    seen = itertools.count()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if log is not None:
                log.append(body)
            if status:
                return self.reply(status, {"error": "forced %d" % status})
            if max_tokens and estimate(json.dumps(body.get("state", ""))) > max_tokens:
                return self.reply(400, {"error": "state is too big for one request"})
            table = fixtures
            if isinstance(fixtures, list):
                table = fixtures[min(next(seen), len(fixtures) - 1)] if fixtures else {}
            answers = {name: table.get(name, DEFAULT) for name in body.get("questions", {})}
            self.reply(200, {
                "model": body.get("model", "jev-1.13.0"),
                "answers": answers,
                "usage": {"input_tokens": estimate(json.dumps(body.get("state", ""))), "output_tokens": 0},
            })

        def reply(self, code, payload):
            out = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args):
            pass

    return Handler


def serve(port=0, fixtures=None, status=0, max_tokens=0, log=None):
    return HTTPServer(("127.0.0.1", port), handler_for(fixtures or {}, status, max_tokens, log))


if __name__ == "__main__":
    path = os.environ.get("FAKE_JEV_FIXTURES", "")
    fixtures = json.load(open(path)) if path else {}
    server = serve(int(os.environ.get("PORT", 4321)), fixtures,
                   int(os.environ.get("FAKE_JEV_STATUS", 0)),
                   int(os.environ.get("FAKE_JEV_MAX_TOKENS", 0)))
    print("fake jev on http://127.0.0.1:%d" % server.server_address[1], file=sys.stderr)
    server.serve_forever()
