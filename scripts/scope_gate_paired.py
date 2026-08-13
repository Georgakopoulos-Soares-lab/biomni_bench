#!/usr/bin/env python3
"""Paired Solver-B vs Solver-A comparison on the gate set. Decides NOTHING.

Written **after** `scripts/scope_gate_analyze.py` produced the B1 verdict. It is
a separate file on purpose: CLAUDE.md's standing rule is never to overwrite a
script that has already produced a gating decision, so the adjudicator is left
exactly as it ran and this descriptive companion lives beside it.

Why this exists. The gate's accuracy bar is an absolute floor (0.2708), and B1
cleared it. But "B1 scored 0.375 where Solver A scored 0.583" invites a
comparative reading that 24 instances cannot support, and the frozen verdict
does not depend on one. This script computes the paired statistics that say how
much the gate set can actually distinguish -- an exact McNemar test on the
discordant pairs and an instance-clustered bootstrap CI on the paired
difference -- so the write-up quotes an interval rather than two point estimates
side by side.

It also computes the cross-solver error-structure counts (both correct, B1 only,
A only, neither), which are a preview of the future study's analysis 4 on a
sample far too small to conclude from, and are labelled as such.
"""

from __future__ import annotations

import argparse
import json
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

KEY = ["task_name", "task_instance_id"]
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260812


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (centre - half, centre + half)


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["correct"] = out["reward"].fillna(0.0).ge(0.5)
    out["usable"] = out["completed"].fillna(False).astype(bool) & (out["answer_parse_status"].fillna("") == "ok")
    return out[KEY + ["correct", "usable"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--solver-b", required=True, help="Solver-B trajectories.csv (K=1)")
    ap.add_argument("--solver-a", required=True, help="Solver-A trajectories.csv on the same instances (K=1)")
    ap.add_argument("--candidate", default="B1")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    b = _prepare(pd.read_csv(args.solver_b))
    a = _prepare(pd.read_csv(args.solver_a))
    m = b.merge(a, on=KEY, suffixes=("_b", "_a"))
    n = len(m)
    if n != len(b) or n != len(a):
        raise SystemExit(f"unmatched instances: b={len(b)} a={len(a)} merged={n}")

    kb, ka = int(m.correct_b.sum()), int(m.correct_a.sum())
    b_only = int((m.correct_b & ~m.correct_a).sum())
    a_only = int((~m.correct_b & m.correct_a).sum())
    both = int((m.correct_b & m.correct_a).sum())
    neither = int((~m.correct_b & ~m.correct_a).sum())

    from scipy.stats import binomtest

    n_disc = b_only + a_only
    mcnemar_p = float(binomtest(b_only, n_disc, 0.5).pvalue) if n_disc else float("nan")

    d = (m.correct_b.astype(int) - m.correct_a.astype(int)).to_numpy()
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    reps = np.array([d[rng.integers(0, n, n)].mean() for _ in range(BOOTSTRAP_REPLICATES)])
    lo, hi = float(np.percentile(reps, 2.5)), float(np.percentile(reps, 97.5))

    payload = {
        "candidate": args.candidate,
        "n_matched_instances": n,
        "solver_b_accuracy": {"k": kb, "n": n, "rate": kb / n, "wilson95": list(wilson(kb, n))},
        "solver_a_accuracy": {"k": ka, "n": n, "rate": ka / n, "wilson95": list(wilson(ka, n))},
        "paired_difference_b_minus_a": (kb - ka) / n,
        "paired_difference_ci95": [lo, hi],
        "paired_difference_ci_excludes_zero": (lo > 0) or (hi < 0),
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED, "unit": "instance"},
        "mcnemar_exact": {"discordant_pairs": n_disc, "b_only": b_only, "a_only": a_only, "p_value": mcnemar_p},
        "error_structure_preview": {
            "both_correct": both,
            "solver_b_only": b_only,
            "solver_a_only": a_only,
            "neither": neither,
            "note": "Preview of the future study's cross-solver analysis 4, on n=24. Not a finding.",
        },
        "usable_rate": {"solver_b": float(m.usable_b.mean()), "solver_a": float(m.usable_a.mean())},
        "decides": "nothing; the verdict is in scope_gate_verdict_*.json",
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"scope_gate_paired_{args.candidate.lower()}.json"
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
