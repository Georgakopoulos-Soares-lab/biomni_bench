#!/usr/bin/env python3
"""RL-signal preflight -- final per-arm verdict and cross-solver interpretation.

`reports/rl_signal_preflight_preregistration.md` SS5 (verdict rule) and SS7
(cross-solver table). Combines `rl_signal_report_{arm}.json` (conditions a, b)
and `rl_signal_simulation_{arm}.json` (condition c) -- computes nothing new,
just applies the frozen rule to already-computed numbers.

Usage
-----
    python scripts/rl_signal_verdict.py --out <dir> --tables-out <dir>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def arm_verdict(report: dict, sim: dict) -> tuple[str, list[str]]:
    guard_clear = report["denominator_guard"]["guard_clear"]
    a = report["go_condition_a_discrimination"]
    b = report["go_condition_b_enrichment"]
    c = sim["go_condition_c_budget_verified_capture"]

    reasons = [
        f"(a) discrimination CI-supported: {a}",
        f"(b) high-uncertainty-stratum enrichment: {b}",
        f"(c) budget-verified capture: {c}",
        f"denominator guard clear (n_mixed={report['n_mixed_reward']} >= 10): {guard_clear}",
    ]

    if not guard_clear:
        return "INCONCLUSIVE", reasons + ["too few mixed_reward instances for a stable estimate"]

    auroc_hi = report["primary_auroc_U_mixed_reward"]["ci95"][1]
    no_discrimination_at_all = auroc_hi is not None and auroc_hi <= 0.5
    enrichment_ratio = report["high_uncertainty_stratum"]["enrichment_ratio"]
    at_or_below_chance = enrichment_ratio is not None and enrichment_ratio <= 1.0

    if a and b and c:
        return "GO", reasons
    if no_discrimination_at_all or at_or_below_chance:
        return "NO-GO", reasons
    return "INCONCLUSIVE", reasons


def cross_solver_reading(verdict_a: str, verdict_b: str) -> str:
    if verdict_a == "GO" and verdict_b == "GO":
        return (
            "uncertainty identifies RL-informative prompts AND generalises across solver family -- "
            "licenses a cross-solver uncertainty-guided-RL hypothesis"
        )
    if verdict_a == "GO" or verdict_b == "GO":
        which = "Arm A (Biomni-R0)" if verdict_a == "GO" else "Arm B (Mistral)"
        return (
            f"the detection-generalises/correction-does-not pattern (D-46) extends to this question too -- "
            f"RL may proceed only for {which}, with a correspondingly narrow claim"
        )
    return (
        "agreement predicts correctness (established, D-46) but does NOT identify prompts with useful "
        "within-group reward variation on either solver -- the current uncertainty-guided curriculum "
        "hypothesis is NOT supported and should not proceed"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tables-out", default="reports/tables/rl_signal_preflight")
    args = ap.parse_args()
    out = Path(args.out)

    reports = {arm: json.loads((out / f"rl_signal_report_{arm}.json").read_text()) for arm in ("a", "b")}
    sims = {arm: json.loads((out / f"rl_signal_simulation_{arm}.json").read_text()) for arm in ("a", "b")}

    verdicts = {}
    for arm in ("a", "b"):
        v, reasons = arm_verdict(reports[arm], sims[arm])
        verdicts[arm] = {"verdict": v, "reasons": reasons}

    final = {
        "arm_a": {"report": reports["a"], "simulation": sims["a"], **verdicts["a"]},
        "arm_b": {"report": reports["b"], "simulation": sims["b"], **verdicts["b"]},
        "cross_solver_reading": cross_solver_reading(verdicts["a"]["verdict"], verdicts["b"]["verdict"]),
    }

    tables = Path(args.tables_out)
    tables.mkdir(parents=True, exist_ok=True)
    (tables / "rl_signal_final_verdict.json").write_text(json.dumps(final, indent=2, sort_keys=True, default=str))

    print(f"Arm A (Biomni-R0): {verdicts['a']['verdict']}")
    for r in verdicts["a"]["reasons"]:
        print(f"  {r}")
    print(f"\nArm B (Mistral): {verdicts['b']['verdict']}")
    for r in verdicts["b"]["reasons"]:
        print(f"  {r}")
    print(f"\nCross-solver reading: {final['cross_solver_reading']}")
    print(f"\nwrote {tables}/rl_signal_final_verdict.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
