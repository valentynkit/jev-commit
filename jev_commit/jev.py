"""The HTTP client: urllib, one deadline across retries, backoff only on 429 and 5xx.

jev-guard src/jev.js:29-67 is the shape. The deadline is one budget for the whole call
because nobody waits longer than that on a commit and git has no hook timeout of its own.
Every error is the caller's cue to exit 0: Jev only makes this stricter, never looser.
"""

import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://api.typesafe.ai"
PATH = "/v1/systemone"
DEADLINE_S = 8.0
LOCAL_SHIM = "local-shim"  # the bearer when JEV_BASE_URL points at a shim holding the key
LOOPBACK = ("127.0.0.1", "localhost", "::1")
RETRIES = 2
TOO_BIG_HINTS = ("too big", "too large", "exceeds", "token limit", "context length")
MAX_BODY_BYTES = 4 * 1024 * 1024  # five nouls answer in bytes, not megabytes


class JevError(Exception):
    pass


class TooBig(JevError):
    """The request did not fit. The caller bisects and retries (every judge.py:184-190)."""


def base_url(env=None):
    env = os.environ if env is None else env
    return (env.get("JEV_BASE_URL") or env.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def api_key(env=None):
    env = os.environ if env is None else env
    key = env.get("TYPESAFE_API_KEY") or env.get("JEV_API_KEY")
    if key:
        return key
    # A local shim holds the real credential; it only needs a non-empty bearer.
    return LOCAL_SHIM if base_url(env) != DEFAULT_BASE_URL else None


def _retry_after(headers, default):
    raw = headers.get("retry-after") if headers else None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return default


def _read_by(response, stop, chunk=65536):
    """Read the body, but give up at the wall-clock deadline.

    urlopen's timeout is per socket operation, not a budget for the call. A server dripping
    bytes under that timeout kept the whole thing alive past the deadline (measured 10.07 s
    against 8.0), and git is holding the terminal the whole time.

    read1, not read: read(n) blocks until it has n bytes or the Content-Length is satisfied,
    so the deadline was only ever checked once the slow body had fully arrived.
    """
    read = getattr(response, "read1", response.read)
    out = bytearray()
    while True:
        if time.monotonic() >= stop:
            raise TimeoutError("deadline reached while reading the response body")
        piece = read(chunk)
        if not piece:
            return bytes(out)
        out += piece
        if len(out) > MAX_BODY_BYTES:
            raise JevError("response body over %d bytes" % MAX_BODY_BYTES)


_warned = False


def warn_if_insecure(url, key):
    """One line when a real key leaves for somewhere that is neither https nor loopback.

    JEV_BASE_URL is how the shim gets used, so it cannot be locked down, but a real
    TYPESAFE_API_KEY plus a plain http:// host sends the key and the whole diff in the
    clear. Warn, never block: this hook does not get to stop a commit over configuration.
    """
    global _warned
    if _warned or key == LOCAL_SHIM:
        return
    split = urllib.parse.urlsplit(url)
    if split.scheme == "https" or split.hostname in LOOPBACK:
        return
    _warned = True
    sys.stderr.write("jev-commit: sending the key to %s, which is not https or loopback\n"
                     % (split.hostname or url))


def ask(state, questions, env=None, model=None, deadline_s=DEADLINE_S):
    """{answers: {name: probability}, model, usage, ms}. Raises JevError on anything else."""
    env = os.environ if env is None else env
    key = api_key(env)
    if not key:
        raise JevError("no api key")
    payload = json.dumps({
        "model": model or env.get("JEV_MODEL") or "jev-1.13.0",
        "state": state,
        "questions": questions,
    }).encode()
    url = base_url(env) + PATH
    warn_if_insecure(url, key)
    started = time.monotonic()
    stop = started + deadline_s
    delay = 0.4
    last = "unknown"
    for attempt in range(RETRIES + 1):
        left = stop - time.monotonic()
        if left <= 0:
            raise JevError("deadline reached: " + last)
        request = urllib.request.Request(url, data=payload, method="POST", headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=left) as response:
                body = json.loads(_read_by(response, stop).decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8", "replace")[:300]
            last = "HTTP %d %s" % (err.code, text.strip())
            # 413 is the status for it; the hints cover backends that answer 400 or 422.
            if err.code == 413 or (err.code in (400, 422)
                                   and any(hint in text.lower() for hint in TOO_BIG_HINTS)):
                raise TooBig(last) from err
            if err.code != 429 and err.code < 500:
                raise JevError(last) from err
            wait = _retry_after(err.headers, delay)
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException) as err:
            last = str(err)
            wait = delay
        except ValueError as err:
            raise JevError("unparseable response: %s" % err) from err
        if attempt == RETRIES:
            raise JevError(last)
        if time.monotonic() + wait >= stop:
            raise JevError("deadline reached: " + last)
        time.sleep(wait)
        delay *= 2
    # A 200 whose body is `null`, a list, or somebody's error envelope is a gateway
    # hiccup, not a reason to stop a commit. Everything unexpected leaves as a JevError.
    if not isinstance(body, dict):
        raise JevError("response was not an object")
    if not isinstance(body.get("answers"), dict):
        raise JevError("response carried no answers object")
    answers = {}
    for name, answer in body["answers"].items():
        value = answer.get("noul", answer.get("probability")) if isinstance(answer, dict) else answer
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise JevError("no probability for question %s" % name)
        answers[name] = float(value)
    missing = set(questions) - set(answers)
    if missing:
        raise JevError("missing answers: %s" % ", ".join(sorted(missing)))
    usage, model = body.get("usage"), body.get("model")
    return {
        "answers": answers,
        "model": model if isinstance(model, str) and model else "unknown",
        "usage": usage if isinstance(usage, dict) else {},
        "ms": int((time.monotonic() - started) * 1000),
    }
