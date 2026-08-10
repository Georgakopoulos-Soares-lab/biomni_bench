"""Tests for the Phase-2B analysis helpers that encode protocol arithmetic
directly (`scripts/phase2b_analyze.py`).

These are the two places a silent bug would corrupt a headline number without
any downstream test catching it: the matched-compute baseline's expectation
formula (D-24) and the "confidently wrong" state classifier (S1). Everything
else in the analysis script composes already-tested library functions
(`policy.replay_one`, `analysis.paired_bootstrap_difference`, ...).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load():
    spec = importlib.util.spec_from_file_location("phase2b_analyze", SCRIPTS / "phase2b_analyze.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


# --------------------------------------------------------------------------
# S1: confidently-wrong state classifier
# --------------------------------------------------------------------------


def test_confident_state_matches_the_protocol_wording_exactly(mod):
    # "≥3-of-4 or 3-of-3 agreement" - both forms count, nothing else does.
    assert mod.is_confidently_wrong_state(support=3, k_used=3) is True
    assert mod.is_confidently_wrong_state(support=3, k_used=4) is True
    assert mod.is_confidently_wrong_state(support=4, k_used=4) is True


def test_confident_state_excludes_weaker_agreement(mod):
    assert mod.is_confidently_wrong_state(support=2, k_used=4) is False
    assert mod.is_confidently_wrong_state(support=2, k_used=3) is False
    assert mod.is_confidently_wrong_state(support=2, k_used=2) is False
    assert mod.is_confidently_wrong_state(support=1, k_used=2) is False


def test_confident_state_excludes_3_of_4_stopped_early_states_correctly(mod):
    # 3-of-4 only counts when k_used is actually 4 (all four were observed).
    # A support of 3 while k_used=3 is the "3-of-3" case (handled above); there
    # is no valid state where support > k_used.
    assert mod.is_confidently_wrong_state(support=3, k_used=2) is False


def test_confident_state_handles_missing_values(mod):
    assert mod.is_confidently_wrong_state(support=np.nan, k_used=4) is False
    assert mod.is_confidently_wrong_state(support=3, k_used=None) is False


def test_confidently_wrong_rate_counts_over_all_instances_not_just_confident_ones(mod):
    """Rate is a fraction of ALL replays (matching Phase 2A's convention), so an
    abstaining policy cannot game the rate down just by answering less."""
    realized = pd.DataFrame(
        [
            # confident (3/3) and wrong -> counts
            {"policy": "p", "support": 3, "k_used": 3, "answered": True, "reward": 0.0},
            # confident (4/4) and correct -> does not count as wrong
            {"policy": "p", "support": 4, "k_used": 4, "answered": True, "reward": 1.0},
            # weak agreement, wrong -> not "confident", does not count
            {"policy": "p", "support": 2, "k_used": 4, "answered": True, "reward": 0.0},
            # not answered at all -> does not count
            {"policy": "p", "support": 1, "k_used": 4, "answered": False, "reward": None},
        ]
    )
    rate, n_confident = mod.confidently_wrong_rate(realized, "p", threshold=0.5)
    assert n_confident == 2  # the two confident (answered) rows
    assert rate == pytest.approx(1 / 4)  # 1 wrong-and-confident out of ALL 4 rows


# --------------------------------------------------------------------------
# D-24: matched-compute baseline expectation formula
# --------------------------------------------------------------------------


def _fake_realized(n: int, reward_k2: float, reward_k3: float) -> pd.DataFrame:
    rows = []
    for i in range(n):
        for policy, r in (("fixed_k2", reward_k2), ("fixed_k3", reward_k3)):
            rows.append(
                {
                    "policy": policy,
                    "task_name": "t",
                    "task_instance_id": i,
                    "reward_abstain_zero": r,
                    "total_tokens": 100.0 if policy == "fixed_k2" else 150.0,
                    "total_output_tokens": 10.0,
                    "llm_calls": 1.0,
                    "tool_calls": 1.0,
                    "wall_time_seconds": 5.0,
                }
            )
        rows.append(
            {
                "policy": "mandatory_k2_online",
                "task_name": "t",
                "task_instance_id": i,
                "k_used": 2 if i < n // 2 else 3,  # exactly designed so m=2, r=n//2
                "reward_abstain_zero": 0.0,
                "total_tokens": 0.0,
                "total_output_tokens": 0.0,
                "llm_calls": 0.0,
                "tool_calls": 0.0,
                "wall_time_seconds": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_matched_compute_m_and_r_come_from_the_controllers_realized_total(mod):
    df = _fake_realized(n=10, reward_k2=0.0, reward_k3=1.0)
    _, meta = mod.matched_compute_baseline(df, n_instances=10)
    assert meta["total_b"] == 2 * 5 + 3 * 5  # 5 instances at k=2, 5 at k=3
    assert meta["m"] == 2
    assert meta["r"] == 5


def test_matched_compute_expectation_is_the_exact_convex_combination(mod):
    """value_i = (1 - r/N)*reward_i(K=m) + (r/N)*reward_i(K=m+1), verbatim."""
    df = _fake_realized(n=10, reward_k2=0.2, reward_k3=0.8)
    out, meta = mod.matched_compute_baseline(df, n_instances=10)
    expectation = out[out.policy == mod.MATCHED_EXPECTATION_NAME]
    frac = meta["r"] / meta["n_instances"]
    expected_value = (1 - frac) * 0.2 + frac * 0.8
    assert expectation.reward_abstain_zero.to_numpy() == pytest.approx(np.full(10, expected_value))
    # every instance gets the identical expectation (no per-instance noise) -
    # the randomization is over WHICH instances are chosen, not a per-instance
    # coin flip, so the marginal is a constant by exchangeability.
    assert expectation.reward_abstain_zero.nunique() == 1


def test_matched_compute_cost_equals_the_controllers_realized_mean_k(mod):
    df = _fake_realized(n=10, reward_k2=0.0, reward_k3=1.0)
    out, meta = mod.matched_compute_baseline(df, n_instances=10)
    expectation = out[out.policy == mod.MATCHED_EXPECTATION_NAME]
    ctrl_mean_k = df[df.policy == "mandatory_k2_online"].k_used.mean()
    assert expectation.k_used.mean() == pytest.approx(ctrl_mean_k)
    assert expectation.k_used.nunique() == 1  # constant cost, matching the point of a "matched" baseline


def test_matched_compute_realized_draw_uses_exactly_r_instances_at_m_plus_1(mod):
    df = _fake_realized(n=20, reward_k2=0.0, reward_k3=1.0)
    out, meta = mod.matched_compute_baseline(df, n_instances=20)
    draw = out[out.policy == mod.MATCHED_REALIZED_NAME]
    assert len(draw) == 20
    # every drawn instance took EITHER reward_k2 or reward_k3 wholesale, never a mixture
    assert set(draw.reward_abstain_zero.unique()) <= {0.0, 1.0}
    n_at_plus_one = int((draw.reward_abstain_zero == 1.0).sum())
    assert n_at_plus_one == meta["r"]


def test_matched_compute_realized_draw_is_deterministic_given_the_frozen_seed(mod):
    df = _fake_realized(n=20, reward_k2=0.0, reward_k3=1.0)
    out1, _ = mod.matched_compute_baseline(df, n_instances=20)
    out2, _ = mod.matched_compute_baseline(df, n_instances=20)
    d1 = out1[out1.policy == mod.MATCHED_REALIZED_NAME].sort_values("task_instance_id").reward_abstain_zero.tolist()
    d2 = out2[out2.policy == mod.MATCHED_REALIZED_NAME].sort_values("task_instance_id").reward_abstain_zero.tolist()
    assert d1 == d2, "the realized draw must reproduce identically, not vary run to run"


# --------------------------------------------------------------------------
# Halt-condition check (§11, re-derived correctly after the gate-script bug)
# --------------------------------------------------------------------------


def test_halt_condition_matches_the_budget_terminated_prefix_not_exact_string(mod):
    """Regression test for the exact bug found in the real run: the runner
    records "budget_terminated_consecutive_runaway", not the bare
    "budget_terminated" a naive exact-match check would look for."""
    pooled = pd.DataFrame(
        {
            "task_name": ["a", "a", "b", "b"],
            "failure_class": ["budget_terminated_consecutive_runaway", None, "model_context_overflow", None],
        }
    )
    result = mod.halt_condition_check(pooled)
    assert result["n_overflow"] == 2
    assert result["rate_overall"] == pytest.approx(0.5)


def test_halt_condition_trips_above_the_frozen_threshold(mod):
    pooled = pd.DataFrame(
        {
            "task_name": ["a"] * 10,
            "failure_class": ["budget_terminated_consecutive_runaway"] * 2 + [None] * 8,
        }
    )
    result = mod.halt_condition_check(pooled)
    assert result["rate_overall"] == pytest.approx(0.2)
    assert result["tripped"] is True  # 0.2 > 0.15
    assert result["threshold"] == pytest.approx(0.15)


def test_halt_condition_does_not_trip_at_exactly_the_threshold(mod):
    pooled = pd.DataFrame(
        {"task_name": ["a"] * 20, "failure_class": ["budget_terminated_consecutive_runaway"] * 3 + [None] * 17}
    )
    result = mod.halt_condition_check(pooled)
    assert result["rate_overall"] == pytest.approx(0.15)
    assert result["tripped"] is False  # strictly greater-than, matching "exceeds 15%"
