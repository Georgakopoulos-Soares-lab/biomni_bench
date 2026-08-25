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
    df["correct"] = pd.to_numeric(df["official_reward"], errors="coerce").ge(1.0).where(df["official_reward"].notna())
    df["key"] = [cluster_key_for(r) for r in df.to_dict("records")]
    per_instance, first, plurality, oracle, selection_failure, all_wrong = [], [], [], [], [], []
    taxonomy = Counter()
    for task_id, g in df.groupby("task_id", sort=True):
        g = g.sort_values("run_index")
        keys, order = g.key.tolist(), g.run_index.astype(int).tolist()
        con = consensus(keys, order)
        valid = g[g.correct.notna()]
        correct = valid.correct.astype(int).tolist()
        winner = g[g.key == con.plurality_key].iloc[0]
        winner_correct = winner.correct
        any_correct = bool(any(correct))
        all_wrong_i = bool(correct) and not any_correct
        if len(set(keys)) == 1 and correct and all(correct):
            state = "stable_correct"
        elif len(set(keys)) == 1 and correct and not any(correct):
            state = "stable_wrong"
        elif any_correct:
            state = "unstable_recoverable"
        else:
            state = "unstable_unrecoverable"
        taxonomy[state] += 1
        first.append(float(g.iloc[0].correct) if pd.notna(g.iloc[0].correct) else np.nan)
        plurality.append(float(winner_correct) if pd.notna(winner_correct) else np.nan)
        oracle.append(float(any_correct) if correct else np.nan)
        selection_failure.append(float(any_correct and winner_correct == 0) if pd.notna(winner_correct) else np.nan)
        all_wrong.append(float(all_wrong_i) if correct else np.nan)
        per_instance.append({"task_id": task_id, "n_requested": len(g), "k_expected": k,
            "plurality_fraction": con.plurality_fraction, "plurality_key": con.plurality_key,
            "plurality_tie": con.is_tie, "plurality_correct": None if pd.isna(winner_correct) else int(winner_correct),
            "oracle_at_k": None if not correct else int(any_correct), "state": state})
    def valid(xs: list[float]) -> list[float]:
        return [x for x in xs if not np.isnan(x)]
    rng = np.random.default_rng(bootstrap_seed)
    metrics = {"pass_at_1": _ci(valid(first), rng, n_bootstrap), "plurality_accuracy": _ci(valid(plurality), rng, n_bootstrap),
               "oracle_at_k": _ci(valid(oracle), rng, n_bootstrap), "agreement_plurality_fraction": _ci([x["plurality_fraction"] for x in per_instance], rng, n_bootstrap),
               "selection_failure_rate": _ci(valid(selection_failure), rng, n_bootstrap), "all_wrong_rate": _ci(valid(all_wrong), rng, n_bootstrap)}
    inst = pd.DataFrame(per_instance)
    metrics["agreement_to_correctness_auroc"] = _auc(inst.plurality_fraction.to_numpy(), inst.plurality_correct.to_numpy(float))
    conf, corr = pd.to_numeric(df.confidence, errors="coerce").to_numpy(float), df.correct.astype(float).to_numpy()
    metrics["verbal_confidence_auroc"] = _auc(conf, corr)
    ok = ~(np.isnan(conf) | np.isnan(corr))
    metrics["calibration"] = None if not ok.any() else {"brier": weighted_brier(conf, corr, np.ones(len(conf))), "ece_10": weighted_ece(conf, corr, np.ones(len(conf)), n_bins=10), "n": int(ok.sum())}
    metrics["risk_coverage"] = _risk_coverage(conf, corr)
    failures = df[~df.completed.astype(bool)]
    return {"schema_version": "reliability-suite-v1.0", "protocol": {"k": k, "n_bootstrap": n_bootstrap, "bootstrap_seed": bootstrap_seed},
            "metrics": metrics, "failure_accounting": {"execution_failure_rate": float(len(failures) / len(df)) if len(df) else None,
            "n_requested_runs": len(df), "n_evaluator_failures": int(df.official_reward.isna().sum()),
            "by_failure_reason": failures.failure_reason.fillna("unspecified").value_counts().to_dict()},
            "failure_taxonomy": dict(taxonomy), "instances": per_instance}
