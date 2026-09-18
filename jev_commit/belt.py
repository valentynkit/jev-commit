"""The regex and entropy belt that sits in front of the secret noul.

Code first, Jev second: a miss here is costly, and pattern matching is exactly what a
decision model is bad at. The thirteen high-precision patterns block on their own. The two
high-recall ones never block; they ride along in the report next to the noul, which is the
only thing that can reach a low-entropy config-shaped credential.
"""

import fnmatch
import math
import re

ALLOW_MARK = "jev-commit: allow"

# Every prefix is anchored on its left, so it only counts when it starts a token. Without
# it `sk-[A-Za-z0-9]{20,}` blocks a commit over `risk-<20 chars>` and `AIza[...]{35}`
# blocks over a base64 blob that happens to contain those four letters.
LEFT = r"(?<![A-Za-z0-9])"

HIGH_PRECISION = [
    ("aws_access_key", re.compile(LEFT + r"AKIA[0-9A-Z]{16}")),
    ("github_pat", re.compile(LEFT + r"github_pat_[A-Za-z0-9_]{20,}")),
    ("github_token", re.compile(LEFT + r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("anthropic_key", re.compile(LEFT + r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_key", re.compile(LEFT + r"sk-[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(LEFT + r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(LEFT + r"AIza[0-9A-Za-z_\-]{35}")),
    ("gitlab_token", re.compile(LEFT + r"glpat-[\w-]{20}")),
    ("sendgrid_key", re.compile(LEFT + r"SG\.[\w-]{22}\.")),
    ("npm_token", re.compile(LEFT + r"npm_[A-Za-z0-9]{36}")),
    ("private_key", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("jwt", re.compile(LEFT + r"eyJ[\w-]{10,}\.eyJ")),
    ("url_credentials", re.compile(LEFT + r"\w[\w+.-]*://[^/\s:@]+:[^/\s:@]+@")),
]

HIGH_RECALL = [
    ("config_credential",
     re.compile(r"(?i)(pass(word|wd)?|secret|token|api[_-]?key|bindpw)\s*[:=]\s*(?P<value>\S{8,})")),
]

ENTROPY_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
ENTROPY_MIN = 4.0

PLACEHOLDER_WORDS = ("example", "placeholder", "dummy", "changeme", "redacted", "sample",
                     "fake", "your_", "xxxx", "test-value", "user:password", "user:pass",
                     "username:password")
PLACEHOLDER_SHAPES = [
    re.compile(r"^[xX*]+$"),
    re.compile(r"^<[^>]*>$"),
    re.compile(r"^\$\{[^}]*\}$"),
    re.compile(r"^\$[A-Z_][A-Z0-9_]*$"),
]


def shannon(text):
    if not text:
        return 0.0
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def is_placeholder(value):
    low = value.lower()
    if any(word in low for word in PLACEHOLDER_WORDS):
        return True
    stripped = value.strip("\"'`,;")
    return any(shape.match(stripped) for shape in PLACEHOLDER_SHAPES)


def says_placeholder(line):
    """The blocking tier reads the whole line, not only the match.

    A matched value carries no context of its own, so `# the example token from the docs:
    eyJ...` and `scheme://user:password@host` both blocked on the match alone. Widening the
    word check to the line loses a real credential sitting next to the word "sample", which
    noul 5 still reports. A false block is the costlier mistake.
    """
    low = line.lower()
    return any(word in low for word in PLACEHOLDER_WORDS)


def redact(value):
    """First four characters, never the secret."""
    return value[:4] + "..." if len(value) > 4 else "..."


def added_lines(hunks):
    """[(path, text)] over added lines only.

    No `+++` guard: a hunk's text starts at its own @@ header, so a `+++ b/path` file
    header never reaches here, while `+++counter;` is real added code that used to be
    dropped along with any secret sitting on it.
    """
    out = []
    for hunk in hunks:
        for line in hunk["text"].splitlines():
            if line.startswith("+"):
                out.append((hunk["path"], line[1:]))
    return out


def scan(hunks, exclude=()):
    """Hits on added lines: {kind, path, line, precision, redacted}."""
    hits = []
    for path, line in added_lines(hunks):
        if any(fnmatch.fnmatch(path, pattern) for pattern in exclude):
            continue
        if ALLOW_MARK in line:
            continue
        for kind, pattern in HIGH_PRECISION:
            match = pattern.search(line)
            if match and not is_placeholder(match.group(0)) and not says_placeholder(line):
                hits.append({"kind": kind, "path": path, "line": line.strip()[:120],
                             "precision": "high", "redacted": redact(match.group(0))})
                break
        else:
            for kind, pattern in HIGH_RECALL:
                match = pattern.search(line)
                if match and not is_placeholder(match.group("value")):
                    hits.append({"kind": kind, "path": path, "line": line.strip()[:120],
                                 "precision": "recall", "redacted": redact(match.group("value"))})
                    break
            else:
                for run in ENTROPY_RUN.findall(line):
                    if shannon(run) >= ENTROPY_MIN and not is_placeholder(run):
                        hits.append({"kind": "high_entropy_string", "path": path,
                                     "line": line.strip()[:120], "precision": "recall",
                                     "redacted": redact(run)})
                        break
    return hits


def blocking(hits):
    return [h for h in hits if h["precision"] == "high"]
