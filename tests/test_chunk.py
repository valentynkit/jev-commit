from jev_commit import chunk as c

PATCH = """diff --git a/src/parser.py b/src/parser.py
index 1111111..2222222 100644
--- a/src/parser.py
+++ b/src/parser.py
@@ -10,3 +10,4 @@ def parse(text):
     if text is None:
+        return None
     return text.split()
diff --git a/uv.lock b/uv.lock
index 3333333..4444444 100644
--- a/uv.lock
+++ b/uv.lock
@@ -1,2 +1,3 @@
 version = 1
+name = "x"
 requires-python = ">=3.10"
"""


def test_token_estimate_matches_the_ported_formula():
    assert c.estimate_tokens("hello") == 1
    assert c.estimate_tokens("verylongidentifier") == 3
    assert c.estimate_tokens("1234") == 2
    assert c.estimate_tokens("a + b") == 3


def test_parse_patch_reads_paths_and_counts():
    files = c.parse_patch(PATCH)
    assert [f["path"] for f in files] == ["src/parser.py", "uv.lock"]
    assert files[0]["added"] == 1 and files[0]["removed"] == 0
    assert files[0]["hunks"][0].startswith("@@ -10,3 +10,4 @@")


def test_deleted_file_keeps_its_old_path():
    patch = ("diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n"
             "@@ -1,2 +0,0 @@\n-x = 1\n-y = 2\n")
    files = c.parse_patch(patch)
    assert files[0]["path"] == "gone.py" and files[0]["removed"] == 2


def test_lockfiles_and_minified_degrade_to_counts():
    prep = c.prepare(PATCH, {"src/parser.py": "M", "uv.lock": "M"})
    assert [t["path"] for t in prep["files"]] == ["src/parser.py", "uv.lock"]
    assert [h["path"] for h in prep["hunks"]] == ["src/parser.py"]
    assert prep["omitted"] == "counts only: uv.lock"
    minified = {"path": "web/app.min.js", "added": 1, "removed": 0, "binary": False, "hunks": ["@@\n+var a=1"]}
    long_line = {"path": "data/blob.json", "added": 1, "removed": 0, "binary": False,
                 "hunks": ["@@\n+" + "x" * 900]}
    assert c.is_degraded(minified) and c.is_degraded(long_line)
    assert not c.is_degraded({"path": "src/a.py", "added": 0, "removed": 0, "binary": False,
                              "hunks": ["@@\n+x = 1"]})


def test_binary_file_never_reaches_the_hunks():
    patch = "diff --git a/logo.png b/logo.png\n--- a/logo.png\n+++ b/logo.png\nBinary files a/logo.png and b/logo.png differ\n"
    prep = c.prepare(patch)
    assert prep["files"][0]["path"] == "logo.png" and prep["hunks"] == []
    assert "logo.png" in prep["omitted"]


def test_per_file_cap_keeps_the_ends_and_says_what_it_dropped():
    hunks = ["@@ -%d,2 +%d,3 @@\n+%s\n context\n" % (i, i, "payload " * 40) for i in range(60)]
    kept = c.cap_file({"path": "src/big.py", "added": 60, "removed": 0, "binary": False, "hunks": hunks})
    assert kept[0] == hunks[0] and kept[-1] == hunks[-1]
    assert kept[1] == "58 hunks omitted (58 added, 0 removed)"
    assert c.estimate_tokens("\n".join(kept)) <= c.PER_FILE_TOKENS


def test_a_two_megabyte_diff_splits_into_chunks_under_budget():
    body = "\n".join("+line %d of a real looking change" % i for i in range(30))
    parts = []
    for n in range(2000):
        parts.append(
            "diff --git a/src/mod%03d.py b/src/mod%03d.py\n--- a/src/mod%03d.py\n+++ b/src/mod%03d.py\n"
            "@@ -1,2 +1,32 @@\n%s\n" % (n, n, n, n, body)
        )
    patch = "".join(parts)
    assert len(patch) > 2_000_000
    prep = c.prepare(patch)
    states = c.chunk_states("feat: add two thousand modules", prep)
    assert len(states) > 1
    for state in states:
        assert c.estimate_tokens(repr(state)) <= c.BUDGET_TOKENS
        assert state["files"] == prep["files"], "every chunk carries the file table"
        assert state["note"] == c.NOTE
        assert state["message"] == "feat: add two thousand modules"
    assert sum(len(s["hunks"]) for s in states) == len(prep["hunks"])
    assert "more files" in states[0]["more"]


def test_quoted_paths_decode_to_the_name_git_reports():
    """core.quotePath is pinned on, so every non-ASCII path arrives C-quoted."""
    patch = ('diff --git "a/h\\303\\251llo.txt" "b/h\\303\\251llo.txt"\n'
             '--- "a/h\\303\\251llo.txt"\n+++ "b/h\\303\\251llo.txt"\n@@ -1 +1 @@\n+x\n')
    assert c.parse_patch(patch)[0]["path"] == "h\u00e9llo.txt"
    # The name-status side never quotes, so the two must agree for the join to work.
    prep = c.prepare(patch, {"h\u00e9llo.txt": "A"})
    assert prep["files"][0] == {"path": "h\u00e9llo.txt", "status": "A", "added": 1, "removed": 0}


def test_a_path_with_a_space_keeps_no_trailing_tab():
    patch = ("diff --git a/has space.txt b/has space.txt\n--- a/has space.txt\t\n"
             "+++ b/has space.txt\t\n@@ -1 +1 @@\n+x\n")
    assert c.parse_patch(patch)[0]["path"] == "has space.txt"


def test_blocks_with_no_hunks_still_show_up():
    """A rename, a mode change and a new empty file carry no ---/+++ pair."""
    rename = ("diff --git a/a.txt b/b.txt\nsimilarity index 100%\n"
              "rename from a.txt\nrename to b.txt\n")
    mode = "diff --git a/s.sh b/s.sh\nold mode 100644\nnew mode 100755\n"
    empty = "diff --git a/new.py b/new.py\nnew file mode 100644\nindex 0000000..e69de29\n"
    assert [f["path"] for f in c.parse_patch(rename)] == ["b.txt"]
    assert [f["path"] for f in c.parse_patch(mode)] == ["s.sh"]
    assert [f["path"] for f in c.parse_patch(empty)] == ["new.py"]
    assert [t["path"] for t in c.prepare(rename + mode + empty)["files"]] == [
        "b.txt", "new.py", "s.sh"]


def test_generated_dirs_match_a_segment_not_a_substring():
    def f(path):
        return {"path": path, "added": 0, "removed": 0, "binary": False, "hunks": ["@@\n+x"]}

    assert c.is_degraded(f("dist/bundle.js")) and c.is_degraded(f("web/vendor/x.go"))
    assert not c.is_degraded(f("mybuild/x.py"))
    assert not c.is_degraded(f("myvendor/config.py"))
    assert not c.is_degraded(f("childtarget/Main.java"))


def test_two_huge_hunks_are_capped_like_any_other_file():
    """Capping only at three or more hunks left this file over the cap and unsplittable."""
    huge = "@@ -1 +1 @@\n" + "+x = {'a': 1, 'b': [2, 3]};  # }{)(*&^%$#@!\n" * 4000
    kept = c.cap_file({"path": "big.py", "added": 0, "removed": 0, "binary": False,
                       "hunks": [huge, huge]})
    assert c.estimate_tokens("\n".join(kept)) <= c.PER_FILE_TOKENS
    single = c.cap_file({"path": "big.py", "added": 0, "removed": 0, "binary": False,
                         "hunks": [huge]})
    assert c.estimate_tokens("\n".join(single)) <= c.PER_FILE_TOKENS


def test_a_giant_message_cannot_blow_the_budget():
    """Bisecting hunks cannot shrink a state the message alone overflows."""
    message = "\n".join("* fix thing %d in module %d" % (i, i) for i in range(6000))
    assert c.estimate_tokens(message) > c.BUDGET_TOKENS
    for state in c.chunk_states(message, c.prepare(PATCH)):
        assert c.estimate_tokens(repr(state)) <= c.BUDGET_TOKENS


def test_the_belt_sees_hunks_the_budget_dropped():
    """all_hunks is undegraded and uncapped: a regex costs no tokens."""
    patch = ("diff --git a/vendor/key.pem b/vendor/key.pem\n--- /dev/null\n"
             "+++ b/vendor/key.pem\n@@ -0,0 +1 @@\n+-----BEGIN OPENSSH PRIVATE KEY-----\n")
    prep = c.prepare(patch)
    assert prep["hunks"] == [], "vendor/ still degrades for Jev"
    assert "PRIVATE KEY" in prep["all_hunks"][0]["text"]


def test_bisect_splits_a_state_and_keeps_the_table():
    prep = c.prepare(PATCH)
    state = c.build_state("m", prep, [{"path": "a", "text": "@@\n+1"}, {"path": "b", "text": "@@\n+2"}])
    left, right = c.bisect(state)
    assert left["hunks"] == [{"path": "a", "text": "@@\n+1"}]
    assert right["hunks"] == [{"path": "b", "text": "@@\n+2"}]
    assert left["files"] == right["files"] == prep["files"]
    assert c.bisect(left) == []
