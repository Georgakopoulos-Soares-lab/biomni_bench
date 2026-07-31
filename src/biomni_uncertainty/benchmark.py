"""BiomniEval1 loading and deterministic balanced manifest construction.

Two files are written, deliberately:

* ``<name>.jsonl``            - agent-visible. Contains prompts, no answers.
* ``<name>.groundtruth.jsonl`` - answers, consumed only by the evaluator wrapper.

Nothing in the sampling path may consult model output or correctness.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = ("instance_id", "task_instance_id", "prompt", "task_name", "split", "answer")


@dataclass(frozen=True)
class ManifestEntry:
    """One selected benchmark instance (agent-visible fields only)."""

    global_instance_id: int
    task_instance_id: int
    task_name: str
    split: str
    prompt: str
    prompt_hash: str

    def to_dict(self) -> dict:
        return asdict(self)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def load_eval1(parquet_uri: str, local_parquet: str | None = None) -> pd.DataFrame:
    """Load the official BiomniEval1 dataframe.

    ``local_parquet`` is a cache of the exact same file; it is preferred when
    present so that runs are reproducible on nodes without internet access.
    """
    src = local_parquet if local_parquet and os.path.exists(local_parquet) else parquet_uri
    df = pd.read_parquet(src)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"BiomniEval1 parquet at {src} is missing columns: {missing}")
    df.attrs["source"] = src
    return df


def dataset_fingerprint(df: pd.DataFrame) -> str:
    """Stable hash of the benchmark content actually used."""
    keyed = df[list(REQUIRED_COLUMNS)].sort_values(["task_name", "task_instance_id"])
    payload = keyed.to_json(orient="records")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rng_order(task_name: str, manifest_seed: int, ids: list[int]) -> list[int]:
    """Deterministic, seed-dependent permutation of ``ids`` for one task.

    Uses a hash of (seed, task, id) rather than numpy's global RNG so the order
    for a task is independent of how many other tasks were processed first.
    """

    def key(i: int) -> str:
        return hashlib.sha256(f"{manifest_seed}|{task_name}|{i}".encode()).hexdigest()

    return sorted(ids, key=key)


def build_manifest(
    df: pd.DataFrame,
    *,
    per_task_target: int,
    target_total_instances: int,
    manifest_seed: int,
    preferred_split: str | None = None,
    exclude_tasks: tuple[str, ...] | list[str] = (),
    max_prompt_chars: int | None = None,
) -> tuple[list[ManifestEntry], dict]:
    """Deterministically sample a task-balanced pilot subset.

    Procedure (recorded verbatim in the returned report):

    1. Restrict to ``preferred_split`` if that split exists; otherwise use all
       rows and record that no held-out split was available.
    2. Drop excluded tasks and prompts over ``max_prompt_chars``.
    3. For each task in alphabetical order, order its instances by a keyed hash
       of (manifest_seed, task_name, task_instance_id) and take the first
       ``per_task_target``. Tasks with fewer suitable instances contribute all
       of them.
    4. If the total falls short of ``target_total_instances``, redistribute the
       remainder over tasks that still have unused instances, one at a time in
       round-robin over alphabetical task order, continuing from each task's
       existing hash order.
    """
    report: dict[str, Any] = {"exclusions": [], "manifest_seed": manifest_seed}

    work = df.copy()
    splits = sorted(work["split"].dropna().unique().tolist())
    report["available_splits"] = splits
    if preferred_split and preferred_split in splits:
        work = work[work["split"] == preferred_split]
        report["split_used"] = preferred_split
        report["held_out_split_available"] = len(splits) > 1
    else:
        report["split_used"] = "ALL"
        report["held_out_split_available"] = False
        if preferred_split:
            report["exclusions"].append(
                {
                    "reason": f"preferred_split {preferred_split!r} not present; using all splits",
                    "n": 0,
                }
            )

    for task in exclude_tasks:
        n = int((work["task_name"] == task).sum())
        if n:
            report["exclusions"].append({"reason": f"task {task!r} excluded by config", "n": n})
        work = work[work["task_name"] != task]

    if max_prompt_chars is not None:
        too_long = work["prompt"].str.len() > max_prompt_chars
        if int(too_long.sum()):
            report["exclusions"].append(
                {"reason": f"prompt longer than {max_prompt_chars} chars", "n": int(too_long.sum())}
            )
        work = work[~too_long]

    tasks = sorted(work["task_name"].unique().tolist())
    ordered: dict[str, list[int]] = {}
    for t in tasks:
        ids = sorted(work[work["task_name"] == t]["task_instance_id"].astype(int).tolist())
        ordered[t] = _rng_order(t, manifest_seed, ids)

    taken: dict[str, list[int]] = {}
    for t in tasks:
        taken[t] = ordered[t][:per_task_target]

    total = sum(len(v) for v in taken.values())
    report["initial_total"] = total
    report["short_tasks"] = {t: len(v) for t, v in taken.items() if len(v) < per_task_target}

    # Round-robin redistribution of the shortfall.
    redistributed: dict[str, int] = {}
    guard = 0
    while total < target_total_instances and guard < 10_000:
        progressed = False
        for t in tasks:
            if total >= target_total_instances:
                break
            pool = ordered[t]
            if len(taken[t]) < len(pool):
                taken[t].append(pool[len(taken[t])])
                redistributed[t] = redistributed.get(t, 0) + 1
                total += 1
                progressed = True
        guard += 1
        if not progressed:
            break
    report["redistributed"] = redistributed
    report["final_total"] = total
    if total < target_total_instances:
        report["exclusions"].append(
            {
                "reason": "benchmark exhausted before reaching target_total_instances",
                "n": target_total_instances - total,
            }
        )

    entries: list[ManifestEntry] = []
    for t in tasks:
        for tid in sorted(taken[t]):
            row = work[(work["task_name"] == t) & (work["task_instance_id"] == tid)].iloc[0]
            entries.append(
                ManifestEntry(
                    global_instance_id=int(row["instance_id"]),
                    task_instance_id=int(tid),
                    task_name=t,
                    split=str(row["split"]),
                    prompt=str(row["prompt"]),
                    prompt_hash=prompt_hash(str(row["prompt"])),
                )
            )

    entries.sort(key=lambda e: (e.task_name, e.task_instance_id))
    report["counts_by_task"] = {t: sum(1 for e in entries if e.task_name == t) for t in tasks}
    report["counts_by_split"] = {s: sum(1 for e in entries if e.split == s) for s in sorted({e.split for e in entries})}
    lengths = sorted(len(e.prompt) for e in entries)
    if lengths:
        report["prompt_length_chars"] = {
            "min": lengths[0],
            "p25": lengths[len(lengths) // 4],
            "median": lengths[len(lengths) // 2],
            "p75": lengths[(3 * len(lengths)) // 4],
            "max": lengths[-1],
            "mean": round(sum(lengths) / len(lengths), 1),
        }
    report["dataset_fingerprint"] = dataset_fingerprint(df)
    return entries, report


def manifest_hash(entries: list[ManifestEntry]) -> str:
    """Stable hash of the complete manifest (order-independent)."""
    payload = sorted(json.dumps(e.to_dict(), sort_keys=True, separators=(",", ":")) for e in entries)
    return hashlib.sha256("\n".join(payload).encode("utf-8")).hexdigest()


def write_manifest(
    entries: list[ManifestEntry],
    df: pd.DataFrame,
    output: str | Path,
) -> tuple[Path, Path]:
    """Write the agent-visible manifest and the separate ground-truth file."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    gt_path = output.with_suffix("").with_suffix(".groundtruth.jsonl")

    lookup = {(r["task_name"], int(r["task_instance_id"])): r["answer"] for _, r in df.iterrows()}

    tmp = output.with_suffix(output.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, output)

    tmp_gt = gt_path.with_suffix(gt_path.suffix + ".tmp")
    with open(tmp_gt, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(
                json.dumps(
                    {
                        "task_name": e.task_name,
                        "task_instance_id": e.task_instance_id,
                        "global_instance_id": e.global_instance_id,
                        "answer": lookup[(e.task_name, e.task_instance_id)],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    os.replace(tmp_gt, gt_path)
    return output, gt_path


def read_manifest(path: str | Path) -> list[ManifestEntry]:
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(ManifestEntry(**json.loads(line)))
    return entries
