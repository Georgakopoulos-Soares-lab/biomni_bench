"""Build the RL harness training-task pool and guard it against the held-out set.

Pure stdlib, CPU-only, no GPU/model dependency -- unit-testable directly.
Reuses the exact frozen split from D-49/`scripts/rl_harness_split_audit.py`:
training pool = manifests/phase1.jsonl UNION manifests/phase2b.jsonl (200
instances); held-out eval = manifests/scope_main.jsonl (120 instances),
never touched here. Loading raises if any overlap is found -- this is a
guard against a future manifest edit silently breaking the split, not a
recomputation of D-49's own disjointness proof.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HeldOutOverlapError(RuntimeError):
    """Raised when a training task collides with the frozen held-out set."""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _key(row: dict[str, Any]) -> tuple[str, int]:
    return (row["task_name"], int(row["task_instance_id"]))


def load_training_tasks(
    repo_root: str | Path,
    train_manifest_names: tuple[str, ...] = ("phase1", "phase2b"),
    holdout_manifest_name: str = "scope_main",
) -> list[dict[str, Any]]:
    """Return the deduplicated training-pool task list, guarded against the held-out set.

    Args:
        repo_root: biomni-uncertainty repo root (containing `manifests/`).
        train_manifest_names: manifest basenames (without `.jsonl`) forming the training pool.
        holdout_manifest_name: manifest basename that must never overlap with the training pool.

    Returns:
        One dict per unique (task_name, task_instance_id), each carrying at least
        `task_name`, `task_instance_id`, `global_instance_id`, `prompt`, `prompt_hash`, `split`.

    Raises:
        HeldOutOverlapError: if any training task collides with the held-out manifest.
    """
    manifests_dir = Path(repo_root) / "manifests"

    train_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for name in train_manifest_names:
        for row in _read_jsonl(manifests_dir / f"{name}.jsonl"):
            train_rows[_key(row)] = row

    holdout_keys = {_key(row) for row in _read_jsonl(manifests_dir / f"{holdout_manifest_name}.jsonl")}

    overlap = set(train_rows) & holdout_keys
    if overlap:
        raise HeldOutOverlapError(
            f"{len(overlap)} training task(s) collide with held-out manifest "
            f"'{holdout_manifest_name}': {sorted(overlap)[:5]}..."
        )

    return list(train_rows.values())
