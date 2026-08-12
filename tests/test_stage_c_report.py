"""Tests for Stage C's §9 reporting analyses.

Synthetic data only. No BiomniEval1 outcome is read, and none exists when
these are written — which is the point: an analysis validated against a real
outcome is an analysis tuned to it.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import stage_c_report as rep  # noqa: E402


def _df(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "pool",
            "task_name",
            "task_instance_id",
            "n_candidates",
            "margin",
            "selected_answer",
            "unresolved_tie",
            "selector_reward",
            "oracle_over_candidates",
            "plurality_reward_descriptive",
            "reachable",
        ],
    )


def _row(sel, plur, oracle=1.0, tie=False, margin=0.1, task="t", iid=0):
    return ["phase2b", task, iid, 2, margin, "a", tie, sel, oracle, plur, oracle > 0]


# ---------------------------------------------------------------------------
# A.2 decomposition
# ---------------------------------------------------------------------------


def test_capture_harm_reconciles_exactly():
    """A.2's identity: Delta == (capture - harm)/n, exactly, for binary rewards."""
    df = _df(
        [
            _row(sel=1.0, plur=0.0),  # capture
            _row(sel=1.0, plur=0.0),  # capture
            _row(sel=0.0, plur=1.0),  # harm
            _row(sel=1.0, plur=1.0),  # neutral
            _row(sel=0.0, plur=0.0),  # neutral
        ]
    )
    out = rep.capture_harm(df)
    assert out["capture"] == 2
    assert out["harm"] == 1
    assert out["delta_from_decomposition"] == pytest.approx((2 - 1) / 5)


def test_harm_is_subdivided_and_sums_to_harm():
    df = _df(
        [
            _row(sel=0.0, plur=1.0, tie=True),  # unresolved tie
            _row(sel=0.0, plur=1.0, oracle=1.0),  # wrong in menu
            _row(sel=0.0, plur=1.0, oracle=0.0),  # unreachable
        ]
    )
    out = rep.capture_harm(df)
    assert out["harm"] == 3
    assert sum(out["harm_breakdown"].values()) == 3


def test_identity_selector_has_zero_capture_and_zero_harm():
    """The plurality identity control must decompose to exactly zero, as in A.2."""
    df = _df([_row(sel=1.0, plur=1.0), _row(sel=0.0, plur=0.0)])
    out = rep.capture_harm(df)
    assert out["capture"] == 0 and out["harm"] == 0
    assert out["delta_from_decomposition"] == 0.0


# ---------------------------------------------------------------------------
# intransitivity
# ---------------------------------------------------------------------------


def _sel(n, pairwise, task="t", iid=0):
    return {
        "pool": "phase2b",
        "task_name": task,
        "task_instance_id": iid,
        "n_candidates": n,
        "candidate_answers": [chr(97 + i) for i in range(n)],
        "mean_preference": [0.5] * n,
        "pairwise": {k: {"p_a_beats_b": v} for k, v in pairwise.items()},
    }


def test_intransitivity_detects_a_genuine_cycle():
    """a>b, b>c, c>a is a cycle: the verifier is guessing."""
    cyc = {"0>1": 0.9, "1>0": 0.1, "1>2": 0.9, "2>1": 0.1, "2>0": 0.9, "0>2": 0.1}
    out = rep.intransitivity([_sel(3, cyc)])
    assert out["n_cyclic"] == 1
    assert out["intransitivity_rate"] == 1.0


def test_transitive_preferences_are_not_flagged():
    tr = {"0>1": 0.9, "1>0": 0.1, "1>2": 0.9, "2>1": 0.1, "0>2": 0.9, "2>0": 0.1}
    out = rep.intransitivity([_sel(3, tr)])
    assert out["n_cyclic"] == 0


def test_two_candidate_instances_are_excluded_from_the_denominator():
    """A cycle needs N>=3; quoting the rate against all 78 would be wrong."""
    pair = {"0>1": 0.9, "1>0": 0.1}
    cyc = {"0>1": 0.9, "1>0": 0.1, "1>2": 0.9, "2>1": 0.1, "2>0": 0.9, "0>2": 0.1}
    out = rep.intransitivity([_sel(2, pair), _sel(2, pair), _sel(3, cyc, iid=1)])
    assert out["n_eligible"] == 1
    assert out["n_total_instances"] == 3
    assert out["intransitivity_rate"] == 1.0


def test_no_eligible_instances_yields_none_not_zero():
    """An undefined rate must not be reported as 0.0."""
    out = rep.intransitivity([_sel(2, {"0>1": 0.9, "1>0": 0.1})])
    assert out["n_eligible"] == 0
    assert out["intransitivity_rate"] is None


# ---------------------------------------------------------------------------
# ranking quality
# ---------------------------------------------------------------------------


def _rank_case(scores, labels):
    sel = [
        {
            "pool": "phase2b",
            "task_name": "t",
            "task_instance_id": 0,
            "n_candidates": len(scores),
            "candidate_answers": [chr(97 + i) for i in range(len(scores))],
            "mean_preference": scores,
            "pairwise": {},
        }
    ]
    rewards = {("phase2b", "t", 0, chr(97 + i)): labels[i] for i in range(len(scores))}
    return sel, rewards


def test_auroc_is_one_when_ranking_is_perfect():
    sel, rewards = _rank_case([0.1, 0.9], [0.0, 1.0])
    assert rep.ranking_auroc(sel, rewards)["auroc"] == 1.0


def test_auroc_is_zero_when_ranking_is_inverted():
    sel, rewards = _rank_case([0.9, 0.1], [0.0, 1.0])
    assert rep.ranking_auroc(sel, rewards)["auroc"] == 0.0


def test_auroc_is_none_when_all_labels_agree():
    sel, rewards = _rank_case([0.9, 0.1], [1.0, 1.0])
    assert rep.ranking_auroc(sel, rewards)["auroc"] is None


# ---------------------------------------------------------------------------
# risk-coverage and PPT secondary
# ---------------------------------------------------------------------------


def test_risk_coverage_is_monotone_in_coverage_and_ends_at_full():
    df = _df([_row(sel=1.0, plur=0.0, margin=m, iid=i) for i, m in enumerate([0.9, 0.7, 0.5, 0.3])])
    curve = rep.risk_coverage(df)["curve"]
    covs = [r["coverage"] for r in curve]
    assert covs == sorted(covs)
    assert curve[-1]["coverage"] == 1.0


def test_ppt_secondary_is_deterministic_under_its_seed():
    cyc = {"0>1": 0.9, "1>0": 0.1, "1>2": 0.8, "2>1": 0.2, "0>2": 0.7, "2>0": 0.3}
    sel = [_sel(3, cyc)]
    rewards = {("phase2b", "t", 0, "a"): 1.0, ("phase2b", "t", 0, "b"): 0.0, ("phase2b", "t", 0, "c"): 0.0}
    a = rep.ppt_secondary(sel, rewards, seed=0)
    b = rep.ppt_secondary(sel, rewards, seed=0)
    assert a == b


def test_ppt_is_labelled_as_never_entering_the_decision_rule():
    cyc = {"0>1": 0.9, "1>0": 0.1, "1>2": 0.8, "2>1": 0.2, "0>2": 0.7, "2>0": 0.3}
    rewards = {("phase2b", "t", 0, x): 0.0 for x in "abc"}
    assert "never substituted" in rep.ppt_secondary([_sel(3, cyc)], rewards)["status"]


def test_cost_records_that_stage_c_generates_no_trajectories():
    out = rep.cost({"comparisons": 5856, "directed_pairs": 244})
    assert out["prefill_calls"] == 5856 * 2
    assert "trajectories generated by Stage C: 0" in out["note"]


def test_audit_corrected_headroom_is_carried_alongside_official():
    assert rep.AUDIT_CORRECTED["official"]["oracle_at_4"] == 0.700
    assert rep.AUDIT_CORRECTED["audit_corrected"]["oracle_at_4"] == 0.720
    assert "20%-51%" in rep.AUDIT_CORRECTED["note"]
