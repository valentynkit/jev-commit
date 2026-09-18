import os
import subprocess

from jev_commit import git as g
from conftest import commit, git, write


def test_child_env_drops_git_vars_and_the_key():
    env = g.child_env({"GIT_DIR": "/evil", "GIT_INDEX_FILE": "x", "TYPESAFE_API_KEY": "sk-live",
                       "JEV_BASE_URL": "http://x", "PATH": "/usr/bin", "HOME": "/home/t"})
    assert "GIT_DIR" not in env and "GIT_INDEX_FILE" not in env
    assert "TYPESAFE_API_KEY" not in env and "JEV_BASE_URL" not in env
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/t"
    assert env["GIT_NO_LAZY_FETCH"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "" and env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_argv_carries_the_lockdown():
    argv = g.git_argv(["diff", "--cached"])
    assert argv[:3] == ["git", "--no-pager", "--literal-pathspecs"]
    for cfg in ("core.hooksPath=/dev/null", "protocol.allow=never", "credential.helper=",
                "diff.external=", "core.attributesFile=/dev/null"):
        assert cfg in argv
    assert g.DIFF_FLAGS == ["--no-color", "--no-ext-diff", "--no-textconv"]


def test_textconv_in_the_repo_does_not_run(repo, tmp_path):
    marker = tmp_path / "textconv-fired"
    script = tmp_path / "evil.sh"
    script.write_text("#!/bin/sh\ntouch %s\ncat \"$1\"\n" % marker)
    script.chmod(0o755)
    commit(repo, "creds.secret", "one\n", "add creds")
    write(repo, ".gitattributes", "*.secret diff=evil\n")
    git(repo, "config", "diff.evil.textconv", str(script))
    write(repo, "creds.secret", "two\n")
    git(repo, "add", "-A")

    out = g.capture(cwd=repo)
    assert not marker.exists(), "textconv ran under the lockdown"
    assert "two" in out["patch"]

    # The same repo without the lockdown: proof the attack was live.
    subprocess.run(["git", "-C", str(repo), "diff", "--cached"], capture_output=True)
    assert marker.exists()


def test_plain_commit_uses_the_index(repo):
    commit(repo, "a.py", "x = 1\n", "add a")
    write(repo, "a.py", "x = 2\n")
    git(repo, "add", "-A")
    assert g.select_base(repo) == (None, "index")
    assert "x = 2" in g.capture(cwd=repo)["patch"]


def test_amend_with_nothing_staged_rebases_to_head_parent(repo):
    commit(repo, "a.py", "x = 1\n", "add a")
    commit(repo, "b.py", "y = 1\n", "add b")
    assert g.select_base(repo) == ("HEAD^", "amend")
    out = g.capture(cwd=repo)
    assert out["mode"] == "amend" and "y = 1" in out["patch"]


def test_staged_amend_sees_only_the_new_delta(repo):
    commit(repo, "a.py", "x = 1\n", "add a")
    commit(repo, "b.py", "y = 1\n", "add b")
    write(repo, "c.py", "z = 1\n")
    git(repo, "add", "-A")
    out = g.capture(cwd=repo)
    assert out["mode"] == "index"
    assert "z = 1" in out["patch"] and "y = 1" not in out["patch"]

    forced = g.capture(cwd=repo, amend_base=True)
    assert forced["mode"] == "amend"
    assert "z = 1" in forced["patch"] and "y = 1" in forced["patch"]


def test_root_commit_with_a_clean_index_is_empty(repo):
    commit(repo, "a.py", "x = 1\n", "add a")
    assert g.select_base(repo) == (None, "empty")
    assert g.capture(cwd=repo)["patch"] == ""
    # --amend-base on a root commit has nothing to rebase to and stays on the index.
    assert g.select_base(repo, amend_base=True) == (None, "index")


def test_first_commit_has_no_head(repo):
    write(repo, "a.py", "x = 1\n")
    git(repo, "add", "-A")
    assert g.select_base(repo) == (None, "index")
    assert "x = 1" in g.capture(cwd=repo)["patch"]


def test_output_over_the_cap_is_truncated(repo, monkeypatch):
    write(repo, "big.txt", "line\n" * 50000)
    git(repo, "add", "-A")
    monkeypatch.setattr(g, "MAX_BYTES", 4096)
    out = g.capture(cwd=repo)
    assert out["truncated"] and len(out["patch"]) <= 4096


def test_parse_name_status_keeps_the_new_path_of_a_rename():
    text = "M\0src/a.py\0R100\0src/old.py\0src/new.py\0A\0src/c.py\0"
    assert g.parse_name_status(text) == {"src/a.py": "M", "src/new.py": "R100", "src/c.py": "A"}


def test_strip_message_cuts_comments_and_scissors():
    raw = "fix: null check\n\nwhy it matters\n# please enter\n# ------------------------ >8 ------------------------\ndiff --git a/x b/x\n"
    assert g.strip_message(raw) == "fix: null check\n\nwhy it matters"
