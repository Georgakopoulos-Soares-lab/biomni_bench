"""Frozen Phase-1 statistical analysis.

Resampling unit is the **task instance**, never the individual trajectory: the
K trajectories of one instance are not independent observations. Trajectory-level
association analyses use grouped (cluster) bootstrap over instances for the same
reason.

Confirmatory quantities (pre-specified in reports/phase1_protocol.md) and
exploratory quantities are returned under separate keys.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from biomni_uncertainty.selectors import (
    DEPLOYABLE_SELECTORS,
    Candidate,
    candidates_from_frame,
    random_expected,
    run_all_selectors,
)

# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Interval:
    point: float | None
    lo: float | None
    hi: float | None
    n: int

    def to_dict(self) -> dict:
        return {"point": self.point, "ci_lo": self.lo, "ci_hi": self.hi, "n": self.n}


def bootstrap_mean(
    values: Sequence[float],
    *,
    replicates: int,
    seed: int,
    alpha: float = 0.05,
) -> Interval:
    """Percentile bootstrap CI for a mean over independent units."""
    arr = np.asarray([v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))], dtype=float)
    if arr.size == 0:
        return Interval(None, None, None, 0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(replicates, arr.size))
    means = arr[idx].mean(axis=1)
    return Interval(
        float(arr.mean()),
        float(np.quantile(means, alpha / 2)),
        float(np.quantile(means, 1 - alpha / 2)),
        int(arr.size),
    )


def paired_bootstrap_difference(
    a: Sequence[float],
    b: Sequence[float],
    *,
    replicates: int,
    seed: int,
    alpha: float = 0.05,
) -> dict:
    """Paired bootstrap of ``mean(a) - mean(b)`` over the same units."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("paired_bootstrap_difference requires aligned arrays")
    mask = ~(np.isnan(a) | np.isnan(b))
    a, b = a[mask], b[mask]
    if a.size == 0:
        return {"difference": None, "ci_lo": None, "ci_hi": None, "n": 0, "p_two_sided_bootstrap": None}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(replicates, a.size))
    diffs = a[idx].mean(axis=1) - b[idx].mean(axis=1)
    point = float(a.mean() - b.mean())
    # Bootstrap two-sided "p-value": how often the resampled difference crosses
    # zero. Reported for descriptive use only - a 50-instance pilot cannot
    # support inference from it.
    frac = float(np.mean(diffs <= 0)) if point > 0 else float(np.mean(diffs >= 0))
    return {
        "difference": point,
        "ci_lo": float(np.quantile(diffs, alpha / 2)),
        "ci_hi": float(np.quantile(diffs, 1 - alpha / 2)),
        "n": int(a.size),
        "p_two_sided_bootstrap": min(1.0, 2 * frac),
    }


def grouped_bootstrap(
    df: pd.DataFrame,
    group_col: str,
    statistic: Callable[[pd.DataFrame], float | None],
    *,
    replicates: int,
    seed: int,
    alpha: float = 0.05,
) -> Interval:
    """Cluster bootstrap: resample whole groups (instances), not rows."""
    groups = df[group_col].unique()
    if len(groups) == 0:
        return Interval(None, None, None, 0)
    point = statistic(df)
    rng = np.random.default_rng(seed)
    by_group = dict(iter(df.groupby(group_col)))
    stats = []
    for _ in range(replicates):
        picked = rng.choice(groups, size=len(groups), replace=True)
        sample = pd.concat([by_group[g] for g in picked], ignore_index=True)
        v = statistic(sample)
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            stats.append(v)
    if not stats:
        return Interval(point, None, None, len(groups))
    return Interval(
        point,
        float(np.quantile(stats, alpha / 2)),
        float(np.quantile(stats, 1 - alpha / 2)),
        len(groups),
    )


# --------------------------------------------------------------------------
# Discrimination and calibration
# --------------------------------------------------------------------------


def auroc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    """Rank-based AUROC (ties get average ranks). ``None`` unless both classes present."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=float)
    mask = ~(np.isnan(s) | np.isnan(y))
    s, y = s[mask], y[mask]
    n1, n0 = int((y == 1).sum()), int((y == 0).sum())
    if n1 == 0 or n0 == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    sorted_s = s[order]
    i = 0
    while i < len(sorted_s):
        j = i
        while j + 1 < len(sorted_s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[i : j + 1] = (i + j) / 2.0 + 1.0
        i = j + 1
    full = np.empty(len(s), dtype=float)
    full[order] = ranks
    return float((full[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def auprc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    """Average precision. ``None`` unless both classes present."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=float)
    mask = ~(np.isnan(s) | np.isnan(y))
    s, y = s[mask], y[mask]
    if len(s) == 0 or (y == 1).sum() == 0 or (y == 0).sum() == 0:
        return None
    order = np.argsort(-s, kind="mergesort")
    y = y[order]
    tp = np.cumsum(y)
    precision = tp / np.arange(1, len(y) + 1)
    n_pos = y.sum()
    return float((precision * y).sum() / n_pos)


def brier_score(probs: Sequence[float], labels: Sequence[int]) -> float | None:
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    mask = ~(np.isnan(p) | np.isnan(y))
    p, y = p[mask], y[mask]
    return float(np.mean((p - y) ** 2)) if p.size else None


def nll(probs: Sequence[float], labels: Sequence[int], clip: float = 1e-6) -> float | None:
    p = np.clip(np.asarray(probs, dtype=float), clip, 1 - clip)
    y = np.asarray(labels, dtype=float)
    mask = ~(np.isnan(p) | np.isnan(y))
    p, y = p[mask], y[mask]
    if p.size == 0:
        return None
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration_bins(
    probs: Sequence[float],
    labels: Sequence[int],
    n_bins: int,
    *,
    equal_frequency: bool = False,
) -> pd.DataFrame:
    """Reliability table with per-bin counts (equal-width by default)."""
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    mask = ~(np.isnan(p) | np.isnan(y))
    p, y = p[mask], y[mask]
    if p.size == 0:
        return pd.DataFrame(columns=["bin", "lo", "hi", "n", "mean_confidence", "accuracy"])
    if equal_frequency:
        edges = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
        if len(edges) < 2:
            edges = np.array([p.min(), p.max() + 1e-9])
    else:
        edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, len(edges) - 2)
    rows = []
    for b in range(len(edges) - 1):
        sel = idx == b
        rows.append(
            {
                "bin": b,
                "lo": float(edges[b]),
                "hi": float(edges[b + 1]),
                "n": int(sel.sum()),
                "mean_confidence": float(p[sel].mean()) if sel.any() else None,
                "accuracy": float(y[sel].mean()) if sel.any() else None,
            }
        )
    return pd.DataFrame(rows)


def expected_calibration_error(probs, labels, n_bins: int, *, equal_frequency: bool = False) -> float | None:
    tab = calibration_bins(probs, labels, n_bins, equal_frequency=equal_frequency)
    tab = tab[tab["n"] > 0]
    if not len(tab):
        return None
    total = tab["n"].sum()
    return float((tab["n"] / total * (tab["mean_confidence"] - tab["accuracy"]).abs()).sum())


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    a = pd.Series(x, dtype="float64")
    b = pd.Series(y, dtype="float64")
    mask = a.notna() & b.notna()
    if mask.sum() < 3 or a[mask].nunique() < 2 or b[mask].nunique() < 2:
        return None
    return float(a[mask].rank().corr(b[mask].rank()))


def selective_accuracy_curve(probs: Sequence[float], labels: Sequence[int]) -> pd.DataFrame:
    """Accuracy as a function of coverage when abstaining on low confidence."""
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    mask = ~(np.isnan(p) | np.isnan(y))
    p, y = p[mask], y[mask]
    if p.size == 0:
        return pd.DataFrame(columns=["coverage", "n_kept", "accuracy", "threshold"])
    order = np.argsort(-p, kind="mergesort")
    y = y[order]
    p = p[order]
    acc = np.cumsum(y) / np.arange(1, len(y) + 1)
    return pd.DataFrame(
        {
            "coverage": np.arange(1, len(y) + 1) / len(y),
            "n_kept": np.arange(1, len(y) + 1),
            "accuracy": acc,
            "threshold": p,
        }
    )


# --------------------------------------------------------------------------
# Oracle@K
# --------------------------------------------------------------------------


def oracle_at_k(instrumented: pd.DataFrame, k_max: int) -> pd.DataFrame:
    """Oracle@K averaged over ALL size-K subsets of each instance's candidates.

    Averaging over all subsets (rather than over prefixes) is the unbiased
    estimate under exchangeable sampling; both are reported so the reader can
    see the labelling.
    """
    rows = []
    for k in range(1, k_max + 1):
        subset_vals, prefix_vals = [], []
        for _, g in instrumented.groupby(["task_name", "task_instance_id"]):
            g = g.sort_values("trajectory_index")
            rewards = [r if r is not None else 0.0 for r in g["reward"].fillna(0.0).tolist()]
            if len(rewards) < k:
                continue
            subs = list(combinations(range(len(rewards)), k))
            subset_vals.append(float(np.mean([max(rewards[i] for i in s) for s in subs])))
            prefix_vals.append(float(max(rewards[:k])))
        rows.append(
            {
                "k": k,
                "oracle_all_subsets": float(np.mean(subset_vals)) if subset_vals else None,
                "oracle_first_k_prefix": float(np.mean(prefix_vals)) if prefix_vals else None,
                "n_instances": len(subset_vals),
            }
        )
    return pd.DataFrame(rows)


def candidate_generation_report(instrumented: pd.DataFrame, instances: pd.DataFrame) -> dict:
    """The headroom question: can trajectory selection help at all?"""
    out: dict[str, Any] = {}
    per_instance = []
    for (task, tid), g in instrumented.groupby(["task_name", "task_instance_id"]):
        g = g.sort_values("trajectory_index")
        rewards = g["reward"].fillna(0.0).tolist()
        correct = [int(r >= 0.5) for r in rewards]
        keys = g["cluster_key"].tolist() if "cluster_key" in g else g["answer_cluster_key"].tolist()
        first_correct = correct[0] if correct else 0
        row = {
            "task_name": task,
            "task_instance_id": int(tid),
            "k": len(correct),
            "first_correct": first_correct,
            "any_correct": int(any(correct)),
            "n_correct": int(sum(correct)),
            "all_correct": int(all(correct)) if correct else 0,
            "all_wrong": int(not any(correct)) if correct else 1,
            "disagreement": int(len(set(keys)) > 1),
            "first_wrong_other_right": int(first_correct == 0 and any(correct)),
        }
        if len(instances):
            m = instances[(instances.task_name == task) & (instances.task_instance_id == int(tid))]
            if len(m):
                pk = m.iloc[0]["plurality_key"]
                plur_rewards = [r for r, kk in zip(rewards, keys, strict=True) if kk == pk]
                row["plurality_correct"] = int(bool(plur_rewards) and max(plur_rewards) >= 0.5)
                row["plurality_wrong_minority_right"] = int(row["plurality_correct"] == 0 and any(correct))
        per_instance.append(row)

    pi = pd.DataFrame(per_instance)
    out["per_instance"] = pi
    if len(pi):
        out["summary"] = {
            "n_instances": len(pi),
            "p_first_correct": float(pi.first_correct.mean()),
            "p_any_correct": float(pi.any_correct.mean()),
            "p_all_wrong": float(pi.all_wrong.mean()),
            "p_disagreement": float(pi.disagreement.mean()),
            "p_first_wrong_other_right": float(pi.first_wrong_other_right.mean()),
            "oracle_headroom_pp": float((pi.any_correct.mean() - pi.first_correct.mean()) * 100),
            "relative_error_reduction_potential": (
                float((pi.any_correct.mean() - pi.first_correct.mean()) / (1 - pi.first_correct.mean()))
                if pi.first_correct.mean() < 1
                else 0.0
            ),
        }
        if "plurality_wrong_minority_right" in pi:
            out["summary"]["p_plurality_wrong_minority_right"] = float(pi.plurality_wrong_minority_right.mean())
        out["by_task"] = (
            pi.groupby("task_name")
            .agg(
                n=("task_instance_id", "count"),
                first=("first_correct", "mean"),
                oracle=("any_correct", "mean"),
                disagreement=("disagreement", "mean"),
            )
            .reset_index()
        )
        out["by_task"]["headroom_pp"] = (out["by_task"]["oracle"] - out["by_task"]["first"]) * 100
    return out


# --------------------------------------------------------------------------
# Selector evaluation
# --------------------------------------------------------------------------


def evaluate_selectors(
    instrumented: pd.DataFrame,
    *,
    length_field: str,
    epsilon: float,
    replicates: int,
    seed: int,
    n_random_resamples: int = 200,
) -> dict:
    """Apply every selector to every instance and bootstrap the comparison."""
    per_instance: list[dict] = []
    detail: list[dict] = []
    rng_master = np.random.default_rng(seed)

    for (task, tid), g in instrumented.groupby(["task_name", "task_instance_id"], sort=True):
        cands: list[Candidate] = candidates_from_frame(g, length_field=length_field)
        sels = run_all_selectors(cands, epsilon=epsilon)
        row = {"task_name": task, "task_instance_id": int(tid), "k": len(cands)}
        for name, s in sels.items():
            row[name] = s.reward if s.reward is not None else 0.0
            detail.append({"task_name": task, "task_instance_id": int(tid), **s.to_dict()})
        row["random_expected"] = random_expected(cands) or 0.0
        # Concrete sampled random baseline via repeated deterministic resampling.
        rng = np.random.default_rng(int(rng_master.integers(0, 2**31 - 1)))
        draws = [cands[int(rng.integers(len(cands)))].reward or 0.0 for _ in range(n_random_resamples)]
        row["random_sampled_mean"] = float(np.mean(draws))
        per_instance.append(row)

    pi = pd.DataFrame(per_instance)
    names = list(DEPLOYABLE_SELECTORS) + ["oracle", "random_expected", "random_sampled_mean"]

    summary = []
    for name in names:
        if name not in pi:
            continue
        ci = bootstrap_mean(pi[name].tolist(), replicates=replicates, seed=seed)
        summary.append({"selector": name, **ci.to_dict(), "is_upper_bound": name == "oracle"})

    comparisons = []
    baselines = ("first", "plurality", "random_expected")
    for name in names:
        if name in baselines or name not in pi:
            continue
        for base in baselines:
            if base not in pi:
                continue
            comparisons.append(
                {
                    "selector": name,
                    "baseline": base,
                    **paired_bootstrap_difference(
                        pi[name].tolist(), pi[base].tolist(), replicates=replicates, seed=seed
                    ),
                }
            )
    # first vs plurality is itself a headline comparison
    if {"plurality", "first"} <= set(pi.columns):
        comparisons.append(
            {
                "selector": "plurality",
                "baseline": "first",
                **paired_bootstrap_difference(
                    pi["plurality"].tolist(), pi["first"].tolist(), replicates=replicates, seed=seed
                ),
            }
        )

    by_task = pi.groupby("task_name")[[n for n in names if n in pi]].mean().reset_index()
    by_task["n"] = pi.groupby("task_name").size().values

    return {
        "per_instance": pi,
        "summary": pd.DataFrame(summary),
        "comparisons": pd.DataFrame(comparisons),
        "by_task": by_task,
        "selection_detail": pd.DataFrame(detail),
    }


# --------------------------------------------------------------------------
# Signal-level analyses
# --------------------------------------------------------------------------

SIGNAL_FIELDS = (
    "final_confidence",
    "agreement_fraction",
    "instance_plurality_fraction",
    "total_output_tokens",
    "total_tokens",
    "log_total_output_tokens",
    "llm_call_count",
    "tool_call_count",
    "unique_tool_count",
    "wall_time_seconds",
    "failed_tool_call_count",
    "failed_tool_call_fraction",
    "repeated_tool_call_count",
    "exception_count",
    "code_execution_count",
    "visible_plan_step_count",
)


def signal_auroc_table(
    df: pd.DataFrame,
    *,
    fields: tuple[str, ...] = SIGNAL_FIELDS,
    replicates: int,
    seed: int,
) -> pd.DataFrame:
    """Trajectory-level AUROC of each signal for correctness, cluster-bootstrapped.

    Signals expected to be *inversely* related to correctness (length, failures)
    are also reported with sign flipped so the direction is explicit rather than
    implied by an AUROC below 0.5.
    """
    if "instance_uid" not in df:
        df = df.copy()
        df["instance_uid"] = df["task_name"] + "::" + df["task_instance_id"].astype(str)

    rows = []
    for f in fields:
        if f not in df.columns:
            rows.append({"signal": f, "available": False, "n": 0})
            continue
        sub = df[["instance_uid", f, "correct"]].dropna()
        if not len(sub) or sub["correct"].nunique() < 2:
            rows.append({"signal": f, "available": True, "n": len(sub), "auroc": None, "note": "single class"})
            continue

        def stat(d: pd.DataFrame, _f=f) -> float | None:
            return auroc(d[_f].tolist(), d["correct"].astype(int).tolist())

        ci = grouped_bootstrap(sub, "instance_uid", stat, replicates=replicates, seed=seed)
        rows.append(
            {
                "signal": f,
                "available": True,
                "n": len(sub),
                "n_instances": ci.n,
                "auroc": ci.point,
                "auroc_ci_lo": ci.lo,
                "auroc_ci_hi": ci.hi,
                "auroc_flipped": (1 - ci.point) if ci.point is not None else None,
                "auprc": auprc(sub[f].tolist(), sub["correct"].astype(int).tolist()),
                "spearman_with_correct": spearman(sub[f].tolist(), sub["correct"].tolist()),
                "base_rate": float(sub["correct"].mean()),
            }
        )
    return pd.DataFrame(rows)


def confidence_calibration(df: pd.DataFrame, *, n_bins: int, replicates: int, seed: int) -> dict:
    """Calibration of verbalized confidence at the trajectory level."""
    sub = df[df["final_confidence"].notna() & df["correct"].notna()].copy()
    total = len(df)
    out: dict[str, Any] = {
        "n_trajectories_total": total,
        "n_with_valid_confidence": len(sub),
        "confidence_parse_rate": (len(sub) / total) if total else None,
        "parse_status_counts": df["confidence_parse_status"].fillna("absent").value_counts().to_dict()
        if "confidence_parse_status" in df
        else {},
    }
    if not len(sub):
        return out
    p = sub["final_confidence"].tolist()
    y = sub["correct"].astype(int).tolist()
    out["mean_confidence"] = float(np.mean(p))
    out["accuracy"] = float(np.mean(y))
    out["overconfidence_gap"] = out["mean_confidence"] - out["accuracy"]
    out["brier"] = brier_score(p, y)
    out["nll"] = nll(p, y)
    out["ece_equal_width"] = expected_calibration_error(p, y, n_bins)
    out["ece_equal_frequency_exploratory"] = expected_calibration_error(p, y, n_bins, equal_frequency=True)
    out["auroc"] = auroc(p, y)
    out["auprc"] = auprc(p, y)
    out["reliability"] = calibration_bins(p, y, n_bins)
    out["reliability_equal_frequency_exploratory"] = calibration_bins(p, y, n_bins, equal_frequency=True)
    out["selective_accuracy"] = selective_accuracy_curve(p, y)
    out["accuracy_at_threshold"] = pd.DataFrame(
        [
            {
                "threshold": t,
                "n_at_or_above": int(np.sum(np.asarray(p) >= t)),
                "accuracy_at_or_above": float(np.mean([yy for pp, yy in zip(p, y, strict=True) if pp >= t]))
                if np.any(np.asarray(p) >= t)
                else None,
            }
            for t in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
        ]
    )
    return out


def prompt_perturbation(instrumented: pd.DataFrame, standard: pd.DataFrame, *, replicates: int, seed: int) -> dict:
    """Condition A vs instrumented trajectory 0 on the same instances."""
    a = standard[standard["trajectory_index"] == 0].copy()
    b = instrumented[instrumented["trajectory_index"] == 0].copy()
    key = ["task_name", "task_instance_id"]
    merged = a.merge(b, on=key, suffixes=("_std", "_inst"))
    out: dict[str, Any] = {"n_paired_instances": len(merged)}
    if not len(merged):
        return out

    out["reward_difference"] = paired_bootstrap_difference(
        merged["reward_inst"].fillna(0.0).tolist(),
        merged["reward_std"].fillna(0.0).tolist(),
        replicates=replicates,
        seed=seed,
    )
    out["standard_reward"] = bootstrap_mean(
        merged["reward_std"].fillna(0.0).tolist(), replicates=replicates, seed=seed
    ).to_dict()
    out["instrumented_t0_reward"] = bootstrap_mean(
        merged["reward_inst"].fillna(0.0).tolist(), replicates=replicates, seed=seed
    ).to_dict()

    same = merged["answer_canonical_std"].fillna("__NA__") == merged["answer_canonical_inst"].fillna("__NA__")
    out["answer_change_rate"] = float(1 - same.mean())

    for field, label in (
        ("total_output_tokens", "output_tokens"),
        ("tool_call_count", "tool_calls"),
        ("wall_time_seconds", "wall_time"),
        ("llm_call_count", "llm_calls"),
    ):
        cs, ci = f"{field}_std", f"{field}_inst"
        if cs in merged and ci in merged:
            out[f"{label}_change"] = paired_bootstrap_difference(
                pd.to_numeric(merged[ci], errors="coerce").tolist(),
                pd.to_numeric(merged[cs], errors="coerce").tolist(),
                replicates=replicates,
                seed=seed,
            )

    if "confidence_parse_status_inst" in merged:
        out["confidence_parse_success_rate"] = float(
            merged["confidence_parse_status_inst"].isin(["ok", "multiple_blocks"]).mean()
        )
    out["completion_rate_standard"] = float(merged["completed_std"].fillna(False).astype(bool).mean())
    out["completion_rate_instrumented"] = float(merged["completed_inst"].fillna(False).astype(bool).mean())
    return out


def learned_selector_cv(
    instrumented: pd.DataFrame,
    *,
    features: tuple[str, ...] = (
        "final_confidence",
        "agreement_fraction",
        "log_total_output_tokens",
        "llm_call_count",
        "tool_call_count",
        "failed_tool_call_count",
    ),
    seed: int = 0,
) -> dict:
    """EXPLORATORY: small L2 logistic regression, grouped CV by task instance.

    Deliberately tiny and regularized: a 50-instance pilot cannot support more.
    All trajectories of one instance stay in the same fold.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    cols = [f for f in features if f in instrumented.columns]
    sub = instrumented[cols + ["task_name", "task_instance_id", "correct", "run_id"]].copy()
    sub = sub.dropna(subset=["correct"])
    if not len(sub) or sub["correct"].nunique() < 2 or not cols:
        return {"status": "insufficient_data", "features_used": cols}

    # Median-impute missing signals and record which were imputed.
    imputed = {c: int(sub[c].isna().sum()) for c in cols}
    for c in cols:
        sub[c] = pd.to_numeric(sub[c], errors="coerce")
        sub[c] = sub[c].fillna(sub[c].median())

    groups = sub["task_name"] + "::" + sub["task_instance_id"].astype(str)
    n_groups = groups.nunique()
    n_splits = min(5, n_groups)
    if n_splits < 2:
        return {"status": "insufficient_groups", "features_used": cols}

    X = sub[cols].to_numpy(dtype=float)
    y = sub["correct"].astype(int).to_numpy()
    oof = np.full(len(y), np.nan)
    for tr, te in GroupKFold(n_splits=n_splits).split(X, y, groups):
        if len(np.unique(y[tr])) < 2:
            continue
        model = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000, random_state=seed))
        model.fit(X[tr], y[tr])
        oof[te] = model.predict_proba(X[te])[:, 1]

    mask = ~np.isnan(oof)
    return {
        "status": "ok",
        "exploratory": True,
        "features_used": cols,
        "n_imputed_per_feature": imputed,
        "n_trajectories": int(mask.sum()),
        "n_groups": int(n_groups),
        "n_splits": n_splits,
        "oof_auroc": auroc(oof[mask].tolist(), y[mask].tolist()),
        "oof_auprc": auprc(oof[mask].tolist(), y[mask].tolist()),
        "oof_scores": oof.tolist(),
        "run_ids": sub["run_id"].tolist(),
    }
