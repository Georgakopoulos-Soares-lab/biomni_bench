"""Self-consistency and behavioural features.

Two levels:

* **Trajectory level** - one row per run. Behavioural signals, plus each
  trajectory's agreement with its siblings.
* **Instance level**   - one row per task instance. Consensus structure over the
  K instrumented trajectories.

Nothing here may consult ground truth. Rewards are joined in afterwards, by the
analysis layer, so a feature can never accidentally leak a label.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# Behavioural columns standardized within task / ranked within instance.
BEHAVIORAL_FIELDS = (
    "total_output_tokens",
    "total_tokens",
    "llm_call_count",
    "tool_call_count",
    "unique_tool_count",
    "wall_time_seconds",
    "model_time_seconds",
    "tool_time_seconds",
    "failed_tool_call_count",
    "failed_tool_call_fraction",
    "retry_count",
    "exception_count",
    "repeated_tool_call_count",
    "repeated_tool_call_fraction",
    "code_execution_count",
    "visible_plan_step_count",
    "generated_chars",
)

UNPARSEABLE_PREFIX = "__UNPARSEABLE__"


def cluster_key_for(row: Any) -> str:
    """Clustering key for one trajectory.

    Trajectories with no parseable answer are each their OWN singleton cluster
    (keyed by run_id). Pooling them would manufacture a false consensus among
    unrelated failures.
    """
    key = row.get("answer_cluster_key") if isinstance(row, dict) else getattr(row, "answer_cluster_key", None)
    if key is None or (isinstance(key, float) and math.isnan(key)) or key == "":
        rid = row.get("run_id") if isinstance(row, dict) else getattr(row, "run_id", "?")
        return f"{UNPARSEABLE_PREFIX}{rid}"
    return str(key)


def normalized_entropy(counts: Iterable[int]) -> float:
    """Shannon entropy of the cluster distribution, normalized to [0,1].

    0 means unanimous, 1 means all K trajectories disagree.
    """
    counts = [c for c in counts if c > 0]
    n = sum(counts)
    k = len(counts)
    if n <= 1 or k <= 1:
        return 0.0
    h = -sum((c / n) * math.log(c / n) for c in counts)
    return float(h / math.log(n)) if n > 1 else 0.0


def pairwise_agreement(keys: list[str]) -> float | None:
    """Fraction of unordered trajectory pairs that share a cluster."""
    n = len(keys)
    if n < 2:
        return None
    agree = 0
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += 1
            agree += int(keys[i] == keys[j])
    return agree / total


@dataclass(frozen=True)
class ConsensusResult:
    plurality_key: str
    plurality_count: int
    plurality_fraction: float
    is_tie: bool
    tied_keys: tuple[str, ...]
    n_unique: int
    entropy: float
    pairwise_agreement: float | None


def consensus(keys: list[str], tiebreak_order: list[int]) -> ConsensusResult:
    """Compute the consensus structure for one instance.

    Tie-breaking is deterministic and ground-truth-free: among clusters of equal
    size the winner is the one containing the lowest ``tiebreak_order`` value
    (trajectory index). The tie is reported, never hidden.
    """
    counts = Counter(keys)
    if not counts:
        raise ValueError("consensus() requires at least one trajectory")
    top = max(counts.values())
    tied = sorted(k for k, c in counts.items() if c == top)
    first_pos = {}
    for k, order in zip(keys, tiebreak_order, strict=True):
        first_pos.setdefault(k, order)
        first_pos[k] = min(first_pos[k], order)
    winner = min(tied, key=lambda k: (first_pos[k], k))
    return ConsensusResult(
        plurality_key=winner,
        plurality_count=top,
        plurality_fraction=top / len(keys),
        is_tie=len(tied) > 1,
        tied_keys=tuple(tied),
        n_unique=len(counts),
        entropy=normalized_entropy(counts.values()),
        pairwise_agreement=pairwise_agreement(keys),
    )


def compute_consistency(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Self-consistency features over instrumented trajectories.

    Args:
        df: trajectory-level table, already filtered to one condition.

    Returns:
        ``(instance_level, trajectory_level_additions)``
    """
    inst_rows = []
    traj_rows = []
    for (task, tid), g in df.groupby(["task_name", "task_instance_id"], sort=True):
        g = g.sort_values("trajectory_index")
        keys = [cluster_key_for(r) for r in g.to_dict("records")]
        order = g["trajectory_index"].astype(int).tolist()
        res = consensus(keys, order)
        counts = Counter(keys)

        n_unparse = sum(1 for k in keys if k.startswith(UNPARSEABLE_PREFIX))
        inst_rows.append(
            {
                "task_name": task,
                "task_instance_id": int(tid),
                "k_trajectories": len(g),
                "n_unique_answers": res.n_unique,
                "plurality_key": res.plurality_key,
                "plurality_count": res.plurality_count,
                "plurality_fraction": res.plurality_fraction,
                "is_tie": res.is_tie,
                "n_tied_clusters": len(res.tied_keys),
                "answer_entropy": res.entropy,
                "pairwise_agreement": res.pairwise_agreement,
                "n_unparseable": n_unparse,
                "answer_frequencies": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            }
        )

        for row, key in zip(g.to_dict("records"), keys, strict=True):
            agree_count = counts[key] - 1  # siblings sharing this answer
            traj_rows.append(
                {
                    "run_id": row["run_id"],
                    "cluster_key": key,
                    "is_unparseable_cluster": key.startswith(UNPARSEABLE_PREFIX),
                    "agreement_count": agree_count,
                    "agreement_fraction": agree_count / (len(g) - 1) if len(g) > 1 else None,
                    "in_plurality_cluster": key == res.plurality_key,
                    "instance_plurality_fraction": res.plurality_fraction,
                    "instance_answer_entropy": res.entropy,
                    "instance_n_unique_answers": res.n_unique,
                    "instance_is_tie": res.is_tie,
                }
            )
    return pd.DataFrame(inst_rows), pd.DataFrame(traj_rows)


def add_behavioral_features(df: pd.DataFrame, fields: tuple[str, ...] = BEHAVIORAL_FIELDS) -> pd.DataFrame:
    """Add within-task standardized values and within-instance ranks.

    Raw values are kept. Standardization uses the task's own mean/sd over the
    trajectories present, and is emitted as NaN when the task has fewer than
    three usable values or zero variance - never fabricated.
    """
    out = df.copy()
    present = [f for f in fields if f in out.columns]
    for f in present:
        col = pd.to_numeric(out[f], errors="coerce")
        out[f] = col

        z = pd.Series(np.nan, index=out.index, dtype="float64")
        for _task, idx in out.groupby("task_name").groups.items():
            vals = col.loc[idx]
            usable = vals.dropna()
            if len(usable) >= 3 and usable.std(ddof=0) > 0:
                z.loc[idx] = (vals - usable.mean()) / usable.std(ddof=0)
        out[f"{f}__z_within_task"] = z

        rank = pd.Series(np.nan, index=out.index, dtype="float64")
        for _, idx in out.groupby(["task_name", "task_instance_id"]).groups.items():
            vals = col.loc[idx]
            if vals.notna().sum() >= 2:
                rank.loc[idx] = vals.rank(method="average", ascending=True)
        out[f"{f}__rank_within_instance"] = rank

    log_fields = ("total_output_tokens", "total_tokens", "generated_chars", "wall_time_seconds")
    for f in log_fields:
        if f in out.columns:
            out[f"log_{f}"] = np.log1p(pd.to_numeric(out[f], errors="coerce"))

    out["feature_availability"] = [{f: bool(pd.notna(out.iloc[i][f])) for f in present} for i in range(len(out))]
    return out


def availability_report(df: pd.DataFrame, fields: tuple[str, ...] = BEHAVIORAL_FIELDS) -> pd.DataFrame:
    """Per-feature availability, so unavailable signals are reported not imputed."""
    rows = []
    for f in fields:
        if f not in df.columns:
            rows.append({"feature": f, "present_column": False, "n_available": 0, "fraction_available": 0.0})
            continue
        col = pd.to_numeric(df[f], errors="coerce")
        rows.append(
            {
                "feature": f,
                "present_column": True,
                "n_available": int(col.notna().sum()),
                "fraction_available": float(col.notna().mean()) if len(col) else 0.0,
            }
        )
    return pd.DataFrame(rows)
