"""Deterministic aggregation of per-run files into analysis tables.

File-per-run records are collected and evaluated here (never during the run, so
ground truth stays out of the execution process), then written as Parquet + CSV.
No concurrent database is used: a single SQLite file on a shared network
filesystem is unsafe for the parallel dispatcher.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from biomni_uncertainty.config import Config
from biomni_uncertainty.evaluation import OfficialEvaluator, binarize
from biomni_uncertainty.features import add_behavioral_features, compute_consistency
from biomni_uncertainty.sampling import COMPLETE_MARKER, FAILED_MARKER, RunSpec

FLAT_TRAJECTORY_STATS = (
    "llm_call_count",
    "total_input_tokens",
    "total_output_tokens",
    "total_tokens",
    "token_usage_available",
    "model_time_seconds",
    "tool_time_seconds",
    "code_execution_count",
    "tool_call_count",
    "unique_tool_count",
    "failed_tool_call_count",
    "failed_tool_call_fraction",
    "repeated_tool_call_count",
    "repeated_tool_call_fraction",
    "retry_count",
    "parse_error_count",
    "exception_count",
    "retrieval_count",
    "generated_chars",
    "message_count",
    "ai_message_count",
    "observation_count",
    "execute_block_count",
    "solution_block_count",
    "parse_error_message_count",
    "visible_plan_step_count",
    "plan_revision_count",
)

IDENTITY_COLUMNS = (
    "experiment_id",
    "run_id",
    "condition",
    "task_name",
    "global_instance_id",
    "task_instance_id",
    "trajectory_index",
    "split",
)

CONFIG_COLUMNS = (
    "requested_seed",
    "seed_supported",
    "model",
    "model_revision",
    "endpoint",
    "temperature",
    "max_tokens",
    "confidence_mode",
    "timeout_seconds",
    "prompt_hash",
)

OUTPUT_COLUMNS = (
    "final_response_raw_chars",
    "solution_block_status",
    "final_answer_parsed",
    "answer_canonical",
    "answer_parse_status",
    "answer_cluster_key",
    "final_confidence",
    "final_confidence_0_100",
    "confidence_parse_status",
    "completed",
    "failure_class",
    "wall_time_seconds",
    "started_at",
    "ended_at",
)


def collect_run_records(specs: list[RunSpec]) -> pd.DataFrame:
    """Load every run directory into a flat trajectory-level frame.

    Runs that never started, or whose metadata is unreadable, appear as rows with
    ``run_present=False`` so missingness is a visible finding, not a silent gap.
    """
    rows: list[dict[str, Any]] = []
    for s in sorted(specs, key=lambda x: (x.task_name, x.task_instance_id, x.condition, x.trajectory_index)):
        d = Path(s.run_dir)
        base: dict[str, Any] = {
            "experiment_id": s.experiment_id,
            "run_id": s.run_id,
            "condition": s.condition,
            "task_name": s.task_name,
            "global_instance_id": s.global_instance_id,
            "task_instance_id": s.task_instance_id,
            "trajectory_index": s.trajectory_index,
            "split": s.split,
            "run_dir": str(d),
            "run_present": False,
            "marker": None,
            "completed": False,
            "failure_class": "missing_run",
        }
        if (d / COMPLETE_MARKER).exists():
            base["marker"] = "COMPLETE"
        elif (d / FAILED_MARKER).exists():
            base["marker"] = "FAILED"

        meta_path = d / "metadata.json"
        if not meta_path.exists():
            # A run killed mid-flight (dispatcher wall clock, node loss) never
            # gets to write metadata.json, but the runner's FAILED marker records
            # why. Trusting it keeps those runs classified by their real failure
            # instead of `missing_run`, which would claim the directory does not
            # exist. Phase 1 mislabelled 2 runaway-generation timeouts this way;
            # see reports/context_overflow_forensics.md section 7.
            failed_path = d / FAILED_MARKER
            if failed_path.exists():
                try:
                    marker = json.loads(failed_path.read_text())
                except (OSError, json.JSONDecodeError):
                    marker = {}
                if isinstance(marker, dict) and marker.get("failure_class"):
                    base["run_present"] = True
                    base["failure_class"] = marker["failure_class"]
                    base["wall_time_seconds"] = marker.get("wall_time_seconds")
                    base["error"] = marker.get("note")
                    base["metadata_missing"] = True
                    base["n_events"] = _count_events(d / "events.jsonl")
            rows.append(base)
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            base["failure_class"] = "unknown_failure"
            base["error"] = f"unreadable metadata.json: {exc!r}"
            rows.append(base)
            continue

        row = dict(base)
        row["run_present"] = True
        row["failure_class"] = meta.get("failure_class")
        for c in IDENTITY_COLUMNS + CONFIG_COLUMNS + OUTPUT_COLUMNS:
            if c in meta:
                row[c] = meta[c]
        row["error"] = meta.get("error")
        stats = meta.get("trajectory_stats") or {}
        for c in FLAT_TRAJECTORY_STATS:
            row[c] = stats.get(c)
        row["finish_reasons"] = json.dumps(stats.get("finish_reasons") or [])
        row["n_events"] = _count_events(d / "events.jsonl")
        rows.append(row)
    return pd.DataFrame(rows)


def _count_events(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return None


def attach_rewards(df: pd.DataFrame, evaluator: OfficialEvaluator, threshold: float) -> pd.DataFrame:
    """Score every trajectory with the official evaluator."""
    out = df.copy()
    rewards, stricts, statuses, errors = [], [], [], []
    for r in out.to_dict("records"):
        res = evaluator.evaluate(
            r["task_name"],
            int(r["task_instance_id"]),
            r.get("answer_canonical"),
            r.get("final_answer_parsed"),
        )
        rewards.append(res.reward)
        stricts.append(res.strict_reward)
        statuses.append(res.status)
        errors.append(res.error)
    out["reward"] = rewards
    out["strict_reward"] = stricts
    out["evaluation_status"] = statuses
    out["evaluation_error"] = errors
    out["correct"] = [binarize(v, threshold) for v in rewards]
    return out


def build_tables(
    specs: list[RunSpec],
    cfg: Config,
    evaluator: OfficialEvaluator,
) -> dict[str, pd.DataFrame]:
    """Produce the full set of analysis tables.

    Returns keys: ``trajectories``, ``instrumented``, ``instances``,
    ``standard``, ``availability``.
    """
    traj = collect_run_records(specs)
    traj = attach_rewards(traj, evaluator, cfg.analysis.binary_reward_threshold)

    instrumented = traj[traj["condition"] == "instrumented"].copy()
    standard = traj[traj["condition"] == "standard"].copy()

    if len(instrumented):
        instances, traj_consistency = compute_consistency(instrumented)
        instrumented = instrumented.merge(traj_consistency, on="run_id", how="left")
        instrumented = add_behavioral_features(instrumented)
        # instance-level roll-up of correctness (used by oracle / selector analysis)
        agg = (
            instrumented.groupby(["task_name", "task_instance_id"])
            .agg(
                any_correct=("correct", lambda s: int(any(v == 1 for v in s))),
                n_correct=("correct", lambda s: int(sum(1 for v in s if v == 1))),
                mean_reward=("reward", "mean"),
                n_completed=("completed", lambda s: int(sum(bool(v) for v in s))),
            )
            .reset_index()
        )
        instances = instances.merge(agg, on=["task_name", "task_instance_id"], how="left")
    else:
        instances = pd.DataFrame()

    if len(standard):
        standard = add_behavioral_features(standard)

    from biomni_uncertainty.features import availability_report

    availability = availability_report(instrumented if len(instrumented) else traj)

    return {
        "trajectories": traj,
        "instrumented": instrumented,
        "instances": instances,
        "standard": standard,
        "availability": availability,
    }


def _jsonify(df: pd.DataFrame) -> pd.DataFrame:
    """Serialize dict/list-valued columns so Parquet and CSV both round-trip."""
    out = df.copy()
    for c in out.columns:
        if out[c].map(lambda v: isinstance(v, (dict, list, tuple))).any():
            out[c] = out[c].map(lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list, tuple)) else v)
    return out


def write_tables(tables: dict[str, pd.DataFrame], out_dir: str | Path) -> dict[str, str]:
    """Write each table as Parquet + CSV. Returns the written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name, df in tables.items():
        if df is None or not len(df):
            continue
        safe = _jsonify(df)
        pq = out_dir / f"{name}.parquet"
        csv = out_dir / f"{name}.csv"
        safe.to_parquet(pq, index=False)
        safe.to_csv(csv, index=False)
        written[name] = str(pq)
        written[f"{name}_csv"] = str(csv)
    return written


def status_summary(df: pd.DataFrame) -> dict:
    """Counts used by the ``status`` CLI command and the end-of-job summary."""
    total = len(df)
    present = int(df["run_present"].sum()) if "run_present" in df else 0
    completed = int(df["completed"].fillna(False).astype(bool).sum()) if "completed" in df else 0
    by_failure = (
        df[df["completed"].fillna(False).astype(bool) == False]["failure_class"]  # noqa: E712
        .fillna("none")
        .value_counts()
        .to_dict()
        if "failure_class" in df
        else {}
    )
    out = {
        "total_planned_runs": total,
        "runs_present": present,
        "runs_completed": completed,
        "runs_missing": total - present,
        "failure_class_counts": by_failure,
    }
    if "condition" in df:
        out["by_condition"] = df.groupby("condition").size().to_dict()
    if "task_name" in df:
        out["by_task"] = df.groupby("task_name").size().to_dict()
    if "confidence_parse_status" in df:
        out["confidence_parse_status"] = df["confidence_parse_status"].fillna("absent").value_counts().to_dict()
    if "answer_parse_status" in df:
        out["answer_parse_status"] = df["answer_parse_status"].fillna("absent").value_counts().to_dict()
    return out
