#!/usr/bin/env python
"""Phase 2A - offline sequential policy replay on the repaired pooled K=4 pool.

Costs zero model calls. Reads the `phase1_pooled` instrumented table, re-measures
every K=1 behavioural signal from the repaired data, fits grouped out-of-fold
calibration, and replays a fixed set of sequential policies over **all 24
arrival orderings** of every instance's four trajectories.

Offline replay is NOT prospective evidence. Nothing produced here licenses a
deployment claim; it selects at most two candidate policies for a frozen
prospective test (Phase 2B).

    python scripts/phase2a_offline_replay.py \
        --tables <output_root>/phase1_pooled/results/tables \
        --out    <output_root>/phase2a/results
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.model_selection import GroupKFold  # noqa: E402

from biomni_uncertainty import analysis as A  # noqa: E402
from biomni_uncertainty import calibration as CAL  # noqa: E402
from biomni_uncertainty import policy as PL  # noqa: E402
from biomni_uncertainty.plotting import STYLE  # noqa: E402
from biomni_uncertainty.provenance import write_json_atomic  # noqa: E402

# Every constant that shapes a result, in one place.
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260802
N_FOLDS = 5
#: A K=1 acceptance must be supported by at least this many training examples
#: before its measured accuracy is trusted enough to set a threshold.
MIN_ACCEPTS_FOR_THRESHOLD = 10
NEVER_ACCEPT = 1.01
#: "Confidently wrong": the policy answered, believed itself at least this
#: reliable, and was wrong. The number that has to go down. 0.70 is chosen to sit
#: just under the observed accuracy of unanimous K=4 agreement (0.765), so it
#: marks claims the controller can actually reach rather than an unreachable bar.
CONFIDENT_THRESHOLD = 0.70

#: Threshold grids are quantiles of the *observed* out-of-fold score
#: distributions, not round numbers. A fixed grid on the [0,1] probability scale
#: silently lands entirely outside the range a calibrated model produces, and a
#: sweep that never fires looks identical to a policy that does nothing.
K1_SWEEP_QUANTILES = (0.50, 0.60, 0.70, 0.80, 0.90, 0.95)
ABSTAIN_QUANTILES = (0.10, 0.25, 0.50)

BEHAVIORAL_SIGNALS = (
    "final_confidence",
    "total_output_tokens",
    "total_input_tokens",
    "total_tokens",
    "wall_time_seconds",
    "llm_call_count",
    "tool_call_count",
    "unique_tool_count",
    "failed_tool_call_count",
    "failed_tool_call_fraction",
    "code_execution_count",
    "visible_plan_step_count",
    "retrieval_count",
    "exception_count",
    "repeated_tool_call_count",
    "generated_chars",
    "final_response_raw_chars",
    "message_count",
)


# --------------------------------------------------------------------------
# 1. Re-measured K=1 signals
# --------------------------------------------------------------------------


def k1_signal_table(df: pd.DataFrame) -> pd.DataFrame:
    """Every K=1 signal's AUROC against correctness, on the repaired pool.

    Reported twice: over all trajectories, and conditional on the trajectory
    having produced a parseable answer. The second column is the one that
    matters for a K=1 acceptance rule, because a failed trajectory is caught by
    the failure override before any score is consulted - so a signal that only
    works by detecting failures is not a signal a controller can use.
    """
    parseable = df[df.completed & (df.answer_parse_status == "ok")]
    rows = []
    for f in BEHAVIORAL_SIGNALS:
        if f not in df.columns:
            continue
        a_all = A.auroc(pd.to_numeric(df[f], errors="coerce"), df.correct)
        a_par = A.auroc(pd.to_numeric(parseable[f], errors="coerce"), parseable.correct)
        rows.append(
            {
                "signal": f,
                "n_all": int(pd.to_numeric(df[f], errors="coerce").notna().sum()),
                "auroc_all": a_all,
                "auroc_all_flipped": None if a_all is None else max(a_all, 1 - a_all),
                "n_parseable": int(pd.to_numeric(parseable[f], errors="coerce").notna().sum()),
                "auroc_parseable": a_par,
                "auroc_parseable_flipped": None if a_par is None else max(a_par, 1 - a_par),
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values("auroc_parseable_flipped", ascending=False, na_position="last").reset_index(drop=True)


# --------------------------------------------------------------------------
# 2. K=1 calibration
# --------------------------------------------------------------------------


def k1_design(df: pd.DataFrame) -> tuple[np.ndarray, tuple[str, ...]]:
    """Secondary (exploratory) K=1 design: confidence plus three cheap
    behavioural signals, standardized. Four features on 50 instances is already
    at the edge of what the north star permits; it does not grow."""
    X_conf, names = CAL.confidence_features(df.final_confidence)
    extra = []
    extra_names = []
    for f in ("llm_call_count", "total_output_tokens", "tool_call_count"):
        v = pd.to_numeric(df[f], errors="coerce")
        v = np.log1p(v.fillna(v.median()))
        extra.append(((v - v.mean()) / (v.std(ddof=0) or 1.0)).to_numpy())
        extra_names.append(f"log_{f}_z")
    return np.column_stack([X_conf, *extra]), (*names, *extra_names)


def fit_k1_calibrations(df: pd.DataFrame) -> tuple[dict[str, CAL.CalibrationResult], pd.DataFrame]:
    """Pooled Platt (primary), isotonic and a small logistic (both secondary).

    Grouping is the instance throughout; nothing is scored by a model that saw
    its own instance.
    """
    groups = df.global_instance_id.to_numpy()
    y = df.correct.to_numpy(dtype=float)
    X_conf, conf_names = CAL.confidence_features(df.final_confidence)
    X_multi, multi_names = k1_design(df)

    results = {
        "platt_confidence": CAL.logistic_oof(
            X_conf, y, groups, name="platt_confidence", feature_names=conf_names, n_splits=N_FOLDS
        ),
        "isotonic_confidence": CAL.isotonic_oof(
            pd.to_numeric(df.final_confidence, errors="coerce").fillna(CAL.MISSING_CONFIDENCE_FILL).to_numpy(),
            y,
            groups,
            name="isotonic_confidence",
            n_splits=N_FOLDS,
        ),
        "logistic_multi": CAL.logistic_oof(
            X_multi, y, groups, name="logistic_multi", feature_names=multi_names, n_splits=N_FOLDS
        ),
    }

    rows = []
    for name, r in results.items():
        wf = CAL.within_fold_auroc(r, A.auroc)
        rows.append(
            {
                "method": name,
                "role": "primary" if name == "platt_confidence" else "secondary/exploratory",
                "n": int(len(r.y)),
                "auroc_within_fold_mean": wf["mean"],
                "auroc_within_fold_min": wf["min"],
                "auroc_within_fold_max": wf["max"],
                "auroc_oof_pooled": A.auroc(r.oof, r.y),
                "brier_oof": CAL.weighted_brier(r.oof, r.y, r.weights),
                "ece_oof": CAL.weighted_ece(r.oof, r.y, r.weights),
                "mean_predicted": float(np.nanmean(r.oof)),
                "base_rate": float(np.average(r.y, weights=r.weights)),
            }
        )
    # The raw signal, for contrast: stated confidence used AS a probability.
    raw = pd.to_numeric(df.final_confidence, errors="coerce")
    m = raw.notna().to_numpy()
    w = CAL.instance_weights(groups)
    rows.append(
        {
            "method": "raw_verbalized_confidence",
            "role": "NOT USED - shown to justify calibrating",
            "n": int(m.sum()),
            "auroc_within_fold_mean": A.auroc(raw[m], y[m]),
            "auroc_within_fold_min": None,
            "auroc_within_fold_max": None,
            "auroc_oof_pooled": A.auroc(raw[m], y[m]),
            "brier_oof": CAL.weighted_brier(raw[m].to_numpy(), y[m], w[m]),
            "ece_oof": CAL.weighted_ece(raw[m].to_numpy(), y[m], w[m]),
            "mean_predicted": float(raw[m].mean()),
            "base_rate": float(np.average(y[m], weights=w[m])),
        }
    )
    return results, pd.DataFrame(rows)


def task_conditioned_calibration(df: pd.DataFrame) -> pd.DataFrame:
    """Exploratory only: per-task base rates and confidence AUROC.

    Five instances per task cannot support a task-conditioned calibrator; this
    table exists to show *why* pooled calibration is the primary choice.
    """
    rows = []
    for task, g in df.groupby("task_name"):
        par = g[g.completed & (g.answer_parse_status == "ok")]
        rows.append(
            {
                "task_name": task,
                "n_trajectories": len(g),
                "n_instances": g.global_instance_id.nunique(),
                "accuracy": float(g.correct.mean()),
                "n_confidence_present": int(g.final_confidence.notna().sum()),
                "confidence_auroc_parseable": A.auroc(
                    pd.to_numeric(par.final_confidence, errors="coerce"), par.correct
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("accuracy", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# 3. Prefix reliability (the K>=2 signal, on a probability scale)
# --------------------------------------------------------------------------


def enumerate_prefixes(pools: list[PL.InstancePool]) -> pd.DataFrame:
    """Every ordered prefix a policy can reach: 64 per instance at K=4.

    Deduplicated by (instance, ordered run_id tuple) - prefix (a,b) is reachable
    from several orderings but is one state.
    """
    rows = []
    for pool in pools:
        seen: set[tuple[str, ...]] = set()
        for ordering in PL.all_orderings(pool.k):
            views = pool.views(ordering)
            for k in range(1, pool.k + 1):
                prefix = views[:k]
                key = tuple(v.run_id for v in prefix)
                if key in seen:
                    continue
                seen.add(key)
                res = PL.resolve(prefix)
                rows.append(
                    {
                        "global_instance_id": int(pool.rows[0]["global_instance_id"]),
                        "task_name": pool.task_name,
                        "task_instance_id": pool.task_instance_id,
                        "prefix": PL.PREFIX_SEPARATOR.join(key),
                        "k": k,
                        "support": res.support,
                        "support_fraction": res.support_fraction,
                        "rests_on_usable": float(res.rests_on_usable),
                        "valid_agreement": float(res.valid_agreement),
                        "n_failed": res.n_failed,
                        "failed_fraction": res.n_failed / k,
                        "soft_support": PL.soft_support(pool.task_name, prefix, res),
                        "correct": pool.reward_of(res.cluster_key, res.members),
                    }
                )
    return pd.DataFrame(rows)


def fit_prefix_reliability(prefixes: pd.DataFrame, k1_p: dict[str, float]) -> tuple[dict, dict, pd.DataFrame]:
    """Map an observed prefix to P(the answer I now hold is correct).

    Primary is deliberately two features - support fraction and whether the
    answer rests on trajectories that actually ran and parsed. That is a
    transparent model whose coefficients can be read in the report. The
    secondary adds the calibrated K=1 confidence of the plurality members and
    the failure rate, and is labelled exploratory.
    """
    df = prefixes.copy()
    df["mean_k1_p"] = [float(np.mean([k1_p.get(r, np.nan) for r in p.split(PL.PREFIX_SEPARATOR)])) for p in df.prefix]
    df["mean_k1_p"] = df.mean_k1_p.fillna(df.mean_k1_p.median())

    groups = df.global_instance_id.to_numpy()
    y = df.correct.to_numpy(dtype=float)
    w = CAL.instance_weights(groups)

    # `support` and `k` are kept separate rather than collapsed into their ratio:
    # 2-of-2 and 4-of-4 are both "unanimous" but are not equally good evidence
    # (observed 0.71 vs 0.76), and a ratio cannot express that.
    primary_feats = ("support", "k", "rests_on_usable")
    secondary_feats = (*primary_feats, "mean_k1_p", "failed_fraction")
    primary = CAL.logistic_oof(
        df[list(primary_feats)].to_numpy(dtype=float),
        y,
        groups,
        name="prefix_primary",
        feature_names=primary_feats,
        n_splits=N_FOLDS,
        weights=w,
    )
    secondary = CAL.logistic_oof(
        df[list(secondary_feats)].to_numpy(dtype=float),
        y,
        groups,
        name="prefix_secondary",
        feature_names=secondary_feats,
        n_splits=N_FOLDS,
        weights=w,
    )
    df["p_primary"] = primary.oof
    df["p_secondary"] = secondary.oof
    lookup_primary = dict(zip(df.prefix, df.p_primary, strict=True))
    lookup_secondary = dict(zip(df.prefix, df.p_secondary, strict=True))
    return lookup_primary, lookup_secondary, df


def prefix_scorer(lookup: dict[str, float]):
    def score(state: PL.PolicyState, res: PL.Resolution) -> float | None:
        key = PL.PREFIX_SEPARATOR.join(v.run_id for v in state.views)
        v = lookup.get(key)
        return None if v is None or not np.isfinite(v) else float(v)

    return score


# --------------------------------------------------------------------------
# 4. Nested, leak-free K=1 acceptance threshold
# --------------------------------------------------------------------------


def _select_threshold(p: np.ndarray, y: np.ndarray, usable: np.ndarray, target_accuracy: float) -> float:
    """Smallest threshold whose accepted set beats what continuing would achieve.

    The acceptance bar is not a free parameter: accepting after one trajectory is
    only justified if the accepted population is at least as accurate as the
    mandatory-K=2 policy would have been on the same data. If no threshold
    clears that bar with enough support, the answer is "never accept at K=1" -
    which is a result, not a failure.
    """
    ok = usable & np.isfinite(p)
    if not ok.any():
        return NEVER_ACCEPT
    for tau in sorted(set(np.round(p[ok], 6))):
        sel = ok & (p >= tau)
        if sel.sum() < MIN_ACCEPTS_FOR_THRESHOLD:
            continue
        if y[sel].mean() >= target_accuracy:
            return float(tau)
    return NEVER_ACCEPT


def nested_k1(
    df: pd.DataFrame, pools: list[PL.InstancePool]
) -> tuple[dict[str, float], dict[str, float], pd.DataFrame]:
    """Out-of-fold K=1 probabilities and a per-fold acceptance threshold.

    Two nested levels, because a threshold chosen on the same predictions it is
    applied to is a tuned parameter wearing an out-of-fold costume:

    * outer fold -> the calibration model is fitted on the outer training
      instances only and applied to the held-out ones;
    * inner grouped CV *inside* the outer training set -> produces the
      predictions the threshold is selected on.

    No instance influences either the model or the threshold that scores it.
    """
    X, names = CAL.confidence_features(df.final_confidence)
    y = df.correct.to_numpy(dtype=float)
    groups = df.global_instance_id.to_numpy()
    usable = (df.completed & (df.answer_parse_status == "ok")).to_numpy()
    by_instance = {p.rows[0]["global_instance_id"]: p for p in pools}

    p_deploy = np.full(len(df), np.nan)
    tau_row = np.full(len(df), NEVER_ACCEPT)
    fold_rows = []

    for fold, (tr, te) in enumerate(GroupKFold(n_splits=N_FOLDS).split(X, y, groups=groups)):
        w_tr = CAL.instance_weights(groups[tr])
        inner = CAL.logistic_oof(
            X[tr], y[tr], groups[tr], name="inner", feature_names=names, n_splits=N_FOLDS, weights=w_tr
        )
        train_pools = [by_instance[g] for g in np.unique(groups[tr]) if g in by_instance]
        target = PL.replay_policy(PL.MandatoryK2(), train_pools).reward_abstain_zero.mean()
        tau = _select_threshold(inner.oof, y[tr], usable[tr], target)

        model = LogisticRegression(max_iter=2000).fit(X[tr], y[tr], sample_weight=w_tr)
        p_deploy[te] = model.predict_proba(X[te])[:, 1]
        tau_row[te] = tau

        accepted = usable[tr] & (inner.oof >= tau)
        fold_rows.append(
            {
                "fold": fold,
                "n_train_trajectories": int(len(tr)),
                "n_test_trajectories": int(len(te)),
                "mandatory_k2_train_reward": float(target),
                "selected_threshold": float(tau),
                "accepts_at_threshold_train": int(accepted.sum()),
                "accepted_train_accuracy": float(y[tr][accepted].mean()) if accepted.any() else None,
                "coef_confidence": float(model.coef_[0][0]),
                "coef_confidence_missing": float(model.coef_[0][1]),
            }
        )

    run_ids = df.run_id.tolist()
    return (
        dict(zip(run_ids, p_deploy, strict=True)),
        dict(zip(run_ids, tau_row, strict=True)),
        pd.DataFrame(fold_rows),
    )


# --------------------------------------------------------------------------
# 5. Policies
# --------------------------------------------------------------------------


def build_policies(
    k1_p: dict[str, float],
    k1_tau: dict[str, float],
    rel_primary,
    all_rewards: dict[str, float],
    k1_sweep: tuple[float, ...],
    abstain_sweep: tuple[float, ...],
) -> list[PL.Policy]:
    def scorer(v: PL.TrajectoryView) -> float | None:
        p = k1_p.get(v.run_id)
        return None if p is None or not np.isfinite(p) else float(p)

    def nested_tau(v: PL.TrajectoryView) -> float:
        return float(k1_tau.get(v.run_id, NEVER_ACCEPT))

    policies: list[PL.Policy] = [PL.FixedK(n) for n in (1, 2, 3, 4)]
    policies += [
        PL.MandatoryK2(max_k=3, name="mandatory_k2_upto3"),
        PL.MandatoryK2(max_k=4, name="mandatory_k2_upto4"),
        PL.FailureEscalation(),
        PL.K1Selective(scorer, nested_tau, name="k1_selective_nested"),
        PL.CombinedAdaptive(scorer, nested_tau, name="combined_adaptive_nested"),
    ]
    policies += [PL.K1Selective(scorer, PL.const_threshold(t), name=f"k1_selective_sweep_t{t:.3f}") for t in k1_sweep]
    policies += [PL.ConfidenceEscalation(scorer, t, name=f"confidence_escalation_t{t:.3f}") for t in k1_sweep]
    policies += [
        PL.Abstaining(PL.MandatoryK2(max_k=4), rel_primary, t, name=f"mandatory_k2_upto4__abstain_t{t:.3f}")
        for t in abstain_sweep
    ]
    policies += [
        PL.Abstaining(
            PL.K1Selective(scorer, nested_tau, name="k1_selective_nested"),
            rel_primary,
            t,
            name=f"k1_selective_nested__abstain_t{t:.3f}",
        )
        for t in abstain_sweep
    ]
    policies += [PL.OracleAtK(all_rewards, n) for n in (1, 2, 3, 4)] + [PL.OracleStop(all_rewards)]
    return policies


# --------------------------------------------------------------------------
# 6. Statistics
# --------------------------------------------------------------------------


def summarize(per_inst: pd.DataFrame, outcomes: pd.DataFrame, rel_lookup: dict[str, float]) -> pd.DataFrame:
    """One row per policy, with instance-level bootstrap CIs on the primary metrics."""
    conf_wrong = _confidently_wrong(outcomes, rel_lookup)
    rows = []
    for policy, g in per_inst.groupby("policy", sort=True):
        g = g.sort_values(["task_name", "task_instance_id"])
        reward = A.bootstrap_mean(g.reward, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
        mean_k = A.bootstrap_mean(g.mean_k, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
        rows.append(
            {
                "policy": policy,
                "deployable": bool(g.deployable.iloc[0]),
                "n_instances": len(g),
                "reward": reward.point,
                "reward_ci_lo": reward.lo,
                "reward_ci_hi": reward.hi,
                "reward_answered_only": float(g.reward_answered_only.mean(skipna=True)),
                "coverage": float(g.coverage.mean()),
                "abstention_rate": float(g.abstention_rate.mean()),
                "mean_k": mean_k.point,
                "mean_k_ci_lo": mean_k.lo,
                "mean_k_ci_hi": mean_k.hi,
                "total_tokens": float(g.total_tokens.mean()),
                "llm_calls": float(g.llm_calls.mean()),
                "tool_calls": float(g.tool_calls.mean()),
                "wall_time_seconds": float(g.wall_time_seconds.mean()),
                "frac_stop_k1": float(g.frac_stop_k1.mean()),
                "frac_stop_k2": float(g.frac_stop_k2.mean()),
                "frac_stop_k3": float(g.frac_stop_k3.mean()),
                "frac_stop_k4": float(g.frac_stop_k4.mean()),
                "resolved_after_failure_rate": float(g.resolved_after_failure_rate.mean()),
                "recovered_failure_rate": float(g.recovered_failure_rate.mean()),
                "confidently_wrong_rate": conf_wrong.get(policy, float("nan")),
            }
        )
    return pd.DataFrame(rows).sort_values(["deployable", "reward"], ascending=[False, False]).reset_index(drop=True)


def _confidently_wrong(outcomes: pd.DataFrame, rel_lookup: dict[str, float]) -> dict[str, float]:
    """Answered, believed itself reliable, and was wrong - as a fraction of all
    replays (not of answered ones), so abstaining cannot game it downward."""
    rel = outcomes.prefix.map(rel_lookup)
    bad = outcomes.answered & (rel >= CONFIDENT_THRESHOLD) & (outcomes.reward_abstain_zero <= 0)
    return bad.groupby(outcomes.policy).mean().to_dict()


def paired_vs(per_inst: pd.DataFrame, reference: str) -> pd.DataFrame:
    """Paired instance-level bootstrap of every policy against one baseline."""
    idx = ["task_name", "task_instance_id"]
    ref = per_inst[per_inst.policy == reference].set_index(idx).sort_index()
    rows = []
    for policy, g in per_inst.groupby("policy", sort=True):
        if policy == reference:
            continue
        g = g.set_index(idx).sort_index()
        common = ref.index.intersection(g.index)
        d = A.paired_bootstrap_difference(
            g.loc[common, "reward"].to_numpy(),
            ref.loc[common, "reward"].to_numpy(),
            replicates=BOOTSTRAP_REPLICATES,
            seed=BOOTSTRAP_SEED,
        )
        dk = A.paired_bootstrap_difference(
            g.loc[common, "mean_k"].to_numpy(),
            ref.loc[common, "mean_k"].to_numpy(),
            replicates=BOOTSTRAP_REPLICATES,
            seed=BOOTSTRAP_SEED,
        )
        rows.append(
            {
                "policy": policy,
                "reference": reference,
                "deployable": bool(per_inst[per_inst.policy == policy].deployable.iloc[0]),
                "reward_delta": d["difference"],
                "reward_ci_lo": d["ci_lo"],
                "reward_ci_hi": d["ci_hi"],
                "p_two_sided_bootstrap": d["p_two_sided_bootstrap"],
                "mean_k_delta": dk["difference"],
                "mean_k_ci_lo": dk["ci_lo"],
                "mean_k_ci_hi": dk["ci_hi"],
                "n": d["n"],
            }
        )
    return pd.DataFrame(rows).sort_values("reward_delta", ascending=False).reset_index(drop=True)


def retention_table(summary: pd.DataFrame) -> pd.DataFrame:
    """How much of the fixed-K=4 gain, and of the Oracle@4 headroom, is retained.

    Both are expressed over the same K=1 floor, so a policy that spends less than
    K=4 and keeps most of the gain is visible as exactly that.
    """
    s = summary.set_index("policy")
    k1, k4, o4 = s.loc["fixed_k1", "reward"], s.loc["fixed_k4", "reward"], s.loc["oracle_at_k4", "reward"]
    rows = []
    for policy, r in s.iterrows():
        gain = r.reward - k1
        rows.append(
            {
                "policy": policy,
                "deployable": r.deployable,
                "reward": r.reward,
                "mean_k": r.mean_k,
                "gain_over_k1": gain,
                "frac_k4_gain_retained": gain / (k4 - k1) if k4 != k1 else None,
                "frac_oracle4_headroom_captured": gain / (o4 - k1) if o4 != k1 else None,
                "reward_per_trajectory": r.reward / r.mean_k if r.mean_k else None,
            }
        )
    return pd.DataFrame(rows).sort_values("frac_k4_gain_retained", ascending=False).reset_index(drop=True)


def stability(per_inst: pd.DataFrame, candidates: list[str]) -> pd.DataFrame:
    """How often each candidate policy survives resampling the instances.

    A point estimate on 50 instances ranks policies that are 0.5 pp apart; that
    ranking is noise. This resamples instances and asks, per replicate, which
    policies are within one instance's worth of reward (1/50 = 0.02) of the best,
    and how each policy ranks. A policy that is only ever best by a hair is not a
    policy to carry into a prospective test.
    """
    idx = ["task_name", "task_instance_id"]
    wide = per_inst[per_inst.policy.isin(candidates)].pivot_table(index=idx, columns="policy", values="reward")
    wide = wide[candidates]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n = len(wide)
    draws = rng.integers(0, n, size=(BOOTSTRAP_REPLICATES, n))
    vals = wide.to_numpy()
    means = np.stack([vals[d].mean(axis=0) for d in draws])
    best = means.max(axis=1, keepdims=True)
    within = means >= best - 0.02
    ranks = (-means).argsort(axis=1).argsort(axis=1) + 1
    # Ties are counted as wins for everyone tied. `idxmax` would award the task
    # to whichever candidate happens to come first in the list, which reads as
    # "never best" for a policy that ties on every single task.
    per_task = per_inst[per_inst.policy.isin(candidates)].groupby(["task_name", "policy"]).reward.mean().unstack()
    per_task = per_task[candidates]
    best_per_task = per_task.max(axis=1)
    n_best = (per_task.sub(best_per_task, axis=0).abs() < 1e-9).sum(axis=0)
    return pd.DataFrame(
        {
            "policy": candidates,
            "reward": vals.mean(axis=0),
            "frac_resamples_best": (means >= best).mean(axis=0),
            "frac_resamples_within_1_instance_of_best": within.mean(axis=0),
            "mean_rank": ranks.mean(axis=0),
            "n_tasks_best_or_tied": [int(n_best[c]) for c in candidates],
            "n_tasks": int(len(per_task)),
        }
    ).sort_values("frac_resamples_within_1_instance_of_best", ascending=False)


def selective_curve(outcomes: pd.DataFrame, rel_lookup: dict[str, float], policy: str) -> pd.DataFrame:
    """Selective risk vs coverage for one policy, sweeping the abstention bar."""
    g = outcomes[(outcomes.policy == policy) & outcomes.answered].copy()
    g["reliability"] = g.prefix.map(rel_lookup)
    rows = []
    for t in np.round(np.arange(0.0, 1.001, 0.05), 3):
        sel = g[g.reliability >= t]
        rows.append(
            {
                "threshold": float(t),
                "coverage": len(sel) / len(g) if len(g) else 0.0,
                "selective_accuracy": float(sel.reward_abstain_zero.mean()) if len(sel) else None,
                "selective_risk": 1 - float(sel.reward_abstain_zero.mean()) if len(sel) else None,
                "mean_k_among_answered": float(sel.k_used.mean()) if len(sel) else None,
            }
        )
    return pd.DataFrame(rows)


def selective_by_agreement(outcomes: pd.DataFrame, policy: str) -> pd.DataFrame:
    """Selective accuracy by the *interpretable* stopping state, not by a score.

    The calibrated-probability curve inherits a real artifact: each fold's
    logistic has its own intercept, so identical agreement states get different
    probabilities depending on which fold scored them, and a high threshold ends
    up selecting a fold rather than a state. Grouping by (trajectories used,
    agreement support) is fold-free, and it is also the rule an operator would
    actually be given.
    """
    g = outcomes[(outcomes.policy == policy) & outcomes.answered]
    t = (
        g.groupby(["k_used", "support"])
        .agg(n_replays=("reward_abstain_zero", "size"), accuracy=("reward_abstain_zero", "mean"))
        .reset_index()
        .sort_values("accuracy", ascending=False)
    )
    t["coverage_if_this_state_and_better"] = t.n_replays.cumsum() / len(g)
    t["cumulative_accuracy"] = (t.accuracy * t.n_replays).cumsum() / t.n_replays.cumsum()
    return t.reset_index(drop=True)


def by_task(per_inst: pd.DataFrame, policies: list[str]) -> pd.DataFrame:
    g = per_inst[per_inst.policy.isin(policies)]
    out = (
        g.groupby(["policy", "task_name"])
        .agg(
            n_instances=("reward", "size"),
            reward=("reward", "mean"),
            mean_k=("mean_k", "mean"),
            coverage=("coverage", "mean"),
            recovered_failure_rate=("recovered_failure_rate", "mean"),
        )
        .reset_index()
    )
    return out.sort_values(["task_name", "reward"], ascending=[True, False]).reset_index(drop=True)


# --------------------------------------------------------------------------
# 7. Figures
# --------------------------------------------------------------------------


def _save(fig, out: Path, name: str) -> None:
    (out / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(out / "figures" / f"{name}.png", dpi=STYLE["dpi"], bbox_inches="tight")
    plt.close(fig)


#: The figure labels only these adaptive policies. Sweep points and abstaining
#: variants stay in the tables: twenty labelled points on one axis buries the
#: fixed-K baseline, which is the comparison that has to stay legible.
#: (policy, label, x offset in points, y offset in points, horizontal alignment).
#: The three adaptive policies land within 0.25 trajectories and 0.02 reward of
#: each other, so the offsets are placed by hand rather than alternated.
FIGURE_POLICIES = (
    ("mandatory_k2_upto4", "mandatory K=2, up to 4", 9, 8, "left"),
    ("mandatory_k2_upto3", "mandatory K=2, up to 3", -9, -20, "right"),
    ("k1_selective_nested", "K=1 selective (nested)", -9, 10, "right"),
    ("failure_escalation", "failure-only escalation", 9, -6, "left"),
)


def fig_reward_cost(summary: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    s = summary.set_index("policy")
    fixed = summary[summary.policy.str.match(r"fixed_k\d$")].sort_values("mean_k")
    oracle = summary[summary.policy.str.match(r"oracle_at_k\d$")].sort_values("mean_k")
    ax.plot(fixed.mean_k, fixed.reward, "-o", color=STYLE["baseline_color"], label="fixed-K plurality (baseline)")
    ax.plot(
        oracle.mean_k, oracle.reward, "--s", color=STYLE["oracle_color"], label="Oracle@K (UPPER BOUND, not deployable)"
    )
    for i, (p, label, dx, dy, ha) in enumerate(FIGURE_POLICIES):
        r = s.loc[p]
        ax.errorbar(
            r.mean_k,
            r.reward,
            yerr=[[r.reward - r.reward_ci_lo], [r.reward_ci_hi - r.reward]],
            fmt="o",
            markersize=7,
            color=STYLE["point_color"],
            ecolor=STYLE["err_color"],
            elinewidth=0.8,
            capsize=3,
            zorder=3,
            label="adaptive policy (95% CI)" if i == 0 else None,
        )
        ax.annotate(label, (r.mean_k, r.reward), fontsize=7.5, xytext=(dx, dy), textcoords="offset points", ha=ha)
    ax.set_ylim(0, 1)
    ax.set_title("Reward vs mean trajectories used (offline replay, all 24 orderings)", fontsize=STYLE["title_size"])
    ax.set_xlabel("mean trajectories per instance", fontsize=STYLE["label_size"])
    ax.set_ylabel("official reward (abstention scored 0)", fontsize=STYLE["label_size"])
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":")
    ax.set_axisbelow(True)
    ax.legend(fontsize=7.5, loc="lower right")
    fig.text(0.01, 0.005, "n=50 instances; offline replay, NOT prospective evidence.", fontsize=7.5, color="#555555")
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    _save(fig, out, "p2a_01_reward_vs_cost")


def fig_stopping(summary: pd.DataFrame, out: Path, policies: list[str]) -> None:
    s = summary[summary.policy.isin(policies)].set_index("policy").loc[policies]
    fig, ax = plt.subplots(figsize=STYLE["figsize_wide"])
    bottom = np.zeros(len(s))
    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]
    for i, k in enumerate((1, 2, 3, 4)):
        v = s[f"frac_stop_k{k}"].to_numpy()
        ax.bar(range(len(s)), v, bottom=bottom, color=colors[i], label=f"stopped at K={k}")
        bottom += v
    ax.set_xticks(range(len(s)))
    ax.set_xticklabels([p.replace("_", "\n") for p in s.index], fontsize=7)
    ax.set_ylim(0, 1)
    ax.set_title("Where each policy stops (fraction of instance x ordering replays)", fontsize=STYLE["title_size"])
    ax.set_ylabel("fraction of replays", fontsize=STYLE["label_size"])
    ax.legend(fontsize=7.5, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":", axis="y")
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, out, "p2a_02_stopping_distribution")


def fig_selective(curves: dict[str, pd.DataFrame], out: Path) -> None:
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    for name, c in curves.items():
        c = c.dropna(subset=["selective_accuracy"])
        ax.plot(c.coverage, c.selective_accuracy, "-o", markersize=3, label=name.replace("_", " "))
    ax.set_ylim(0, 1)
    ax.set_title("Selective accuracy vs coverage (abstention sweep)", fontsize=STYLE["title_size"])
    ax.set_xlabel("coverage (fraction of instances answered)", fontsize=STYLE["label_size"])
    ax.set_ylabel("accuracy among answered", fontsize=STYLE["label_size"])
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":")
    ax.set_axisbelow(True)
    ax.legend(fontsize=7.5)
    fig.text(
        0.01,
        0.005,
        "n=50 instances; reliability from grouped out-of-fold prefix calibration.",
        fontsize=7.5,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    _save(fig, out, "p2a_03_selective_risk_coverage")


def fig_calibration(results: dict[str, CAL.CalibrationResult], df: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    ax.plot([0, 1], [0, 1], "--", color=STYLE["ref_color"], label="perfect calibration")
    for name, r in results.items():
        t = CAL.reliability_table(r.oof, r.y, r.weights, n_bins=5).dropna(subset=["observed_accuracy"])
        ax.plot(t.mean_predicted, t.observed_accuracy, "-o", markersize=4, label=f"{name} (OOF)")
    raw = pd.to_numeric(df.final_confidence, errors="coerce")
    m = raw.notna()
    ax.scatter(
        [raw[m].mean()],
        [df.correct[m].mean()],
        marker="X",
        s=90,
        color=STYLE["wrong_color"],
        zorder=4,
        label="raw verbalized confidence",
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("K=1 calibration: out-of-fold predicted vs observed accuracy", fontsize=STYLE["title_size"])
    ax.set_xlabel("predicted P(correct)", fontsize=STYLE["label_size"])
    ax.set_ylabel("observed accuracy", fontsize=STYLE["label_size"])
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":")
    ax.set_axisbelow(True)
    ax.legend(fontsize=7.5, loc="upper left")
    fig.text(
        0.01, 0.005, "n=200 trajectories, 50 instances; GroupKFold on the instance.", fontsize=7.5, color="#555555"
    )
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    _save(fig, out, "p2a_04_k1_calibration")


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
    ax.set_title("Reward by task (5 instances per task - directional only)", fontsize=STYLE["title_size"])
    ax.set_ylabel("official reward", fontsize=STYLE["label_size"])
    ax.legend(fontsize=7.5)
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":", axis="y")
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, out, "p2a_05_by_task")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", required=True, type=Path, help="phase1_pooled results/tables directory")
    ap.add_argument("--out", required=True, type=Path, help="output directory for phase2a results")
    args = ap.parse_args()

    out = args.out
    (out / "tables").mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(args.tables / "instrumented.parquet").sort_values(
        ["task_name", "task_instance_id", "trajectory_index"]
    )
    print(f"[phase2a] {len(df)} instrumented trajectories, {df.global_instance_id.nunique()} instances")

    tables: dict[str, pd.DataFrame] = {}

    # 1. re-measured signals
    tables["p2a_k1_signal_auroc"] = k1_signal_table(df)

    # 2. K=1 calibration
    k1_results, cal_summary = fit_k1_calibrations(df)
    tables["p2a_k1_calibration"] = cal_summary
    tables["p2a_k1_reliability"] = CAL.reliability_table(
        k1_results["platt_confidence"].oof,
        k1_results["platt_confidence"].y,
        k1_results["platt_confidence"].weights,
    )
    tables["p2a_task_conditioned_exploratory"] = task_conditioned_calibration(df)

    # 3. pools and prefix reliability
    pools = PL.build_pools(df)
    all_rewards = {rid: r for p in pools for rid, r in p.rewards.items()}
    prefixes = enumerate_prefixes(pools)
    k1_oof_by_run = dict(zip(df.run_id, k1_results["platt_confidence"].oof, strict=True))
    rel_primary_lookup, rel_secondary_lookup, prefix_df = fit_prefix_reliability(prefixes, k1_oof_by_run)
    tables["p2a_prefix_reliability"] = (
        prefix_df.drop(columns=["prefix"])
        .groupby(["k", "support", "rests_on_usable"], as_index=False)
        .agg(
            n=("correct", "size"),
            observed_accuracy=("correct", "mean"),
            p_primary_oof=("p_primary", "mean"),
            p_secondary_oof=("p_secondary", "mean"),
        )
    )

    # 4. nested threshold
    k1_p, k1_tau, fold_tbl = nested_k1(df, pools)
    tables["p2a_nested_k1_folds"] = fold_tbl
    print(f"[phase2a] nested K=1 thresholds per fold: {fold_tbl.selected_threshold.tolist()}")

    # 5. replay. Sweep grids come from the observed score distributions.
    rel_primary = prefix_scorer(rel_primary_lookup)
    usable = df.completed & (df.answer_parse_status == "ok")
    k1_scores = np.array([k1_p[r] for r in df.run_id[usable]])
    k1_sweep = tuple(sorted({round(float(q), 3) for q in np.quantile(k1_scores, K1_SWEEP_QUANTILES)}))
    rel_scores = np.array([v for v in rel_primary_lookup.values() if np.isfinite(v)])
    abstain_sweep = tuple(sorted({round(float(q), 3) for q in np.quantile(rel_scores, ABSTAIN_QUANTILES)}))
    print(f"[phase2a] K=1 score range {k1_scores.min():.3f}-{k1_scores.max():.3f}, sweep {k1_sweep}")
    print(f"[phase2a] prefix reliability range {rel_scores.min():.3f}-{rel_scores.max():.3f}, abstain {abstain_sweep}")
    policies = build_policies(k1_p, k1_tau, rel_primary, all_rewards, k1_sweep, abstain_sweep)
    print(f"[phase2a] replaying {len(policies)} policies x {len(pools)} instances x 24 orderings")
    outcomes = PL.replay_many(policies, pools)
    per_inst = PL.per_instance(outcomes)
    tables["p2a_per_instance"] = per_inst

    # 6. statistics
    summary = summarize(per_inst, outcomes, rel_primary_lookup)
    tables["p2a_policy_summary"] = summary
    tables["p2a_paired_vs_fixed_k4"] = paired_vs(per_inst, "fixed_k4")
    tables["p2a_paired_vs_fixed_k2"] = paired_vs(per_inst, "fixed_k2")
    tables["p2a_paired_vs_fixed_k1"] = paired_vs(per_inst, "fixed_k1")
    tables["p2a_retention"] = retention_table(summary)

    headline = ["fixed_k4", "mandatory_k2_upto4", "k1_selective_nested", "combined_adaptive_nested"]
    tables["p2a_by_task"] = by_task(per_inst, headline + ["fixed_k1", "fixed_k2", "fixed_k3", "oracle_at_k4"])
    tables["p2a_stability"] = stability(
        per_inst,
        [
            "fixed_k1",
            "fixed_k2",
            "fixed_k3",
            "fixed_k4",
            "mandatory_k2_upto3",
            "mandatory_k2_upto4",
            "k1_selective_nested",
            "combined_adaptive_nested",
            "failure_escalation",
        ],
    )

    curves = {p: selective_curve(outcomes, rel_primary_lookup, p) for p in ("fixed_k4", "mandatory_k2_upto4")}
    for name, c in curves.items():
        tables[f"p2a_selective_{name}"] = c
        tables[f"p2a_selective_by_agreement_{name}"] = selective_by_agreement(outcomes, name)

    # 7. figures
    fig_reward_cost(summary, out)
    fig_stopping(
        summary,
        out,
        [
            "fixed_k1",
            "fixed_k2",
            "fixed_k4",
            "mandatory_k2_upto4",
            "k1_selective_nested",
            "combined_adaptive_nested",
            "failure_escalation",
        ],
    )
    fig_selective(curves, out)
    fig_calibration(k1_results, df, out)
    fig_by_task(tables["p2a_by_task"], out, headline)

    for name, t in tables.items():
        t.to_csv(out / "tables" / f"{name}.csv", index=False)
    outcomes.to_parquet(out / "tables" / "p2a_outcomes.parquet", index=False)

    s = summary.set_index("policy")
    write_json_atomic(
        out / "phase2a_results.json",
        {
            "experiment": "phase2a_offline_replay",
            "evidence_class": "OFFLINE REPLAY - not prospective evidence",
            "source_tables": str(args.tables),
            "n_instances": int(df.global_instance_id.nunique()),
            "n_trajectories": int(len(df)),
            "n_orderings_per_instance": 24,
            "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED, "unit": "task instance"},
            "calibration": {"folds": N_FOLDS, "grouping": "global_instance_id", "primary": "platt_confidence"},
            "nested_thresholds": fold_tbl.selected_threshold.tolist(),
            "k1_score_range": [float(k1_scores.min()), float(k1_scores.max())],
            "k1_sweep": list(k1_sweep),
            "prefix_reliability_range": [float(rel_scores.min()), float(rel_scores.max())],
            "abstain_sweep": list(abstain_sweep),
            "confidently_wrong_threshold": CONFIDENT_THRESHOLD,
            "policy_summary": summary.to_dict("records"),
            "retention": tables["p2a_retention"].to_dict("records"),
            "stability": tables["p2a_stability"].to_dict("records"),
            "by_task": tables["p2a_by_task"].to_dict("records"),
            "paired_vs_fixed_k4": tables["p2a_paired_vs_fixed_k4"].to_dict("records"),
            "paired_vs_fixed_k1": tables["p2a_paired_vs_fixed_k1"].to_dict("records"),
            "headline": {
                p: {"reward": float(s.loc[p, "reward"]), "mean_k": float(s.loc[p, "mean_k"])}
                for p in [
                    "fixed_k1",
                    "fixed_k2",
                    "fixed_k3",
                    "fixed_k4",
                    "mandatory_k2_upto4",
                    "k1_selective_nested",
                    "combined_adaptive_nested",
                    "oracle_at_k4",
                ]
            },
        },
    )
    print(summary.to_string(index=False))
    print(f"[phase2a] wrote {len(tables)} tables + 5 figures to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
