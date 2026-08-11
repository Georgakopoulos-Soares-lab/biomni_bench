"""Tests for the pre-commit shrink guard (`scripts/git_hooks/pre-commit`).

D-27's lesson, applied: a guard whose FAILURE path has never been exercised is
not a guard. Every test here drives the real hook through a real `git commit` in
a real temporary repository — no mocking of git, because `git commit`'s exit
status is precisely the behaviour being relied on.

The motivating incident (2026-08-11): `DECISIONS.md`, 1585 lines, was reduced to
a single character in the working tree. `git add -A && git commit` would have
committed the loss silently.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "git_hooks" / "pre-commit"


def _git(repo: Path, *args, env=None, check=True):
    e = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(repo)}
    if env:
        e.update(env)
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, env=e, check=check
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "commit.gpgsign", "false")
    hooks = r / "hooks"
    hooks.mkdir()
    dst = hooks / "pre-commit"
    dst.write_text(HOOK.read_text())
    dst.chmod(0o755)
    _git(r, "config", "core.hooksPath", "hooks")
    # A tracked file big enough to judge, mirroring DECISIONS.md's role.
    (r / "DECISIONS.md").write_text("# Design decisions\n" + ("x" * 4000) + "\n")
    (r / "small.txt").write_text("tiny\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "baseline", check=False)
    return r


def test_the_guard_refuses_a_catastrophic_truncation(repo):
    """THE motivating case: 4000 bytes -> 1 character."""
    (repo / "DECISIONS.md").write_text("w")
    _git(repo, "add", "-A")
    out = _git(repo, "commit", "-m", "oops", check=False)
    assert out.returncode != 0, "the guard must refuse this commit"
    assert "REFUSING TO COMMIT" in out.stderr
    assert "DECISIONS.md" in out.stderr
    # and the loss is genuinely not committed
    assert "baseline" in _git(repo, "log", "--oneline").stdout


def test_an_ordinary_edit_is_allowed(repo):
    (repo / "DECISIONS.md").write_text("# Design decisions\n" + ("x" * 3900) + "\nnew line\n")
    _git(repo, "add", "-A")
    out = _git(repo, "commit", "-m", "normal edit", check=False)
    assert out.returncode == 0, out.stderr


def test_a_substantial_but_not_catastrophic_deletion_is_allowed(repo):
    """Half the file is a big edit, not a wipe. The guard must not cry wolf, or
    it will be disabled and stop protecting anything."""
    (repo / "DECISIONS.md").write_text("# Design decisions\n" + ("x" * 2000) + "\n")
    _git(repo, "add", "-A")
    out = _git(repo, "commit", "-m", "big but legitimate edit", check=False)
    assert out.returncode == 0, out.stderr


def test_the_override_is_honoured_and_logged(repo):
    (repo / "DECISIONS.md").write_text("w")
    _git(repo, "add", "-A")
    out = _git(repo, "commit", "-m", "deliberate", env={"BIOMNI_ALLOW_SHRINK": "1"}, check=False)
    assert out.returncode == 0, out.stderr
    assert "overridden" in out.stderr
    log = repo / ".git" / "shrink_guard.log"
    assert log.exists(), "an override must leave a record; a silent override is the failure mode"
    assert "OVERRIDE" in log.read_text() and "DECISIONS.md" in log.read_text()


def test_a_new_file_is_not_flagged(repo):
    """A brand-new small file has no committed size to shrink from."""
    (repo / "brand_new.txt").write_text("a")
    _git(repo, "add", "-A")
    out = _git(repo, "commit", "-m", "add a new tiny file", check=False)
    assert out.returncode == 0, out.stderr


def test_a_deliberate_deletion_is_not_flagged(repo):
    """Removing a file is not the failure mode this guard is for; conflating the
    two would make deletions require an override and train people to set it."""
    (repo / "DECISIONS.md").unlink()
    _git(repo, "add", "-A")
    out = _git(repo, "commit", "-m", "remove a file on purpose", check=False)
    assert out.returncode == 0, out.stderr


def test_tiny_files_are_ignored(repo):
    """Below the byte floor the percentage is meaningless."""
    (repo / "small.txt").write_text("t")
    _git(repo, "add", "-A")
    out = _git(repo, "commit", "-m", "shrink a tiny file", check=False)
    assert out.returncode == 0, out.stderr
