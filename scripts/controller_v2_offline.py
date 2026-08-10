#!/usr/bin/env python
"""Controller-v2 OFFLINE redesign analysis. CPU only, no model calls, no GPU.

**This is not prospective evidence and can never become prospective evidence.**
It replays candidate stop-rules over trajectories that already exist, on two
pools that have both already been used:

* ``phase1_pooled`` (50 instances) — the pool the frozen Controller v1 was
  designed on (Phase 2A);
* ``phase2b`` (150 instances) — the pool on which Controller v1 was
  prospectively falsified.

Its only job is to decide whether a *new* prospective experiment is justified,
against the bar written down in `reports/post_phase2b_assessment.md` §5 before
this script was run. Any rule that looks good here is a candidate, not a result.

Cross-pool evaluation is the one real check available without new GPU time:
select on one pool, evaluate on the other, in both directions. A rule chosen by
inspecting a pool's selective table and then scored on that same pool is
circular, and is labelled as such in the output.

    python scripts/controller_v2_offline.py --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from biomni_uncertainty.policy import (  # noqa: E402
    ABSTAIN,
    ACCEPT,
    CONTINUE,
    Decision,
    FixedK,
    InstancePool,
    Policy,
    PolicyState,
    Resolution,
    all_orderings,
    build_pools,
    replay_one,
)

BOOTSTRAP_SEED = 20260810  # new stream: not Phase 2B's 20260802
BOOTSTRAP_REPS = 10000
REALIZED_ORDER = (0, 1, 2, 3)


# --------------------------------------------------------------------------
# Candidate rules
# --------------------------------------------------------------------------

#: An acceptance predicate sees only the current step's resolution and the
#: observed views — never a future trajectory, never a reward. Same leakage
#: barrier as `policy.TrajectoryView`; these predicates are handed a
#: `PolicyState`, which is the only object a policy is allowed to condition on.
AcceptFn = Callable[[PolicyState, Resolution], bool]


class StateRule(Policy):
    """Generic consensus-history rule: accept when ``accept`` fires, else continue.

    At the budget cap a rule either accepts the plurality (``abstain_at_cap``
    false) or abstains (true). ``min_k`` keeps mandatory verification explicit:
    with ``min_k=2`` a single unverified analysis is never returned, which every
    candidate here inherits from Controller v1 because Phase 2A's negative
    result on the K=1 trigger has not been overturned.
    """

    def __init__(
        self,
        accept: AcceptFn,
        *,
        name: str,
        description: str = "",
        max_k: int = 4,
        min_k: int = 2,
        abstain_at_cap: bool = True,
    ):
        self.accept = accept
        self.name = name
        self.description = description
        self.max_k = max_k
        self.min_k = min_k
        self.abstain_at_cap = abstain_at_cap

    def decide(self, state: PolicyState) -> Decision:
        cap = min(self.max_k, state.k_max)
        if state.k < min(self.min_k, cap):
            return Decision(CONTINUE, f"mandatory verification, at k={state.k}")
        res = state.resolution()
        if self.accept(state, res):
            return Decision(ACCEPT, f"rule fired: support {res.support}/{res.k}", res.support_fraction)
        if state.k < cap:
            return Decision(CONTINUE, f"rule not satisfied at k={state.k}")
        if self.abstain_at_cap:
            return Decision(ABSTAIN, f"no acceptable state at K={cap}; escalate", res.support_fraction)
        return Decision(ACCEPT, f"cap K={cap}, plurality answer", res.support_fraction)


# --- the predicates, each one sentence long ------------------------------


def any_agreement(_s: PolicyState, res: Resolution) -> bool:
    """Controller v1: two usable trajectories share an answer. Support is always 2."""
    return res.valid_agreement


def strict_majority(_s: PolicyState, res: Resolution) -> bool:
    """The held answer is backed by a strict majority of everything seen.

    2-of-2 yes, 2-of-3 yes, 3-of-4 yes, **2-of-4 no**. This is the prompt's
    candidate expressed without a tunable parameter.
    """
    return res.valid_agreement and 2 * res.support > res.k


def usable_majority(_s: PolicyState, res: Resolution) -> bool:
    """Strict majority among *usable* trajectories; dead runs get no vote.

    Motivated by the post-hoc finding that over half of Controller v1's
    abstentions had at most one usable trajectory — a failure, not a
    disagreement. Here [failed, failed, A, A] accepts (2 of 2 opinions) while
    [A, B, A, B] does not.
    """
    return res.valid_agreement and 2 * res.support > res.n_usable


def unanimous_usable(_s: PolicyState, res: Resolution) -> bool:
    """Every usable trajectory seen so far agrees, and there are at least two."""
    return res.valid_agreement and res.support == res.n_usable


def majority_or_confident_pair(s: PolicyState, res: Resolution) -> bool:
    """Strict majority, or a bare plurality whose winning cluster states 1.00.

    The only candidate that reads verbalized confidence. Included to test the
    prompt's question directly — does the prospectively-validated S4 signal add
    decision value on top of consensus history — not because the evidence
    already supports it.
    """
    if strict_majority(s, res):
        return True
    if not res.valid_agreement:
        return False
    return any(
        m.final_confidence is not None
        and m.final_confidence == m.final_confidence
        and abs(float(m.final_confidence) - 1.0) < 1e-9
        for m in res.members
    )


def abstain_only_on_total_failure(_s: PolicyState, res: Resolution) -> bool:
    """Accept anything backed by at least one usable trajectory; abstain only when
    the instance produced no usable answer at all.

    The minimal abstention rule the post-hoc decomposition suggests: Controller
    v1's abstentions were dominated by instances with fewer than two opinions,
    not by conflicting ones. This keeps escalation for the genuinely empty case
    and stops charging 0 for a weak-but-real answer.
    """
    return res.valid_agreement or res.n_usable >= 1


def build_candidates() -> list[Policy]:
    """Every policy scored by this analysis, baselines first."""
    pols: list[Policy] = [FixedK(n) for n in (1, 2, 3, 4)]
    pols += [
        # --- Controller v1, exactly as frozen, and its no-abstention twin ---
        StateRule(any_agreement, name="v1_frozen", description="Controller v1: accept any 2-agreement, abstain at K=4"),
        StateRule(
            any_agreement,
            name="v1_no_abstain",
            abstain_at_cap=False,
            description="Controller v1 without abstention: accept the K=4 plurality",
        ),
        # --- consensus-history rules ---
        StateRule(
            strict_majority, name="v2_majority", description="strict majority of trajectories seen; abstain else"
        ),
        StateRule(
            strict_majority,
            name="v2_majority_no_abstain",
            abstain_at_cap=False,
            description="strict majority; accept the K=4 plurality rather than abstain",
        ),
        StateRule(
            usable_majority,
            name="v2_usable_majority",
            description="strict majority among usable trajectories (failures get no vote); abstain else",
        ),
        StateRule(
            usable_majority,
            name="v2_usable_majority_no_abstain",
            abstain_at_cap=False,
            description="usable-majority; accept the K=4 plurality rather than abstain",
        ),
        StateRule(unanimous_usable, name="v2_unanimous", description="every usable trajectory agrees; abstain else"),
        # --- cheap rules: stop early or give up early ---
        StateRule(any_agreement, name="v2_k2_or_abstain", max_k=2, description="accept 2-of-2, else abstain (K<=2)"),
        StateRule(any_agreement, name="v2_k3_cap", max_k=3, description="Controller v1 truncated at K=3"),
        StateRule(strict_majority, name="v2_majority_k3", max_k=3, description="strict majority, K<=3"),
        StateRule(
            any_agreement,
            name="v2_no_abstain_k3",
            max_k=3,
            abstain_at_cap=False,
            description="mandatory K=2, stop on agreement, accept the K=3 plurality; the cheapest continuing rule",
        ),
        StateRule(
            abstain_only_on_total_failure,
            name="v2_abstain_on_failure_only",
            description="escalate only when no usable trajectory exists; accept weak-but-real answers",
        ),
        StateRule(
            abstain_only_on_total_failure,
            name="v2_abstain_on_failure_only_k3",
            max_k=3,
            description="escalate only on total failure, K<=3",
        ),
        # --- the one confidence-using rule ---
        StateRule(
            majority_or_confident_pair,
            name="v2_majority_or_conf1",
            description="strict majority, or a bare plurality stating final_confidence == 1.00",
        ),
    ]
    return pols


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PoolData:
    name: str
    pools: list[InstancePool]
    exhaustive: bool  # replay all 24 orderings as well as the realized one


def load_pool(name: str, table: Path) -> PoolData:
    df = pd.read_csv(table)
    if "condition" in df.columns:
        df = df[df.condition.isin(["instrumented", "shadow"])]
    pools = [p for p in build_pools(df) if p.k == 4]
    return PoolData(name, pools, exhaustive=True)


def replay(policies: list[Policy], pd_: PoolData, orderings: list[tuple[int, ...]]) -> pd.DataFrame:
    rows = []
    for pol in policies:
        for pool in pd_.pools:
            for o in orderings:
                rows.append(replay_one(pol, pool, o).to_dict())
    return pd.DataFrame(rows)


def per_instance(out: pd.DataFrame) -> pd.DataFrame:
    """One row per (policy, instance), averaged over the orderings replayed."""
    g = out.groupby(["policy", "task_name", "task_instance_id"], sort=True)
    return g.agg(
        reward=("reward_abstain_zero", "mean"),
        reward_answered_only=("reward", "mean"),
        coverage=("answered", "mean"),
        mean_k=("k_used", "mean"),
        total_tokens=("total_tokens", "mean"),
        support=("support", "mean"),
        valid_agreement=("valid_agreement", "mean"),
        first_view_failed=("first_view_failed", "mean"),
        recovered_failure=("recovered_failure", "mean"),
        resolved_after_failure=("resolved_after_failure", "mean"),
    ).reset_index()


def matched_compute(pi: pd.DataFrame, budget_mean_k: float) -> np.ndarray:
    """D-24's runnable equal-cost baseline, as a per-instance expectation.

    Spend `m` trajectories everywhere and `m+1` on a uniformly random share
    `p = mean_k - m` of instances. Uses no information about any instance, which
    is exactly the point: an adaptive controller that cannot beat this has not
    shown that its adaptivity does anything.
    """
    m = int(np.floor(budget_mean_k))
    p = budget_mean_k - m
    if m >= 4:
        return pivot_reward(pi, "fixed_k4")
    lo = pivot_reward(pi, f"fixed_k{m}") if m >= 1 else np.zeros(len(pivot_reward(pi, "fixed_k1")))
    hi = pivot_reward(pi, f"fixed_k{m + 1}")
    return (1 - p) * lo + p * hi


def pivot_reward(pi: pd.DataFrame, policy: str) -> np.ndarray:
    s = pi[pi.policy == policy].sort_values(["task_name", "task_instance_id"])
    return s["reward"].to_numpy()


def boot_ci(vals: np.ndarray, seed: int = BOOTSTRAP_SEED, reps: int = BOOTSTRAP_REPS) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(vals), size=(reps, len(vals)))
    stat = vals[idx].mean(axis=1)
    return float(np.percentile(stat, 2.5)), float(np.percentile(stat, 97.5))


def confidently_wrong_rate(out: pd.DataFrame) -> pd.Series:
    """S1's definition: answered, held >=3-of-4 or 3-of-3 support, and wrong,
    as a fraction of ALL instances so abstaining cannot game it down."""
    conf = out.answered & (out.support >= 3)
    wrong = conf & (out.reward.fillna(0) <= 0)
    n = out.groupby("policy").size()
    return (out.assign(w=wrong).groupby("policy")["w"].sum() / n).rename("confidently_wrong")


def summarize(out: pd.DataFrame, pi: pd.DataFrame, label: str) -> pd.DataFrame:
    g = pi.groupby("policy")
    summ = g.agg(
        n=("reward", "size"),
        reward=("reward", "mean"),
        reward_answered_only=("reward_answered_only", "mean"),
        coverage=("coverage", "mean"),
        mean_k=("mean_k", "mean"),
        mean_tokens=("total_tokens", "mean"),
        failure_recovery=("recovered_failure", "mean"),
    )
    summ["abstention_rate"] = 1.0 - summ["coverage"]
    summ = summ.join(confidently_wrong_rate(out))

    lo, hi, mlo, mhi = [], [], [], []
    for p in summ.index:
        a, b = boot_ci(pivot_reward(pi, p))
        lo.append(a)
        hi.append(b)
        s = pi[pi.policy == p].sort_values(["task_name", "task_instance_id"])["mean_k"].to_numpy()
        c, d = boot_ci(s)
        mlo.append(c)
        mhi.append(d)
    summ["reward_ci_lo"], summ["reward_ci_hi"] = lo, hi
    summ["mean_k_ci_lo"], summ["mean_k_ci_hi"] = mlo, mhi

    # --- the decisive column: reward minus same-cost blind allocation -----
    deltas, dlo, dhi = [], [], []
    for p in summ.index:
        r = pivot_reward(pi, p)
        mc = matched_compute(pi, float(summ.loc[p, "mean_k"]))
        d = r - mc
        a, b = boot_ci(d)
        deltas.append(float(d.mean()))
        dlo.append(a)
        dhi.append(b)
    summ["vs_matched_compute"] = deltas
    summ["vs_mc_ci_lo"], summ["vs_mc_ci_hi"] = dlo, dhi

    # --- and against fixed K=2, the simplest thing that works -------------
    k2 = pivot_reward(pi, "fixed_k2")
    vs2, v2lo, v2hi = [], [], []
    for p in summ.index:
        d = pivot_reward(pi, p) - k2
        a, b = boot_ci(d)
        vs2.append(float(d.mean()))
        v2lo.append(a)
        v2hi.append(b)
    summ["vs_fixed_k2"] = vs2
    summ["vs_k2_ci_lo"], summ["vs_k2_ci_hi"] = v2lo, v2hi

    summ.insert(0, "pool", label)
    return summ.sort_values("reward", ascending=False).reset_index()


def selective_table(out: pd.DataFrame, policy: str) -> pd.DataFrame:
    s = out[(out.policy == policy) & out.answered]
    return (
        s.groupby(["k_used", "support"])
        .agg(n=("reward", "size"), accuracy=("reward", "mean"))
        .reset_index()
        .assign(policy=policy)
    )


def by_task(pi: pd.DataFrame) -> pd.DataFrame:
    return (
        pi.groupby(["policy", "task_name"])
        .agg(n=("reward", "size"), reward=("reward", "mean"), mean_k=("mean_k", "mean"), coverage=("coverage", "mean"))
        .reset_index()
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase2b-table", type=Path, required=True)
    ap.add_argument("--phase1-table", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pols = build_candidates()
    print(f"{len(pols)} policies, none with a fitted parameter\n")

    results = {}
    tables: dict[str, pd.DataFrame] = {}

    for label, table, orders in (
        ("phase2b_realized", args.phase2b_table, [REALIZED_ORDER]),
        ("phase2b_all_orderings", args.phase2b_table, all_orderings(4)),
        ("phase1_pooled_all_orderings", args.phase1_table, all_orderings(4)),
    ):
        pdata = load_pool(label, table)
        print(f"== {label}: {len(pdata.pools)} instances x {len(orders)} ordering(s) ==")
        out = replay(pols, pdata, orders)
        pi = per_instance(out)
        summ = summarize(out, pi, label)
        tables[f"summary__{label}"] = summ
        tables[f"by_task__{label}"] = by_task(pi)
        tables[f"selective_v1__{label}"] = selective_table(out, "v1_frozen")
        tables[f"selective_majority__{label}"] = selective_table(out, "v2_majority")
        results[label] = summ.to_dict("records")
        cols = ["policy", "reward", "mean_k", "coverage", "vs_matched_compute", "vs_fixed_k2", "confidently_wrong"]
        print(summ[cols].to_string(index=False, float_format=lambda v: f"{v: .4f}"))
        print()

    for name, df in tables.items():
        df.to_csv(args.out / f"{name}.csv", index=False)
    (args.out / "controller_v2_offline.json").write_text(json.dumps(results, indent=2, default=float))
    print(f"wrote {len(tables)} tables to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
