#!/usr/bin/env python
"""Build the frozen Phase-2B held-out manifest.

Selects prospective instances from BiomniEval1 under two hard constraints:

* **No Phase-1 instance may appear.** Every (task_name, task_instance_id) used
  by `manifests/phase1.jsonl` is removed before selection. This is the whole
  point of the prospective run and is asserted, not assumed.
* **Per-task quotas are explicit**, not the round-robin balancing Phase 1 used.
  Two tasks are pool-limited (`crispr_delivery` has 5 instances left in the
  entire benchmark) and one is deliberately over-sampled
  (`rare_disease_diagnosis`, the pre-declared high-risk stratum). Forcing equal
  cells would either be impossible or would throw away the stratum that matters
  most.

Selection *within* a task reuses Phase 1's deterministic keyed-hash ordering
(`benchmark._rng_order`) under a new seed, so the procedure is the same in kind
and equally auditable — only the quotas and the exclusion set are new.

Writes the agent-visible manifest, the separate ground-truth file, a build
report, and prints the manifest hash to be pasted into
`reports/phase2_protocol.md` before any inference runs.

    python scripts/prepare_phase2b_manifest.py --config configs/phase2b.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biomni_uncertainty.benchmark import (  # noqa: E402
    ManifestEntry,
    _rng_order,
    dataset_fingerprint,
    load_eval1,
    manifest_hash,
    prompt_hash,
    write_manifest,
)
from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.provenance import write_json_atomic  # noqa: E402

#: Explicit per-task quotas. Justified in reports/phase2_protocol.md §3.
#:
#: `crispr_delivery`        - only 5 instances remain in the whole benchmark;
#:                            take all of them or lose the task entirely.
#: `rare_disease_diagnosis` - take all 25 remaining. It is the documented
#:                            high-risk stratum where the controller spends the
#:                            most (mean K 3.73 offline), recovers the most
#:                            failures, and where Phase 1 could only report n=5.
#: everything else          - 15, three times Phase 1's per-task cell.
QUOTAS: dict[str, int] = {
    "crispr_delivery": 5,
    "gwas_causal_gene_gwas_catalog": 15,
    "gwas_causal_gene_opentargets": 15,
    "gwas_causal_gene_pharmaprojects": 15,
    "gwas_variant_prioritization": 15,
    "lab_bench_dbqa": 15,
    "lab_bench_seqqa": 15,
    "patient_gene_detection": 15,
    "rare_disease_diagnosis": 25,
    "screen_gene_retrieval": 15,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--phase1-manifest", type=Path, default=Path("manifests/phase1.jsonl"))
    ap.add_argument("--output", type=Path, default=Path("manifests/phase2b.jsonl"))
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args()

    cfg = load_config(args.config)
    df = load_eval1(cfg.benchmark.parquet_uri, cfg.benchmark.local_parquet)
    fingerprint = dataset_fingerprint(df)

    used = {
        (json.loads(line)["task_name"], int(json.loads(line)["task_instance_id"]))
        for line in open(args.phase1_manifest)
    }

    report: dict = {
        "purpose": "Phase-2B prospective held-out sample",
        "dataset_fingerprint": fingerprint,
        "manifest_seed": cfg.benchmark.manifest_seed,
        "phase1_manifest": str(args.phase1_manifest),
        "n_phase1_instances_excluded": len(used),
        "quotas": QUOTAS,
        "split_used": cfg.benchmark.preferred_split,
    }

    work = df[df["split"] == cfg.benchmark.preferred_split] if cfg.benchmark.preferred_split else df
    entries: list[ManifestEntry] = []
    pool_rows = []

    for task in sorted(QUOTAS):
        task_df = work[work["task_name"] == task]
        all_ids = sorted(task_df["task_instance_id"].astype(int).tolist())
        held_out = [i for i in all_ids if (task, i) not in used]
        quota = QUOTAS[task]
        chosen = sorted(_rng_order(task, cfg.benchmark.manifest_seed, held_out)[:quota])

        pool_rows.append(
            {
                "task_name": task,
                "n_in_benchmark": len(all_ids),
                "n_used_by_phase1": len(all_ids) - len(held_out),
                "n_held_out": len(held_out),
                "quota": quota,
                "n_selected": len(chosen),
                "pool_exhausted": len(chosen) == len(held_out),
                "n_reserved_for_future": len(held_out) - len(chosen),
            }
        )
        for tid in chosen:
            row = task_df[task_df["task_instance_id"] == tid].iloc[0]
            entries.append(
                ManifestEntry(
                    global_instance_id=int(row["instance_id"]),
                    task_instance_id=int(tid),
                    task_name=task,
                    split=str(row["split"]),
                    prompt=str(row["prompt"]),
                    prompt_hash=prompt_hash(str(row["prompt"])),
                )
            )

    entries.sort(key=lambda e: (e.task_name, e.task_instance_id))
    report["pool"] = pool_rows
    report["counts_by_task"] = {t: sum(1 for e in entries if e.task_name == t) for t in sorted(QUOTAS)}
    report["n_entries"] = len(entries)
    report["manifest_hash"] = manifest_hash(entries)
    lengths = sorted(len(e.prompt) for e in entries)
    report["prompt_length_chars"] = {
        "min": lengths[0],
        "median": lengths[len(lengths) // 2],
        "max": lengths[-1],
        "mean": round(sum(lengths) / len(lengths), 1),
    }

    # --- the assertions that make this a held-out sample --------------------
    selected = {(e.task_name, e.task_instance_id) for e in entries}
    overlap = selected & used
    if overlap:
        raise SystemExit(
            f"FATAL: {len(overlap)} Phase-1 instances leaked into the Phase-2B manifest: {sorted(overlap)[:5]}"
        )
    if len(selected) != len(entries):
        raise SystemExit("FATAL: duplicate instances in the Phase-2B manifest")
    report["overlap_with_phase1"] = 0

    print(f"{'task':34s} {'bench':>6s} {'ph1':>4s} {'held':>5s} {'quota':>6s} {'sel':>4s} {'reserve':>8s}")
    for r in pool_rows:
        print(
            f"{r['task_name']:34s} {r['n_in_benchmark']:6d} {r['n_used_by_phase1']:4d} "
            f"{r['n_held_out']:5d} {r['quota']:6d} {r['n_selected']:4d} {r['n_reserved_for_future']:8d}"
        )
    tot = {
        k: sum(r[k] for r in pool_rows)
        for k in ("n_in_benchmark", "n_used_by_phase1", "n_held_out", "n_selected", "n_reserved_for_future")
    }
    print(
        f"{'TOTAL':34s} {tot['n_in_benchmark']:6d} {tot['n_used_by_phase1']:4d} "
        f"{tot['n_held_out']:5d} {'':>6s} {tot['n_selected']:4d} {tot['n_reserved_for_future']:8d}"
    )
    print()
    print(f"dataset fingerprint : {fingerprint}")
    print(f"manifest hash       : {report['manifest_hash']}")
    print(f"overlap with Phase 1: {len(overlap)}  (must be 0)")
    print(f"trajectories at K=4 : {len(entries) * 4}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    mpath, gpath = write_manifest(entries, df, args.output)
    rpath = args.output.with_suffix(".report.json")
    write_json_atomic(rpath, report)
    print(f"\nwrote {mpath}\n      {gpath}\n      {rpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
