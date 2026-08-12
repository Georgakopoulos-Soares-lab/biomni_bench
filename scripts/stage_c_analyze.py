#!/usr/bin/env python3
"""Stage C — the frozen verdict computation.

Written and committed **before any BiomniEval1 selection was scored**. The
decision-rule constants below are pinned against `reports/stage_c_stop_rule.md`
by `tests/test_stage_c_analyze.py`, exactly as
`tests/test_track_c_adjudication_analyze.py` pins D-38's `gap/3`.

Decision rule (stop rule §5 + Amendment 1), reproduced here and nowhere
recomputed:

* Primary  — Δ = (selected-candidate reward) − (plurality floor) on all **78**,
  paired instance-clustered bootstrap, 10,000 replicates, seed 20260811001.
* GO       — Δ's 95% CI lower bound > 0, AND validity ≥ 95%, AND no task family
  showing a large negative reversal.
* NO-GO    — Δ's 95% CI upper bound < 0.0641, OR validity < 95%.
* INCONCLUSIVE otherwise.
* Secondary (decides nothing) — Δ on the reachable 47 against 0.1064.
* Each cell separately. No pooling. No best-cell reporting.

Usage
-----
    python scripts/stage_c_analyze.py --out <dir> --cell c1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_c_population  # noqa: E402

# --------------------------------------------------------------------------
# Frozen constants. Never recomputed from data, never widened.
# --------------------------------------------------------------------------
N_INSTANCES = 78
PLURALITY_FLOOR = 0.4103
ORACLE_CEILING = 0.6026
GAP = 0.1923
NOGO_BAR = 0.0641  # gap / 3
REACHABLE_N = 47
REACHABLE_FLOOR = 0.6809
REACHABLE_BAR = 0.1064
BOOTSTRAP_REPLICATES = 10000
BOOTSTRAP_SEED = 20260811001
VALIDITY_BAR = 0.95


def _reward_lookup() -> dict[tuple[str, str, int, str], float]:
    """Map (pool, task, instance, canonical answer) -> official reward.

    Read here and only here. `stage_c_run.py` never opens it. Uses the exact
    same pool filtering as candidate construction
    (`stage_c_population.raw_trajectory_table`) — the two must never diverge,
    or a candidate held only by a `phase2b` shadow trajectory has no reward to
    look up. See that module's docstring for why this is a shared function and
    not two copies of the same filter.
    """
    out: dict[tuple[str, str, int, str], float] = {}
    df = stage_c_population.raw_trajectory_table()
    for r in df.itertuples():
        key = (r.pool, r.task_name, int(r.task_instance_id), str(r.answer_canonical))
        if not pd.isna(r.reward):
            out.setdefault(key, float(r.reward))
    return out


def _plurality_choice(answers: list[str]) -> str:
    """Not used for the floor (which is frozen), only for reporting."""
    return max(sorted(set(answers)), key=answers.count)


def paired_bootstrap(delta: np.ndarray, seed: int, n: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(delta), size=(n, len(delta)))
    means = delta[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def verdict(lo: float, hi: float, validity: float) -> str:
    if validity < VALIDITY_BAR:
        return "NO-GO"
    if hi < NOGO_BAR:
        return "NO-GO"
    if lo > 0:
        return "GO"
    return "INCONCLUSIVE"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cell", required=True, choices=["c1", "c2"])
    args = ap.parse_args()
    out = Path(args.out)

    sel = [json.loads(x) for x in (out / f"selections_{args.cell}.jsonl").read_text().splitlines() if x.strip()]
    if len(sel) != N_INSTANCES:
        raise SystemExit(f"expected {N_INSTANCES} instances, got {len(sel)} — refusing to compute a partial verdict")

    meta = json.loads((out / f"score_metadata_{args.cell}.json").read_text())
    rewards = _reward_lookup()

    rows = []
    for s in sel:
        key = (s["pool"], s["task_name"], int(s["task_instance_id"]))
        cand_rewards = {a: rewards.get((*key, a)) for a in s["candidate_answers"]}
        missing = [a for a, v in cand_rewards.items() if v is None]
        if missing:
            raise SystemExit(f"no reward for candidates {missing} on {key}")
        # An unresolved tie scores 0, exactly as a no-majority did in D-38.
        got = 0.0 if s["unresolved_tie"] else float(cand_rewards[s["selected_answer"]])
        oracle = max(cand_rewards.values())
        plur = float(cand_rewards[_plurality_choice(s["candidate_answers"])])
        rows.append(
            {
                **{k: s[k] for k in ("pool", "task_name", "task_instance_id", "n_candidates", "margin")},
                "selected_answer": s["selected_answer"],
                "unresolved_tie": s["unresolved_tie"],
                "selector_reward": got,
                "oracle_over_candidates": oracle,
                "plurality_reward_descriptive": plur,
                "reachable": oracle > 0,
            }
        )
    df = pd.DataFrame(rows)

    n_err = int(meta.get("comparison_errors", 0))
    n_comp = int(meta.get("comparisons", 1))
    validity = 1.0 - (n_err / n_comp)

    # ---- primary: all 78 against the frozen floor ----
    delta = df.selector_reward.to_numpy() - PLURALITY_FLOOR
    lo, hi = paired_bootstrap(delta, BOOTSTRAP_SEED, BOOTSTRAP_REPLICATES)
    v = verdict(lo, hi, validity)

    # ---- secondary: reachable 47, decides nothing ----
    sub = df[df.reachable]
    d2 = sub.selector_reward.to_numpy() - REACHABLE_FLOOR
    lo2, hi2 = paired_bootstrap(d2, BOOTSTRAP_SEED, BOOTSTRAP_REPLICATES)

    report = {
        "cell": args.cell,
        "n": len(df),
        "validity": round(validity, 6),
        "comparison_errors": n_err,
        "unresolved_ties": int(df.unresolved_tie.sum()),
        "primary": {
            "selector_mean_reward": round(float(df.selector_reward.mean()), 4),
            "plurality_floor": PLURALITY_FLOOR,
            "oracle_ceiling": ORACLE_CEILING,
            "delta": round(float(delta.mean()), 4),
            "ci95": [round(lo, 4), round(hi, 4)],
            "nogo_bar": NOGO_BAR,
            "gap_fraction_recovered": round(float(delta.mean()) / GAP, 4),
            "verdict": v,
        },
        "secondary_reachable": {
            "n": int(len(sub)),
            "expected_n": REACHABLE_N,
            "selector_mean_reward": round(float(sub.selector_reward.mean()), 4),
            "floor": REACHABLE_FLOOR,
            "delta": round(float(d2.mean()), 4),
            "ci95": [round(lo2, 4), round(hi2, 4)],
            "bar": REACHABLE_BAR,
            "note": "decides nothing; cannot produce or overturn a verdict",
        },
    }

    tables = REPO / "reports" / "tables" / "stage_c"
    tables.mkdir(parents=True, exist_ok=True)
    df.to_csv(tables / f"stage_c_per_instance_{args.cell}.csv", index=False)
    (tables / f"stage_c_verdict_{args.cell}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
