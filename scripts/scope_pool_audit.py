#!/usr/bin/env python3
"""Audit which BiomniEval1 instances have ever been consumed, from artifacts only.

Written for the scope-and-boundary study (`reports/scope_study_preflight.md` SS2).
CPU only, read-only, no model calls, no GPU.

**Prose is not evidence here.** The prior record (D-22,
`reports/phase2_protocol.md` SS3.1) states that Phase 1 took 50 and Phase 2B took
150, leaving 233 reserved. This script does not trust that. It reconstructs
consumption from three independent artifact sources and reports whatever they
say, including any disagreement with the prose:

1. the benchmark parquet itself -- the denominator, per task;
2. every ``manifests/*.jsonl`` -- declared consumption;
3. every ``<output_root>/*/runs/<task>/i####/`` directory -- consumption that
   actually happened on disk, including diagnostic and smoke runs that were
   never written to ``manifests/``.

Source 3 is the one that matters: a run directory exists if and only if a
trajectory was generated against that instance, whether or not any manifest
records it. An instance is "never used" only if it appears in none of the three.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

# The two task families the prior record says were exhausted by D-22. Verified,
# not assumed -- the audit reports their remaining counts like any other task.
CLAIMED_EXHAUSTED = ("crispr_delivery", "rare_disease_diagnosis")

INSTANCE_DIR = re.compile(r"^i(\d+)$")


def benchmark_totals(parquet: str) -> dict[str, set[int]]:
    df = pd.read_parquet(parquet)
    out: dict[str, set[int]] = defaultdict(set)
    for task, tid in zip(df["task_name"], df["task_instance_id"], strict=True):
        out[str(task)].add(int(tid))
    return dict(out)


def manifest_consumption(manifests_dir: Path) -> dict[str, set[tuple[str, int]]]:
    """Every (task, task_instance_id) named by any manifest, ground truth excluded."""
    out: dict[str, set[tuple[str, int]]] = {}
    for mf in sorted(manifests_dir.glob("*.jsonl")):
        if mf.name.endswith(".groundtruth.jsonl"):
            continue
        pairs: set[tuple[str, int]] = set()
        for line in mf.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            task, tid = obj.get("task_name"), obj.get("task_instance_id")
            if task is not None and tid is not None:
                pairs.add((str(task), int(tid)))
        if pairs:
            out[f"manifest:{mf.name}"] = pairs
    return out


def rundir_consumption(output_root: Path) -> dict[str, set[tuple[str, int]]]:
    """Every instance with a run directory on disk, per experiment tree."""
    out: dict[str, set[tuple[str, int]]] = {}
    if not output_root.is_dir():
        return out
    for exp in sorted(output_root.iterdir()):
        runs = exp / "runs"
        if not runs.is_dir():
            continue
        pairs: set[tuple[str, int]] = set()
        for task_dir in runs.iterdir():
            if not task_dir.is_dir():
                continue
            for inst_dir in task_dir.iterdir():
                m = INSTANCE_DIR.match(inst_dir.name)
                if m:
                    pairs.add((task_dir.name, int(m.group(1))))
        if pairs:
            out[f"rundir:{exp.name}"] = pairs
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", required=True, help="local BiomniEval1 parquet")
    ap.add_argument("--manifests", default="manifests")
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--out", required=True, help="directory for pool_audit.{json,csv}")
    args = ap.parse_args()

    bench = benchmark_totals(args.parquet)
    sources: dict[str, set[tuple[str, int]]] = {}
    sources.update(manifest_consumption(Path(args.manifests)))
    sources.update(rundir_consumption(Path(args.output_root)))

    all_consumed: set[tuple[str, int]] = set()
    for pairs in sources.values():
        all_consumed |= pairs

    orphans = sorted(p for p in all_consumed if p[1] not in bench.get(p[0], set()))
    if orphans:
        raise SystemExit(f"consumed instances absent from the benchmark: {orphans}")

    # The two confirmatory/prospective sets the scope study must not overlap.
    confirmatory = sources["manifest:phase1.jsonl"] | sources["manifest:phase2b.jsonl"]
    beyond = sorted(all_consumed - confirmatory)

    rows = []
    for task in sorted(bench):
        used = {i for (t, i) in all_consumed if t == task}
        conf = {i for (t, i) in confirmatory if t == task}
        rows.append(
            {
                "task_name": task,
                "total_in_benchmark": len(bench[task]),
                "consumed_phase1_or_phase2b": len(conf),
                "consumed_other": len(used - conf),
                "consumed_total": len(used),
                "never_used": len(bench[task] - used),
                "eligible_for_scope_study": (len(bench[task] - used) > 0),
            }
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "pool_audit.csv", index=False)

    payload = {
        "benchmark_total": int(df.total_in_benchmark.sum()),
        "consumed_total": int(df.consumed_total.sum()),
        "never_used_total": int(df.never_used.sum()),
        "per_task": rows,
        "sources": {k: len(v) for k, v in sorted(sources.items())},
        "consumed_beyond_phase1_phase2b": [{"task_name": t, "task_instance_id": i} for t, i in beyond],
        "claimed_exhausted_verified": {
            t: {"never_used": len(bench[t] - {i for (tt, i) in all_consumed if tt == t})} for t in CLAIMED_EXHAUSTED
        },
        "never_used_ids": {t: sorted(bench[t] - {i for (tt, i) in all_consumed if tt == t}) for t in sorted(bench)},
    }
    (out_dir / "pool_audit.json").write_text(json.dumps(payload, indent=2, sort_keys=True))

    print(df.to_string(index=False))
    print(
        f"\nTOTAL  benchmark={payload['benchmark_total']}  consumed={payload['consumed_total']}  "
        f"never_used={payload['never_used_total']}"
    )
    print(f"consumed beyond phase1 U phase2b: {len(beyond)}")
    for t, i in beyond:
        print(f"  {t}/{i}")
    print(f"\nwrote {out_dir}/pool_audit.json and pool_audit.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
