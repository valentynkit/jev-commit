"""The HTTP client: urllib, one deadline across retries, backoff only on 429 and 5xx.

jev-guard src/jev.js:29-67 is the shape. The deadline is one budget for the whole call
because nobody waits longer than that on a commit and git has no hook timeout of its own.
Every error is the caller's cue to exit 0: Jev only makes this stricter, never looser.
"""

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://api.typesafe.ai"
PATH = "/v1/systemone"
DEADLINE_S = 8.0
RETRIES = 2
TOO_BIG_HINTS = ("too big", "too large", "exceeds", "token limit", "context length")


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
    return "local-shim" if base_url(env) != DEFAULT_BASE_URL else None


def _retry_after(headers, default):
    raw = headers.get("retry-after") if headers else None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return default


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
                body = json.loads(response.read().decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as err:
            text = err.read().decode("utf-8", "replace")[:300]
            last = "HTTP %d %s" % (err.code, text.strip())
            if err.code in (400, 413, 422) and any(hint in text.lower() for hint in TOO_BIG_HINTS):
                raise TooBig(last) from err
            if err.code != 429 and err.code < 500:
                raise JevError(last) from err
            wait = _retry_after(err.headers, delay)
        except (urllib.error.URLError, TimeoutError, OSError) as err:
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
    answers = {}
    for name, answer in (body.get("answers") or {}).items():
        value = answer.get("noul", answer.get("probability")) if isinstance(answer, dict) else answer
        if not isinstance(value, (int, float)):
            raise JevError("no probability for question %s" % name)
        answers[name] = float(value)
    missing = set(questions) - set(answers)
    if missing:
        raise JevError("missing answers: %s" % ", ".join(sorted(missing)))
    return {
        "answers": answers,
        "model": body.get("model") or "unknown",
        "usage": body.get("usage") or {},
        "ms": int((time.monotonic() - started) * 1000),
    }
