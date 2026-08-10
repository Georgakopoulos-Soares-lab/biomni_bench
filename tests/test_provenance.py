"""Tests for the D-36 process-debt closures: the dirty-tree launch guard and
per-trajectory source hashing (`reports/phase2b_provenance.md`, D-29, D-36).

Real git repositories are used throughout rather than mocked subprocess calls -
`assert_clean_tree` exists specifically because `git status --porcelain` is the
ground truth this project has to trust, so a test that mocks it away would not
be testing the thing that failed in Phase 2B.
"""

from __future__ import annotations

import subprocess

import pytest

from biomni_uncertainty.provenance import DirtyTreeError, assert_clean_tree, source_hashes


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def clean_repo(tmp_path):
    repo = tmp_path / "clean"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "a.txt").write_text("hello")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture
def dirty_repo(clean_repo):
    (clean_repo / "a.txt").write_text("changed, uncommitted")
    return clean_repo


# --------------------------------------------------------------------------
# assert_clean_tree
# --------------------------------------------------------------------------


def test_clean_tree_passes_silently(clean_repo):
    info = assert_clean_tree(clean_repo)
    assert info["dirty"] is False
    assert "warning" not in info


def test_dirty_tree_raises_by_default(dirty_repo):
    """This is the launch-time guard D-29 needed and did not have: a prospective
    run must not be able to start from an uncommitted tree."""
    with pytest.raises(DirtyTreeError, match="DIRTY TREE"):
        assert_clean_tree(dirty_repo)


def test_dirty_tree_with_allow_dirty_returns_a_warning_instead_of_raising(dirty_repo, capsys):
    info = assert_clean_tree(dirty_repo, allow_dirty=True)
    assert info["dirty"] is True
    assert "warning" in info and "DIRTY TREE" in info["warning"]
    # written to stderr, not silently swallowed
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "DIRTY TREE" in captured.err


def test_allow_dirty_warning_is_written_to_the_given_log_path(dirty_repo, tmp_path):
    log = tmp_path / "run.log"
    assert_clean_tree(dirty_repo, allow_dirty=True, log_path=log)
    assert "DIRTY TREE" in log.read_text()


def test_a_repo_with_only_untracked_files_still_counts_as_dirty(clean_repo):
    """git status --porcelain reports untracked files too - an untracked new
    controller module (exactly D-29's failure) must trip the guard."""
    (clean_repo / "untracked.py").write_text("# new file, never added")
    with pytest.raises(DirtyTreeError):
        assert_clean_tree(clean_repo)


def test_nonexistent_repo_path_does_not_raise_dirty_tree_error(tmp_path):
    """git_info already returns dirty=None for a path with no git history;
    assert_clean_tree must not misinterpret that as dirty."""
    info = assert_clean_tree(tmp_path / "does_not_exist")
    assert info["dirty"] is None


# --------------------------------------------------------------------------
# source_hashes
# --------------------------------------------------------------------------


def test_source_hashes_populates_from_matching_files(tmp_path):
    (tmp_path / "src" / "biomni_uncertainty").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "biomni_uncertainty" / "foo.py").write_text("x = 1\n")
    (tmp_path / "scripts" / "bar.py").write_text("y = 2\n")
    (tmp_path / "scripts" / "not_python.txt").write_text("irrelevant")

    hashes = source_hashes(tmp_path)
    assert "src/biomni_uncertainty/foo.py" in hashes
    assert "scripts/bar.py" in hashes
    assert not any(k.endswith("not_python.txt") for k in hashes)
    assert all(len(v) == 16 for v in hashes.values())


def test_source_hashes_changes_when_a_file_changes(tmp_path):
    d = tmp_path / "src" / "biomni_uncertainty"
    d.mkdir(parents=True)
    f = d / "foo.py"
    f.write_text("x = 1\n")
    before = source_hashes(tmp_path)["src/biomni_uncertainty/foo.py"]

    f.write_text("x = 2\n")
    after = source_hashes(tmp_path)["src/biomni_uncertainty/foo.py"]

    assert before != after


def test_source_hashes_is_stable_for_unchanged_content(tmp_path):
    d = tmp_path / "src" / "biomni_uncertainty"
    d.mkdir(parents=True)
    (d / "foo.py").write_text("x = 1\n")
    assert source_hashes(tmp_path) == source_hashes(tmp_path)


def test_source_hashes_on_a_directory_with_no_matching_files_is_empty(tmp_path):
    (tmp_path / "src" / "biomni_uncertainty").mkdir(parents=True)
    assert source_hashes(tmp_path) == {}
