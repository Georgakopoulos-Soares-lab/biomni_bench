"""Import existing Biomni trajectory tables into Reliability Suite v1.

This adapter deliberately does not call Biomni or rescore an answer.  Its input
is the post-official-scorer trajectory table produced by ``aggregation.py``.
That makes importing historic runs a regression check rather than a rerun.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or (isinstance(value, str) and not value.strip())


def normalize_biomni_table(path: str | Path) -> list[dict[str, Any]]:
    """Return standard reliability rows from a Biomni ``instrumented.csv``."""
    frame = pd.read_csv(path)
    required = {"task_name", "task_instance_id", "trajectory_index", "answer_cluster_key", "reward"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"Biomni table missing columns: {sorted(missing)}")
    rows: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        task_id = f"{row['task_name']}:{int(row['task_instance_id'])}"
        completion = bool(row.get("completed", False))
        failure = row.get("failure_class")
        official = None if _missing(row.get("reward")) else float(row["reward"])
        rows.append({
            "schema_version": "reliability-suite-trajectory-v1.0",
            "run_id": row.get("run_id"), "agent": "biomni", "benchmark": "BiomniEval1",
            "task_id": task_id, "task_name": row["task_name"], "task_instance_id": int(row["task_instance_id"]),
            "run_index": int(row["trajectory_index"]), "trajectory_index": int(row["trajectory_index"]),
            "seed": row.get("requested_seed"), "model": row.get("model"), "model_revision": row.get("model_revision"),
            "serving_backend": row.get("endpoint"), "temperature": row.get("temperature"),
            "raw_final_answer": row.get("final_answer_parsed"), "canonical_final_answer": row.get("answer_canonical"),
            "answer_cluster_key": row.get("answer_cluster_key"), "official_reward": official,
            "official_pass": None if official is None else int(official >= 1.0), "completed": completion,
            "failure_reason": failure, "failure_class": failure,
            "llm_input_tokens": row.get("total_input_tokens"), "llm_output_tokens": row.get("total_output_tokens"),
            "tool_calls": row.get("tool_call_count"), "execution_errors": row.get("exception_count"),
            "termination_reason": row.get("finish_reasons"), "artifact_path": row.get("run_dir"),
            "verbal_confidence": row.get("final_confidence"), "confidence": row.get("final_confidence"),
            "start_time": row.get("started_at"), "end_time": row.get("ended_at"),
        })
    return rows
