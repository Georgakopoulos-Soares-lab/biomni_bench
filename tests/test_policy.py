"""Tests for the Phase-2A sequential policy replay.

The load-bearing ones are the leakage tests: a policy that can see a reward, a
future trajectory, or the native trajectory index would make the whole offline
replay meaningless, and that failure is silent unless it is asserted.
"""

from __future__ import annotations

from dataclasses import fields

import pandas as pd
import pytest

from biomni_uncertainty.features import UNPARSEABLE_PREFIX
from biomni_uncertainty.policy import (
    ABSTAIN,
    ACCEPT,
    CONTINUE,
    FORBIDDEN_VIEW_FIELDS,
    Abstaining,
    CombinedAdaptive,
    ConfidenceEscalation,
    Decision,
    FailureEscalation,
    FixedK,
    InstancePool,
    K1Selective,
    MandatoryK2,
    OracleAtK,
    OracleStop,
    Policy,
    PolicyState,
    TrajectoryView,
    all_orderings,
    answer_similarity,
    build_pools,
    const_threshold,
    per_instance,
    replay_one,
    replay_policy,
    resolve,
    view_from_row,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def row(
    idx: int,
    answer: str | None,
    *,
    reward: float,
    conf: float | None = 0.95,
    completed: bool = True,
    parse: str = "ok",
    task: str = "gwas_causal_gene_opentargets",
    tokens: float = 1000.0,
    tool_calls: float = 2.0,
) -> dict:
    return {
        "run_id": f"{task}-i0001-inst-t{idx}",
        "task_name": task,
        "task_instance_id": 1,
        "trajectory_index": idx,
        "completed": completed,
        "answer_parse_status": parse,
        "answer_cluster_key": answer,
        "answer_canonical": answer,
        "final_confidence": conf,
        "confidence_parse_status": "ok" if conf is not None else "missing",
        "failure_class": None if completed else "model_context_overflow",
        "reward": reward,
        "correct": int(reward > 0),
        "strict_reward": reward,
        "evaluation_status": "ok",
        "total_tokens": tokens,
        "total_output_tokens": tokens / 2,
        "total_input_tokens": tokens / 2,
        "llm_call_count": 10.0,
        "tool_call_count": tool_calls,
        "failed_tool_call_count": 0.0,
        "code_execution_count": 3.0,
        "unique_tool_count": 2.0,
        "retrieval_count": 1.0,
        "exception_count": 0.0,
        "visible_plan_step_count": 4.0,
        "generated_chars": tokens * 4,
        "wall_time_seconds": 100.0,
    }


def pool_from(rows: list[dict], task: str = "gwas_causal_gene_opentargets") -> InstancePool:
    return InstancePool(
        task_name=task,
        task_instance_id=1,
        rows=tuple(rows),
        rewards={r["run_id"]: float(r["reward"]) for r in rows},
    )


@pytest.fixture
def agree_pool() -> InstancePool:
    """A, A, B, B — the plurality answer depends on arrival order."""
    return pool_from(
        [
            row(0, "A", reward=1.0),
            row(1, "A", reward=1.0),
            row(2, "B", reward=0.0),
            row(3, "B", reward=0.0),
        ]
    )


@pytest.fixture
def failure_pool() -> InstancePool:
    """One dead trajectory, one unparseable, two that agree on a correct answer."""
    return pool_from(
        [
            row(0, None, reward=0.0, completed=False, parse="empty", conf=None),
            row(1, None, reward=0.0, parse="unparseable", conf=None),
            row(2, "A", reward=1.0),
            row(3, "A", reward=1.0),
        ]
    )


# --------------------------------------------------------------------------
# Leakage barrier
# --------------------------------------------------------------------------


def test_trajectory_view_cannot_carry_a_label():
    names = {f.name for f in fields(TrajectoryView)}
    assert names & FORBIDDEN_VIEW_FIELDS == set(), "TrajectoryView exposes an evaluation-only field"


def test_view_from_row_drops_reward_and_native_index():
    v = view_from_row(row(2, "A", reward=1.0), position=1)
    assert not hasattr(v, "reward")
    assert not hasattr(v, "correct")
    assert not hasattr(v, "trajectory_index")
    # position is the ARRIVAL order, deliberately unequal to the native index
    assert v.position == 1


def test_view_is_frozen_and_slotted():
    v = view_from_row(row(0, "A", reward=1.0), position=1)
    with pytest.raises((AttributeError, TypeError)):
        v.total_tokens = 5.0  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        v.reward = 1.0  # type: ignore[attr-defined]


def test_policy_state_only_holds_the_observed_prefix(agree_pool):
    views = agree_pool.views((0, 1, 2, 3))
    seen = []

    class Spy(Policy):
        name = "spy"

        def decide(self, state: PolicyState) -> Decision:
            seen.append(tuple(v.run_id for v in state.views))
            assert len(state.views) == state.k
            return Decision(ACCEPT if state.k == 3 else CONTINUE, "spy")

    replay_one(Spy(), agree_pool, (0, 1, 2, 3))
    assert seen == [
        (views[0].run_id,),
        (views[0].run_id, views[1].run_id),
        (views[0].run_id, views[1].run_id, views[2].run_id),
    ]


def test_scorers_never_receive_ground_truth(agree_pool):
    """A scorer is handed a view; the view has no path back to the reward map."""
    captured: list[TrajectoryView] = []

    def scorer(v: TrajectoryView) -> float:
        captured.append(v)
        return 0.99

    replay_one(K1Selective(scorer, const_threshold(0.9)), agree_pool, (0, 1, 2, 3))
    assert captured
    for v in captured:
        assert not any(hasattr(v, f) for f in FORBIDDEN_VIEW_FIELDS)


# --------------------------------------------------------------------------
# Resolution and agreement
# --------------------------------------------------------------------------


def test_unparseable_answers_are_singleton_clusters(failure_pool):
    views = failure_pool.views((0, 1, 2, 3))
    assert views[0].cluster_key.startswith(UNPARSEABLE_PREFIX)
    assert views[1].cluster_key.startswith(UNPARSEABLE_PREFIX)
    assert views[0].cluster_key != views[1].cluster_key
    res = resolve(views[:2])
    assert res.support == 1
    assert not res.valid_agreement, "two unrelated failures must never count as consensus"


def test_valid_agreement_requires_usable_trajectories(failure_pool):
    views = failure_pool.views((2, 3, 0, 1))
    assert resolve(views[:2]).valid_agreement
    assert not resolve(views[2:]).valid_agreement


def test_resolution_ties_break_to_earliest_arrival(agree_pool):
    a_first = resolve(agree_pool.views((0, 2, 1, 3))[:2])
    b_first = resolve(agree_pool.views((2, 0, 1, 3))[:2])
    assert a_first.is_tie and b_first.is_tie
    assert a_first.canonical_answer == "A"
    assert b_first.canonical_answer == "B"


def test_a_failed_trajectory_never_wins_a_tie_against_a_real_answer(failure_pool):
    """The failure arrives first and ties 1-1 with a real answer; the real answer
    must win, or the controller hands back a non-answer it could have avoided."""
    views = failure_pool.views((0, 2, 3, 1))  # dead run, then a correct answer
    res = resolve(views[:2])
    assert res.canonical_answer == "A"
    assert res.rests_on_usable
    assert res.n_failed == 1
    assert res.support_fraction == 0.5, "the failure still counts against support"
    assert failure_pool.reward_of(res.cluster_key, res.members) == 1.0


def test_resolution_falls_back_when_nothing_is_usable(failure_pool):
    views = failure_pool.views((0, 1, 2, 3))
    res = resolve(views[:2])  # both failed
    assert not res.rests_on_usable
    assert res.cluster_key.startswith(UNPARSEABLE_PREFIX)


def test_reward_of_rejects_an_inconsistent_cluster():
    p = pool_from([row(0, "A", reward=1.0), row(1, "A", reward=0.0)])
    views = p.views((0, 1))
    with pytest.raises(ValueError, match="inconsistent rewards"):
        p.reward_of("A", views)


def test_task_aware_similarity_grades_set_valued_answers():
    a = view_from_row(row(0, "G1|G2|G3", reward=1.0, task="patient_gene_detection"), 1)
    b = view_from_row(row(1, "G1|G2", reward=1.0, task="patient_gene_detection"), 2)
    c = view_from_row(row(2, "G9", reward=0.0, task="patient_gene_detection"), 3)
    assert answer_similarity("patient_gene_detection", a, a) == 1.0
    assert answer_similarity("patient_gene_detection", a, b) == pytest.approx(2 / 3)
    assert answer_similarity("patient_gene_detection", a, c) == 0.0
    # single-label tasks stay strict
    assert answer_similarity("gwas_causal_gene_opentargets", a, b) == 0.0


def test_failed_answers_never_agree_even_with_themselves(failure_pool):
    v = failure_pool.views((0, 1, 2, 3))[0]
    assert answer_similarity("patient_gene_detection", v, v) == 0.0


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def test_all_orderings_is_exhaustive():
    assert len(all_orderings(4)) == 24
    assert len(set(all_orderings(4))) == 24


def test_replay_covers_every_ordering(agree_pool):
    df = replay_policy(FixedK(2), [agree_pool])
    assert len(df) == 24
    assert df.ordering.nunique() == 24


def test_ordering_changes_the_answer_but_averaging_removes_the_artifact(agree_pool):
    """A/A/B/B is a coin flip at K=2; averaged over orderings it is exactly 0.5."""
    df = replay_policy(FixedK(2), [agree_pool])
    assert set(df.reward_abstain_zero) == {0.0, 1.0}
    assert df.reward_abstain_zero.mean() == pytest.approx(0.5)


def test_fixed_k1_equals_the_mean_trajectory_reward(agree_pool):
    df = replay_policy(FixedK(1), [agree_pool])
    assert df.reward_abstain_zero.mean() == pytest.approx(0.5)
    assert (df.k_used == 1).all()


# --------------------------------------------------------------------------
# Cost accounting
# --------------------------------------------------------------------------


def test_cost_counts_only_trajectories_actually_consumed(agree_pool):
    df = replay_policy(FixedK(3), [agree_pool])
    assert (df.k_used == 3).all()
    assert (df.total_tokens == 3000.0).all()
    assert (df.tool_calls == 6.0).all()
    assert (df.llm_calls == 30.0).all()


def test_cost_is_monotone_in_budget(agree_pool):
    costs = [replay_policy(FixedK(n), [agree_pool]).total_tokens.mean() for n in (1, 2, 3, 4)]
    assert costs == sorted(costs)
    assert costs[0] == 1000.0 and costs[3] == 4000.0


def test_early_stopping_actually_saves_cost(failure_pool):
    """FailureEscalation stops at the first usable trajectory, so its mean cost
    must sit strictly between fixed K=1 and fixed K=4."""
    cheap = replay_policy(FailureEscalation(), [failure_pool]).total_tokens.mean()
    k1 = replay_policy(FixedK(1), [failure_pool]).total_tokens.mean()
    k4 = replay_policy(FixedK(4), [failure_pool]).total_tokens.mean()
    assert k1 < cheap < k4


# --------------------------------------------------------------------------
# Failure overrides
# --------------------------------------------------------------------------


def test_failure_override_blocks_k1_acceptance(failure_pool):
    """Even a scorer that always says 'certain' must not accept a failed run."""
    p = K1Selective(lambda v: 1.0, const_threshold(0.5))
    out = replay_one(p, failure_pool, (0, 2, 3, 1))
    # k=2 holds [failed, A]: only ONE usable analysis, so mandatory verification
    # is still unsatisfied and the policy pays for a third.
    assert out.k_used == 3
    assert out.reward == 1.0
    # and the same policy does accept at K=1 when the first trajectory is healthy
    assert replay_one(p, failure_pool, (2, 3, 0, 1)).k_used == 1


def test_failure_override_fires_for_unparseable_as_well_as_dead_runs(failure_pool):
    p = K1Selective(lambda v: 1.0, const_threshold(0.5))
    for start in (0, 1):  # 0 = execution failure, 1 = completed but unparseable
        assert replay_one(p, failure_pool, (start, 2, 3, (1 if start == 0 else 0))).k_used > 1


def test_failure_escalation_stops_immediately_on_a_usable_trajectory(failure_pool):
    out = replay_one(FailureEscalation(), failure_pool, (2, 0, 1, 3))
    assert out.k_used == 1 and out.reward == 1.0


def test_failure_recovery_is_recorded(failure_pool):
    out = replay_one(MandatoryK2(), failure_pool, (0, 2, 3, 1))
    assert out.first_view_failed
    assert out.resolved_after_failure
    assert out.recovered_failure
    # fixed K=1 cannot recover anything, by construction
    k1 = replay_one(FixedK(1), failure_pool, (0, 2, 3, 1))
    assert k1.first_view_failed and not k1.recovered_failure


# --------------------------------------------------------------------------
# Policy contract
# --------------------------------------------------------------------------


def _all_policies(pool: InstancePool) -> list[Policy]:
    return [
        FixedK(1),
        FixedK(2),
        FixedK(3),
        FixedK(4),
        MandatoryK2(max_k=3),
        MandatoryK2(max_k=4),
        K1Selective(lambda v: 0.9, const_threshold(0.95)),
        ConfidenceEscalation(lambda v: 0.9, 0.95),
        FailureEscalation(),
        CombinedAdaptive(lambda v: 0.9, const_threshold(0.95)),
        Abstaining(MandatoryK2(), lambda s, r: 0.1, 0.5),
        OracleStop(pool.rewards),
        OracleAtK(pool.rewards, 4),
    ]


def test_no_policy_returns_continue_at_the_final_step(agree_pool, failure_pool):
    for pool in (agree_pool, failure_pool):
        for policy in _all_policies(pool):
            for ordering in all_orderings(pool.k):
                replay_one(policy, pool, ordering)  # raises if the contract breaks


def test_a_policy_that_never_stops_is_rejected(agree_pool):
    class NeverStops(Policy):
        name = "never_stops"

        def decide(self, state: PolicyState) -> Decision:
            return Decision(CONTINUE, "never")

    with pytest.raises(RuntimeError, match="CONTINUE at the final step"):
        replay_one(NeverStops(), agree_pool, (0, 1, 2, 3))


def test_mandatory_k2_never_accepts_a_single_trajectory(agree_pool, failure_pool):
    for pool in (agree_pool, failure_pool):
        df = replay_policy(MandatoryK2(), [pool])
        assert (df.k_used >= 2).all()


def test_mandatory_k2_stops_at_2_on_agreement_and_continues_on_disagreement(agree_pool):
    assert replay_one(MandatoryK2(), agree_pool, (0, 1, 2, 3)).k_used == 2  # A,A
    assert replay_one(MandatoryK2(), agree_pool, (0, 2, 1, 3)).k_used > 2  # A,B


def test_k1_selective_degenerates_to_mandatory_k2_when_it_never_accepts(agree_pool):
    strict = replay_policy(K1Selective(lambda v: 0.5, const_threshold(1.01)), [agree_pool])
    base = replay_policy(MandatoryK2(), [agree_pool])
    assert strict.k_used.tolist() == base.k_used.tolist()
    assert strict.reward_abstain_zero.tolist() == base.reward_abstain_zero.tolist()


def test_k1_selective_accepts_at_k1_when_the_score_clears_the_bar(agree_pool):
    df = replay_policy(K1Selective(lambda v: 0.99, const_threshold(0.9)), [agree_pool])
    assert (df.k_used == 1).all()


def test_threshold_may_vary_per_trajectory(agree_pool):
    """Nested cross-validated thresholds differ by fold; the policy must honour
    a per-trajectory threshold without knowing which fold it is in."""
    accept_only_t0 = K1Selective(lambda v: 0.9, lambda v: 0.5 if v.run_id.endswith("t0") else 1.01)
    df = replay_policy(accept_only_t0, [agree_pool])
    stopped_at_1 = df[df.k_used == 1]
    assert len(stopped_at_1) == 6  # the 6 orderings that present t0 first
    assert all(o.startswith("0") for o in stopped_at_1.ordering)


# --------------------------------------------------------------------------
# Abstention
# --------------------------------------------------------------------------


def test_abstention_replaces_acceptance_and_is_scored_two_ways(agree_pool):
    always = Abstaining(MandatoryK2(), lambda s, r: 0.0, 0.5)
    df = replay_policy(always, [agree_pool])
    assert (df.action == ABSTAIN).all()
    assert not df.answered.any()
    assert df.reward.isna().all(), "an abstention has no reward, it is not a zero"
    assert (df.reward_abstain_zero == 0.0).all(), "the conservative accounting charges for it"


def test_abstention_does_not_fire_when_reliability_is_high(agree_pool):
    never = Abstaining(MandatoryK2(), lambda s, r: 1.0, 0.5)
    base = replay_policy(MandatoryK2(), [agree_pool])
    df = replay_policy(never, [agree_pool])
    assert (df.action == ACCEPT).all()
    assert df.reward_abstain_zero.tolist() == base.reward_abstain_zero.tolist()
    assert df.k_used.tolist() == base.k_used.tolist()


def test_coverage_and_selective_risk_are_consistent(agree_pool):
    """Abstain exactly when the resolved answer has no majority support."""
    pol = Abstaining(FixedK(2), lambda s, r: 1.0 if r.support >= 2 else 0.0, 0.5)
    df = replay_policy(pol, [agree_pool])
    answered = df[df.answered]
    # A/A/B/B at K=2: 8 of 24 orderings show a matching pair, and those pairs are
    # A,A (correct) or B,B (wrong) equally often.
    assert len(answered) == 8
    assert answered.reward.mean() == pytest.approx(0.5)
    assert df.answered.mean() == pytest.approx(8 / 24)


def test_abstaining_wrapper_preserves_base_deployability(agree_pool):
    assert Abstaining(MandatoryK2(), lambda s, r: 1.0, 0.5).deployable
    assert not Abstaining(OracleStop(agree_pool.rewards), lambda s, r: 1.0, 0.5).deployable


# --------------------------------------------------------------------------
# Oracles
# --------------------------------------------------------------------------


def test_oracle_policies_are_marked_non_deployable(agree_pool):
    assert not OracleStop(agree_pool.rewards).deployable
    assert not OracleAtK(agree_pool.rewards, 4).deployable
    assert FixedK(4).deployable and MandatoryK2().deployable


def test_oracle_at_k_dominates_every_deployable_policy(agree_pool, failure_pool):
    for pool in (agree_pool, failure_pool):
        oracle = replay_policy(OracleAtK(pool.rewards, 4), [pool]).reward_abstain_zero.mean()
        for policy in _all_policies(pool):
            if not policy.deployable:
                continue
            assert replay_policy(policy, [pool]).reward_abstain_zero.mean() <= oracle + 1e-9


def test_oracle_stop_is_cheaper_than_fixed_k4_at_equal_reward(agree_pool):
    stop = replay_policy(OracleStop(agree_pool.rewards), [agree_pool])
    at4 = replay_policy(OracleAtK(agree_pool.rewards, 4), [agree_pool])
    assert stop.reward_abstain_zero.mean() == pytest.approx(at4.reward_abstain_zero.mean())
    assert stop.k_used.mean() < at4.k_used.mean()


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def test_build_pools_groups_by_instance_and_hides_rewards():
    df = pd.DataFrame([row(i, "A", reward=1.0) for i in range(4)])
    pools = build_pools(df)
    assert len(pools) == 1 and pools[0].k == 4
    assert set(pools[0].rewards.values()) == {1.0}
    for v in pools[0].views((0, 1, 2, 3)):
        assert not any(hasattr(v, f) for f in FORBIDDEN_VIEW_FIELDS)


def test_per_instance_collapses_orderings_to_one_row_per_instance(agree_pool):
    df = replay_policy(MandatoryK2(), [agree_pool])
    agg = per_instance(df)
    assert len(agg) == 1
    assert agg.n_orderings.iloc[0] == 24
    assert agg.reward.iloc[0] == pytest.approx(df.reward_abstain_zero.mean())
    assert agg[[f"frac_stop_k{k}" for k in (1, 2, 3, 4)]].sum(axis=1).iloc[0] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Agreement with the frozen Phase-1 selector
# --------------------------------------------------------------------------


def test_native_ordering_k4_matches_the_frozen_phase1_plurality_selector():
    """Replay at K=4 under the native ordering must equal `select_plurality`.

    This is the invariant that reconciles Phase-2A's 0.577 with Phase-1's 0.620
    (report §1.1): the two differ only because Phase 2A averages over arrival
    orderings, not because the resolution rule changed. Locked here so a future
    edit to `resolve` cannot silently break the correspondence.

    Restricted to pools where every trajectory is usable, because D-18
    deliberately diverges from the Phase-1 selector when a non-answer would
    otherwise win a tie — that divergence is tested separately.
    """
    from biomni_uncertainty.selectors import candidates_from_frame, select_plurality

    cases = [
        [("A", 1.0), ("A", 1.0), ("B", 0.0), ("B", 0.0)],  # 2-2 split, index 0 correct
        [("B", 0.0), ("B", 0.0), ("A", 1.0), ("A", 1.0)],  # 2-2 split, index 0 wrong
        [("A", 1.0), ("B", 0.0), ("C", 0.0), ("D", 0.0)],  # 4-way, no consensus
        [("A", 1.0), ("A", 1.0), ("A", 1.0), ("B", 0.0)],  # clear majority
    ]
    for case in cases:
        rows = [row(i, a, reward=r) for i, (a, r) in enumerate(case)]
        pool = pool_from(rows)
        frozen = select_plurality(candidates_from_frame(pd.DataFrame(rows)))
        replayed = replay_one(FixedK(4), pool, (0, 1, 2, 3))
        assert replayed.reward == frozen.reward
        assert replayed.prefix[0].endswith("t0")


def test_averaging_over_orderings_differs_from_a_single_order_only_on_ties():
    """A tie is order-sensitive; a clear majority is not. The whole 0.620 vs
    0.577 gap is the first kind."""
    tie = pool_from([row(i, a, reward=r) for i, (a, r) in enumerate([("A", 1.0), ("A", 1.0), ("B", 0.0), ("B", 0.0)])])
    clear = pool_from(
        [row(i, a, reward=r) for i, (a, r) in enumerate([("A", 1.0), ("A", 1.0), ("A", 1.0), ("B", 0.0)])]
    )

    tie_df = replay_policy(FixedK(4), [tie])
    assert tie_df[tie_df.ordering == "0123"].reward_abstain_zero.iloc[0] == 1.0
    assert tie_df.reward_abstain_zero.mean() == pytest.approx(0.5)

    clear_df = replay_policy(FixedK(4), [clear])
    assert clear_df.reward_abstain_zero.nunique() == 1, "a clear majority cannot be order-sensitive"
    assert clear_df.reward_abstain_zero.mean() == pytest.approx(1.0)
