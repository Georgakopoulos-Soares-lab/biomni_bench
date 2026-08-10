#!/usr/bin/env python
"""Phase 2B - prospective analysis of the completed online controller run.

CPU only; reads only artifacts already on disk (decision logs, trajectory
metadata, the official evaluator). No GPU, no model calls, no new inference.

This implements `reports/phase2_protocol.md` verbatim: the co-primary
hypotheses (H1 reward retention, H2 cost reduction), the six pre-registered
secondary hypotheses (S1-S6), the matched-compute baseline (S6.1), and the
realized-order-primary / ordering-averaged-secondary split (S7.3). Every
threshold, margin and bootstrap seed is copied from the frozen protocol, not
chosen here.

    python scripts/phase2b_analyze.py \
        --config configs/phase2b.yaml \
        --manifest manifests/phase2b.jsonl \
        --out <output_root>/phase2b/results
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biomni_uncertainty import analysis as A  # noqa: E402
from biomni_uncertainty import policy as PL  # noqa: E402
from biomni_uncertainty.aggregation import attach_rewards, collect_run_records  # noqa: E402
from biomni_uncertainty.benchmark import ManifestEntry, manifest_hash  # noqa: E402
from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.controller import DECISION_LOG_NAME, DecisionLog, build_controller  # noqa: E402
from biomni_uncertainty.evaluation import OfficialEvaluator, binarize  # noqa: E402
from biomni_uncertainty.plotting import STYLE  # noqa: E402
from biomni_uncertainty.provenance import write_json_atomic  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase2b_run import CONDITION_CONSUMED, CONDITION_SHADOW, spec_for  # noqa: E402

# Every threshold below is copied verbatim from reports/phase2_protocol.md.
MANIFEST_HASH = "7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd"
H1_MARGIN = 0.05
H2_MEAN_K_CEILING = 3.0
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260802
CONTROLLER_POLICY_NAME = "mandatory_k2_online"
MATCHED_EXPECTATION_NAME = "matched_compute_expectation"
MATCHED_REALIZED_NAME = "matched_compute_realized_draw"


# --------------------------------------------------------------------------
# 1. Load the run: decision logs are authoritative for what the controller did
# --------------------------------------------------------------------------


def load_decision_logs(cfg, entries: list[ManifestEntry]) -> pd.DataFrame:
    """One row per instance: depth, terminal action/reason, chain integrity."""
    rows = []
    for e in entries:
        d = cfg.runs_dir / e.task_name / f"i{e.task_instance_id:04d}"
        log = DecisionLog(d / DECISION_LOG_NAME)
        ok, why = log.verify()
        term = log.terminal()
        if term is None:
            raise RuntimeError(f"{e.task_name}/i{e.task_instance_id:04d}: no terminal decision in {d}")
        rows.append(
            {
                "task_name": e.task_name,
                "task_instance_id": e.task_instance_id,
                "global_instance_id": e.global_instance_id,
                "depth": term.step,
                "action": term.action,
                "reason": term.reason,
                "support": term.support,
                "valid_agreement": term.valid_agreement,
                "resolved_cluster_key": term.resolved_cluster_key,
                "decided_at": term.decided_at,
                "chain_root": log.last_hash,
                "chain_ok": ok,
                "chain_why": why,
                "n_records": log.n_steps,
            }
        )
    return pd.DataFrame(rows)


def build_pooled_trajectory_table(cfg, entries: list[ManifestEntry], decisions: pd.DataFrame) -> pd.DataFrame:
    """All 600 trajectories (consumed + shadow), with official reward attached.

    Reuses `collect_run_records` (no ground truth) and `attach_rewards` (the
    official evaluator) exactly as Phase 1's pipeline does - no scoring logic is
    reimplemented here.
    """
    by_key = decisions.set_index(["task_name", "task_instance_id"])
    specs = []
    for e in entries:
        depth = int(by_key.loc[(e.task_name, e.task_instance_id), "depth"])
        for idx in range(cfg.controller.max_trajectories):
            condition = CONDITION_CONSUMED if idx < depth else CONDITION_SHADOW
            specs.append(spec_for(cfg, e, idx, condition))

    df = collect_run_records(specs)
    evaluator = OfficialEvaluator.from_groundtruth_file("manifests/phase2b.groundtruth.jsonl")
    df = attach_rewards(df, evaluator, cfg.analysis.binary_reward_threshold)

    counts = df.groupby(["task_name", "task_instance_id"]).size()
    bad = counts[counts != cfg.controller.max_trajectories]
    if len(bad):
        raise RuntimeError(f"instances without exactly K trajectories: {bad.to_dict()}")
    role_mismatch = 0
    for (task, tid), g in df.groupby(["task_name", "task_instance_id"]):
        depth = int(by_key.loc[(task, tid), "depth"])
        expected = {i: (CONDITION_CONSUMED if i < depth else CONDITION_SHADOW) for i in range(len(g))}
        for r in g.to_dict("records"):
            if r["condition"] != expected[int(r["trajectory_index"])]:
                role_mismatch += 1
    if role_mismatch:
        raise RuntimeError(f"{role_mismatch} trajectories have a condition inconsistent with their instance's depth")
    return df


def integrity_check_decisions(pools: list[PL.InstancePool], decisions: pd.DataFrame) -> pd.DataFrame:
    """Recompute the terminal resolution from stored metadata and compare it to
    what the online controller actually committed. A mismatch would mean the
    online run and the offline analysis disagree about what happened - it must
    be surfaced, not silently trusted."""
    by_key = decisions.set_index(["task_name", "task_instance_id"])
    rows = []
    for pool in pools:
        depth = int(by_key.loc[(pool.task_name, pool.task_instance_id), "depth"])
        views = pool.views(tuple(range(depth)))
        res = PL.resolve(views)
        logged = by_key.loc[(pool.task_name, pool.task_instance_id)]
        rows.append(
            {
                "task_name": pool.task_name,
                "task_instance_id": pool.task_instance_id,
                "recomputed_cluster_key": res.cluster_key,
                "logged_cluster_key": logged["resolved_cluster_key"],
                "recomputed_support": res.support,
                "logged_support": logged["support"],
                "recomputed_valid_agreement": res.valid_agreement,
                "logged_valid_agreement": bool(logged["valid_agreement"]),
                "match": (
                    res.cluster_key == logged["resolved_cluster_key"]
                    and res.support == logged["support"]
                    and res.valid_agreement == bool(logged["valid_agreement"])
                ),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 2. Realized-order outcomes: controller (authoritative) + every baseline
# --------------------------------------------------------------------------

REPLAY_OUTCOME_FIELDS = (
    "policy",
    "deployable",
    "task_name",
    "task_instance_id",
    "ordering",
    "prefix",
    "k_used",
    "action",
    "stop_reason",
    "answered",
    "reward",
    "reward_abstain_zero",
    "reliability",
    "support",
    "support_fraction",
    "valid_agreement",
    "soft_support",
    "n_failed_seen",
    "first_view_failed",
    "resolved_after_failure",
    "recovered_failure",
    "total_tokens",
    "total_output_tokens",
    "llm_calls",
    "tool_calls",
    "wall_time_seconds",
)


def controller_realized_row(pool: PL.InstancePool, depth: int, term_row: pd.Series) -> dict:
    """The online controller's actual outcome, in the same shape as
    `policy.ReplayOutcome.to_dict()` so it stacks with the baseline rows."""
    views = pool.views(tuple(range(depth)))
    res = PL.resolve(views)
    action = term_row["action"]
    answered = action == PL.ACCEPT
    reward = pool.reward_of(res.cluster_key, res.members) if answered else None
    first_failed = views[0].any_failure
    return {
        "policy": CONTROLLER_POLICY_NAME,
        "deployable": True,
        "task_name": pool.task_name,
        "task_instance_id": pool.task_instance_id,
        "ordering": tuple(range(4)),
        "prefix": tuple(v.run_id for v in views),
        "k_used": depth,
        "action": action,
        "stop_reason": term_row["reason"],
        "answered": answered,
        "reward": reward,
        "reward_abstain_zero": float(reward) if answered else 0.0,
        "reliability": None,
        "support": res.support,
        "support_fraction": res.support_fraction,
        "valid_agreement": res.valid_agreement,
        "soft_support": PL.soft_support(pool.task_name, views, res),
        "n_failed_seen": res.n_failed,
        "first_view_failed": first_failed,
        "resolved_after_failure": bool(first_failed and answered and res.rests_on_usable),
        "recovered_failure": bool(first_failed and answered and (reward or 0.0) > 0),
        "total_tokens": float(np.nansum([v.total_tokens for v in views])),
        "total_output_tokens": float(np.nansum([v.total_output_tokens for v in views])),
        "llm_calls": float(np.nansum([v.llm_call_count for v in views])),
        "tool_calls": float(np.nansum([v.tool_call_count for v in views])),
        "wall_time_seconds": float(np.nansum([v.wall_time_seconds for v in views])),
    }


def realized_order_outcomes(pools: list[PL.InstancePool], decisions: pd.DataFrame) -> pd.DataFrame:
    """One row per (policy, instance) at the single realized arrival order.

    `trajectory_index` order **is** generation order in this driver (spec_for
    is called with idx=0,1,2,...  strictly increasing, both for the consumed
    prefix and for the shadows that follow it), so ordering=(0,1,2,3) is the
    realized order, not a choice.
    """
    by_key = decisions.set_index(["task_name", "task_instance_id"])
    rewards_all = {rid: r for p in pools for rid, r in p.rewards.items()}
    rows = []
    baselines = [PL.FixedK(k) for k in (1, 2, 3, 4)]
    oracles = [PL.OracleAtK(rewards_all, k) for k in (1, 2, 3, 4)] + [PL.OracleStop(rewards_all)]
    for pool in pools:
        term = by_key.loc[(pool.task_name, pool.task_instance_id)]
        rows.append(controller_realized_row(pool, int(term["depth"]), term))
        for policy in [*baselines, *oracles]:
            rows.append(PL.replay_one(policy, pool, (0, 1, 2, 3)).to_dict())
    df = pd.DataFrame(rows)
    df["ordering"] = df["ordering"].apply(lambda o: "".join(str(i) for i in o))
    df["prefix"] = df["prefix"].apply(lambda p: ";".join(p))
    return df


def matched_compute_baseline(realized: pd.DataFrame, n_instances: int) -> tuple[pd.DataFrame, dict]:
    """A REAL non-adaptive allocation at exactly the controller's realized cost
    (D-24) - not an interpolation. m/r are computed from the controller's own
    total, never chosen."""
    ctrl = realized[realized.policy == CONTROLLER_POLICY_NAME].set_index(["task_name", "task_instance_id"])
    total_b = int(ctrl.k_used.sum())
    m, r = divmod(total_b, n_instances)
    frac = r / n_instances
    meta = {"total_b": total_b, "n_instances": n_instances, "m": m, "r": r, "frac_getting_m_plus_1": frac}

    fk_m = realized[realized.policy == f"fixed_k{m}"].set_index(["task_name", "task_instance_id"])
    fk_m1 = realized[realized.policy == f"fixed_k{m + 1}"].set_index(["task_name", "task_instance_id"])
    idx = fk_m.index

    expectation_rows = []
    for i in idx:
        r_m, r_m1 = fk_m.loc[i, "reward_abstain_zero"], fk_m1.loc[i, "reward_abstain_zero"]
        c_m = {
            f: fk_m.loc[i, f]
            for f in ("total_tokens", "total_output_tokens", "llm_calls", "tool_calls", "wall_time_seconds")
        }
        c_m1 = {f: fk_m1.loc[i, f] for f in c_m}
        expectation_rows.append(
            {
                "policy": MATCHED_EXPECTATION_NAME,
                "deployable": True,
                "task_name": i[0],
                "task_instance_id": i[1],
                "k_used": m + frac,
                "action": "ACCEPT",
                "answered": True,
                "reward": (1 - frac) * r_m + frac * r_m1,
                "reward_abstain_zero": (1 - frac) * r_m + frac * r_m1,
                "support": np.nan,
                "valid_agreement": np.nan,
                **{f: (1 - frac) * c_m[f] + frac * c_m1[f] for f in c_m},
            }
        )
    expectation = pd.DataFrame(expectation_rows)

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    plus_one = set(rng.choice(len(idx), size=r, replace=False).tolist())
    realized_rows = []
    for pos, i in enumerate(idx):
        src = fk_m1 if pos in plus_one else fk_m
        row = src.loc[i].to_dict()
        row = {**row, "policy": MATCHED_REALIZED_NAME, "task_name": i[0], "task_instance_id": i[1]}
        realized_rows.append(row)
    realized_draw = pd.DataFrame(realized_rows)[
        [c for c in expectation.columns if c in pd.DataFrame(realized_rows).columns]
    ]

    return pd.concat([expectation, realized_draw], ignore_index=True), meta


# --------------------------------------------------------------------------
# 3. Statistics
# --------------------------------------------------------------------------


def paired(realized: pd.DataFrame, policy: str, reference: str, value_col: str = "reward_abstain_zero") -> dict:
    idx = ["task_name", "task_instance_id"]
    a = realized[realized.policy == policy].set_index(idx).sort_index()
    b = realized[realized.policy == reference].set_index(idx).sort_index()
    common = a.index.intersection(b.index)
    return A.paired_bootstrap_difference(
        a.loc[common, value_col].astype(float).to_numpy(),
        b.loc[common, value_col].astype(float).to_numpy(),
        replicates=BOOTSTRAP_REPLICATES,
        seed=BOOTSTRAP_SEED,
    )


def policy_summary(realized: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for policy, g in realized.groupby("policy", sort=True):
        reward = A.bootstrap_mean(g.reward_abstain_zero, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
        mean_k = A.bootstrap_mean(g.k_used.astype(float), replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
        rows.append(
            {
                "policy": policy,
                "n": len(g),
                "reward": reward.point,
                "reward_ci_lo": reward.lo,
                "reward_ci_hi": reward.hi,
                "reward_answered_only": float(g.loc[g.answered, "reward"].astype(float).mean())
                if g.answered.any()
                else None,
                "coverage": float(g.answered.mean()),
                "abstention_rate": float((~g.answered).mean()) if "action" in g else None,
                "mean_k": mean_k.point,
                "mean_k_ci_lo": mean_k.lo,
                "mean_k_ci_hi": mean_k.hi,
                "total_tokens": float(g.total_tokens.mean()),
                "total_output_tokens": float(g.total_output_tokens.mean()),
                "tool_calls": float(g.tool_calls.mean()),
                "wall_time_seconds": float(g.wall_time_seconds.mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("reward", ascending=False).reset_index(drop=True)


def is_confidently_wrong_state(support, k_used) -> bool:
    """S1: >=3-of-4 or 3-of-3 agreement. Exact wording of the protocol."""
    if pd.isna(support) or pd.isna(k_used):
        return False
    support, k_used = int(support), int(k_used)
    return (k_used == 3 and support == 3) or (k_used == 4 and support >= 3)


def confidently_wrong_rate(realized: pd.DataFrame, policy: str, threshold: float) -> tuple[float, int]:
    g = realized[realized.policy == policy]
    confident = g.apply(lambda r: is_confidently_wrong_state(r.support, r.k_used), axis=1)
    wrong = g.answered & confident & (g.reward.fillna(0).apply(lambda v: binarize(v, threshold)) == 0)
    return float(wrong.mean()), int((g.answered & confident).sum())


def s2_abstention(realized: pd.DataFrame) -> dict:
    ctrl = realized[realized.policy == CONTROLLER_POLICY_NAME].set_index(["task_name", "task_instance_id"])
    fk4 = realized[realized.policy == "fixed_k4"].set_index(["task_name", "task_instance_id"])
    answered_accuracy = float(ctrl.loc[ctrl.answered, "reward"].astype(float).mean())
    # Full-coverage counterfactual: accept even where the controller abstained.
    # At ABSTAIN the controller always holds all 4 (§2.1), so its resolved
    # answer there is identical to fixed_k4's - reuse that reward directly.
    full_coverage = ctrl.reward_abstain_zero.where(ctrl.answered, fk4.reward_abstain_zero)
    return {
        "answered_accuracy": answered_accuracy,
        "coverage": float(ctrl.answered.mean()),
        "full_coverage_accuracy": float(full_coverage.mean()),
        "s2_holds": answered_accuracy > float(full_coverage.mean()),
    }


def s3_failure_recovery(pooled: pd.DataFrame, realized: pd.DataFrame) -> dict:
    first = pooled[pooled.trajectory_index == 0]
    failed_first = first[(~first.completed) | (first.answer_parse_status != "ok")]
    n_failed_first = len(failed_first)
    if n_failed_first == 0:
        return {"n_instances_with_failed_first_trajectory": 0, "applicable": False}
    keys = set(zip(failed_first.task_name, failed_first.task_instance_id.astype(int), strict=True))
    ctrl = realized[realized.policy == CONTROLLER_POLICY_NAME]
    sub = ctrl[ctrl.apply(lambda r: (r.task_name, int(r.task_instance_id)) in keys, axis=1)]
    return {
        "n_instances_with_failed_first_trajectory": n_failed_first,
        "applicable": True,
        "controller_resolved_to_real_answer_rate": float(sub.answered.mean()),
        "fixed_k1_resolved_rate": 0.0,
    }


def s4_confidence_one(pooled: pd.DataFrame) -> dict:
    par = pooled[(pooled.completed) & (pooled.answer_parse_status == "ok")]
    conf1 = par[par.final_confidence == 1.0]
    rest = par[par.final_confidence != 1.0]
    return {
        "n_confidence_1": len(conf1),
        "n_rest": len(rest),
        "accuracy_confidence_1": float(conf1.correct.mean()) if len(conf1) else None,
        "accuracy_rest": float(rest.correct.mean()) if len(rest) else None,
    }


MAX_OVERFLOW_FRACTION = 0.15  # reports/phase2_protocol.md §11, run-level halt condition
HIGH_RISK_TASK = "rare_disease_diagnosis"


def halt_condition_check(pooled: pd.DataFrame) -> dict:
    """§11's residual-failure halt condition, computed the way it should have
    been checked in real time.

    `scripts/phase2b_verify.py`'s gate had a bug (exact string match against
    "budget_terminated" when the runner records the fuller
    "budget_terminated_consecutive_runaway") that let this go undetected through
    both the smoke test and the full run. It is recomputed here, correctly,
    against the completed data - not to retroactively halt a run that already
    finished, but because the protocol requires reporting a tripped halt
    condition rather than analyzing "as planned" once one is found.
    """
    is_overflow = pooled.failure_class.astype(str).str.startswith(("model_context_overflow", "budget_terminated"))
    overall = float(is_overflow.mean())
    by_task = (
        pooled.assign(is_overflow=is_overflow).groupby("task_name").is_overflow.mean().sort_values(ascending=False)
    )
    high_risk = pooled[pooled.task_name == HIGH_RISK_TASK]
    rest = pooled[pooled.task_name != HIGH_RISK_TASK]
    return {
        "threshold": MAX_OVERFLOW_FRACTION,
        "n_trajectories": len(pooled),
        "n_overflow": int(is_overflow.sum()),
        "rate_overall": overall,
        "tripped": overall > MAX_OVERFLOW_FRACTION,
        "rate_by_task": by_task.to_dict(),
        "rate_high_risk_task": float(is_overflow[pooled.task_name == HIGH_RISK_TASK].mean())
        if len(high_risk)
        else None,
        "rate_excluding_high_risk_task": float(is_overflow[pooled.task_name != HIGH_RISK_TASK].mean())
        if len(rest)
        else None,
    }


def sensitivity_excluding_task(realized: pd.DataFrame, task: str) -> dict:
    """H1/H2 recomputed excluding one task - the same pre-registered statistics
    (paired bootstrap, same seed, same margins), restricted to a pre-registered
    stratification variable (§8/S6 require rare_disease_diagnosis reported
    separately). This is a robustness breakdown, not a re-run with a different
    threshold chosen after seeing the result."""
    sub = realized[realized.task_name != task]
    idx = ["task_name", "task_instance_id"]
    a = sub[sub.policy == CONTROLLER_POLICY_NAME].set_index(idx).sort_index()
    b = sub[sub.policy == "fixed_k4"].set_index(idx).sort_index()
    common = a.index.intersection(b.index)
    h1 = A.paired_bootstrap_difference(
        a.loc[common, "reward_abstain_zero"].astype(float).to_numpy(),
        b.loc[common, "reward_abstain_zero"].astype(float).to_numpy(),
        replicates=BOOTSTRAP_REPLICATES,
        seed=BOOTSTRAP_SEED,
    )
    h2 = A.bootstrap_mean(a.k_used.astype(float), replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
    return {
        "excluded_task": task,
        "n_instances": len(common),
        "H1_difference": h1["difference"],
        "H1_ci_lo": h1["ci_lo"],
        "H1_ci_hi": h1["ci_hi"],
        "H1_pass": h1["ci_lo"] > -H1_MARGIN,
        "H2_mean_k": h2.point,
        "H2_ci_lo": h2.lo,
        "H2_ci_hi": h2.hi,
        "H2_pass": h2.hi < H2_MEAN_K_CEILING,
        "controller_reward": float(a.reward_abstain_zero.mean()),
        "fixed_k4_reward": float(b.reward_abstain_zero.mean()),
    }


def by_task_table(realized: pd.DataFrame, policies: list[str]) -> pd.DataFrame:
    g = realized[realized.policy.isin(policies)]
    out = (
        g.groupby(["policy", "task_name"])
        .agg(
            n=("reward_abstain_zero", "size"),
            reward=("reward_abstain_zero", "mean"),
            mean_k=("k_used", "mean"),
            coverage=("answered", "mean"),
        )
        .reset_index()
    )
    return out.sort_values(["task_name", "reward"], ascending=[True, False]).reset_index(drop=True)


def selective_by_agreement(realized: pd.DataFrame, policy: str) -> pd.DataFrame:
    g = realized[(realized.policy == policy) & (realized.answered)].copy()
    t = (
        g.groupby(["k_used", "support"])
        .agg(n=("reward_abstain_zero", "size"), accuracy=("reward_abstain_zero", "mean"))
        .reset_index()
        .sort_values("accuracy", ascending=False)
    )
    t["cumulative_coverage"] = t.n.cumsum() / len(g)
    t["cumulative_accuracy"] = (t.accuracy * t.n).cumsum() / t.n.cumsum()
    return t.reset_index(drop=True)


# --------------------------------------------------------------------------
# 4. Figures
# --------------------------------------------------------------------------


def fig_reward_cost(summary: pd.DataFrame, out: Path) -> None:
    s = summary.set_index("policy")
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    fixed = summary[summary.policy.str.match(r"fixed_k\d$")].sort_values("mean_k")
    oracle = summary[summary.policy.str.match(r"oracle_at_k\d$")].sort_values("mean_k")
    ax.plot(fixed.mean_k, fixed.reward, "-o", color=STYLE["baseline_color"], label="fixed-K plurality (realized order)")
    ax.plot(
        oracle.mean_k, oracle.reward, "--s", color=STYLE["oracle_color"], label="Oracle@K (UPPER BOUND, not deployable)"
    )
    r = s.loc[CONTROLLER_POLICY_NAME]
    ax.errorbar(
        r.mean_k,
        r.reward,
        yerr=[[r.reward - r.reward_ci_lo], [r.reward_ci_hi - r.reward]],
        fmt="o",
        markersize=10,
        color=STYLE["point_color"],
        ecolor=STYLE["err_color"],
        capsize=4,
        zorder=4,
        label="controller (prospective, 95% CI)",
    )
    ax.annotate(
        "mandatory K=2\n(online controller)",
        (r.mean_k, r.reward),
        fontsize=8,
        xytext=(8, -18),
        textcoords="offset points",
    )
    m = s.loc[MATCHED_EXPECTATION_NAME]
    ax.scatter(
        [m.mean_k],
        [m.reward],
        marker="D",
        s=70,
        color=STYLE["bar_color_alt"],
        zorder=3,
        label="matched-compute baseline",
    )
    ax.set_ylim(0, 1)
    ax.set_title("Phase 2B prospective: reward vs cost, realized order", fontsize=STYLE["title_size"])
    ax.set_xlabel("mean trajectories per instance", fontsize=STYLE["label_size"])
    ax.set_ylabel("official reward (abstention scored 0)", fontsize=STYLE["label_size"])
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":")
    ax.set_axisbelow(True)
    ax.legend(fontsize=7.5, loc="lower right")
    fig.text(
        0.01, 0.005, "n=150 instances; PROSPECTIVE evidence, realized generation order.", fontsize=7.5, color="#555555"
    )
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    (out / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "figures" / "p2b_01_reward_vs_cost.png", dpi=STYLE["dpi"], bbox_inches="tight")
    plt.close(fig)


def fig_stopping(summary: pd.DataFrame, realized: pd.DataFrame, out: Path) -> None:
    g = realized[realized.policy == CONTROLLER_POLICY_NAME]
    dist = g.k_used.value_counts(normalize=True).reindex([1, 2, 3, 4], fill_value=0.0)
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]
    ax.bar([f"K={k}" for k in dist.index], dist.values, color=colors)
    ax.set_ylim(0, 1)
    ax.set_title("Prospective stopping distribution (n=150 instances)", fontsize=STYLE["title_size"])
    ax.set_ylabel("fraction of instances", fontsize=STYLE["label_size"])
    for i, v in enumerate(dist.values):
        ax.text(i, v + 0.02, f"{v:.0%}", ha="center", fontsize=9)
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":", axis="y")
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out / "figures" / "p2b_02_stopping_distribution.png", dpi=STYLE["dpi"], bbox_inches="tight")
    plt.close(fig)


def fig_by_task(task_tbl: pd.DataFrame, out: Path, policies: list[str]) -> None:
    piv = task_tbl[task_tbl.policy.isin(policies)].pivot(index="task_name", columns="policy", values="reward")
    piv = piv[policies].sort_values(policies[0])
    fig, ax = plt.subplots(figsize=STYLE["figsize_wide"])
    x = np.arange(len(piv))
    width = 0.8 / len(policies)
    for i, p in enumerate(policies):
        ax.bar(x + i * width, piv[p], width, label=p.replace("_", " "))
    ax.set_xticks(x + width * (len(policies) - 1) / 2)
    ax.set_xticklabels(piv.index, rotation=30, ha="right", fontsize=7.5)
    ax.set_ylim(0, 1)
    ax.set_title("Prospective reward by task (realized order)", fontsize=STYLE["title_size"])
    ax.set_ylabel("official reward", fontsize=STYLE["label_size"])
    ax.legend(fontsize=7.5)
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":", axis="y")
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out / "figures" / "p2b_03_by_task.png", dpi=STYLE["dpi"], bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    out = args.out or (cfg.output_dir / "results")
    (out / "tables").mkdir(parents=True, exist_ok=True)

    entries = [ManifestEntry(**json.loads(li)) for li in args.manifest.read_text().splitlines() if li.strip()]
    h = manifest_hash(entries)
    if h != MANIFEST_HASH:
        raise SystemExit(f"FATAL: manifest hash {h} != frozen {MANIFEST_HASH}. Refusing to analyze a drifted sample.")
    print(f"[phase2b_analyze] manifest verified: {len(entries)} instances, hash {h}")

    decisions = load_decision_logs(cfg, entries)
    broken = decisions[~decisions.chain_ok]
    if len(broken):
        raise SystemExit(
            f"FATAL: {len(broken)} decision chains fail to verify - not prospective evidence. {broken[['task_name', 'task_instance_id', 'chain_why']]}"
        )
    print(f"[phase2b_analyze] {len(decisions)} decision logs loaded, all chains verify")

    pooled = build_pooled_trajectory_table(cfg, entries, decisions)
    print(f"[phase2b_analyze] {len(pooled)} trajectories (consumed + shadow), reward attached via OfficialEvaluator")

    pools = PL.build_pools(pooled)
    integrity = integrity_check_decisions(pools, decisions)
    n_mismatch = int((~integrity.match).sum())
    if n_mismatch:
        print(
            f"[phase2b_analyze] WARNING: {n_mismatch} instances where the recomputed resolution disagrees with the online decision log"
        )
    else:
        print(
            f"[phase2b_analyze] integrity check: all {len(integrity)} recomputed resolutions match the online decision log"
        )

    tables: dict[str, pd.DataFrame] = {
        "p2b_decisions": decisions,
        "p2b_integrity_check": integrity,
        "p2b_pooled_trajectories": pooled,
    }

    realized = realized_order_outcomes(pools, decisions)
    matched, matched_meta = matched_compute_baseline(realized, len(pools))
    realized = pd.concat([realized, matched], ignore_index=True)
    tables["p2b_realized_outcomes"] = realized

    summary = policy_summary(realized)
    tables["p2b_policy_summary"] = summary

    # -- co-primary hypotheses ---------------------------------------------
    h1 = paired(realized, CONTROLLER_POLICY_NAME, "fixed_k4")
    ctrl_k = realized[realized.policy == CONTROLLER_POLICY_NAME].k_used.astype(float)
    h2 = A.bootstrap_mean(ctrl_k, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
    h1_pass = h1["ci_lo"] > -H1_MARGIN
    h2_pass = h2.hi < H2_MEAN_K_CEILING
    s_summary = summary.set_index("policy")
    h2_tokens_pass = s_summary.loc[CONTROLLER_POLICY_NAME, "total_tokens"] < s_summary.loc["fixed_k4", "total_tokens"]

    print(
        f"[phase2b_analyze] H1 reward delta vs fixed_k4: {h1['difference']:.4f} [{h1['ci_lo']:.4f}, {h1['ci_hi']:.4f}] -> {'PASS' if h1_pass else 'FAIL'}"
    )
    print(
        f"[phase2b_analyze] H2 mean K: {h2.point:.4f} [{h2.lo:.4f}, {h2.hi:.4f}] -> {'PASS' if h2_pass else 'FAIL'} (tokens: {'PASS' if h2_tokens_pass else 'FAIL'})"
    )

    # -- paired comparisons vs every baseline -------------------------------
    paired_rows = []
    for ref in (
        "fixed_k1",
        "fixed_k2",
        "fixed_k3",
        "fixed_k4",
        MATCHED_EXPECTATION_NAME,
        MATCHED_REALIZED_NAME,
        "oracle_at_k4",
    ):
        d = paired(realized, CONTROLLER_POLICY_NAME, ref)
        dk = paired(realized, CONTROLLER_POLICY_NAME, ref, "k_used")
        paired_rows.append(
            {
                "reference": ref,
                "reward_delta": d["difference"],
                "reward_ci_lo": d["ci_lo"],
                "reward_ci_hi": d["ci_hi"],
                "mean_k_delta": dk["difference"],
                "mean_k_ci_lo": dk["ci_lo"],
                "mean_k_ci_hi": dk["ci_hi"],
                "n": d["n"],
            }
        )
    tables["p2b_paired_vs_baselines"] = pd.DataFrame(paired_rows)

    # -- retention -----------------------------------------------------------
    k1, k4, o4 = (
        s_summary.loc["fixed_k1", "reward"],
        s_summary.loc["fixed_k4", "reward"],
        s_summary.loc["oracle_at_k4", "reward"],
    )
    gain = s_summary.loc[CONTROLLER_POLICY_NAME, "reward"] - k1
    retention = {
        "gain_over_k1": gain,
        "frac_k4_gain_retained": gain / (k4 - k1) if k4 != k1 else None,
        "frac_oracle4_headroom_captured": gain / (o4 - k1) if o4 != k1 else None,
    }

    # -- secondary hypotheses -------------------------------------------------
    s1_ctrl, n1_ctrl = confidently_wrong_rate(realized, CONTROLLER_POLICY_NAME, cfg.analysis.binary_reward_threshold)
    s1_fk4, n1_fk4 = confidently_wrong_rate(realized, "fixed_k4", cfg.analysis.binary_reward_threshold)
    s1 = {
        "controller_rate": s1_ctrl,
        "controller_n_confident": n1_ctrl,
        "fixed_k4_rate": s1_fk4,
        "fixed_k4_n_confident": n1_fk4,
        "s1_holds": s1_ctrl <= s1_fk4,
    }
    s2 = s2_abstention(realized)
    s3 = s3_failure_recovery(pooled, realized)
    s4 = s4_confidence_one(pooled)

    halt = halt_condition_check(pooled)
    if halt["tripped"]:
        print(
            f"[phase2b_analyze] *** HALT CONDITION TRIPPED ***  residual failure rate "
            f"{halt['n_overflow']}/{halt['n_trajectories']} = {halt['rate_overall']:.1%} > {halt['threshold']:.0%}. "
            f"By task: {halt['rate_by_task']}"
        )
    sensitivity_excl_hr = sensitivity_excluding_task(realized, HIGH_RISK_TASK)

    tables["p2b_by_task"] = by_task_table(
        realized, [CONTROLLER_POLICY_NAME, "fixed_k1", "fixed_k2", "fixed_k3", "fixed_k4", "oracle_at_k4"]
    )
    tables["p2b_selective_controller"] = selective_by_agreement(realized, CONTROLLER_POLICY_NAME)
    tables["p2b_selective_fixed_k4"] = selective_by_agreement(realized, "fixed_k4")

    # -- S5: ordering-averaged secondary (offline replay, explicitly labelled) --
    offline_controller = build_controller(cfg.controller)
    offline_policies = [PL.FixedK(k) for k in (1, 2, 3, 4)] + [
        PL.OracleAtK({rid: r for p in pools for rid, r in p.rewards.items()}, 4),
        offline_controller,
    ]
    offline_outcomes = PL.replay_many(offline_policies, pools)
    offline_per_instance = PL.per_instance(offline_outcomes)
    tables["p2b_s5_ordering_averaged_OFFLINE_REPLAY"] = offline_per_instance
    s5_summary = offline_per_instance.groupby("policy").reward.mean().to_dict()

    tables["p2b_halt_condition_by_task"] = pd.DataFrame(
        [{"task_name": t, "overflow_rate": v} for t, v in halt["rate_by_task"].items()]
    )
    tables["p2b_sensitivity_excl_high_risk_task"] = pd.DataFrame([sensitivity_excl_hr])

    # -- write everything ------------------------------------------------
    for name, t in tables.items():
        t.to_csv(out / "tables" / f"{name}.csv", index=False)

    fig_reward_cost(summary, out)
    fig_stopping(summary, realized, out)
    fig_by_task(tables["p2b_by_task"], out, [CONTROLLER_POLICY_NAME, "fixed_k1", "fixed_k4", "oracle_at_k4"])

    results = {
        "experiment": "phase2b",
        "evidence_class": "PROSPECTIVE (realized order); S5 explicitly OFFLINE REPLAY",
        "manifest_hash": h,
        "n_instances": len(entries),
        "n_trajectories": len(pooled),
        "integrity_check_mismatches": n_mismatch,
        "halt_condition_11": halt,
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED, "unit": "task instance"},
        "H1_reward_retention": {
            "margin": H1_MARGIN,
            "difference": h1["difference"],
            "ci_lo": h1["ci_lo"],
            "ci_hi": h1["ci_hi"],
            "pass": h1_pass,
        },
        "H2_cost_reduction": {
            "ceiling": H2_MEAN_K_CEILING,
            "mean_k": h2.point,
            "ci_lo": h2.lo,
            "ci_hi": h2.hi,
            "pass": h2_pass,
            "tokens_below_k4": bool(h2_tokens_pass),
        },
        "headline_pass": bool(h1_pass and h2_pass and h2_tokens_pass),
        "sensitivity_excluding_high_risk_task": sensitivity_excl_hr,
        "matched_compute_baseline": matched_meta,
        "retention": retention,
        "S1_confidently_wrong": s1,
        "S2_abstention": s2,
        "S3_failure_recovery": s3,
        "S4_confidence_one": s4,
        "S5_ordering_averaged_offline_replay": s5_summary,
        "policy_summary": summary.to_dict("records"),
    }
    write_json_atomic(out / "phase2b_results.json", results)
    print(json.dumps({k: v for k, v in results.items() if k not in ("policy_summary",)}, indent=2, default=str))
    print(f"\n[phase2b_analyze] wrote {len(tables)} tables + 3 figures + phase2b_results.json to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
