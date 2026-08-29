#!/usr/bin/env python3
"""Combine the 12 per-task AutoBA K=4 pilot v1 campaigns into one 48-row
Reliability Suite v1 report.

`scripts/run_autoba_k4_reliability.py` is intentionally single-task, like
`run_genomas_k4_reliability.py`; this script only concatenates each task
campaign's already-written `records.jsonl` (never re-scores or re-runs
anything) and calls the unchanged `evaluate_reliability` once over the
combined table, per reports/autoba_k4_pilot_v1_preregistration.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biomni_uncertainty.reliability import evaluate_reliability  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--campaign-prefix",
        type=Path,
        required=True,
        help="Directory containing the 12 <NN>_<test_id>_k4 subdirectories.",
    )
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    records: list[dict] = []
    task_dirs = sorted(d for d in args.campaign_prefix.iterdir() if d.is_dir() and d.name[:2].isdigit())
    for task_dir in task_dirs:
        records_path = task_dir / "records.jsonl"
        if not records_path.is_file():
            print(f"WARNING: missing records.jsonl in {task_dir}", file=sys.stderr)
            continue
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))

    report = evaluate_reliability(records, k=4, n_bootstrap=2000, bootstrap_seed=20260825)
    report["campaign_prefix"] = str(args.campaign_prefix)
    report["n_task_dirs_found"] = len(task_dirs)
    report["n_records_total"] = len(records)
    report["preregistration"] = str(ROOT / "reports" / "autoba_k4_pilot_v1_preregistration.md")
    report["cost"] = {
        "input_tokens": sum(r.get("input_tokens") or 0 for r in records),
        "output_tokens": sum(r.get("output_tokens") or 0 for r in records),
        "runtime_seconds": sum(r.get("runtime_seconds") or 0 for r in records),
        "paid_api_cost_usd": 0.0,
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(records)} records from {len(task_dirs)} task dirs)")


if __name__ == "__main__":
    main()
