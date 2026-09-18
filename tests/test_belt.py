import pytest

from jev_commit import belt
from jev_commit.record import load_corpus

VENDOR_POSITIVES = [
    ("aws_access_key", "AWS_ACCESS_KEY_ID=AKIA2X7QF4LMZ3VBNTYE"),
    ("github_pat", "token: github_pat_11ABCDEFG0aZ4rTuVwXy2Kq7LmNpQrStUvWxYz01234567"),
    ("github_token", "GITHUB_TOKEN=ghp_EzSQ8bZBuYZ1vkmATAmbMbFVdTKuGd8SA15p"),
    ("anthropic_key", 'key = "sk-ant-api03-7Hn2Kq4RtYu8Wz1Bc3Df5Gh7Jk9Lm0Np"'),
    ("openai_key", "OPENAI_API_KEY=sk-Xy7Kq2RtYu8Wz1Bc3Df5Gh7J"),
    ("slack_token", "SLACK_BOT_TOKEN=xoxb-2847193052-4471928374-Kq7RtYu8Wz1Bc3Df"),
    ("google_api_key", "maps_key: AIzaSyD4kQ2r7TvXw9Yz1Bc3Df5Gh7Jk9Lm0Np1"),
    ("gitlab_token", "CI_TOKEN=glpat-Kq7RtYu8Wz1Bc3Df5Gh7"),
    ("sendgrid_key", "SENDGRID=SG.Kq7RtYu8Wz1Bc3Df5Gh7Jk.Np1Qr3St5Uv7Wx9Yz0Ab2Cd4Ef6Gh8Jk0Lm2"),
    ("npm_token", "//registry.npmjs.org/:_authToken=npm_Kq7RtYu8Wz1Bc3Df5Gh7Jk9Lm0Np1Qr3StUv"),
    ("private_key", "-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("jwt", "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.Kq7RtYu8"),
    ("url_credentials", "DATABASE_URL=postgres://warehouse:Beacon-3061@db01.internal:5432/app"),
]


def hunk(path, *lines):
    return [{"path": path, "text": "@@ -0,0 +1,%d @@\n" % len(lines) + "\n".join("+" + x for x in lines)}]


@pytest.mark.parametrize("kind,line", VENDOR_POSITIVES)
def test_every_high_precision_pattern_fires(kind, line):
    hits = belt.scan(hunk(".env", line))
    assert [h["kind"] for h in hits] == [kind]
    assert hits[0]["precision"] == "high"
    assert len(hits[0]["redacted"]) <= 7


def test_the_report_never_carries_the_secret():
    hits = belt.scan(hunk(".env", "GITHUB_TOKEN=ghp_EzSQ8bZBuYZ1vkmATAmbMbFVdTKuGd8SA15p"))
    assert hits[0]["redacted"] == "ghp_..."
    assert "EzSQ8bZBuYZ1" not in hits[0]["redacted"]


@pytest.mark.parametrize("line", [
    "GITHUB_TOKEN=ghp_your_token_here_xxxxxxxxxxxxxxxxx",
    "OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXX",
    "password = <your password>",
    "api_key = ${LARKSPUR_GATEWAY_KEY}",
    "SECRET_KEY=changeme-before-deploying-this",
])
def test_placeholders_are_suppressed(line):
    assert belt.scan(hunk(".env.example", line)) == []


def test_allow_comment_and_exclude_globs():
    line = "GITHUB_TOKEN=ghp_EzSQ8bZBuYZ1vkmATAmbMbFVdTKuGd8SA15p  # jev-commit: allow"
    assert belt.scan(hunk("docs/rotate.md", line)) == []
    real = "GITHUB_TOKEN=ghp_EzSQ8bZBuYZ1vkmATAmbMbFVdTKuGd8SA15p"
    assert belt.scan(hunk("tests/fixtures/keys.txt", real), exclude=["tests/fixtures/*"]) == []
    assert belt.scan(hunk("tests/fixtures/keys.txt", real)) != []


def test_removed_lines_are_not_scanned():
    hunks = [{"path": ".env", "text": "@@ -1,2 +1,1 @@\n-GITHUB_TOKEN=ghp_EzSQ8bZBuYZ1vkmATAmbMbFVdTKuGd8SA15p\n KEEP=1"}]
    assert belt.scan(hunks) == []


def test_entropy_rule_catches_an_unprefixed_random_string():
    hits = belt.scan(hunk("deploy/keys.txt", "session = " + "Kq7RtYu8Wz1Bc3Df5Gh7Jk9Lm0Np1Qr3St5Uv7Wx"))
    assert hits and hits[0]["precision"] == "recall"


def test_a_commit_sha_does_not_trip_the_entropy_rule():
    assert belt.scan(hunk("CHANGELOG.md", "pinned at 9f1c2d3e4b5a60718293a4b5c6d7e8f90a1b2c3d")) == []


def test_no_config_shaped_case_blocks():
    """The whole point of the 15/20 number: this class is out of the belt's reach."""
    cases = load_corpus("secret")
    assert len(cases) == 20
    blocked = [c["id"] for c in cases if belt.blocking(belt.scan(c["hunks"]))]
    assert blocked == []


def test_the_recall_pattern_reaches_some_of_them_and_decides_none():
    cases = load_corpus("secret")
    flagged = {c["id"] for c in cases if belt.scan(c["hunks"])}
    secrets = {c["id"] for c in cases if c["label"]["secret"]}
    assert flagged & secrets, "the recall pattern should reach the delimited ones"
    assert flagged - secrets, "and it flags non-secrets too, which is why the noul decides"


BOUNDARY_NEGATIVES = [
    ("sk- inside a word", 'label = "risk-Kq7RtYu8Wz1Bc3Df5Gh7Jk9"'),
    ("sk- as a css class", ".desk-Kq7RtYu8Wz1Bc3Df5Gh7Jk9 { display: none; }"),
    ("AIza inside base64", 'blob = "xzAIzaSyD4kQ2r7TvXw9Yz1Bc3Df5Gh7Jk9Lm0Np1XYZ=="'),
]

CONTEXT_NEGATIVES = [
    ("a DSN spelled out in docs", "# format: scheme://user:password@host:port/path"),
    ("the jwt.io token in a comment",
     "# example token from the docs: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.Kq7RtYu8"),
]


def scan_one(line, path="src/app.py"):
    return belt.scan([{"path": path, "text": "@@ -1 +1 @@\n+" + line}])


@pytest.mark.parametrize("why,line", BOUNDARY_NEGATIVES)
def test_a_prefix_mid_token_never_blocks(why, line):
    assert belt.blocking(scan_one(line)) == [], why


@pytest.mark.parametrize("why,line", CONTEXT_NEGATIVES)
def test_a_line_that_calls_itself_an_example_never_blocks(why, line):
    assert belt.blocking(scan_one(line)) == [], why


def test_an_added_line_starting_with_plus_is_still_scanned():
    """`+++counter;` is C, not a diff header: a hunk starts at its own @@ line."""
    hits = scan_one("+++counter; // AKIA2X7QF4LMZ3VBNTYE")
    assert [h["kind"] for h in belt.blocking(hits)] == ["aws_access_key"]


def test_the_real_shapes_still_block_behind_the_left_anchor():
    for kind, line in VENDOR_POSITIVES:
        assert [h["kind"] for h in belt.blocking(scan_one(line))] == [kind], line
