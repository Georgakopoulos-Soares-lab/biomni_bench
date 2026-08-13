#!/usr/bin/env python3
"""Adjudicate a Solver-B candidate against the frozen capability gate.

`reports/scope_study_preflight.md` SS6. **Every constant below was written and
committed before any Solver-B trajectory existed**, and is pinned against that
document by `tests/test_scope_gate.py`. CPU only.

The gate answers exactly one question:

    Can this model operate the Biomni scaffold well enough that a future matched
    solver-family comparison would be interpretable?

It is **not** a model-selection contest. The highest-accuracy candidate does not
win; a candidate that clears the frozen bars is frozen as Solver B, and the
fallback is reached only through the FAIL branch. That asymmetry is the point:
"run B2 because B1's accuracy disappointed" is model shopping, and the ordering
below makes it impossible without editing a committed file.

Three verdicts, evaluated strictly in order:

**FAIL** -- clear interface/scaffold incompatibility or catastrophic agent
behaviour. The model cannot be driven through the scaffold at all, or destroys
itself doing so. This is the only branch that authorises the predeclared B2.

**CAPABILITY-CONFOUNDED** -- the model technically runs, but its usable-answer
rate and/or basic task competence sits materially below Solver A, such that a
later family contrast could not cleanly be read as solver-family
generalisation. A candidate landing here is *not* promoted by pointing at
normalized headroom recovery: see the interpretation rule in SS6.4 of the design
document, which is binding and is restated in `INTERPRETATION_RULE` below.

**PASS** -- neither of the above. The model is frozen as Solver B.

Bars are derived from Solver A's own historical behaviour on the same eight task
families, with practical margins. Solver B is **not** required to match Solver A
-- that would defeat the purpose of testing a different family. It is required
not to be a floor-effect solver, because a floor-effect solver later described
as "an independent replication" would be the single most misleading outcome this
gate can prevent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------
# Solver-A reference, frozen. Biomni-R0-32B-Preview, experiment `phase2b`,
# first trajectory (K=1, the gate's own budget), restricted to the eight task
# families with a non-empty never-used pool. n = 120 instances.
# Source: <output_root>/phase2b/results/tables/p2b_pooled_trajectories.csv
# --------------------------------------------------------------------------
SOLVER_A_REFERENCE = {
    "population": "phase2b, 8 eligible task families, trajectory_index == 0",
    "n": 120,
    "completion_rate": 0.8917,
    "usable_rate": 0.8250,
    "accuracy": 0.5417,
    "degeneration_rate": 0.1083,
    "code_block_error_fraction_all_k": 0.2604,
}

# Descriptive only -- the exact 24 gate instances, n too small to set a bar from.
SOLVER_A_ON_GATE_SET = {
    "n": 24,
    "completion_rate": 0.9167,
    "usable_rate": 0.8333,
    "accuracy": 0.5833,
    "oracle_at_4": 0.7083,
    "mean_wall_seconds": 309.7,
}

# --------------------------------------------------------------------------
# The bars. Frozen. Do not edit after a Solver-B number exists; amend by dated
# appendix to the design document instead, per the project's standing D-32 rule.
# --------------------------------------------------------------------------
FAIL_BARS = {
    # fewer than half the runs finish at all
    "completion_rate_lt": 0.50,
    # fewer than half of Solver A's usable answers, in absolute terms below 0.40
    "usable_rate_lt": 0.40,
    # the scaffold's own answer protocol is not being followed on most runs
    "solution_block_ok_rate_lt": 0.50,
    # runaway/degeneration terminates 2 in 5 runs -- ~4x Solver A's 0.1083
    "degeneration_rate_gte": 0.40,
    # a quarter of runs die from serving/integration faults rather than agent behaviour
    "infra_failure_rate_gte": 0.25,
}

CONFOUNDED_BARS = {
    # materially below Solver A's 0.8250
    "usable_rate_lt": 0.65,
    # below half of Solver A's matched first-trajectory accuracy (0.5 x 0.5417).
    # Pooled random-guess accuracy across the eight families is roughly 0.115,
    # so this bar sits at about 2.4x chance -- low enough not to demand parity,
    # high enough to exclude a floor-effect solver.
    "accuracy_lt": 0.2708,
    # more than double Solver A's degeneration rate
    "degeneration_rate_gte": 0.25,
}

INFRA_FAILURE_CLASSES = ("model_server_failure", "model_timeout", "dependency_failure")
DEGENERATION_FAILURE_CLASSES = ("budget_terminated_consecutive_runaway", "model_context_overflow")

INTERPRETATION_RULE = (
    "If Solver B is materially capability-confounded, normalized headroom recovery does NOT cure "
    "the confound. The main cross-family claim must be labelled capability-confounded."
)


def compute_metrics(traj: pd.DataFrame) -> dict:
    """Per-candidate gate metrics. One trajectory per instance (K=1)."""
    n = len(traj)
    completed = traj["completed"].fillna(False).astype(bool)
    parse_ok = traj["answer_parse_status"].fillna("") == "ok"
    usable = completed & parse_ok
    fc = traj["failure_class"].fillna("")
    sol_ok = traj["solution_block_status"].fillna("") == "ok"

    denom_blocks = float(traj["code_execution_count"].fillna(0).sum())
    return {
        "n": int(n),
        "completion_rate": float(completed.mean()),
        "usable_rate": float(usable.mean()),
        "solution_block_ok_rate": float(sol_ok[completed].mean()) if completed.any() else 0.0,
        "degeneration_rate": float(fc.isin(DEGENERATION_FAILURE_CLASSES).mean()),
        "infra_failure_rate": float(fc.isin(INFRA_FAILURE_CLASSES).mean()),
        "code_block_error_fraction": (
            float(traj["failed_tool_call_count"].fillna(0).sum() / denom_blocks) if denom_blocks else None
        ),
        "mean_tool_calls": float(traj["tool_call_count"].fillna(0).mean()),
        "zero_tool_fraction": float((traj["tool_call_count"].fillna(0) == 0).mean()),
        "mean_llm_calls": float(traj["llm_call_count"].fillna(0).mean()),
        "mean_output_tokens": float(traj["total_output_tokens"].fillna(0).mean()),
        "mean_wall_seconds": float(traj["wall_time_seconds"].fillna(0).mean()),
        "total_wall_seconds": float(traj["wall_time_seconds"].fillna(0).sum()),
        # Ground truth is applied only here, after inference, as a capability
        # diagnostic. It never reached the solver.
        "accuracy": float(traj["reward"].fillna(0.0).ge(0.5).mean()),
    }


def adjudicate(m: dict) -> tuple[str, list[str]]:
    """Return (verdict, reasons). Order is FAIL, then CAPABILITY-CONFOUNDED, then PASS."""
    fail: list[str] = []
    if m["completion_rate"] < FAIL_BARS["completion_rate_lt"]:
        fail.append(f"completion_rate {m['completion_rate']:.4f} < {FAIL_BARS['completion_rate_lt']}")
    if m["usable_rate"] < FAIL_BARS["usable_rate_lt"]:
        fail.append(f"usable_rate {m['usable_rate']:.4f} < {FAIL_BARS['usable_rate_lt']}")
    if m["solution_block_ok_rate"] < FAIL_BARS["solution_block_ok_rate_lt"]:
        fail.append(
            f"solution_block_ok_rate {m['solution_block_ok_rate']:.4f} < {FAIL_BARS['solution_block_ok_rate_lt']}"
        )
    if m["degeneration_rate"] >= FAIL_BARS["degeneration_rate_gte"]:
        fail.append(f"degeneration_rate {m['degeneration_rate']:.4f} >= {FAIL_BARS['degeneration_rate_gte']}")
    if m["infra_failure_rate"] >= FAIL_BARS["infra_failure_rate_gte"]:
        fail.append(f"infra_failure_rate {m['infra_failure_rate']:.4f} >= {FAIL_BARS['infra_failure_rate_gte']}")
    if fail:
        return "FAIL", fail

    conf: list[str] = []
    if m["usable_rate"] < CONFOUNDED_BARS["usable_rate_lt"]:
        conf.append(f"usable_rate {m['usable_rate']:.4f} < {CONFOUNDED_BARS['usable_rate_lt']}")
    if m["accuracy"] < CONFOUNDED_BARS["accuracy_lt"]:
        conf.append(f"accuracy {m['accuracy']:.4f} < {CONFOUNDED_BARS['accuracy_lt']}")
    if m["degeneration_rate"] >= CONFOUNDED_BARS["degeneration_rate_gte"]:
        conf.append(f"degeneration_rate {m['degeneration_rate']:.4f} >= {CONFOUNDED_BARS['degeneration_rate_gte']}")
    if conf:
        return "CAPABILITY-CONFOUNDED", conf

    return "PASS", []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trajectories", required=True, help="aggregated trajectories.csv for the candidate")
    ap.add_argument("--candidate", required=True, help="B1 or B2")
    ap.add_argument("--model", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    traj = pd.read_csv(args.trajectories)
    metrics = compute_metrics(traj)
    verdict, reasons = adjudicate(metrics)

    by_task = (
        traj.assign(
            usable=lambda d: d["completed"].fillna(False).astype(bool) & (d["answer_parse_status"].fillna("") == "ok"),
            correct=lambda d: d["reward"].fillna(0.0).ge(0.5),
        )
        .groupby("task_name")
        .agg(
            n=("run_id", "size"),
            completion_rate=("completed", "mean"),
            usable_rate=("usable", "mean"),
            accuracy=("correct", "mean"),
            mean_wall_seconds=("wall_time_seconds", "mean"),
        )
        .round(4)
    )

    payload = {
        "candidate": args.candidate,
        "model": args.model,
        "revision": args.revision,
        "verdict": verdict,
        "verdict_reasons": reasons,
        "metrics": metrics,
        "solver_a_reference": SOLVER_A_REFERENCE,
        "solver_a_on_gate_set": SOLVER_A_ON_GATE_SET,
        "fail_bars": FAIL_BARS,
        "confounded_bars": CONFOUNDED_BARS,
        "interpretation_rule": INTERPRETATION_RULE,
        "failure_class_counts": traj["failure_class"].fillna("(none)").value_counts().to_dict(),
        "by_task": by_task.reset_index().to_dict(orient="records"),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"scope_gate_verdict_{args.candidate.lower()}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )
    by_task.to_csv(out / f"scope_gate_by_task_{args.candidate.lower()}.csv")

    print(f"candidate {args.candidate}: {args.model} @ {args.revision}")
    for k, v in metrics.items():
        print(f"  {k:28s} {v}")
    print(f"\nVERDICT: {verdict}")
    for r in reasons:
        print(f"  - {r}")
    print(f"\n{by_task.to_string()}")
    print(f"\nwrote {out}/scope_gate_verdict_{args.candidate.lower()}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
