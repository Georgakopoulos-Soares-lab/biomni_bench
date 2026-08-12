#!/usr/bin/env python3
"""Stage C — the single source of truth for the frozen 78's trajectory table.

`stage_c_run.py` (candidate/capsule construction) and `stage_c_analyze.py`
(reward lookup) each need the same underlying trajectory rows, filtered the
same way, or their two views of "the frozen 78" can silently diverge. This
module exists because they *did* diverge once: `stage_c_run.py` correctly left
`phase2b` unfiltered (D-37's shadow trajectories are part of the frozen
candidate sets), but a duplicated copy of the filter in `stage_c_analyze.py`
restricted `phase2b` to `condition == "instrumented"` as well, dropping the
reward row for any candidate held only by a shadow trajectory
(`crispr_delivery`/18's `'c'`, held by `crispr_delivery-i0018-shad-t3-*`) and
raising `no reward for candidates ['c']` before any verdict number existed.

Caught before any BiomniEval1 comparison was scored had already run its
analysis — the failure is a `KeyError`-shaped crash, not a silently wrong
number — but the fix belongs in one place, not two independently-maintained
copies.
"""

from __future__ import annotations

import pandas as pd

#: `phase2b` is deliberately **unfiltered**: D-37's evaluation-only shadow
#: trajectories are part of the candidate sets that produced the frozen
#: plurality floor (0.4103) and oracle ceiling (0.6026). `phase1_pooled` is
#: restricted to `condition == "instrumented"`, exactly as
#: `track_c_adjudication_pilot.py` did when it built the frozen 78. This
#: asymmetry is a property of the frozen population, not a filtering choice
#: made here — do not "fix" it into symmetry.
POOL_TABLES = {
    "phase2b": "/scratch/11034/atzanakak/biomni_unc_runs/phase2b/results/tables/p2b_pooled_trajectories.csv",
    "phase1_pooled": "/scratch/11034/atzanakak/biomni_unc_runs/phase1_pooled/results/tables/trajectories.csv",
}


def raw_trajectory_table() -> pd.DataFrame:
    """All columns, including reward. Callers that must not see ground truth
    drop `reward`/`strict_reward`/`correct` themselves, immediately, so the
    barrier is visible at the call site rather than hidden in here."""
    frames = []
    for pool, path in POOL_TABLES.items():
        df = pd.read_csv(path)
        if pool == "phase1_pooled":
            df = df[df.condition == "instrumented"]
        frames.append(df.assign(pool=pool))
    return pd.concat(frames, ignore_index=True)
