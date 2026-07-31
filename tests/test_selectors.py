from __future__ import annotations

import math

import numpy as np
import pytest

from biomni_uncertainty.features import consensus, normalized_entropy, pairwise_agreement
from biomni_uncertainty.selectors import (
    Candidate,
    random_expected,
    random_sampled,
    run_all_selectors,
    select_first,
    select_max_confidence,
    select_min_length,
    select_oracle,
    select_plurality,
    select_plurality_then_confidence,
    select_rank_combination,
    select_srlm_style,
    srlm_score,
)


def C(idx, key, conf=None, length=None, reward=None):
    return Candidate(
        run_id=f"r{idx}",
        trajectory_index=idx,
        cluster_key=key,
        canonical_answer=key,
        confidence=conf,
        length=length,
        reward=reward,
    )


# --------------------------------------------------------------------------
# Agreement clustering
# --------------------------------------------------------------------------


def test_exact_agreement_clustering():
    keys = ["A", "A", "B", "A"]
    r = consensus(keys, [0, 1, 2, 3])
    assert r.plurality_key == "A"
    assert r.plurality_count == 3
    assert r.plurality_fraction == pytest.approx(0.75)
    assert r.n_unique == 2
    assert not r.is_tie


def test_entropy_bounds():
    assert normalized_entropy([4]) == pytest.approx(0.0)
    assert normalized_entropy([1, 1, 1, 1]) == pytest.approx(1.0)
    mid = normalized_entropy([3, 1])
    assert 0.0 < mid < 1.0


def test_pairwise_agreement():
    assert pairwise_agreement(["A", "A", "A", "A"]) == pytest.approx(1.0)
    assert pairwise_agreement(["A", "B", "C", "D"]) == pytest.approx(0.0)
    # 3 of 4 agree -> 3 agreeing pairs out of 6.
    assert pairwise_agreement(["A", "A", "A", "B"]) == pytest.approx(0.5)
    assert pairwise_agreement(["A"]) is None


def test_consensus_tie_broken_by_lowest_trajectory_index_and_reported():
    r = consensus(["B", "B", "A", "A"], [0, 1, 2, 3])
    assert r.is_tie
    assert set(r.tied_keys) == {"A", "B"}
    assert r.plurality_key == "B"  # B's lowest trajectory index is 0


def test_consensus_tie_order_independent_of_row_order():
    a = consensus(["A", "B"], [1, 0])
    assert a.plurality_key == "B"  # index 0 wins regardless of list position


# --------------------------------------------------------------------------
# Selectors
# --------------------------------------------------------------------------


def test_first_picks_lowest_index():
    cands = [C(2, "X"), C(0, "Y"), C(1, "Z")]
    assert select_first(cands).run_id == "r0"


def test_plurality_and_tie_reporting():
    s = select_plurality([C(0, "A", reward=1), C(1, "A", reward=1), C(2, "B", reward=0)])
    assert s.canonical_answer == "A"
    assert not s.tie_broken

    tied = select_plurality([C(0, "A", reward=0), C(1, "B", reward=1)])
    assert tied.tie_broken
    assert tied.run_id == "r0"


def test_max_confidence_and_all_missing_fallback():
    s = select_max_confidence([C(0, "A", conf=0.2), C(1, "B", conf=0.9)])
    assert s.run_id == "r1"

    fb = select_max_confidence([C(0, "A"), C(1, "B")])
    assert fb.run_id == "r0"
    assert fb.missing_feature_handling == "all_missing_fallback_first"


def test_max_confidence_ignores_missing_but_records_count():
    s = select_max_confidence([C(0, "A"), C(1, "B", conf=0.3)])
    assert s.run_id == "r1"
    assert "1_candidates_missing_confidence" == s.missing_feature_handling


def test_min_length_picks_shortest():
    s = select_min_length([C(0, "A", length=500), C(1, "B", length=100)])
    assert s.run_id == "r1"


def test_min_length_ties_broken_deterministically():
    s = select_min_length([C(1, "A", length=100), C(0, "B", length=100)])
    assert s.run_id == "r0"
    assert s.tie_broken
    assert set(s.tied_run_ids) == {"r0", "r1"}


def test_plurality_then_confidence_restricts_to_cluster():
    cands = [C(0, "A", conf=0.1), C(1, "A", conf=0.6), C(2, "B", conf=0.99)]
    s = select_plurality_then_confidence(cands)
    # The 0.99-confidence candidate is outside the plurality cluster.
    assert s.run_id == "r1"


# --------------------------------------------------------------------------
# SRLM-style score
# --------------------------------------------------------------------------


def test_srlm_score_is_non_positive_and_maximized_by_confident_short():
    confident_short = srlm_score(0.9, 100, 1e-3)
    confident_long = srlm_score(0.9, 1000, 1e-3)
    unsure_short = srlm_score(0.1, 100, 1e-3)
    assert confident_short <= 0
    assert confident_short > confident_long  # shorter is better
    assert confident_short > unsure_short  # more confident is better


def test_srlm_score_clamps_zero_confidence_to_epsilon():
    eps = 1e-3
    assert srlm_score(0.0, 10, eps) == pytest.approx(math.log(eps) * 10)
    assert math.isfinite(srlm_score(0.0, 10, eps))


def test_srlm_score_confidence_one_gives_zero():
    assert srlm_score(1.0, 500, 1e-3) == pytest.approx(0.0)


def test_srlm_score_missing_inputs_return_none():
    assert srlm_score(None, 10, 1e-3) is None
    assert srlm_score(0.5, None, 1e-3) is None
    assert srlm_score(float("nan"), 10, 1e-3) is None


def test_select_srlm_style_restricted_to_plurality_cluster():
    cands = [
        C(0, "A", conf=0.5, length=1000, reward=1),
        C(1, "A", conf=0.9, length=100, reward=1),
        C(2, "B", conf=1.0, length=10, reward=0),
    ]
    s = select_srlm_style(cands, epsilon=1e-3)
    assert s.run_id == "r1"
    assert s.reward == 1


def test_select_srlm_style_falls_back_when_score_undefined():
    cands = [C(0, "A"), C(1, "A")]
    s = select_srlm_style(cands)
    assert s.run_id == "r0"
    assert s.missing_feature_handling.startswith("all_missing")


# --------------------------------------------------------------------------
# Rank combination
# --------------------------------------------------------------------------


def test_rank_combination_equal_weights():
    cands = [
        C(0, "A", conf=0.9, length=1000),  # best conf, worst length
        C(1, "A", conf=0.8, length=100),  # 2nd conf, best length -> wins
        C(2, "A", conf=0.1, length=500),
    ]
    s = select_rank_combination(cands)
    assert s.run_id == "r1"


def test_rank_combination_missing_signal_gets_worst_rank_and_is_reported():
    cands = [C(0, "A", conf=None, length=None), C(1, "A", conf=0.5, length=100)]
    s = select_rank_combination(cands)
    assert s.run_id == "r1"
    assert "missing_a_signal" in s.missing_feature_handling


def test_rank_combination_single_member_cluster():
    s = select_rank_combination([C(0, "A", conf=0.5, length=10), C(1, "B", conf=0.9, length=5)])
    # Tie between two singleton clusters -> plurality picks index 0.
    assert s.run_id == "r0"


# --------------------------------------------------------------------------
# Oracle and random
# --------------------------------------------------------------------------


def test_oracle_picks_any_correct():
    s = select_oracle([C(0, "A", reward=0), C(1, "B", reward=1), C(2, "C", reward=1)])
    assert s.reward == 1
    assert s.run_id == "r1"
    assert "UPPER BOUND" in s.reason


def test_oracle_with_no_correct_candidate():
    s = select_oracle([C(0, "A", reward=0), C(1, "B", reward=0)])
    assert s.reward == 0


def test_random_expected_is_the_mean():
    assert random_expected([C(0, "A", reward=1), C(1, "B", reward=0)]) == pytest.approx(0.5)


def test_random_sampled_is_deterministic_given_a_seed():
    cands = [C(i, f"K{i}", reward=i) for i in range(4)]
    a = random_sampled(cands, np.random.default_rng(7)).run_id
    b = random_sampled(cands, np.random.default_rng(7)).run_id
    assert a == b


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_run_all_selectors_returns_every_selector_with_full_provenance():
    cands = [
        C(0, "A", conf=0.4, length=800, reward=0),
        C(1, "A", conf=0.7, length=300, reward=0),
        C(2, "B", conf=0.9, length=200, reward=1),
        C(3, "A", conf=0.5, length=600, reward=0),
    ]
    out = run_all_selectors(cands)
    expected = {
        "first",
        "plurality",
        "max_confidence",
        "min_length",
        "plurality_then_confidence",
        "plurality_then_shortest",
        "srlm_style",
        "rank_combination",
        "oracle",
    }
    assert set(out) == expected
    for name, s in out.items():
        assert s.selector == name
        assert s.run_id is not None
        assert s.reason
        assert isinstance(s.tie_broken, bool)
        assert s.missing_feature_handling is not None
    # Only the oracle may find the minority-correct answer here.
    assert out["oracle"].reward == 1
    assert out["plurality"].reward == 0


def test_selectors_never_read_reward_except_oracle():
    """Same candidates, rewards permuted: only the oracle's choice may change."""
    base = [
        C(i, k, conf=c, length=ln)
        for i, (k, c, ln) in enumerate([("A", 0.4, 800), ("A", 0.7, 300), ("B", 0.9, 200), ("A", 0.5, 600)])
    ]
    v1 = [Candidate(**{**c.__dict__, "reward": r}) for c, r in zip(base, [1, 0, 0, 0], strict=True)]
    v2 = [Candidate(**{**c.__dict__, "reward": r}) for c, r in zip(base, [0, 0, 1, 0], strict=True)]
    a, b = run_all_selectors(v1), run_all_selectors(v2)
    for name in a:
        if name == "oracle":
            continue
        assert a[name].run_id == b[name].run_id, name


def test_single_candidate_is_handled():
    out = run_all_selectors([C(0, "A", conf=0.5, length=10, reward=1)])
    assert all(s.run_id == "r0" for s in out.values())


def test_empty_candidate_list_rejected():
    with pytest.raises(ValueError):
        run_all_selectors([])
