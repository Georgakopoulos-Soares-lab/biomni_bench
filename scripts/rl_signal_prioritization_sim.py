#!/usr/bin/env python3
"""RL-signal preflight -- offline prioritization simulation, per arm.

`reports/rl_signal_preflight_preregistration.md` SS6, plus GO condition (c)
from SS5. CPU only. Reads `rl_signal_per_instance_{arm}.csv`
(`rl_signal_preflight_analyze.py`'s output) -- no ground truth is consulted by
the uncertainty ranking at any point; it is enforced structurally, by never
passing `mixed_reward`/`reward`/`correct` into the ranking function.

Three curves over the frozen budget grid {5%, 10%, ..., 100%} of 120
instances (exact instance counts: 6, 12, ..., 120 -- 120 is evenly divisible
by every 5% step, so no rounding rule is needed):

* **uniform** -- 10,000 without-replacement draws of the budget's instance
  count from the ORIGINAL 120; empirical mean and 95% band of mixed_reward
  instances captured. This is a Monte Carlo simulation of the actual
  deployable random strategy, not a significance-test bootstrap.
* **uncertainty** -- deterministic: instances ranked by U descending, ties
  broken by (task_name, task_instance_id) ascending -- a fully deterministic
  secondary/tertiary key, since the preregistration's "lowest task_instance_id"
  is ambiguous across tasks (instance ids are only unique within a task).
  Single line, no band: given the observed data, this ranking has no random
  component.
* **oracle** -- deterministic upper bound: ranked by the TRUE mixed_reward
  label descending (same deterministic tie-break). Never a deployable policy.

GO condition (c) is answered separately by a proper bootstrap (not the Monte
Carlo curve above): `grouped_bootstrap` resamples instances (with
replacement, the same instance-clustered mechanism as every other bootstrap in
this project) and recomputes, in each resample, the PAIRED difference between
(i) uncertainty-ranked top-25%-of-resample capture and (ii) uniform's expected
capture in that same resample (`0.25 * n_mixed_in_resample`). The GO
condition is this paired difference's 95% CI lower bound `> 0` -- the same
paired-instance-clustered-bootstrap-of-a-difference method already used
throughout this project (D-38, D-43, D-46), applied to a new statistic, not a
new method.

Usage
-----
    python scripts/rl_signal_prioritization_sim.py --arm a --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))

BUDGET_FRACTIONS = [round(0.05 * i, 2) for i in range(1, 21)]  # 5% .. 100%
MONTE_CARLO_DRAWS = 10_000
MONTE_CARLO_SEED = 20260821
BUDGET_25_FRACTION = 0.25  # GO condition (c)


def _ranked(df: pd.DataFrame, score_col: str) -> pd.DataFrame:
    """Deterministic ranking, ties broken by (task_name, task_instance_id) asc."""
    return df.sort_values([score_col, "task_name", "task_instance_id"], ascending=[False, True, True])


def uniform_monte_carlo(df: pd.DataFrame, budget_n: int, draws: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = len(df)
    mixed = df["mixed_reward"].to_numpy()
    idx_all = np.arange(n)
    captures = np.empty(draws, dtype=int)
    for i in range(draws):
        picked = rng.choice(idx_all, size=budget_n, replace=False)
        captures[i] = int(mixed[picked].sum())
    return {
        "mean": float(captures.mean()),
        "ci95": [float(np.percentile(captures, 2.5)), float(np.percentile(captures, 97.5))],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", required=True, choices=["a", "b"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    df = pd.read_csv(out / f"rl_signal_per_instance_{args.arm}.csv")
    n = len(df)
    if n != 120:
        raise SystemExit(f"expected 120 instances, got {n}")
    n_mixed = int(df.mixed_reward.sum())

    unc_ranked = _ranked(df, "U")
    orc_ranked = _ranked(df, "mixed_reward")

    curve = []
    for frac in BUDGET_FRACTIONS:
        budget_n = round(frac * n)
        uncertainty_capture = int(unc_ranked.head(budget_n).mixed_reward.sum())
        oracle_capture = int(orc_ranked.head(budget_n).mixed_reward.sum())
        uniform = uniform_monte_carlo(df, budget_n, MONTE_CARLO_DRAWS, MONTE_CARLO_SEED + budget_n)
        curve.append(
            {
                "budget_fraction": frac,
                "budget_n_instances": budget_n,
                "uniform_mean_capture": uniform["mean"],
                "uniform_ci95": uniform["ci95"],
                "uncertainty_capture": uncertainty_capture,
                "oracle_capture": oracle_capture,
                "enrichment_uncertainty_over_uniform": (
                    uncertainty_capture / uniform["mean"] if uniform["mean"] > 0 else None
                ),
                "mixed_per_100_prompts_uncertainty": round(100 * uncertainty_capture / budget_n, 2)
                if budget_n
                else None,
                "mixed_per_100_prompts_uniform": round(100 * uniform["mean"] / budget_n, 2) if budget_n else None,
            }
        )

    # ---- GO condition (c): paired bootstrap of the 25%-budget difference --
    # Instance-clustered resample via numpy row-indexing: every row here is
    # already one instance, so this is the same resampling unit as
    # `analysis.grouped_bootstrap` (resample instances with replacement),
    # implemented directly rather than through its per-group `pd.concat`
    # path, which is markedly slower for a table with no genuine sub-grouping.
    budget_25_n = round(BUDGET_25_FRACTION * n)

    def diff_stat(d: pd.DataFrame) -> float:
        ranked = _ranked(d, "U")
        capture = int(ranked.head(round(BUDGET_25_FRACTION * len(d))).mixed_reward.sum())
        uniform_expected = BUDGET_25_FRACTION * d.mixed_reward.sum()
        return capture - uniform_expected

    diff_point = diff_stat(df)
    rng = np.random.default_rng(20260821)
    diffs = np.empty(10_000)
    for i in range(10_000):
        idx = rng.integers(0, n, size=n)
        diffs[i] = diff_stat(df.iloc[idx])
    diff_lo, diff_hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    go_condition_c = diff_lo > 0

    report = {
        "arm": args.arm,
        "n_instances": n,
        "n_mixed_reward": n_mixed,
        "budget_curve": curve,
        "budget_25pct": {
            "budget_n": budget_25_n,
            "uncertainty_minus_uniform_expected_capture": diff_point,
            "ci95": [diff_lo, diff_hi],
        },
        "go_condition_c_budget_verified_capture": bool(go_condition_c),
        "monte_carlo": {"draws": MONTE_CARLO_DRAWS, "seed_base": MONTE_CARLO_SEED},
        "bootstrap": {"replicates": 10_000, "seed": 20260821, "unit": "instance"},
    }
    (out / f"rl_signal_simulation_{args.arm}.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str)
    )
    pd.DataFrame(curve).to_csv(out / f"rl_signal_budget_curve_{args.arm}.csv", index=False)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"\nwrote {out}/rl_signal_simulation_{args.arm}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
