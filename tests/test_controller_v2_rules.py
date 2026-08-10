"""Tests for the Controller-v2 candidate rules (`scripts/controller_v2_offline.py`).

Two things here are load-bearing and would otherwise fail silently:

1. **`v1_frozen` must reproduce the frozen Phase-2B controller exactly.** The
   whole offline comparison is meaningless if the reimplementation of the
   incumbent drifts from `controller.build_controller`.
2. **The "no-abstention" variants are claimed to be the identical policy.** That
   claim is the offline assessment's central structural finding — consensus
   history cannot act within this action set except through abstention — so it
   is asserted, not asserted-in-prose.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from tests.test_policy import row  # reuse the frozen fixture builder

from biomni_uncertainty.config import ControllerCfg
from biomni_uncertainty.controller import build_controller
from biomni_uncertainty.policy import (
    ABSTAIN,
    ACCEPT,
    CONTINUE,
    InstancePool,
    PolicyState,
    all_orderings,
    replay_one,
    resolve,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location("controller_v2_offline", SCRIPTS / "controller_v2_offline.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["controller_v2_offline"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


def pool_from(rows):
    return InstancePool("gwas_causal_gene_opentargets", 1, tuple(rows), {r["run_id"]: float(r["reward"]) for r in rows})


def state(pool: InstancePool, k: int) -> PolicyState:
    return PolicyState(pool.task_name, pool.views((0, 1, 2, 3))[:k], 4)


# --------------------------------------------------------------------------
# The predicates
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answers, k, expect_majority",
    [
        (["A", "A", "B", "C"], 2, True),  # 2 of 2
        (["A", "B", "A", "C"], 3, True),  # 2 of 3
        (["A", "B", "A", "C"], 4, False),  # 2 of 4  <- the state the redesign targets
        (["A", "B", "A", "A"], 4, True),  # 3 of 4
        (["A", "B", "C", "D"], 4, False),  # no agreement at all
    ],
)
def test_strict_majority_separates_2_of_4_from_every_other_agreeing_state(mod, answers, k, expect_majority):
    pool = pool_from([row(i, a, reward=1.0) for i, a in enumerate(answers)])
    s = state(pool, k)
    assert mod.strict_majority(s, resolve(s.views)) is expect_majority


def test_usable_majority_gives_dead_trajectories_no_vote(mod):
    """[failed, failed, A, A] is 2-of-2 opinions, not 2-of-4 trajectories."""
    pool = pool_from(
        [
            row(0, None, reward=0.0, completed=False),
            row(1, None, reward=0.0, completed=False),
            row(2, "A", reward=1.0),
            row(3, "A", reward=1.0),
        ]
    )
    s = state(pool, 4)
    res = resolve(s.views)
    assert mod.strict_majority(s, res) is False  # 2 of 4 trajectories
    assert mod.usable_majority(s, res) is True  # 2 of 2 opinions


def test_abstain_only_on_total_failure_escalates_when_nothing_is_usable(mod):
    dead = pool_from([row(i, None, reward=0.0, completed=False) for i in range(4)])
    s = state(dead, 4)
    assert mod.abstain_only_on_total_failure(s, resolve(s.views)) is False

    one_real = pool_from(
        [row(0, None, reward=0.0, completed=False)] + [row(i, chr(65 + i), reward=0.0) for i in (1, 2, 3)]
    )
    s2 = state(one_real, 4)
    assert mod.abstain_only_on_total_failure(s2, resolve(s2.views)) is True


def test_confidence_rule_accepts_a_bare_plurality_only_when_it_states_one(mod):
    """2-of-4 with the winning cluster at confidence 1.00 accepts; at 0.95 it does not."""
    for conf, expect in ((1.0, True), (0.95, False)):
        pool = pool_from(
            [
                row(0, "A", reward=1.0, conf=conf),
                row(1, "B", reward=0.0, conf=0.95),
                row(2, "A", reward=1.0, conf=conf),
                row(3, "C", reward=0.0, conf=0.95),
            ]
        )
        s = state(pool, 4)
        assert mod.majority_or_confident_pair(s, resolve(s.views)) is expect


# --------------------------------------------------------------------------
# The two load-bearing structural claims
# --------------------------------------------------------------------------


POOLS = [
    ["A", "A", "B", "B"],
    ["A", "B", "A", "C"],
    ["A", "B", "C", "D"],
    ["A", "A", "A", "A"],
    ["A", "B", "B", "B"],
]


def _pools():
    out = []
    for answers in POOLS:
        out.append(pool_from([row(j, a, reward=1.0 if a == "A" else 0.0) for j, a in enumerate(answers)]))
    return out


def test_v1_frozen_reproduces_the_frozen_phase2b_controller(mod):
    """Byte-for-byte agreement with `controller.build_controller` on every state."""
    frozen = build_controller(
        ControllerCfg(
            enabled=True,
            policy="mandatory_k2",
            min_trajectories=2,
            max_trajectories=4,
            abstain_on_no_agreement=True,
            failure_override=True,
            generate_shadows=True,
        )
    )
    candidate = {p.name: p for p in mod.build_candidates()}["v1_frozen"]
    for pool in _pools():
        for ordering in all_orderings(4):
            a = replay_one(frozen, pool, ordering)
            b = replay_one(candidate, pool, ordering)
            assert (a.action, a.k_used, a.reward_abstain_zero) == (b.action, b.k_used, b.reward_abstain_zero)


def test_without_abstention_consensus_history_cannot_change_any_decision(mod):
    """v1, strict-majority and usable-majority are the SAME policy once abstention
    is removed — the structural reason a Controller-v2 stop-rule has no room to
    act inside the frozen ACCEPT/CONTINUE/ABSTAIN action set."""
    by = {p.name: p for p in mod.build_candidates()}
    a, b, c = by["v1_no_abstain"], by["v2_majority_no_abstain"], by["v2_usable_majority_no_abstain"]
    for pool in _pools():
        for ordering in all_orderings(4):
            ra, rb, rc = (replay_one(p, pool, ordering) for p in (a, b, c))
            assert (ra.action, ra.k_used, ra.reward_abstain_zero) == (rb.action, rb.k_used, rb.reward_abstain_zero)
            assert (ra.action, ra.k_used, ra.reward_abstain_zero) == (rc.action, rc.k_used, rc.reward_abstain_zero)


def test_no_candidate_ever_returns_continue_at_the_budget_cap(mod):
    """The replay harness raises on this; assert it directly for every candidate."""
    for policy in mod.build_candidates():
        for pool in _pools():
            for ordering in all_orderings(4):
                out = replay_one(policy, pool, ordering)
                assert out.action in (ACCEPT, ABSTAIN)


def test_a_capped_rule_never_spends_more_than_its_cap(mod):
    by = {p.name: p for p in mod.build_candidates()}
    for name, cap in (("v2_no_abstain_k3", 3), ("v2_majority_k3", 3), ("v2_k2_or_abstain", 2)):
        for pool in _pools():
            for ordering in all_orderings(4):
                assert replay_one(by[name], pool, ordering).k_used <= cap


def test_mandatory_verification_is_preserved_by_every_candidate(mod):
    """No candidate accepts after a single trajectory: Phase 2A's negative result
    on the K=1 trigger has not been overturned, so no redesign may quietly drop it."""
    for policy in mod.build_candidates():
        if policy.name.startswith("fixed_k1"):
            continue
        for pool in _pools():
            s = state(pool, 1)
            assert policy.decide(s).action == CONTINUE
