"""Pin Phase 2's frozen constants and structural guarantees.

`scripts/scope_main_verifier_run.py`, `scope_main_detection_analysis.py` and
`scope_main_h1_verdict.py` implement `reports/scope_study_preregistration.md`
SS4-SS5. These tests catch a later edit silently drifting from that document,
the same discipline `tests/test_stage_c_analyze.py` applies to D-38's `gap/3`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scope_main_h1_verdict import (  # noqa: E402
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    CAPABILITY_CONFOUND_CI_UPPER_BOUND,
    GUARD_MIN_ABS_HEADROOM,
    GUARD_MIN_RECOVERABLE_N,
    h1_row,
    paired_bootstrap,
)
from scope_main_verifier_run import N_EVALUATIONS  # noqa: E402

PREREG = ROOT / "reports" / "scope_study_preregistration.md"


def test_bootstrap_constants_match_the_preregistration():
    assert BOOTSTRAP_REPLICATES == 10_000
    assert BOOTSTRAP_SEED == 20260813
    text = PREREG.read_text()
    assert "10,000 replicates, resampling the instance, seed 20260813" in text


def test_capability_confound_bar_matches_the_preregistration():
    assert CAPABILITY_CONFOUND_CI_UPPER_BOUND == -0.15
    assert "upper bound < −0.15**" in PREREG.read_text()


def test_denominator_guard_matches_the_preflight():
    assert GUARD_MIN_ABS_HEADROOM == 0.10
    assert GUARD_MIN_RECOVERABLE_N == 5


def test_scoring_config_matches_stage_c_unchanged():
    """K=8 repeated evaluations, the one number most tempting to change for speed."""
    assert N_EVALUATIONS == 8


def test_paired_bootstrap_is_instance_clustered_and_deterministic():
    import numpy as np

    delta = np.array([1.0, 1.0, -1.0, -1.0, 0.0])
    lo1, hi1 = paired_bootstrap(delta, seed=1, n=500)
    lo2, hi2 = paired_bootstrap(delta, seed=1, n=500)
    assert (lo1, hi1) == (lo2, hi2)  # deterministic under a fixed seed
    assert lo1 <= 0.0 <= hi1  # symmetric data straddles zero


# --------------------------------------------------------------------------
# H1 verdict table -- every branch of the frozen four-row rule
# --------------------------------------------------------------------------


def _arm(detection_established: bool, correction_established: bool) -> dict:
    return {
        "detection": {"detection_established": detection_established},
        "correction_established": correction_established,
    }


def test_h1_replicated_when_both_arms_show_the_separation():
    verdict, _ = h1_row(_arm(True, False), _arm(True, False))
    assert verdict == "REPLICATED"


def test_h1_not_replicated_when_correction_is_solver_specific():
    verdict, reason = h1_row(_arm(True, False), _arm(True, True))
    assert verdict == "NOT REPLICATED"
    assert "solver-specific" in reason


def test_h1_not_replicated_when_detection_absent_for_b():
    verdict, reason = h1_row(_arm(True, False), _arm(False, False))
    assert verdict == "NOT REPLICATED"
    assert "detection not established for Solver B" in reason


def test_h1_mixed_when_a_lacks_detection_but_b_shows_full_separation():
    """Not row 1 (A has no detection to separate on), not row 2 (needs A's
    separation to hold), not row 3 (B's detection IS established) -> MIXED,
    the pre-registered catch-all for a combination none of the three rows names.
    """
    verdict, _ = h1_row(_arm(False, True), _arm(True, False))
    assert verdict == "MIXED"


def test_h1_not_replicated_when_b_detection_absent_even_if_a_also_lacks_it():
    """Row 3 ("detection not established for B") is unconditional on A's state
    as written in the preregistration -- it fires whenever B lacks detection,
    not only when A has it.
    """
    verdict, reason = h1_row(_arm(False, True), _arm(False, True))
    assert verdict == "NOT REPLICATED"
    assert "detection not established for Solver B" in reason


def test_prereg_verdict_rows_are_all_reachable_from_h1_row():
    text = PREREG.read_text()
    for label in ("REPLICATED", "NOT REPLICATED", "MIXED"):
        assert label in text
