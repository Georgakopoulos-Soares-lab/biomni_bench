"""Pin the RL-signal preflight's frozen constants and verdict logic against
`reports/rl_signal_preflight_preregistration.md`.

Same discipline as `tests/test_scope_main_phase2.py`: a decision constant that
lives only in a script can be edited after a result exists and nobody notices.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rl_signal_preflight_analyze import (  # noqa: E402
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    HIGH_UNCERTAINTY_STRATUM_AGREEMENT,
    MIN_ENRICHMENT_RATIO,
    MIN_MIXED_REWARD_N,
    build_per_instance_table,
)
from rl_signal_prioritization_sim import BUDGET_25_FRACTION, BUDGET_FRACTIONS, _ranked  # noqa: E402
from rl_signal_verdict import arm_verdict, cross_solver_reading  # noqa: E402

PREREG = ROOT / "reports" / "rl_signal_preflight_preregistration.md"


def test_bootstrap_constants_match_the_preregistration():
    assert BOOTSTRAP_REPLICATES == 10_000
    assert BOOTSTRAP_SEED == 20260821
    assert "seed `20260821`" in PREREG.read_text()


def test_go_rule_constants_match_the_preregistration():
    assert HIGH_UNCERTAINTY_STRATUM_AGREEMENT == 0.25
    assert MIN_ENRICHMENT_RATIO == 1.5
    assert MIN_MIXED_REWARD_N == 10
    text = PREREG.read_text()
    assert ">= 1.5" in text
    assert "fewer than 10" in text


def test_budget_grid_is_5_to_100_percent_and_25_is_in_it():
    assert BUDGET_FRACTIONS[0] == 0.05
    assert BUDGET_FRACTIONS[-1] == 1.0
    assert len(BUDGET_FRACTIONS) == 20
    assert 0.25 in BUDGET_FRACTIONS
    assert BUDGET_25_FRACTION == 0.25


def test_all_120_budget_counts_are_exact_integers_no_rounding_needed():
    for frac in BUDGET_FRACTIONS:
        n = frac * 120
        assert abs(n - round(n)) < 1e-9, frac


# --------------------------------------------------------------------------
# reward-vector / mixed-reward representation (synthetic, no real data needed)
# --------------------------------------------------------------------------


def test_mixed_reward_partition_is_exhaustive_and_exclusive():
    for s in range(5):
        all_correct = s == 4
        all_wrong = s == 0
        mixed = 0 < s < 4
        assert sum([all_correct, all_wrong, mixed]) == 1, s


def test_reward_variance_matches_binomial_formula():
    for s in range(5):
        p = s / 4.0
        v = p * (1 - p)
        if s in (0, 4):
            assert v == 0.0
        if s == 2:
            assert v == 0.25  # maximal at p=0.5


# --------------------------------------------------------------------------
# deterministic ranking / tie-break
# --------------------------------------------------------------------------


def test_ranking_tie_break_is_fully_deterministic_across_tasks():
    df = pd.DataFrame(
        {
            "task_name": ["b_task", "a_task", "a_task"],
            "task_instance_id": [1, 2, 1],
            "U": [0.5, 0.5, 0.5],
            "mixed_reward": [1, 0, 1],
        }
    )
    ranked = _ranked(df, "U")
    # all tied on U -> break by (task_name, task_instance_id) ascending
    assert ranked["task_name"].tolist() == ["a_task", "a_task", "b_task"]
    assert ranked["task_instance_id"].tolist() == [1, 2, 1]


def test_ranking_is_stable_under_repetition():
    df = pd.DataFrame({"task_name": ["x"] * 4, "task_instance_id": [1, 2, 3, 4], "U": [0.75, 0.5, 0.5, 0.25]})
    r1 = _ranked(df, "U")["task_instance_id"].tolist()
    r2 = _ranked(df, "U")["task_instance_id"].tolist()
    assert r1 == r2 == [1, 2, 3, 4]


# --------------------------------------------------------------------------
# the frozen verdict rule, every branch
# --------------------------------------------------------------------------


def _report(n_mixed=20, guard_clear=True, a=True, b=True, auroc_hi=0.9, enrichment=2.0):
    return {
        "n_mixed_reward": n_mixed,
        "denominator_guard": {"guard_clear": guard_clear},
        "go_condition_a_discrimination": a,
        "go_condition_b_enrichment": b,
        "primary_auroc_U_mixed_reward": {"ci95": [0.55, auroc_hi]},
        "high_uncertainty_stratum": {"enrichment_ratio": enrichment},
    }


def _sim(c=True):
    return {"go_condition_c_budget_verified_capture": c}


def test_go_requires_all_three_conditions():
    v, _ = arm_verdict(_report(a=True, b=True), _sim(c=True))
    assert v == "GO"


def test_missing_any_single_condition_is_not_go():
    assert arm_verdict(_report(a=False, b=True), _sim(c=True))[0] != "GO"
    assert arm_verdict(_report(a=True, b=False), _sim(c=True))[0] != "GO"
    assert arm_verdict(_report(a=True, b=True), _sim(c=False))[0] != "GO"


def test_denominator_guard_forces_inconclusive_regardless_of_point_estimates():
    v, reasons = arm_verdict(_report(n_mixed=3, guard_clear=False, a=True, b=True), _sim(c=True))
    assert v == "INCONCLUSIVE"
    assert any("too few" in r for r in reasons)


def test_no_go_when_no_discrimination_at_all():
    v, _ = arm_verdict(_report(a=False, b=False, auroc_hi=0.5), _sim(c=False))
    assert v == "NO-GO"


def test_no_go_when_enrichment_at_or_below_chance():
    v, _ = arm_verdict(_report(a=False, b=False, auroc_hi=0.9, enrichment=1.0), _sim(c=False))
    assert v == "NO-GO"


def test_inconclusive_when_conditions_disagree_without_meeting_no_go():
    """a holds but b/c don't, and neither NO-GO trigger fires -> INCONCLUSIVE, not NO-GO."""
    v, _ = arm_verdict(_report(a=True, b=False, auroc_hi=0.9, enrichment=1.2), _sim(c=False))
    assert v == "INCONCLUSIVE"


def test_cross_solver_reading_covers_all_three_prereg_rows():
    assert "licenses a cross-solver" in cross_solver_reading("GO", "GO")
    assert "Arm A" in cross_solver_reading("GO", "NO-GO")
    assert "Arm B" in cross_solver_reading("NO-GO", "GO")
    assert "NOT supported" in cross_solver_reading("NO-GO", "NO-GO")
    assert "NOT supported" in cross_solver_reading("INCONCLUSIVE", "INCONCLUSIVE")


# --------------------------------------------------------------------------
# terminal-failure representation, against real data (skipped if absent)
# --------------------------------------------------------------------------


def test_every_instance_has_a_full_length_4_reward_vector_both_arms():
    for arm in ("a", "b"):
        root = Path(f"/scratch/11034/atzanakak/biomni_unc_runs/scope_main_{arm}/results/tables")
        if not root.exists():
            continue
        df = build_per_instance_table(arm)
        assert len(df) == 120
        assert df["reward_vector"].map(len).eq(4).all()
        assert df["sum_reward"].between(0, 4).all()
