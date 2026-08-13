#!/usr/bin/env python3
"""Build the frozen matched-scope-study manifest from NEVER-USED instances.

`reports/scope_study_preregistration.md` SS2. CPU only.

This is the one script in the scope study that spends fresh benchmark instances,
so every guard it carries is fatal rather than advisory:

* every selected instance must be in the never-used set reported by
  `scripts/scope_pool_audit.py`;
* the selected set must be disjoint from **all** 213 consumed instances -- not
  merely from the two confirmatory manifests, because 13 instances were consumed
  by runs that never wrote a manifest (D-44 SS2);
* exactly ``--per-task`` instances from each of the 8 eligible families;
* the audit itself is re-run semantics: the script reads the committed audit
  artifact, and refuses if any selected id is absent from it.

Selection reuses the project's deterministic keyed-hash permutation
(`benchmark._rng_order`) under a new seed. Nothing about difficulty, Solver-A
history, or any model output enters the ordering -- there is no model output for
these instances, by construction.

**Both solvers receive this identical manifest.** The matched design is the whole
point: every comparison in the study is paired on the instance.
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

MAIN_SEED = 20260813


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--pool-audit", default=str(ROOT / "reports" / "tables" / "scope_study" / "pool_audit.json"))
    ap.add_argument("--per-task", type=int, default=15)
    ap.add_argument("--seed", type=int, default=MAIN_SEED)
    ap.add_argument("--out", default=str(ROOT / "manifests" / "scope_main.jsonl"))
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet)
    audit = json.loads(Path(args.pool_audit).read_text())
    never_used = {t: set(v) for t, v in audit["never_used_ids"].items()}

    # Reconstruct the full consumed set as the complement of never-used, per task.
    all_ids: dict[str, set[int]] = {}
    for task, tid in zip(df["task_name"], df["task_instance_id"], strict=True):
        all_ids.setdefault(str(task), set()).add(int(tid))
    consumed = {t: all_ids[t] - never_used.get(t, set()) for t in all_ids}

    entries: list[ManifestEntry] = []
    ground_truth: list[dict] = []
    per_task: dict[str, list[int]] = {}

    for task in ELIGIBLE_TASKS:
        pool = sorted(never_used.get(task, set()))
        if len(pool) < args.per_task:
            raise SystemExit(f"{task}: only {len(pool)} never-used instances, need {args.per_task}")
        chosen = sorted(_rng_order(task, args.seed, pool)[: args.per_task])
        per_task[task] = chosen
        for tid in chosen:
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

    # --- fatal guards ------------------------------------------------------
    for e in entries:
        if e.task_instance_id not in never_used.get(e.task_name, set()):
            raise SystemExit(f"GUARD: {e.task_name}/{e.task_instance_id} is NOT in the never-used pool")
        if e.task_instance_id in consumed.get(e.task_name, set()):
            raise SystemExit(f"GUARD: {e.task_name}/{e.task_instance_id} was already consumed")
    if len(entries) != args.per_task * len(ELIGIBLE_TASKS):
        raise SystemExit(f"GUARD: expected {args.per_task * len(ELIGIBLE_TASKS)} entries, built {len(entries)}")
    # cross-check against every manifest on disk, including the gate's
    for mf in sorted((ROOT / "manifests").glob("*.jsonl")):
        if mf.name.endswith(".groundtruth.jsonl") or "_runs" in mf.name:
            continue
        seen = set()
        for line in mf.read_text().splitlines():
            if line.strip():
                o = json.loads(line)
                seen.add((o["task_name"], o["task_instance_id"]))
        clash = {(e.task_name, e.task_instance_id) for e in entries} & seen
        if clash:
            raise SystemExit(f"GUARD: overlap with {mf.name}: {sorted(clash)[:5]}")

    out = Path(args.out)
    out.write_text("".join(json.dumps(e.to_dict(), sort_keys=True) + "\n" for e in entries))
    gt = out.parent / (out.stem + ".groundtruth.jsonl")
    gt.write_text("".join(json.dumps(g, sort_keys=True) + "\n" for g in ground_truth))

    manifest_hash = hashlib.sha256(out.read_bytes()).hexdigest()
    remaining = {t: len(never_used.get(t, set())) - args.per_task for t in ELIGIBLE_TASKS}
    report = {
        "purpose": "matched scope study; both solvers receive this identical manifest",
        "n_entries": len(entries),
        "per_task": per_task,
        "per_task_count": {k: len(v) for k, v in per_task.items()},
        "selection_rule": "benchmark._rng_order(task, seed, never_used_ids)[:per_task]",
        "seed": args.seed,
        "manifest_hash": manifest_hash,
        "never_used_before": {t: len(never_used.get(t, set())) for t in ELIGIBLE_TASKS},
        "never_used_after": remaining,
        "never_used_remaining_total": sum(remaining.values()),
        "overlap_with_any_prior_manifest": 0,
    }
    (out.parent / (out.stem + ".report.json")).write_text(json.dumps(report, indent=2, sort_keys=True))

    print(f"wrote {out} ({len(entries)} instances), {gt}, and the report")
    print(f"manifest hash: {manifest_hash}")
    for t in ELIGIBLE_TASKS:
        print(f"  {t:34s} n={len(per_task[t]):2d}  pool {report['never_used_before'][t]} -> {remaining[t]} left")
    print(f"never-used remaining after this study: {report['never_used_remaining_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
