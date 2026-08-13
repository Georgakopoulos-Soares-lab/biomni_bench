#!/usr/bin/env python3
"""Build the frozen Solver-B capability-gate manifest from ALREADY-CONSUMED instances.

`reports/scope_study_preflight.md` SS5. CPU only.

**This script must never touch a never-used instance.** The gate exists to test
whether a candidate Solver B can operate the Biomni scaffold at all; spending a
fresh scope-study question on that would consume the very pool the scope study
needs. Two structural guards enforce it, and both abort the build:

* every selected instance must appear in the Phase-2B manifest (i.e. it already
  carries four frozen Solver-A trajectories under the same scaffold and config,
  which is what makes the capability comparison matched);
* the selected set is asserted disjoint from the never-used pool reported by
  `scripts/scope_pool_audit.py`.

**Selection is label-free.** Instances are ordered by the project's existing
deterministic keyed-hash permutation (`benchmark._rng_order`) under a new seed,
and the first ``--per-task`` are taken. Nothing about Solver A's reward, failure
class, agreement, or difficulty enters the ordering -- selecting historical cases
by whether Biomni got them right would make the gate's accuracy diagnostic
uninterpretable before it was ever run.

Ground truth is written to a separate file, exactly as every other manifest in
this project, and is read only by ``OfficialEvaluator`` after inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from biomni_uncertainty.benchmark import ManifestEntry, _rng_order, prompt_hash  # noqa: E402

# The eight task families with a non-empty never-used pool. `crispr_delivery`
# and `rare_disease_diagnosis` are excluded because the audit shows 0 remaining
# -- not because of anything about their content.
ELIGIBLE_TASKS = (
    "gwas_causal_gene_gwas_catalog",
    "gwas_causal_gene_opentargets",
    "gwas_causal_gene_pharmaprojects",
    "gwas_variant_prioritization",
    "lab_bench_dbqa",
    "lab_bench_seqqa",
    "patient_gene_detection",
    "screen_gene_retrieval",
)

GATE_SEED = 20260812


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--phase2b-manifest", default=str(ROOT / "manifests" / "phase2b.jsonl"))
    ap.add_argument("--pool-audit", default=str(ROOT / "reports" / "tables" / "scope_study" / "pool_audit.json"))
    ap.add_argument("--per-task", type=int, default=3)
    ap.add_argument("--seed", type=int, default=GATE_SEED)
    ap.add_argument("--out", default=str(ROOT / "manifests" / "scope_gate.jsonl"))
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet)

    consumed: dict[str, set[int]] = {}
    for line in Path(args.phase2b_manifest).read_text().splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        consumed.setdefault(o["task_name"], set()).add(int(o["task_instance_id"]))

    never_used = json.loads(Path(args.pool_audit).read_text())["never_used_ids"]

    entries: list[ManifestEntry] = []
    ground_truth: list[dict] = []
    per_task: dict[str, list[int]] = {}

    for task in ELIGIBLE_TASKS:
        pool = sorted(consumed.get(task, set()))
        if len(pool) < args.per_task:
            raise SystemExit(f"{task}: only {len(pool)} consumed instances, need {args.per_task}")
        chosen = _rng_order(task, args.seed, pool)[: args.per_task]
        per_task[task] = sorted(chosen)
        for tid in sorted(chosen):
            row = df[(df.task_name == task) & (df.task_instance_id == tid)]
            if len(row) != 1:
                raise SystemExit(f"{task}/{tid}: expected exactly 1 benchmark row, got {len(row)}")
            r = row.iloc[0]
            entries.append(
                ManifestEntry(
                    global_instance_id=int(r["instance_id"]),
                    task_instance_id=int(r["task_instance_id"]),
                    task_name=str(r["task_name"]),
                    split=str(r["split"]),
                    prompt=str(r["prompt"]),
                    prompt_hash=prompt_hash(str(r["prompt"])),
                )
            )
            ground_truth.append(
                {
                    "global_instance_id": int(r["instance_id"]),
                    "task_instance_id": int(r["task_instance_id"]),
                    "task_name": str(r["task_name"]),
                    "answer": str(r["answer"]),
                }
            )

    # --- guards, both fatal ------------------------------------------------
    for e in entries:
        if e.task_instance_id not in consumed.get(e.task_name, set()):
            raise SystemExit(f"GUARD: {e.task_name}/{e.task_instance_id} is not a Phase-2B consumed instance")
        if e.task_instance_id in set(never_used.get(e.task_name, [])):
            raise SystemExit(f"GUARD: {e.task_name}/{e.task_instance_id} is in the NEVER-USED scope-study pool")

    out = Path(args.out)
    out.write_text("".join(json.dumps(e.to_dict(), sort_keys=True) + "\n" for e in entries))
    gt = out.with_suffix("").with_suffix("")
    gt = out.parent / (out.stem + ".groundtruth.jsonl")
    gt.write_text("".join(json.dumps(g, sort_keys=True) + "\n" for g in ground_truth))

    manifest_hash = hashlib.sha256(out.read_bytes()).hexdigest()
    report = {
        "purpose": "Solver-B capability gate; already-consumed instances only",
        "n_entries": len(entries),
        "per_task": per_task,
        "per_task_count": {k: len(v) for k, v in per_task.items()},
        "selection_rule": "benchmark._rng_order(task, seed, phase2b_consumed_ids)[:per_task]",
        "seed": args.seed,
        "manifest_hash": manifest_hash,
        "source_pool": "manifests/phase2b.jsonl (already consumed, K=4 Solver-A trajectories exist)",
        "never_used_instances_consumed": 0,
    }
    (out.parent / (out.stem + ".report.json")).write_text(json.dumps(report, indent=2, sort_keys=True))

    print(f"wrote {out} ({len(entries)} instances), {gt}, and the report")
    print(f"manifest hash: {manifest_hash}")
    for t in ELIGIBLE_TASKS:
        print(f"  {t:34s} {per_task[t]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
