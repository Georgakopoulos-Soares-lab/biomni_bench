"""Agent-agnostic Reliability Suite v1 evaluation core.

Adapters own execution, answer canonicalization, and the *official* scorer.
This module only consumes their recorded trajectory rows; it never invents a
benchmark-specific judge or inspects ground truth.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Protocol

import numpy as np
import pandas as pd

from biomni_uncertainty.calibration import weighted_brier, weighted_ece
from biomni_uncertainty.features import cluster_key_for, consensus


class ReliabilityAdapter(Protocol):
    """Minimal contract implemented once per agent/benchmark pair."""
    def run_agent(self, task: dict[str, Any], seed_or_run_index: int) -> dict[str, Any]: ...
    def canonicalize(self, task: dict[str, Any], final_answer: str | None) -> str | None: ...
    def score(self, task: dict[str, Any], final_answer: str | None) -> dict[str, Any]: ...


def _auc(score: np.ndarray, label: np.ndarray) -> float | None:
    """AUROC with average ranks; returns None for a one-class sample."""
    valid = ~(np.isnan(score) | np.isnan(label))
    score, label = score[valid], label[valid]
    n_pos = int(label.sum())
    n_neg = len(label) - n_pos
    if not n_pos or not n_neg:
        return None
    ranks = pd.Series(score).rank(method="average").to_numpy()
    return float((ranks[label.astype(bool)].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _auprc(score: np.ndarray, label: np.ndarray) -> float | None:
    """Average precision using deterministic descending-score ordering."""
    valid = ~(np.isnan(score) | np.isnan(label))
    score, label = score[valid], label[valid].astype(int)
    if not len(label) or not label.sum():
        return None
    # Group tied scores: precision/recall only change after the whole tie.
    order = np.argsort(-score, kind="stable")
    y, s = label[order], score[order]
    tp = np.cumsum(y)
    ends = np.r_[np.flatnonzero(s[:-1] != s[1:]), len(s) - 1]
    precision = tp[ends] / (ends + 1)
    recall = tp[ends] / tp[-1]
    return float(np.sum((recall - np.r_[0.0, recall[:-1]]) * precision))


def _ci(values: list[float], rng: np.random.Generator, n_bootstrap: int) -> dict[str, float | None]:
    if not values:
        return {"estimate": None, "ci95_low": None, "ci95_high": None, "n": 0}
    a = np.asarray(values, dtype=float)
    boots = np.array([a[rng.integers(0, len(a), len(a))].mean() for _ in range(n_bootstrap)])
    return {"estimate": float(a.mean()), "ci95_low": float(np.quantile(boots, .025)),
            "ci95_high": float(np.quantile(boots, .975)), "n": len(a)}


def _risk_coverage(confidence: np.ndarray, correct: np.ndarray) -> dict[str, Any] | None:
    valid = ~(np.isnan(confidence) | np.isnan(correct))
    if not valid.any():
        return None
    c, y = confidence[valid], correct[valid]
    order = np.argsort(-c, kind="stable")
    rows = []
    for coverage in np.linspace(.1, 1, 10):
        n = max(1, int(np.ceil(coverage * len(order))))
        rows.append({"coverage": float(n / len(order)), "selective_accuracy": float(y[order[:n]].mean()), "risk": float(1-y[order[:n]].mean())})
    return {"curve": rows, "aurc": float(np.mean([r["risk"] for r in rows]))}


def evaluate_reliability(records: list[dict[str, Any]] | pd.DataFrame, *, k: int = 4,
                         n_bootstrap: int = 2000, bootstrap_seed: int = 20260825) -> dict[str, Any]:
    """Evaluate v1 metrics from one row per requested trajectory.

    Required columns: ``task_id``, ``run_index``, ``answer_cluster_key``,
    ``official_reward``.  ``completed``, ``failure_reason`` and ``confidence``
    are optional.  Rows whose official scorer failed (reward is null) are
    retained in failure accounting but excluded from correctness denominators.
    """
    df = pd.DataFrame(records).copy()
    rename = {"task_instance_id": "task_id", "trajectory_index": "run_index", "reward": "official_reward",
              "final_confidence": "confidence"}
    df = df.rename(columns={a: b for a, b in rename.items() if a in df and b not in df})
    required = {"task_id", "run_index", "answer_cluster_key", "official_reward"}
    missing = required - set(df)
    if missing:
        raise ValueError(f"missing reliability columns: {sorted(missing)}")
    if "completed" not in df:
        df["completed"] = df["official_reward"].notna()
    if "failure_reason" not in df:
        df["failure_reason"] = None
    if "confidence" not in df:
        df["confidence"] = np.nan
    # A trajectory an adapter marks incomplete (execution/artifact-contract/scorer
    # failure) never counts as an evaluable outcome, even if its aborted or
    # truncated artifact happened to still yield a defined reward -- that reward
    # describes an answer the agent never actually settled on, not a real one.
    evaluable = df["official_reward"].notna() & df["completed"].astype(bool)
    df["correct"] = pd.to_numeric(df["official_reward"], errors="coerce").ge(1.0).where(evaluable)
    df["key"] = [cluster_key_for(r) for r in df.to_dict("records")]
    per_instance, first, plurality, oracle, selection_failure, all_wrong = [], [], [], [], [], []
    plurality_legacy, selection_failure_legacy = [], []
    taxonomy = Counter()
    for task_id, g in df.groupby("task_id", sort=True):
        g = g.sort_values("run_index")
        keys, order = g.key.tolist(), g.run_index.astype(int).tolist()
        # Legacy/all-runs consensus: every requested trajectory votes, including
        # execution/artifact-contract/scorer failures. This is the pre-existing
        # behaviour, kept under an explicit name for compatibility with anything
        # that already consumes it (e.g. historical Biomni tables re-run through
        # this evaluator) -- never the primary signal going forward.
        con_legacy = consensus(keys, order)
        winner_legacy_correct = g[g.key == con_legacy.plurality_key].iloc[0].correct
        # Primary consensus: only completed, evaluable trajectories vote. A
        # trajectory that never finished (execution/artifact-contract/scorer
        # failure) has no real answer to contribute and must never win, or even
        # contest, the plurality -- it stays visible only in failure accounting.
        gc = g[g.completed.astype(bool)]
        con = consensus(gc.key.tolist(), gc.run_index.astype(int).tolist()) if len(gc) else None
        winner_correct = gc[gc.key == con.plurality_key].iloc[0].correct if con is not None else np.nan
        valid = g[g.correct.notna()]
        correct = valid.correct.astype(int).tolist()
        any_correct = bool(any(correct))
        all_wrong_i = bool(correct) and not any_correct
        # Scorer outages are neither stable failures nor unstable reasoning.
        # Keep them in failure accounting, but do not manufacture a taxonomy
        # label when this instance has no evaluable trajectory. "Agreement"
        # for this label means completed trajectories agreeing with each
        # other -- an execution failure sitting next to one real trajectory
        # is not instability, there was never a second real answer to disagree.
        completed_keys = gc.key.tolist()
        if not correct:
            state = None
        elif len(set(completed_keys)) == 1 and all(correct):
            state = "stable_correct"
        elif len(set(completed_keys)) == 1 and not any(correct):
            state = "stable_wrong"
        elif any_correct:
            state = "unstable_recoverable"
        else:
            state = "unstable_unrecoverable"
        if state is not None:
            taxonomy[state] += 1
        first.append(float(g.iloc[0].correct) if pd.notna(g.iloc[0].correct) else np.nan)
        plurality.append(float(winner_correct) if pd.notna(winner_correct) else np.nan)
        plurality_legacy.append(float(winner_legacy_correct) if pd.notna(winner_legacy_correct) else np.nan)
        oracle.append(float(any_correct) if correct else np.nan)
        selection_failure.append(float(any_correct and winner_correct == 0) if pd.notna(winner_correct) else np.nan)
        selection_failure_legacy.append(
            float(any_correct and winner_legacy_correct == 0) if pd.notna(winner_legacy_correct) else np.nan)
        all_wrong.append(float(all_wrong_i) if correct else np.nan)
        per_instance.append({"task_id": task_id, "n_requested": len(g), "k_expected": k, "n_completed_runs": len(gc),
            "plurality_fraction": np.nan if con is None else con.plurality_fraction,
            "plurality_key": None if con is None else con.plurality_key,
            "plurality_tie": None if con is None else con.is_tie,
            "plurality_correct": None if pd.isna(winner_correct) else int(winner_correct),
            "plurality_fraction_legacy_all_runs": con_legacy.plurality_fraction,
            "plurality_key_legacy_all_runs": con_legacy.plurality_key,
            "plurality_tie_legacy_all_runs": con_legacy.is_tie,
            "plurality_correct_legacy_all_runs": None if pd.isna(winner_legacy_correct) else int(winner_legacy_correct),
            "oracle_at_k": None if not correct else int(any_correct), "state": state,
            "n_evaluable_runs": len(correct), "n_correct_runs": int(sum(correct))})
    def valid(xs: list[float]) -> list[float]:
        return [x for x in xs if not np.isnan(x)]
    rng = np.random.default_rng(bootstrap_seed)
    metrics = {"pass_at_1": _ci(valid(first), rng, n_bootstrap), "plurality_accuracy": _ci(valid(plurality), rng, n_bootstrap),
               "plurality_accuracy_legacy_all_runs": _ci(valid(plurality_legacy), rng, n_bootstrap),
               "oracle_at_k": _ci(valid(oracle), rng, n_bootstrap),
               "agreement_plurality_fraction": _ci(valid([x["plurality_fraction"] for x in per_instance]), rng, n_bootstrap),
               "agreement_plurality_fraction_legacy_all_runs": _ci([x["plurality_fraction_legacy_all_runs"] for x in per_instance], rng, n_bootstrap),
               "selection_failure_rate": _ci(valid(selection_failure), rng, n_bootstrap),
               "selection_failure_rate_legacy_all_runs": _ci(valid(selection_failure_legacy), rng, n_bootstrap),
               "all_wrong_rate": _ci(valid(all_wrong), rng, n_bootstrap)}
    inst = pd.DataFrame(per_instance)
    metrics["agreement_to_correctness_auroc"] = _auc(inst.plurality_fraction.to_numpy(), inst.plurality_correct.to_numpy(float))
    metrics["agreement_to_correctness_auprc"] = _auprc(inst.plurality_fraction.to_numpy(), inst.plurality_correct.to_numpy(float))
    metrics["agreement_risk_coverage"] = _risk_coverage(inst.plurality_fraction.to_numpy(), inst.plurality_correct.to_numpy(float))
    conf, corr = pd.to_numeric(df.confidence, errors="coerce").to_numpy(float), df.correct.astype(float).to_numpy()
    metrics["verbal_confidence_auroc"] = _auc(conf, corr)
    ok = ~(np.isnan(conf) | np.isnan(corr))
    metrics["calibration"] = None if not ok.any() else {"brier": weighted_brier(conf, corr, np.ones(len(conf))), "ece_10": weighted_ece(conf, corr, np.ones(len(conf)), n_bins=10), "n": int(ok.sum())}
    metrics["risk_coverage"] = _risk_coverage(conf, corr)
    failures = df[~df.completed.astype(bool)]
    failure_reason = failures.failure_reason.fillna("unspecified")
    # Accept either an adapter-level class or the legacy Biomni failure_reason.
    failure_class = failures.get("failure_class", failure_reason).fillna("unspecified")
    infrastructure_classes = ("execution_failure", "tool_failure", "context_failure", "timeout", "agent_control_failure", "other_infrastructure_failure")
    class_counts = failure_class.value_counts().to_dict()
    return {"schema_version": "reliability-suite-v1.0", "protocol": {"k": k, "n_bootstrap": n_bootstrap, "bootstrap_seed": bootstrap_seed},
            "metrics": metrics, "failure_accounting": {"execution_failure_rate": float(len(failures) / len(df)) if len(df) else None,
            "n_requested_runs": len(df), "n_evaluator_failures": int(df.official_reward.isna().sum()),
            "by_failure_reason": failure_reason.value_counts().to_dict(), "by_failure_class": class_counts,
            "infrastructure_categories": {name: int(class_counts.get(name, 0)) for name in infrastructure_classes},
            "failure_layers": _failure_layers(df)},
            "failure_taxonomy": dict(taxonomy), "selection_failure_count": int(sum(valid(selection_failure))), "instances": per_instance}


def _failure_layers(df: pd.DataFrame) -> dict[str, int] | None:
    """Bucket each requested run into the first layer of the pipeline it failed at.

    Layers, in order: ``agent_execution_success`` -> ``artifact_contract_valid``
    -> ``native_scorer_success`` -> scored (correct/incorrect). An adapter
    reports these as optional per-row booleans; a missing score never
    conflates with a score of zero, and it never gets a layer it did not
    actually report. Returns ``None`` when an adapter reports none of these
    columns, rather than guessing a layer from ``completed``/``failure_class``.
    """
    layer_cols = ("agent_execution_success", "artifact_contract_valid", "native_scorer_success")
    if not any(c in df.columns for c in layer_cols):
        return None
    counts = Counter()
    for row in df.to_dict("records"):
        if row.get("agent_execution_success") is False:
            counts["execution_failure"] += 1
        elif row.get("artifact_contract_valid") is False:
            counts["artifact_contract_failure"] += 1
        elif row.get("native_scorer_success") is False:
            counts["native_scorer_failure"] += 1
        elif pd.isna(row.get("official_reward")):
            counts["unscored_other"] += 1
        else:
            counts["scored"] += 1
    return dict(counts)
