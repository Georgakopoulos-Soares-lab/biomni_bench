#!/usr/bin/env python3
"""Scope study primary #1 -- reliability detection, verifier-free.

`reports/scope_study_preregistration.md` SS5.1. Computed entirely from
`<output_root>/scope_main_{a,b}/results/tables/{instances,instrumented}.csv`,
which `cli aggregate` already produced against `manifests/scope_main.groundtruth.jsonl`.

Every quantity here reuses the project's own established machinery rather than
a new implementation:

* `selectors.candidates_from_frame` / `select_plurality` / `select_oracle` --
  the same functions behind every Pass@1 / plurality / Oracle@K number this
  project has ever reported;
* `analysis.signal_auroc_table` -- the same instance-clustered-bootstrap AUROC
  used for Phase 1's `agreement_fraction` result (AUROC 0.874).

No new statistical method is introduced for this half of the study.

Usage
-----
    python scripts/scope_main_detection_analysis.py --arm a --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))

from biomni_uncertainty.analysis import signal_auroc_table  # noqa: E402
from biomni_uncertainty.selectors import candidates_from_frame, select_oracle, select_plurality  # noqa: E402

BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260813


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", required=True, choices=["a", "b"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(f"/scratch/11034/atzanakak/biomni_unc_runs/scope_main_{args.arm}/results/tables")
    instrumented = pd.read_csv(root / "instrumented.csv")

    per_instance = []
    for (task, tid), g in instrumented.groupby(["task_name", "task_instance_id"], sort=True):
        cands = candidates_from_frame(g)
        first = next((c for c in cands if c.trajectory_index == 0), None)
        plur = select_plurality(cands)
        orac = select_oracle(cands)
        per_instance.append(
            {
                "task_name": task,
                "task_instance_id": int(tid),
                "pass_at_1_reward": first.reward if first else None,
                "plurality_reward": plur.reward,
                "plurality_answer": plur.canonical_answer,
                "plurality_tie_broken": plur.tie_broken,
                "oracle_reward": orac.reward,
                "oracle_tie_broken": orac.tie_broken,
                "n_usable": sum(1 for c in cands if c.canonical_answer is not None),
            }
        )
    pi = pd.DataFrame(per_instance)
    n = len(pi)
    if n != 120:
        raise SystemExit(f"expected 120 instances, got {n}")

    def _mean(col: str) -> float:
        return float(pi[col].fillna(0.0).mean())

    pass1 = _mean("pass_at_1_reward")
    plurality = _mean("plurality_reward")
    oracle = _mean("oracle_reward")
    headroom = oracle - plurality

    auroc_table = signal_auroc_table(
        instrumented.assign(correct=instrumented["reward"].fillna(0.0).ge(0.5).astype(int)),
        fields=("agreement_fraction",),
        replicates=BOOTSTRAP_REPLICATES,
        seed=BOOTSTRAP_SEED,
    )
    agreement_row = auroc_table[auroc_table.signal == "agreement_fraction"].iloc[0].to_dict()

    detection_established = agreement_row.get("auroc_ci_lo") is not None and agreement_row["auroc_ci_lo"] > 0.5

    report = {
        "arm": args.arm,
        "n_instances": n,
        "pass_at_1": round(pass1, 4),
        "plurality": round(plurality, 4),
        "oracle_at_4": round(oracle, 4),
        "headroom": round(headroom, 4),
        "agreement_fraction_auroc": {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in agreement_row.items()
            if k not in ("signal", "available")
        },
        "detection_established": bool(detection_established),
        "detection_rule": "agreement_fraction AUROC 95% CI lower bound > 0.5",
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED, "unit": "instance"},
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pi.to_csv(out / f"detection_per_instance_{args.arm}.csv", index=False)
    (out / f"detection_report_{args.arm}.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nwrote {out}/detection_report_{args.arm}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
