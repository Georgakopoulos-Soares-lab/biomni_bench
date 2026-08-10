"""Tests for the Phase-2B provenance classifier (`scripts/phase2b_provenance_audit.py`).

The load-bearing property is negative: **a filesystem timestamp must never be
allowed to upgrade a file to ESTABLISHED.** mtime is settable, so treating "it
predates the run" as proof would manufacture confidence the artifacts do not
support. That is exactly the kind of silent over-claim this audit exists to
prevent, so it is asserted rather than trusted to code review.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

T0 = 1_786_300_000.0  # run start
T1 = 1_786_330_000.0  # run end


def _load():
    spec = importlib.util.spec_from_file_location("phase2b_provenance_audit", SCRIPTS / "phase2b_provenance_audit.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase2b_provenance_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


def test_a_tracked_clean_file_is_established(mod):
    klass, why = mod.classify("x.py", "sha", T0 - 1000, T0, T1, tracked=True, clean=True)
    assert klass == mod.ESTABLISHED
    assert "identical to HEAD" in why


def test_mtime_before_the_run_never_upgrades_an_untracked_file(mod):
    """The whole point: 'it looks old' is not provenance."""
    klass, why = mod.classify("x.py", "sha", T0 - 999_999, T0, T1, tracked=False, clean=False)
    assert klass == mod.UNPROVEN
    assert "circumstantial" in why


def test_modification_after_the_run_is_reported_as_changed(mod):
    klass, why = mod.classify("x.py", "sha", T1 + 1, T0, T1, tracked=False, clean=False)
    assert klass == mod.CHANGED_AFTER
    assert "after the run ended" in why


def test_modification_inside_the_run_window_is_unproven_not_changed(mod):
    """A file touched mid-run cannot be said to have 'changed after' - it may have
    been the version that ran for part of it. Refuse to guess."""
    klass, why = mod.classify("x.py", "sha", (T0 + T1) / 2, T0, T1, tracked=False, clean=False)
    assert klass == mod.UNPROVEN
    assert "inside the run window" in why


def test_a_tracked_but_modified_file_is_not_established(mod):
    klass, _ = mod.classify("x.py", "sha", T0 - 10, T0, T1, tracked=True, clean=False)
    assert klass != mod.ESTABLISHED


def test_sha256_file_matches_hashlib(mod, tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"provenance" * 1000)
    assert mod.sha256_file(p) == hashlib.sha256(b"provenance" * 1000).hexdigest()


def test_the_frozen_manifest_hash_constant_is_the_protocol_value(mod):
    """If this constant is ever edited to match a changed manifest, the audit
    would silently bless a substituted sample."""
    assert mod.FROZEN_MANIFEST_HASH == "7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd"


def test_every_in_scope_entry_names_a_real_repo_path(mod):
    repo = Path(__file__).resolve().parents[1]
    missing = [rel for rel, _ in mod.IN_SCOPE if not (repo / rel).exists()]
    assert not missing, f"IN_SCOPE lists paths that do not exist: {missing}"
