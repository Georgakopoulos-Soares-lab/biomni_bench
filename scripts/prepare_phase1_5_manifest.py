#!/usr/bin/env python
"""Build the phase1_5 run manifest: the 62 Phase-1 model_context_overflow
failures, remapped to run under the repaired (Arm 2) config.

Not a fresh sample. Each target run keeps its EXACT original task_name,
task_instance_id, condition and trajectory_index, and the identical prompt
(from phase1_runs.jsonl) - only the serving config changes (configs/phase1_5.yaml:
max_tokens 2048, the bounding guards R2/R4/R5, no input-token budget). This is
what makes "did the repair rescue this specific failure" a meaningful question.

Selection criterion: failure_class in {model_context_overflow, missing_run}, per
the pilot results table. Both are the same pathology - `missing_run` is the
`reports/context_overflow_forensics.md` SS7 correction: two runs killed on the
dispatcher wall clock after runaway generation, which never got a metadata.json
and were originally miscounted as "missing" rather than "failed".

Writes:
  manifests/phase1_5_runs.jsonl        - the 62 remapped RunSpecs
  manifests/phase1_5_original_map.json - repaired run_id -> original phase1 run_id

    python scripts/prepare_phase1_5_manifest.py \
        --phase1-trajectories <output_root>/phase1/results/tables/trajectories.parquet \
        --phase1-run-manifest manifests/phase1_runs.jsonl \
        --config configs/phase1_5.yaml \
        --output manifests/phase1_5_runs.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.sampling import RunSpec, make_run_id, run_dir_for, write_run_manifest  # noqa: E402

TARGET_FAILURE_CLASSES = ("model_context_overflow", "missing_run")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase1-trajectories", required=True, type=Path)
    ap.add_argument("--phase1-run-manifest", required=True, type=Path)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--map-output", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)

    df = pd.read_parquet(args.phase1_trajectories)
    targets = df[df["failure_class"].isin(TARGET_FAILURE_CLASSES)]
    if targets.empty:
        print("ERROR: no matching failed runs found - check --phase1-trajectories", file=sys.stderr)
        return 1

    original_specs = {
        json.loads(line)["run_id"]: json.loads(line)
        for line in args.phase1_run_manifest.read_text().splitlines()
        if line.strip()
    }

    repaired_specs: list[RunSpec] = []
    id_map: dict[str, str] = {}
    missing_from_manifest = []

    for _, row in targets.sort_values(["task_name", "task_instance_id", "condition", "trajectory_index"]).iterrows():
        orig_id = row["run_id"]
        if orig_id not in original_specs:
            missing_from_manifest.append(orig_id)
            continue
        orig = original_specs[orig_id]

        new_run_id = make_run_id(
            cfg.experiment_id, orig["task_name"], orig["task_instance_id"], orig["condition"], orig["trajectory_index"]
        )
        base = {
            "task_name": orig["task_name"],
            "task_instance_id": orig["task_instance_id"],
            "condition": orig["condition"],
            "trajectory_index": orig["trajectory_index"],
        }
        spec = RunSpec(
            experiment_id=cfg.experiment_id,
            run_id=new_run_id,
            condition=orig["condition"],
            task_name=orig["task_name"],
            global_instance_id=orig["global_instance_id"],
            task_instance_id=orig["task_instance_id"],
            trajectory_index=orig["trajectory_index"],
            prompt=orig["prompt"],
            prompt_hash=orig["prompt_hash"],
            split=orig["split"],
            requested_seed=orig["requested_seed"],
            confidence_mode=orig["confidence_mode"],
            model=cfg.model.identifier,
            model_revision=cfg.model.revision,
            temperature=cfg.model.temperature,
            max_tokens=cfg.model.max_tokens,
            timeout_seconds=cfg.execution.run_timeout_seconds,
            run_dir=str(run_dir_for(cfg, base)),
        )
        repaired_specs.append(spec)
        id_map[new_run_id] = orig_id

    print(f"targets in results table : {len(targets)}")
    print(f"resolved against phase1_runs.jsonl : {len(repaired_specs)}")
    if missing_from_manifest:
        print(f"WARNING: {len(missing_from_manifest)} target run_id(s) not found in phase1_run_manifest:")
        for rid in missing_from_manifest:
            print(f"  - {rid}")

    by_task: dict[str, int] = {}
    by_cond: dict[str, int] = {}
    for s in repaired_specs:
        by_task[s.task_name] = by_task.get(s.task_name, 0) + 1
        by_cond[s.condition] = by_cond.get(s.condition, 0) + 1
    print("by task:")
    for t, n in sorted(by_task.items()):
        print(f"  {t:<34} {n}")
    print("by condition:", by_cond)

    if args.dry_run:
        print("[dry-run] nothing written")
        return 0

    map_path = args.map_output or args.output.with_suffix("").with_suffix(".original_map.json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_run_manifest(repaired_specs, args.output)
    map_path.write_text(json.dumps(id_map, indent=2, sort_keys=True))
    print(f"\nwrote {args.output}")
    print(f"wrote {map_path}  (repaired run_id -> original phase1 run_id)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
