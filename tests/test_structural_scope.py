"""The structural collapse result holds *under stated conditions* — asserted here.

`tests/test_controller_v2_rules.py` already asserts the collapse itself: with
abstention removed, `v1_no_abstain`, `v2_majority_no_abstain` and
`v2_usable_majority_no_abstain` make the identical decision on every instance
under every ordering. That is the positive claim.

This file asserts the **scope**, which is the part a reader is most likely to
over-generalise and the part a future edit is most likely to silently widen.
The claim in `reports/writeup_draft.md` §4.3 is:

    Under exchangeable resampling from a single policy, a fixed maximum K, the
    same terminal plurality resolver, and no terminal action beyond accept or
    abstain, the tested no-abstention consensus rules collapse to one policy;
    and at the budget ceiling, consensus history can only trigger abstention.

It is NOT the claim that any policy over {accept, resample, abstain} is
equivalent. Each test below drops one stated condition and shows the collapse
stops holding — which is what makes the condition load-bearing rather than
decorative.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from tests.test_policy import row

from biomni_uncertainty.policy import (
    ABSTAIN,
    ACCEPT,
    CONTINUE,
    InstancePool,
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


def pool_of(answers):
    return pool_from([row(j, a, reward=1.0 if a == "A" else 0.0) for j, a in enumerate(answers)])


# --------------------------------------------------------------------------
# Condition: "a fixed maximum K" — and specifically K=4.
# --------------------------------------------------------------------------


def test_the_collapse_is_specific_to_the_budget_ceiling_and_breaks_when_it_is_raised(mod):
    """At K=4 a 2-agreement is always already a majority of what has been seen,
    so `any_agreement` and `strict_majority` cannot diverge before the cap; at
    the cap the no-abstain fallback accepts the plurality either way. Raise the
    ceiling and that coincidence ends: with 6 slots, a 2-of-5 agreement is
    accepted by v1 and is NOT a majority, so consensus history changes the
    decision *before* the ceiling.

    This is the concrete content of the draft's clause "consensus history can
    act on continuation before the ceiling."
    """
    by = {p.name: p for p in mod.build_candidates()}
    v1, majority = by["v1_no_abstain"], by["v2_majority_no_abstain"]

    # K=4: identical, as the collapse result says.
    for answers in (("A", "A", "B", "C"), ("A", "B", "A", "C"), ("A", "B", "C", "A")):
        pool = pool_of(answers)
        for ordering in all_orderings(4):
            a, b = replay_one(v1, pool, ordering), replay_one(majority, pool, ordering)
            assert (a.action, a.k_used) == (b.action, b.k_used)

    # K=6: a 2-of-5 agreement is not a majority. The two rules now differ.
    # The registered candidates hard-cap at max_k=4, so the raised ceiling has
    # to be built explicitly - the claim is about the rule family, not about
    # the particular instances registered for the K=4 analysis.
    v1_k6 = mod.StateRule(mod.any_agreement, name="v1_no_abstain_k6", max_k=6, abstain_at_cap=False)
    majority_k6 = mod.StateRule(mod.strict_majority, name="v2_majority_no_abstain_k6", max_k=6, abstain_at_cap=False)

    pool6 = pool_of(("A", "B", "C", "D", "A", "E"))
    ordering = tuple(range(6))
    a, b = replay_one(v1_k6, pool6, ordering), replay_one(majority_k6, pool6, ordering)
    assert a.k_used != b.k_used, (
        "with the ceiling raised, consensus history must be able to change how much is spent; "
        f"got identical k_used={a.k_used} for both rules"
    )
    assert a.k_used == 5, "v1 accepts as soon as two agree (slots 1 and 5)"
    assert b.k_used == 6, "strict majority cannot accept 2-of-5 and must continue to the cap"


# --------------------------------------------------------------------------
# Condition: "the same terminal plurality resolver".
# --------------------------------------------------------------------------


def test_the_collapse_assumes_a_counting_resolver_and_a_ranking_resolver_escapes_it():
    """Every collapsed rule ends by accepting the same terminal *plurality*, so
    the collapse is a statement about a resolver that COUNTS. A resolver that
    RANKS — here, trust the highest-confidence trajectory rather than the
    largest cluster — returns a different answer on exactly the shape of
    instance where the headroom lives (a correct minority against a wrong
    plurality). The terminal resolver is therefore a free parameter the result
    holds fixed, not something it rules out.
    """
    # Wrong plurality {B, B} against a correct, more-confident minority {A}.
    rows = [
        row(0, "B", reward=0.0, conf=0.60),
        row(1, "B", reward=0.0, conf=0.55),
        row(2, "A", reward=1.0, conf=1.00),
    ]
    pool = pool_from(rows)
    views = pool.views((0, 1, 2))

    counted = resolve(views)
    assert counted.cluster_key == "B", "plurality counts, and the wrong answer is the larger cluster"

    def rank_by_confidence(vs):
        usable = [v for v in vs if v.usable]
        return max(usable, key=lambda v: v.final_confidence or 0.0).cluster_key

    assert rank_by_confidence(views) == "A"
    assert rank_by_confidence(views) != counted.cluster_key, (
        "a ranking terminal resolver must be able to disagree with the counting one, "
        "or the 'same terminal plurality resolver' condition would be vacuous"
    )


# --------------------------------------------------------------------------
# Condition: "no terminal action beyond accept or abstain".
# --------------------------------------------------------------------------


def test_the_action_set_contains_no_trajectory_changing_action(mod):
    """The collapse holds because the only non-terminal move is to draw another
    correlated sample. Pin that: every policy in the candidate set returns only
    ACCEPT / CONTINUE / ABSTAIN, and CONTINUE is resampling — there is no
    VERIFY or REPAIR. Escaping the result requires *extending* this set, which
    would make this test fail and force the claim to be restated.
    """
    allowed = {ACCEPT, CONTINUE, ABSTAIN}
    seen = set()
    for policy in mod.build_candidates():
        for answers in (("A", "A", "B", "C"), ("A", "B", "C", "D"), ("A", "B", "C", "A")):
            pool = pool_of(answers)
            for ordering in all_orderings(4):
                out = replay_one(policy, pool, ordering)
                seen.add(out.action)
                assert out.action in allowed

    assert seen <= allowed
    assert seen & {ACCEPT, ABSTAIN}, "terminal actions must actually be exercised by the fixture set"


def test_at_the_ceiling_the_only_lever_consensus_history_has_is_abstention(mod):
    """The second half of the claim, asserted directly: on a 2-of-4 state — the
    one state where the rules genuinely disagree about whether consensus is
    sufficient — the abstaining and non-abstaining variants of the SAME
    consensus rule differ, while the two non-abstaining rules with DIFFERENT
    consensus definitions do not. Consensus history is visible at the cap, and
    abstention is the only thing it can drive.
    """
    by = {p.name: p for p in mod.build_candidates()}
    # The first three answers must be distinct, or a 2-agreement fires earlier
    # and the cap is never reached: A,B,C,A is the only shape that produces a
    # genuine 2-of-4 decision *at* the ceiling.
    pool = pool_of(("A", "B", "C", "A"))
    ordering = (0, 1, 2, 3)

    strict_abstains = replay_one(by["v2_majority"], pool, ordering)
    strict_accepts = replay_one(by["v2_majority_no_abstain"], pool, ordering)
    v1_accepts = replay_one(by["v1_no_abstain"], pool, ordering)

    # Same consensus rule, abstention toggled -> different action. The lever works.
    assert strict_abstains.action != strict_accepts.action

    # Different consensus rules, abstention removed -> identical. No other lever exists.
    assert (v1_accepts.action, v1_accepts.k_used) == (strict_accepts.action, strict_accepts.k_used)
