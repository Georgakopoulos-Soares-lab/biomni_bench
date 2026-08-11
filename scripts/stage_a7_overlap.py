#!/usr/bin/env python
"""A.7 - unreachable-instance overlap with Stage C's frozen 78, and the
recomputed bars for a reachable-subset secondary analysis. CPU only.

WHY: a verifier that scores the *committed candidates* cannot reach an instance
where none of the committed candidates is correct - the correct answer is not in
the set it is choosing from. On those instances every verifier scores zero by
construction, while they still sit in the denominator of any mean.

A.5b flagged such instances by two routes, `singled_out` and extraction
failure. Those routes are NOT disjoint - the 3 extraction failures are a strict
subset of the 18 singled-out, so the flagged set is 18, not 21 (verified
directly; unsurprising, since a trajectory that generated the correct answer and
lost it to parsing would also have discussed it preferentially). The property is
in any case more general, and is used in that general form here: **an instance is unreachable iff its oracle over committed candidates is
0**, i.e. no usable trajectory committed the correct answer. That is exactly
`oracle_reward == 0` in D-37's canonical table, and it needs no heuristic.

Both the count and the recomputed bars are written into Stage C's frozen file
as a dated amendment BEFORE Stage C runs. Declared in advance this is a stated
limitation; discovered afterwards it would read as a denominator chosen to fit.

    python scripts/stage_a7_overlap.py --out reports/tables/stage_a
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

STEP2 = REPO / "reports" / "tables" / "track_c_step2"
PREFLIGHT = Path("/scratch/11034/atzanakak/biomni_unc_runs/track_c_preflight/results")
STAGE_A = REPO / "reports" / "tables" / "stage_a"

KEY = ["task_name", "task_instance_id"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cands = [json.loads(x) for x in (STEP2 / "candidates_slim.jsonl").read_text().splitlines() if x.strip()]
    frozen78 = pd.DataFrame(cands)[["pool", "task_name", "task_instance_id"]]
    frozen78["task_instance_id"] = frozen78.task_instance_id.astype(int)

    p2 = pd.read_csv(PREFLIGHT / "instance_table__phase2b.csv").assign(pool="phase2b")
    p1 = pd.read_csv(PREFLIGHT / "instance_table__phase1_pooled.csv").assign(pool="phase1_pooled")
    table = pd.concat([p2, p1], ignore_index=True)
    table["task_instance_id"] = table.task_instance_id.astype(int)

    m = frozen78.merge(table, on=["pool", *KEY], how="left", validate="one_to_one")
    assert len(m) == 78 and m.oracle_reward.notna().all(), "the frozen 78 must join cleanly"

    m["unreachable"] = m.oracle_reward == 0
    reachable = m[~m.unreachable]

    # A.5b's flagged set (18, see the docstring), intersected with the frozen 78
    # (phase2b only - A.5b audited the phase2b no-correct set).
    tri = pd.read_csv(STAGE_A / "a5_label_triage.csv")
    tri["task_instance_id"] = tri.task_instance_id.astype(int)
    flagged = tri[tri.singled_out.fillna(False).astype(bool) | tri.extraction_failure.fillna(False).astype(bool)]
    flagged_keys = {tuple(x) for x in flagged[KEY].values}
    p2b_78 = m[m.pool == "phase2b"]
    overlap = p2b_78[[tuple(x) in flagged_keys for x in p2b_78[KEY].values]]

    def bars(df: pd.DataFrame) -> dict:
        floor = float(df.plurality_reward.mean())
        ceiling = float(df.oracle_reward.mean())
        gap = ceiling - floor
        return {
            "n": int(len(df)),
            "plurality_floor": round(floor, 4),
            "oracle_ceiling": round(ceiling, 4),
            "gap": round(gap, 4),
            "gap_over_3_NOGO_bar": round(gap / 3, 4),
        }

    report = {
        "frozen_78": bars(m),
        "unreachable": {
            "definition": "oracle over committed candidates is 0 - no usable trajectory committed the correct answer",
            "n": int(m.unreachable.sum()),
            "share_of_78": round(float(m.unreachable.mean()), 4),
            "by_pool": m[m.unreachable].pool.value_counts().to_dict(),
            "note": (
                "every verifier that scores committed candidates gets 0 on these by construction, "
                "while they remain in the denominator of any mean over the 78"
            ),
        },
        "a5b_flagged_overlap": {
            "n_flagged_in_a5b": int(len(flagged)),
            "n_of_those_inside_the_frozen_78": int(len(overlap)),
            "all_flagged_are_unreachable": bool(overlap.unreachable.all()) if len(overlap) else None,
            "note": (
                "A.5b's flagged set (18 distinct instances; the 3 extraction failures are a "
                "subset of the 18 singled-out, not additional to them) is drawn from phase2b's 45 "
                "no-correct instances; the no-correct axis cuts across stratum B (D-37), so the "
                "overlap with the frozen 78 is real rather than hypothetical"
            ),
        },
        "reachable_subset": bars(reachable),
        "preregistration": {
            "primary": (
                "Delta on all 78 against the existing 0.0641 bar, unchanged, for direct comparability with D-38"
            ),
            "secondary": (
                "Delta on the reachable subset against its own recomputed bar, since unreachable "
                "instances contribute zero to the numerator while sitting in the denominator"
            ),
            "both_bars_fixed_before_stage_c_runs": True,
        },
    }

    m.to_csv(args.out / "a7_reachability.csv", index=False)
    (args.out / "a7_overlap.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
