import subprocess

import pytest

# Setup git, not the hook's git: this machine has a global core.hooksPath, so every
# scratch repo pins its own.
SETUP_CFG = [
    "-c", "core.hooksPath=.git/hooks",
    "-c", "user.name=t",
    "-c", "user.email=t@t",
    "-c", "commit.gpgsign=false",
    "-c", "init.defaultBranch=main",
]


def git(repo, *args, check=True):
    proc = subprocess.run(
        ["git", "-C", str(repo)] + SETUP_CFG + list(args),
        capture_output=True, text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), proc.stderr))
    return proc


def write(repo, name, text):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def commit(repo, name, text, message):
    write(repo, name, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    return path
