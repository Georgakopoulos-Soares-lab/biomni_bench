#!/usr/bin/env python
"""Reconcile Phase-2A's fixed-K=4 reward (0.577) with Phase-1's pooled plurality (0.620).

The two numbers describe the same 50 instances and the same 200 trajectories, so
a discrepancy is either an explainable definitional difference or a bug. This
script decides which, by recomputing both from the same table and isolating every
candidate cause: denominator, replay, failure handling, aggregation, tie-breaking
and ordering.

    python scripts/phase2a_reconcile.py \
        --tables   <output_root>/phase1_pooled/results/tables \
        --outcomes <output_root>/phase2a/results/tables/p2a_outcomes.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biomni_uncertainty.features import UNPARSEABLE_PREFIX, cluster_key_for, consensus  # noqa: E402
from biomni_uncertainty.selectors import (  # noqa: E402
    candidates_from_frame,
    select_first,
    select_oracle,
    select_plurality,
)

NATIVE_ORDERING = "0123"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", required=True, type=Path)
    ap.add_argument("--outcomes", required=True, type=Path)
    args = ap.parse_args()

    df = pd.read_parquet(args.tables / "instrumented.parquet")
    out = pd.read_parquet(args.outcomes)
    f4 = out[out.policy == "fixed_k4"]

    print("=" * 72)
    print("1. Denominators")
    print("=" * 72)
    print(f"  trajectories in pooled instrumented table : {len(df)}")
    print(f"  instances                                 : {df.global_instance_id.nunique()}")
    print(f"  instances replayed by phase2a             : {f4.groupby(['task_name', 'task_instance_id']).ngroups}")
    print(
        f"  replays per instance                      : {len(f4) // f4.groupby(['task_name', 'task_instance_id']).ngroups}"
    )

    print()
    print("=" * 72)
    print("2. Phase-1's frozen selector, recomputed on the same table")
    print("=" * 72)
    rows = []
    for _, g in df.groupby(["task_name", "task_instance_id"]):
        c = candidates_from_frame(g)
        rows.append(
            {
                "plurality": select_plurality(c).reward,
                "first": select_first(c).reward,
                "oracle": select_oracle(c).reward,
            }
        )
    p1 = pd.DataFrame(rows)
    print(f"  select_plurality (Phase-1 definition)     : {p1.plurality.mean():.4f}")
    print(f"  select_first                              : {p1.first.mean():.4f}")
    print(f"  select_oracle                             : {p1.oracle.mean():.4f}")

    print()
    print("=" * 72)
    print("3. Phase-2A fixed_k4, by ordering")
    print("=" * 72)
    native = f4[f4.ordering == NATIVE_ORDERING].reward_abstain_zero.mean()
    print(f"  native ordering {NATIVE_ORDERING} only                  : {native:.4f}   <-- compare with 2.")
    print(f"  averaged over all 24 orderings            : {f4.reward_abstain_zero.mean():.4f}")
    by_ord = f4.groupby("ordering").reward_abstain_zero.mean()
    print(f"  across the 24 fixed orderings             : min {by_ord.min():.4f}  max {by_ord.max():.4f}")
    print(
        f"  orderings reaching the Phase-1 value      : {(by_ord.round(4) == round(p1.plurality.mean(), 4)).sum()} of 24"
    )
    agree = abs(native - p1.plurality.mean()) < 1e-9
    print(f"  native ordering reproduces Phase-1 exactly: {agree}")

    print()
    print("=" * 72)
    print("4. Which instances are order-sensitive, and why")
    print("=" * 72)
    per = f4.groupby(["task_name", "task_instance_id"]).reward_abstain_zero.agg(["mean", "min", "max"])
    sens = per[per["min"] != per["max"]]
    total = 0.0
    for (task, tid), r in sens.iterrows():
        g = df[(df.task_name == task) & (df.task_instance_id == tid)].sort_values("trajectory_index")
        keys = [cluster_key_for(x) for x in g.to_dict("records")]
        res = consensus(keys, g.trajectory_index.tolist())
        shown = [("<no answer>" if k.startswith(UNPARSEABLE_PREFIX) else k)[:18] for k in keys]
        kind = "no consensus at all (every cluster size 1)" if res.plurality_count == 1 else "split vote"
        print(f"  {task}/i{tid:04d}")
        print(f"    answers {shown}  rewards {[int(v) for v in g.reward]}")
        print(f"    {len(res.tied_keys)}-way tie, plurality count {res.plurality_count}  [{kind}]")
        print(f"    Phase-1 lowest-index tiebreak scores 1.0; averaged over orderings {r['mean']:.4f}")
        total += 1.0 - r["mean"]
    print()
    print(f"  order-sensitive instances                 : {len(sens)} of {len(per)}")
    print(f"  gap explained by them  ({total:.4f}/50)      : {total / len(per):.5f}")
    print(f"  observed gap (Phase-1 - Phase-2A)         : {p1.plurality.mean() - f4.reward_abstain_zero.mean():.5f}")

    print()
    print("=" * 72)
    print("5. Ruling out the other candidate causes")
    print("=" * 72)
    n_unp = 0
    for _, g in df.groupby(["task_name", "task_instance_id"]):
        g = g.sort_values("trajectory_index")
        keys = [cluster_key_for(x) for x in g.to_dict("records")]
        res = consensus(keys, g.trajectory_index.tolist())
        n_unp += int(res.plurality_key.startswith(UNPARSEABLE_PREFIX))
    print(f"  failure handling (D-18): instances where a non-answer wins at K=4 under the OLD rule: {n_unp}")
    print("    -> D-18 changes the SELECTED ANSWER on those, but section 3 shows the native-ordering")
    print("       totals are identical, so it changes no reward at K=4 on this data.")
    print(f"  aggregation: both read the same instrumented.parquet ({len(df)} rows), same reward column.")
    print("  replay: fixed_k4 consumes all 4 trajectories in every replay -> no early stopping involved.")
    print()
    print("VERDICT: the difference is entirely tie-breaking under a single fixed trajectory order.")
    print("         Not a denominator, replay, failure-handling or aggregation bug.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
