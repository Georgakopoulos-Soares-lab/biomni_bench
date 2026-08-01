#!/usr/bin/env python
"""Select the balanced repair-ablation instance set and write its manifests.

Design is fixed in ``reports/context_overflow_forensics.md`` section 9: four
strata of six instances each, so the ablation can show both that the repair
removes the degeneration *and* that it leaves previously-healthy trajectories
alone. Selection uses only Phase-1 failure structure and a deterministic hash -
never reward, never ground truth.

    python scripts/prepare_ablation.py \
        --runs-root <output_root>/phase1/runs \
        --manifest manifests/phase1.jsonl \
        --out-prefix manifests/ablation
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

# Overflow-prone families, from the measured per-task failure rates.
OVERFLOW_PRONE = ("rare_disease_diagnosis", "crispr_delivery", "patient_gene_detection")
# Short/easy families: low failure rate, short trajectories.
SHORT_EASY = ("lab_bench_dbqa", "screen_gene_retrieval")
# Low-overflow GWAS controls: 0% and 4% failure in the pilot.
GWAS_CONTROL = ("gwas_causal_gene_opentargets", "gwas_variant_prioritization")

STRATUM_SIZE = 6


def stable_key(seed: int, *parts: object) -> str:
    payload = "|".join(str(p) for p in parts)
    return hashlib.sha256(f"{seed}|{payload}".encode()).hexdigest()


def instance_failure_counts(runs_root: Path) -> dict[tuple[str, int], dict]:
    """Per (task, instance): how many of its Phase-1 runs failed, and how."""
    out: dict[tuple[str, int], dict] = defaultdict(lambda: {"n": 0, "failed": 0, "runaway": 0})
    for meta_dir in sorted(runs_root.glob("*/i*/*/t*")):
        task = meta_dir.parts[-4]
        inst = int(meta_dir.parts[-3].lstrip("i"))
        meta_path = meta_dir / "metadata.json"
        failed_path = meta_dir / "FAILED"
        completed = False
        if meta_path.exists():
            try:
                completed = bool(json.loads(meta_path.read_text()).get("completed"))
            except (OSError, json.JSONDecodeError):
                completed = False
        rec = out[(task, inst)]
        rec["n"] += 1
        if not completed:
            rec["failed"] += 1
        # A generation that stopped on `length` is the degeneration signature.
        ev = meta_dir / "events.jsonl"
        if ev.exists():
            with open(ev, encoding="utf-8") as fh:
                for line in fh:
                    if '"finish_reason": "length"' in line:
                        rec["runaway"] += 1
                        break
        if failed_path.exists():
            rec["has_failed_marker"] = True
    return dict(out)


def select(manifest: list[dict], counts: dict, seed: int) -> dict[str, list[dict]]:
    by_key = {(e["task_name"], e["task_instance_id"]): e for e in manifest}
    strata: dict[str, list[dict]] = {}

    def rank(entries, keyfn):
        return sorted(entries, key=lambda e: (keyfn(e), stable_key(seed, e["task_name"], e["task_instance_id"])))

    def stats(e):
        return counts.get((e["task_name"], e["task_instance_id"]), {"n": 0, "failed": 0, "runaway": 0})

    pool = list(by_key.values())

    # 1. Overflow-prone: the instances that actually degenerated most.
    prone = [e for e in pool if e["task_name"] in OVERFLOW_PRONE and stats(e)["failed"] > 0]
    strata["overflow_prone"] = rank(prone, lambda e: -stats(e)["failed"])[:STRATUM_SIZE]

    # 2. Controls from the *same* families that previously completed cleanly.
    chosen = {(e["task_name"], e["task_instance_id"]) for e in strata["overflow_prone"]}
    same_family = [
        e
        for e in pool
        if e["task_name"] in OVERFLOW_PRONE
        and (e["task_name"], e["task_instance_id"]) not in chosen
        and stats(e)["failed"] == 0
    ]
    if len(same_family) < STRATUM_SIZE:
        # Fall back to the least-failing remaining instances in those families.
        same_family = [
            e
            for e in pool
            if e["task_name"] in OVERFLOW_PRONE and (e["task_name"], e["task_instance_id"]) not in chosen
        ]
    strata["same_family_control"] = rank(same_family, lambda e: stats(e)["failed"])[:STRATUM_SIZE]

    # 3. Short/easy controls.
    strata["short_easy_control"] = rank(
        [e for e in pool if e["task_name"] in SHORT_EASY], lambda e: stats(e)["failed"]
    )[:STRATUM_SIZE]

    # 4. Low-overflow GWAS controls.
    strata["gwas_control"] = rank([e for e in pool if e["task_name"] in GWAS_CONTROL], lambda e: stats(e)["failed"])[
        :STRATUM_SIZE
    ]
    return strata


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-root", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--ground-truth", type=Path, default=None)
    ap.add_argument("--out-prefix", type=Path, default=Path("manifests/ablation"))
    ap.add_argument("--seed", type=int, default=20260801)
    args = ap.parse_args()

    manifest = [json.loads(line) for line in args.manifest.read_text().splitlines() if line.strip()]
    gt_path = args.ground_truth or args.manifest.with_suffix("").with_suffix(".groundtruth.jsonl")
    ground_truth = [json.loads(line) for line in gt_path.read_text().splitlines() if line.strip()]

    counts = instance_failure_counts(args.runs_root)
    strata = select(manifest, counts, args.seed)

    selected, seen, strata_report = [], set(), []
    print(f"{'stratum':<22}{'task':<34}{'inst':>6}{'failed':>8}{'runaway':>9}")
    print("-" * 79)
    for name, entries in strata.items():
        for e in entries:
            key = (e["task_name"], e["task_instance_id"])
            c = counts.get(key, {})
            print(
                f"{name:<22}{e['task_name']:<34}{e['task_instance_id']:>6}{c.get('failed', 0):>8}{c.get('runaway', 0):>9}"
            )
            if key not in seen:
                seen.add(key)
                selected.append(e)
                # The stratum is provenance, not a manifest field: ManifestEntry
                # has a fixed schema, and adding a key here would change the
                # manifest hash semantics for no benefit.
                strata_report.append(
                    {
                        "task_name": e["task_name"],
                        "task_instance_id": e["task_instance_id"],
                        "global_instance_id": e["global_instance_id"],
                        "stratum": name,
                        "phase1_failed_runs": c.get("failed", 0),
                        "phase1_runs_with_runaway": c.get("runaway", 0),
                    }
                )

    print("-" * 79)
    print(f"selected {len(selected)} unique instances across {len(strata)} strata")

    gid = {e["global_instance_id"] for e in selected}
    out_m = Path(f"{args.out_prefix}.jsonl")
    out_g = Path(f"{args.out_prefix}.groundtruth.jsonl")
    out_m.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in selected))
    out_g.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in ground_truth if e.get("global_instance_id") in gid)
    )
    out_s = Path(f"{args.out_prefix}.strata.json")
    out_s.write_text(json.dumps(strata_report, indent=2))
    digest = hashlib.sha256(out_m.read_bytes()).hexdigest()
    print(f"wrote {out_m} ({len(selected)} instances)")
    print(f"wrote {out_g}")
    print(f"wrote {out_s}")
    print(f"ablation manifest hash: {digest}")


if __name__ == "__main__":
    main()
