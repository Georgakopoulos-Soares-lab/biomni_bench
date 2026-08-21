#!/usr/bin/env python3
"""Scope study primary #2 and the H1 verdict.

`reports/scope_study_preregistration.md` SS5.2-SS5.4, SS7 (denominator guard,
carried unchanged from `reports/scope_study_preflight.md` SS7). Joins verifier
selections (`scope_main_verifier_run.py`) to official rewards, computes the
absolute verifier gain over plurality with its CI, applies the denominator
guard to normalized headroom recovery, evaluates the capability-confound bar,
and assembles the four-row H1 verdict across both arms.

**Terminal `model_context_overflow` failures.** A trajectory that never
produced a parseable answer contributes no candidate to the verifier's set
(`scope_main_verifier_run.py` restricts capsule construction to
`answer_parse_status == "ok"` trajectories, exactly as Stage C did). This
script does not discard or re-score those instances differently: every one of
the 120 instances enters the plurality/oracle/verifier means with whatever
answer its usable trajectories support, and an instance with zero usable
trajectories scores 0 under every selector, plurality and verifier alike --
the same "a non-answer never wins a tie" convention (D-18) already enforced by
`selectors.select_plurality` for the plurality baseline. No terminal failure is
retried, repaired, or excluded from a denominator. This mirrors exactly how
`scope_main_detection_analysis.py` treats the same 120 instances, so both
halves of the primary analysis share one population.

Nothing here is decided from the observed numbers: every bar below is copied
verbatim from the frozen documents, never recomputed or adjusted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Frozen constants, reports/scope_study_preregistration.md SS5.2-SS5.4 and
# reports/scope_study_preflight.md SS7. Never recomputed from data.
# --------------------------------------------------------------------------
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260813
CAPABILITY_CONFOUND_CI_UPPER_BOUND = -0.15

# Denominator guard (preflight SS7): normalized recovery is defined only if
# BOTH hold; otherwise report `undefined` and give the absolute gain instead.
GUARD_MIN_ABS_HEADROOM = 0.10
GUARD_MIN_RECOVERABLE_N = 5


def paired_bootstrap(delta: np.ndarray, seed: int, n: int) -> tuple[float, float]:
    """Instance-clustered paired bootstrap. Identical method to stage_c_analyze.py."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(delta), size=(n, len(delta)))
    means = delta[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _reward_lookup(arm: str) -> dict[tuple[str, int, str], float]:
    """(task, instance, canonical answer) -> official reward, this arm only."""
    df = pd.read_csv(f"/scratch/11034/atzanakak/biomni_unc_runs/scope_main_{arm}/results/tables/instrumented.csv")
    df = df[df.answer_parse_status.astype(str) == "ok"]
    out: dict[tuple[str, int, str], float] = {}
    for r in df.itertuples():
        key = (r.task_name, int(r.task_instance_id), str(r.answer_canonical))
        if not pd.isna(r.reward):
            out.setdefault(key, float(r.reward))
    return out


def arm_verifier_analysis(arm: str, out: Path) -> dict:
    sel = [json.loads(x) for x in (out / f"selections_{arm}.jsonl").read_text().splitlines() if x.strip()]
    if len(sel) != 120:
        raise SystemExit(f"arm {arm}: expected 120 instances, got {len(sel)}")
    meta = json.loads((out / f"score_metadata_{arm}.json").read_text())
    rewards = _reward_lookup(arm)
    det = json.loads((out / f"detection_report_{arm}.json").read_text())
    pi = pd.read_csv(out / f"detection_per_instance_{arm}.csv")
    plurality_by_instance = {(r.task_name, int(r.task_instance_id)): float(r.plurality_reward) for r in pi.itertuples()}
    oracle_by_instance = {(r.task_name, int(r.task_instance_id)): float(r.oracle_reward) for r in pi.itertuples()}

    rows = []
    for s in sel:
        key = (s["task_name"], int(s["task_instance_id"]))
        if s["n_candidates"] == 0:
            # No candidate exists to select. Non-answer, scores 0 -- same
            # convention the plurality/oracle selectors already apply.
            got = 0.0
        elif s["unresolved_tie"]:
            got = 0.0
        else:
            cand_key = (*key, str(s["selected_answer"]))
            if cand_key not in rewards:
                raise SystemExit(f"no reward for selected candidate {cand_key}")
            got = float(rewards[cand_key])
        rows.append(
            {
                "task_name": key[0],
                "task_instance_id": key[1],
                "n_candidates": s["n_candidates"],
                "trivial": s.get("trivial", False),
                "unresolved_tie": s["unresolved_tie"],
                "selected_answer": s["selected_answer"],
                "verifier_selected_reward": got,
                "plurality_reward": plurality_by_instance[key],
                "oracle_reward": oracle_by_instance[key],
            }
        )
    df = pd.DataFrame(rows)
    if len(df) != 120:
        raise SystemExit(f"arm {arm}: joined table has {len(df)} rows, expected 120")

    n_err = int(meta.get("comparison_errors", 0))
    n_comp = int(meta.get("comparisons", 0))
    validity = 1.0 - (n_err / n_comp) if n_comp else 1.0

    plurality_mean = float(df.plurality_reward.mean())
    oracle_mean = float(df.oracle_reward.mean())
    verifier_mean = float(df.verifier_selected_reward.mean())
    headroom = oracle_mean - plurality_mean

    delta = df.verifier_selected_reward.to_numpy() - df.plurality_reward.to_numpy()
    lo, hi = paired_bootstrap(delta, BOOTSTRAP_SEED, BOOTSTRAP_REPLICATES)
    gain = float(delta.mean())
    correction_established = lo > 0

    n_recoverable = int(((df.oracle_reward > df.plurality_reward) & (df.oracle_reward > 0)).sum())
    guard_ok = headroom >= GUARD_MIN_ABS_HEADROOM and n_recoverable >= GUARD_MIN_RECOVERABLE_N
    normalized = (gain / headroom) if (guard_ok and headroom != 0) else None

    return {
        "arm": arm,
        "n_instances": len(df),
        "validity": round(validity, 6),
        "comparison_errors": n_err,
        "comparisons": n_comp,
        "n_zero_candidate": int((df.n_candidates == 0).sum()),
        "n_trivial_single_candidate": int(df.trivial.sum()),
        "n_scoreable_ge2_candidates": int((df.n_candidates >= 2).sum()),
        "n_unresolved_ties": int(df.unresolved_tie.sum()),
        "plurality_mean": round(plurality_mean, 4),
        "oracle_mean": round(oracle_mean, 4),
        "verifier_selected_mean": round(verifier_mean, 4),
        "headroom": round(headroom, 4),
        "absolute_verifier_gain": round(gain, 4),
        "gain_ci95": [round(lo, 4), round(hi, 4)],
        "correction_established": bool(correction_established),
        "correction_rule": "verifier absolute gain over plurality, 95% CI lower bound > 0",
        "denominator_guard": {
            "min_abs_headroom": GUARD_MIN_ABS_HEADROOM,
            "min_recoverable_n": GUARD_MIN_RECOVERABLE_N,
            "observed_headroom": round(headroom, 4),
            "observed_recoverable_n": n_recoverable,
            "guard_passed": bool(guard_ok),
        },
        "normalized_recovery": (round(normalized, 4) if normalized is not None else "undefined"),
        "detection": det,
        "per_instance_csv": f"h1_per_instance_{arm}.csv",
        "_df": df,
    }


def h1_row(a: dict, b: dict) -> tuple[str, str]:
    a_sep = a["detection"]["detection_established"] and not a["correction_established"]
    b_sep = b["detection"]["detection_established"] and not b["correction_established"]
    if a_sep and b_sep:
        return "REPLICATED", "both solvers show detection established and correction not established"
    if not b["detection"]["detection_established"]:
        return (
            "NOT REPLICATED",
            "detection not established for Solver B -- the arms are not comparing the same regime",
        )
    if a["detection"]["detection_established"] and b["detection"]["detection_established"]:
        if a["correction_established"] != b["correction_established"]:
            return "NOT REPLICATED", "correction is solver-specific (established for one arm, not the other)"
    return "MIXED", "observed combination does not match a single pre-registered row"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tables-out", default="reports/tables/scope_study")
    args = ap.parse_args()
    out = Path(args.out)

    result_a = arm_verifier_analysis("a", out)
    result_b = arm_verifier_analysis("b", out)

    tables = Path(args.tables_out)
    tables.mkdir(parents=True, exist_ok=True)
    for r in (result_a, result_b):
        df = r.pop("_df")
        df.to_csv(tables / r["per_instance_csv"], index=False)

    # ---- capability-confound bar: paired Pass@1 difference (B - A) --------
    pi_a = pd.read_csv(out / "detection_per_instance_a.csv").set_index(["task_name", "task_instance_id"])
    pi_b = pd.read_csv(out / "detection_per_instance_b.csv").set_index(["task_name", "task_instance_id"])
    joined = pi_a[["pass_at_1_reward"]].join(pi_b[["pass_at_1_reward"]], lsuffix="_a", rsuffix="_b", how="inner")
    if len(joined) != 120:
        raise SystemExit(f"expected 120 matched instances for the capability bar, got {len(joined)}")
    diff = joined.pass_at_1_reward_b.fillna(0).to_numpy() - joined.pass_at_1_reward_a.fillna(0).to_numpy()
    d_lo, d_hi = paired_bootstrap(diff, BOOTSTRAP_SEED, BOOTSTRAP_REPLICATES)
    capability_confounded = d_hi < CAPABILITY_CONFOUND_CI_UPPER_BOUND

    verdict, verdict_reason = h1_row(result_a, result_b)

    report = {
        "study": "matched scope study, H1",
        "arm_a": result_a,
        "arm_b": result_b,
        "capability_confound_check": {
            "paired_pass_at_1_diff_b_minus_a": round(float(diff.mean()), 4),
            "ci95": [round(d_lo, 4), round(d_hi, 4)],
            "bar": f"upper bound < {CAPABILITY_CONFOUND_CI_UPPER_BOUND}",
            "capability_confounded": bool(capability_confounded),
        },
        "h1_verdict": verdict,
        "h1_verdict_reason": verdict_reason,
        "h1_label": f"{verdict} [CAPABILITY-CONFOUNDED]" if capability_confounded else verdict,
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED, "unit": "instance"},
    }

    (tables / "scope_main_h1_verdict.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"\nwrote {tables}/scope_main_h1_verdict.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
