"""Capturing the message and the staged diff, under the commit-miner lockdown.

Every call is an argv array with the same hardened config and a stripped environment,
because the child reads bytes an attacker may have written (commit-miner src/git.rs:35-77,
commit 977617e). Four additions beyond that list: --no-textconv and --no-ext-diff, since a
repo's .gitattributes can point a path at a command git would otherwise run, and
credential.helper= plus GIT_ASKPASS="", which closes the helper path GIT_TERMINAL_PROMPT=0
leaves open.
"""

import os
import re
import subprocess

GIT_CFG = [
    "core.hooksPath=/dev/null",
    "core.fsmonitor=false",
    "core.quotePath=true",
    "core.alternateRefsCommand=:",
    "core.attributesFile=/dev/null",
    "color.ui=false",
    "log.showSignature=false",
    "gc.auto=0",
    "maintenance.auto=false",
    "fetch.recurseSubmodules=false",
    "submodule.recurse=false",
    "protocol.allow=never",
    "credential.helper=",
    "diff.external=",
]

GIT_ENV = {
    "GIT_ALLOW_PROTOCOL": "",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_LFS_SKIP_SMUDGE": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
}

# The key never enters the child env: the child reads attacker-shaped bytes.
SECRET_ENV = ("TYPESAFE_API_KEY", "JEV_API_KEY", "TYPESAFE_BASE_URL", "JEV_BASE_URL")

TIMEOUT_S = 10
MAX_BYTES = 10 * 1024 * 1024

DIFF_FLAGS = ["--no-color", "--no-ext-diff", "--no-textconv"]


class GitError(Exception):
    pass


def child_env(env=None):
    out = dict(os.environ if env is None else env)
    for name in list(out):
        if name.startswith("GIT_") or name in SECRET_ENV:
            del out[name]
    out.update(GIT_ENV)
    return out


def git_argv(args):
    argv = ["git", "--no-pager", "--literal-pathspecs"]
    for cfg in GIT_CFG:
        argv += ["-c", cfg]
    return argv + list(args)


def run_git(args, cwd=None, env=None, check=True, timeout=TIMEOUT_S):
    """Returns (text, returncode, truncated). Output past 10 MB is dropped, not buffered further."""
    try:
        proc = subprocess.run(
            git_argv(args),
            cwd=cwd,
            env=child_env(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError("git timed out after %ds" % timeout) from exc
    if check and proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", "replace").strip()[:300] or "git exited %d" % proc.returncode)
    raw = proc.stdout
    truncated = len(raw) > MAX_BYTES
    return raw[:MAX_BYTES].decode("utf-8", "replace"), proc.returncode, truncated


def _resolves(rev, cwd=None):
    _, code, _ = run_git(["rev-parse", "--verify", "--quiet", rev + "^{commit}"], cwd=cwd, check=False)
    return code == 0


def staged_is_empty(cwd=None):
    _, code, _ = run_git(["diff", "--cached", "--quiet"] + DIFF_FLAGS, cwd=cwd, check=False)
    return code == 0


def select_base(cwd=None, amend_base=False):
    """(base, mode). mode is index, amend or empty.

    A commit-msg hook cannot tell an amend from a plain commit: the env is byte-identical.
    So the only detectable amend is the one with nothing newly staged, where --cached is
    empty and HEAD^ holds the real diff. That path warns and never blocks, because
    --allow-empty lands there too. With a root commit there is no HEAD^ to fall back to.
    """
    if amend_base:
        if _resolves("HEAD^", cwd):
            return "HEAD^", "amend"
        return None, "index"  # root commit, nothing to compare against
    if staged_is_empty(cwd):
        if _resolves("HEAD^", cwd):
            return "HEAD^", "amend"
        return None, "empty"
    return None, "index"


def capture(cwd=None, amend_base=False):
    """Two lockdown git calls: the name-status table and the -U2 patch."""
    base, mode = select_base(cwd, amend_base)
    if mode == "empty":
        return {"mode": mode, "base": None, "name_status": "", "patch": "", "truncated": False}
    tail = ([base] if base else []) + ["--"]
    names, _, cut_a = run_git(["diff", "--cached"] + DIFF_FLAGS + ["--name-status", "-z"] + tail, cwd=cwd)
    patch, _, cut_b = run_git(["diff", "--cached"] + DIFF_FLAGS + ["-U2"] + tail, cwd=cwd)
    return {"mode": mode, "base": base, "name_status": names, "patch": patch, "truncated": cut_a or cut_b}


def parse_name_status(text):
    """NUL-delimited pairs; renames and copies carry two paths, and we keep the new one."""
    parts = [p for p in text.split("\0") if p != ""]
    out = {}
    i = 0
    while i < len(parts):
        status = parts[i]
        if status[0] in "RC" and i + 2 < len(parts):
            out[parts[i + 2]] = status
            i += 3
        elif i + 1 < len(parts):
            out[parts[i + 1]] = status
            i += 2
        else:
            break
    return out


SCISSORS = re.compile(r"^-{4,}\s*>8\s*-{4,}")


def strip_message(text):
    """Drop comment lines and everything past the scissors line git writes under --verbose."""
    lines = []
    for line in text.splitlines():
        if SCISSORS.match(line.lstrip("#").strip()):
            break
        if line.startswith("#"):
            continue
        lines.append(line.rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)
