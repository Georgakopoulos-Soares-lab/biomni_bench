#!/usr/bin/env python3
"""RL-signal preflight -- primary + secondary analyses, per arm.

`reports/rl_signal_preflight_preregistration.md` SS3-SS5, SS7. CPU only, no new
inference. Reuses existing, unmodified project code wherever possible:
`selectors.select_plurality`/`select_oracle` (the frozen selectors), and
`analysis.auroc`/`analysis.spearman`/`analysis.grouped_bootstrap` (the same
rank-based AUROC and instance-clustered bootstrap already used for every prior
detection result in this project). No new statistical method is introduced.

Usage
-----
    python scripts/rl_signal_preflight_analyze.py --arm a --out <dir>
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

from biomni_uncertainty.analysis import auroc, grouped_bootstrap, spearman  # noqa: E402
from biomni_uncertainty.selectors import candidates_from_frame, select_oracle, select_plurality  # noqa: E402

# --------------------------------------------------------------------------
# Frozen constants, reports/rl_signal_preflight_preregistration.md SS4-SS5.
# --------------------------------------------------------------------------
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260821
HIGH_UNCERTAINTY_STRATUM_AGREEMENT = 0.25  # lowest natural plurality_fraction value
MIN_ENRICHMENT_RATIO = 1.5
MIN_MIXED_REWARD_N = 10  # denominator guard


def _instance_uid(df: pd.DataFrame) -> pd.Series:
    return df["task_name"] + "::" + df["task_instance_id"].astype(str)


def build_per_instance_table(arm: str) -> pd.DataFrame:
    root = Path(f"/scratch/11034/atzanakak/biomni_unc_runs/scope_main_{arm}/results/tables")
    instrumented = pd.read_csv(root / "instrumented.csv")
    instances = pd.read_csv(root / "instances.csv")

    rows = []
    for (task, tid), g in instrumented.groupby(["task_name", "task_instance_id"], sort=True):
        g = g.sort_values("trajectory_index")
        if len(g) != 4:
            raise SystemExit(f"{task}/{tid}: expected 4 trajectory rows, got {len(g)}")
        r = g["reward"].fillna(0.0).ge(0.5).astype(int).tolist()
        s = sum(r)
        p = s / 4.0

        cands = candidates_from_frame(g)
        plur = select_plurality(cands)
        orac = select_oracle(cands)
        selection_failure = bool(orac.reward is not None and orac.reward >= 0.5 and (plur.reward or 0.0) < 0.5)

        rows.append(
            {
                "task_name": task,
                "task_instance_id": int(tid),
                "instance_uid": f"{task}::{tid}",
                "reward_vector": "".join(str(x) for x in r),
                "sum_reward": s,
                "all_correct": s == 4,
                "all_wrong": s == 0,
                "mixed_reward": int(0 < s < 4),
                "reward_variance": p * (1 - p),
                "oracle_positive": int((orac.reward or 0.0) >= 0.5),
                "selection_failure": int(selection_failure),
                "plurality_reward": plur.reward,
                "oracle_reward": orac.reward,
            }
        )
    per_inst = pd.DataFrame(rows)

    keep = instances[["task_name", "task_instance_id", "plurality_fraction", "pairwise_agreement", "n_unique_answers"]]
    out = per_inst.merge(keep, on=["task_name", "task_instance_id"], how="left", validate="one_to_one")
    if out["plurality_fraction"].isna().any():
        raise SystemExit(f"arm {arm}: missing plurality_fraction for some instances after merge")

    out["U"] = 1.0 - out["plurality_fraction"]
    out["U_secondary"] = 1.0 - out["pairwise_agreement"]
    return out


def _auroc_ci(df: pd.DataFrame, score_col: str, label_col: str) -> dict:
    def stat(d: pd.DataFrame) -> float | None:
        return auroc(d[score_col].tolist(), d[label_col].tolist())

    ci = grouped_bootstrap(df, "instance_uid", stat, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
    return {"auroc": ci.point, "ci95": [ci.lo, ci.hi], "n": ci.n}


def _rate_ci(df: pd.DataFrame, label_col: str) -> dict:
    def stat(d: pd.DataFrame) -> float:
        return float(d[label_col].mean())

    ci = grouped_bootstrap(df, "instance_uid", stat, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
    return {"rate": ci.point, "ci95": [ci.lo, ci.hi], "n": ci.n}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", required=True, choices=["a", "b"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = build_per_instance_table(args.arm)
    n = len(df)
    if n != 120:
        raise SystemExit(f"expected 120 instances, got {n}")

    n_mixed = int(df.mixed_reward.sum())
    base_rate_mixed = float(df.mixed_reward.mean())
    denominator_guard_clear = n_mixed >= MIN_MIXED_REWARD_N

    # ---- primary: AUROC(U, mixed_reward) ----------------------------------
    primary_auroc = _auroc_ci(df, "U", "mixed_reward")
    detection_a = primary_auroc["ci95"][0] is not None and primary_auroc["ci95"][0] > 0.5

    # ---- secondary: AUROC(U_secondary, mixed_reward), robustness only -----
    secondary_auroc = _auroc_ci(df, "U_secondary", "mixed_reward")

    # ---- stratum table: natural plurality_fraction levels ------------------
    strata = []
    for level in sorted(df.plurality_fraction.unique(), reverse=True):  # 1.0 -> 0.25 (agreement desc)
        sub = df[df.plurality_fraction == level]
        r = _rate_ci(sub, "mixed_reward")
        strata.append(
            {
                "agreement_level": level,
                "U_level": round(1 - level, 4),
                "n": len(sub),
                "p_mixed_reward": r["rate"],
                "ci95": r["ci95"],
                "enrichment_ratio": (r["rate"] / base_rate_mixed) if base_rate_mixed else None,
            }
        )
    high_unc = next(s for s in strata if s["agreement_level"] == HIGH_UNCERTAINTY_STRATUM_AGREEMENT)
    enrichment_b = (
        high_unc["enrichment_ratio"] is not None
        and high_unc["enrichment_ratio"] >= MIN_ENRICHMENT_RATIO
        and high_unc["ci95"][0] is not None
        and high_unc["ci95"][0] > base_rate_mixed
    )

    # ---- secondary: reward-variance rank correlation -----------------------
    def spearman_stat(d: pd.DataFrame) -> float | None:
        return spearman(d["U"].tolist(), d["reward_variance"].tolist())

    variance_corr_ci = grouped_bootstrap(
        df, "instance_uid", spearman_stat, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED
    )

    # ---- secondary: selection-failure analysis -----------------------------
    sel_fail_rate = _rate_ci(df, "selection_failure")
    sel_fail_auroc = _auroc_ci(df, "U", "selection_failure")

    report = {
        "arm": args.arm,
        "n_instances": n,
        "n_mixed_reward": n_mixed,
        "n_all_correct": int(df.all_correct.sum()),
        "n_all_wrong": int(df.all_wrong.sum()),
        "base_rate_mixed_reward": round(base_rate_mixed, 4),
        "denominator_guard": {
            "min_mixed_reward_n": MIN_MIXED_REWARD_N,
            "observed_n_mixed": n_mixed,
            "guard_clear": denominator_guard_clear,
        },
        "primary_auroc_U_mixed_reward": primary_auroc,
        "go_condition_a_discrimination": bool(detection_a),
        "secondary_auroc_U2_mixed_reward": secondary_auroc,
        "uncertainty_strata": strata,
        "go_condition_b_enrichment": bool(enrichment_b),
        "high_uncertainty_stratum": high_unc,
        "reward_variance_spearman": {
            "rho": variance_corr_ci.point,
            "ci95": [variance_corr_ci.lo, variance_corr_ci.hi],
        },
        "selection_failure_rate": sel_fail_rate,
        "selection_failure_auroc": sel_fail_auroc,
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED, "unit": "instance"},
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / f"rl_signal_per_instance_{args.arm}.csv", index=False)
    (out / f"rl_signal_report_{args.arm}.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"\nwrote {out}/rl_signal_report_{args.arm}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
