#!/usr/bin/env python
"""A.8 - matched-K oracle comparison. CPU only.

A.1 compared Arm 2's Oracle@3 (0.513, over its own three adjudication samples)
against the original pool's Oracle@**4** (0.6026). That is not like-for-like:
Phase 1 measured K=3 -> K=4 as worth 2.5 points, so part of the gap is simply
the extra sample.

This recomputes the pool's oracle at K=3, matched: for each instance, average
the oracle over every 3-subset of its usable trajectories, then average over
instances. The comparison then differs only in *what* the three samples were,
not how many there were.

WHAT TURNS ON IT: if Arm 2's oracle still falls below the pool's matched-K
oracle, then the best answer obtainable from Arm 2's own outputs is worse than
the best answer already sitting in the candidate set it was handed. An
adjudicator cannot do that - selecting from a set cannot produce something worse
than the set's best element. It means the arm was **re-solving the task rather
than adjudicating between the candidates**, which is a stronger and cleaner
basis for D-39 than the information-monotonicity argument alone.

    python scripts/stage_a8_matched_k.py --out reports/tables/stage_a
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

STEP2 = REPO / "reports" / "tables" / "track_c_step2"
PHASE2B = Path("/scratch/11034/atzanakak/biomni_unc_runs/phase2b/results/tables")
PHASE1 = Path("/scratch/11034/atzanakak/biomni_unc_runs/phase1_pooled/results/tables")

BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260811001


def oracle_at_k(rewards: list[float], k: int) -> float | None:
    """Expected oracle over a uniformly random k-subset, computed exactly by
    averaging over all subsets rather than sampling."""
    r = [float(x) for x in rewards]
    if len(r) < k:
        return None
    return float(np.mean([max(c) for c in combinations(r, k)]))


def cluster_ci(values: list[float], seed=BOOTSTRAP_SEED, reps=BOOTSTRAP_REPLICATES) -> dict:
    a = np.asarray([v for v in values if v is not None], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(reps, len(a)))
    m = a[idx].mean(axis=1)
    return {
        "point": float(a.mean()),
        "ci_lo": float(np.quantile(m, 0.025)),
        "ci_hi": float(np.quantile(m, 0.975)),
        "n": int(len(a)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cands = [json.loads(x) for x in (STEP2 / "candidates_slim.jsonl").read_text().splitlines() if x.strip()]
    keys = {(c["pool"], c["task_name"], int(c["task_instance_id"])) for c in cands}

    p2 = pd.read_csv(PHASE2B / "p2b_pooled_trajectories.csv").assign(pool="phase2b")
    p1 = pd.read_csv(PHASE1 / "trajectories.csv")
    p1 = p1[p1.condition == "instrumented"].assign(pool="phase1_pooled")
    pool = pd.concat([p2, p1], ignore_index=True)
    pool["task_instance_id"] = pool.task_instance_id.astype(int)
    pool = pool[[(r.pool, r.task_name, int(r.task_instance_id)) in keys for r in pool.itertuples()]]
    pool = pool[pool.completed.fillna(False).astype(bool) & pool.answer_canonical.notna()]

    rows = []
    for (p, t, i), g in pool.groupby(["pool", "task_name", "task_instance_id"]):
        r = list(g.reward.fillna(0))
        rows.append(
            {
                "pool": p,
                "task_name": t,
                "task_instance_id": int(i),
                "n_usable": len(r),
                "oracle_at_3": oracle_at_k(r, 3),
                "oracle_at_4": oracle_at_k(r, 4),
                "oracle_all": float(max(r)) if r else 0.0,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(args.out / "a8_matched_k.csv", index=False)

    # Instances with <3 usable trajectories have no defined Oracle@3; they are
    # reported separately rather than silently imputed, since imputing 0 or the
    # observed max would each bias the comparison in a different direction.
    have3 = df[df.oracle_at_3.notna()]

    # Arm 2's oracle must be recomputed on the SAME instances, or the comparison
    # swaps one mismatch (K) for another (population) - the exact denominator
    # error A.7 was written to avoid. A.1's 0.5128 is over all 78; the pool's
    # matched Oracle@3 is only defined on the 67 with >=3 usable trajectories.
    a2 = pd.read_csv(STEP2 / "arm2_per_trajectory.csv")
    a2["task_instance_id"] = a2.task_instance_id.astype(int)
    a2 = a2[a2.completed.fillna(False).astype(bool) & a2.answer_canonical.notna()]
    a2_oracle = {
        (t, int(i)): float(g.reward.fillna(0).max()) for (t, i), g in a2.groupby(["task_name", "task_instance_id"])
    }
    matched_keys = [(r.task_name, int(r.task_instance_id)) for r in have3.itertuples()]
    arm2_matched = [a2_oracle.get(k, 0.0) for k in matched_keys]

    arm2_oracle3_all78 = 0.5128205128205128  # from A.1, over all 78

    report = {
        "n_instances_total": int(len(df)),
        "n_instances_with_at_least_3_usable": int(len(have3)),
        "n_instances_excluded_no_oracle3": int(df.oracle_at_3.isna().sum()),
        "pool_oracle_at_3_matched": cluster_ci(list(have3.oracle_at_3)),
        "pool_oracle_at_4_where_defined": cluster_ci(list(df[df.oracle_at_4.notna()].oracle_at_4)),
        "pool_oracle_over_all_usable": cluster_ci(list(df.oracle_all)),
        "arm2_oracle_same_67_instances": cluster_ci(arm2_matched),
        "arm2_oracle_at_3_all_78_for_reference": arm2_oracle3_all78,
        "arm2_minus_pool_matched_k": None,
        "interpretation": None,
    }
    pm = report["pool_oracle_at_3_matched"]["point"]
    arm2_oracle3 = report["arm2_oracle_same_67_instances"]["point"]
    report["arm2_minus_pool_matched_k"] = round(arm2_oracle3 - pm, 4)
    report["interpretation"] = (
        "Arm 2's best obtainable answer is WORSE than the best already present in the candidate "
        "set it was handed, at matched K. Selection from a set cannot fall below the set's best "
        "element, so the arm was re-solving the task rather than adjudicating between candidates."
        if arm2_oracle3 < pm
        else "Arm 2's oracle is at or above the matched-K pool oracle; the re-solving reading is NOT supported."
    )

    (args.out / "a8_matched_k.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
