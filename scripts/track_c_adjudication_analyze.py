#!/usr/bin/env python
"""Track-C Step 2 - analysis of the candidate-adjudication pilot.

Implements `reports/track_c_step2_acceptance_rule.md` (frozen 2026-08-10,
before any Arm-1/Arm-2 trajectory existed) verbatim: the population, the
floor/ceiling, the majority-resolution rule, the paired instance-clustered
bootstrap, and the GO / NO-GO / INCONCLUSIVE thresholds. Nothing in this
script chooses a threshold - every number that decides the verdict is copied
from that file.

Arm 2 completeness is checked against the full population (78 instances x 3
samples = 234 trajectories) before any verdict is computed; a partial run is
reported descriptively only, tagged INCOMPLETE, never given a verdict.

    python scripts/track_c_adjudication_analyze.py \
        --candidates <dir>/candidates.jsonl \
        --arm1 <dir>/arm1_results.jsonl \
        --config <dir>/step2_adjudication_config.yaml \
        --out reports/tables/track_c_step2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from biomni_uncertainty.aggregation import attach_rewards, collect_run_records  # noqa: E402
from biomni_uncertainty.analysis import paired_bootstrap_difference  # noqa: E402
from biomni_uncertainty.benchmark import prompt_hash  # noqa: E402
from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.evaluation import OfficialEvaluator  # noqa: E402
from biomni_uncertainty.sampling import RunSpec, make_run_id, run_dir_for  # noqa: E402

N_SAMPLES_PER_ARM = 3
SEED_BASE = 9000
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260811001

# Frozen floor/ceiling, copied verbatim from step2_acceptance_rule.md.
FROZEN_GAP_THIRD = 0.0641

# Frozen task-family stratification (D-37-revised, step2_acceptance_rule.md).
EVIDENCE_RETRIEVABLE_TASKS = frozenset(
    {
        "gwas_causal_gene_gwas_catalog",
        "gwas_causal_gene_opentargets",
        "gwas_causal_gene_pharmaprojects",
        "gwas_variant_prioritization",
        "lab_bench_dbqa",
        "lab_bench_seqqa",
    }
)
DOMAIN_JUDGMENT_TASKS = frozenset(
    {"crispr_delivery", "patient_gene_detection", "rare_disease_diagnosis", "screen_gene_retrieval"}
)


def _majority(picks: list[str | None]) -> tuple[str | None, str]:
    """Majority-resolve 3 samples. Returns (answer_or_None, status).

    status is one of: "majority" (>=2 of 3 agree on a real answer),
    "no_majority" (3 distinct, or all null/off-menu), "all_missing".
    """
    usable = [p for p in picks if p is not None]
    if not usable:
        return None, "all_missing"
    counts = Counter(usable)
    top, n = counts.most_common(1)[0]
    if n >= 2:
        return top, "majority"
    return None, "no_majority"


def load_floor_ceiling(preflight_root: Path) -> pd.DataFrame:
    p2b = pd.read_csv(preflight_root / "instance_table__phase2b.csv")
    p2b["pool"] = "phase2b"
    p1 = pd.read_csv(preflight_root / "instance_table__phase1_pooled.csv")
    p1["pool"] = "phase1_pooled"
    both = pd.concat([p2b, p1], ignore_index=True)
    return both[["pool", "task_name", "task_instance_id", "plurality_reward", "oracle_reward"]]


def load_ground_truth() -> OfficialEvaluator:
    gt: dict[tuple[str, int], str] = {}
    for name in ("phase2b.groundtruth.jsonl", "phase1.groundtruth.jsonl"):
        path = REPO / "manifests" / name
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            gt[(rec["task_name"], int(rec["task_instance_id"]))] = rec["answer"]
    return OfficialEvaluator(gt)


# --------------------------------------------------------------------------
# Arm 1
# --------------------------------------------------------------------------


def analyze_arm1(path: Path, evaluator: OfficialEvaluator) -> pd.DataFrame:
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        picks = [s.get("picked") for s in r["samples"]]
        # Arm 1 has no reliable answer parser independent of exact-string
        # matching against the candidate list, so a null `picked` conflates
        # two different things: a genuine off-menu answer and an extraction
        # failure (ambiguous tail text). Reported as one combined
        # "unresolved" rate - see Arm 2's n_off_menu for the clean version,
        # which uses this project's real answer parser and can distinguish
        # the two.
        n_unresolved = sum(1 for s in r["samples"] if s.get("picked") is None and s.get("error") is None)
        answer, status = _majority(picks)
        res = evaluator.evaluate(r["task_name"], int(r["task_instance_id"]), answer, answer)
        rows.append(
            {
                "pool": r["pool"],
                "task_name": r["task_name"],
                "task_instance_id": r["task_instance_id"],
                "n_candidates": len(r["candidates"]),
                "picks": picks,
                "majority_answer": answer,
                "majority_status": status,
                "n_unresolved": n_unresolved,
                "reward": res.reward,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Arm 2
# --------------------------------------------------------------------------


def _arm2_specs(candidates: list[dict], cfg) -> list[RunSpec]:
    specs = []
    for r in candidates:
        for s in range(N_SAMPLES_PER_ARM):
            condition = "adjudication"
            run_id = make_run_id(cfg.experiment_id, r["task_name"], r["task_instance_id"], condition, s)
            base = {
                "task_name": r["task_name"],
                "task_instance_id": r["task_instance_id"],
                "condition": condition,
                "trajectory_index": s,
            }
            specs.append(
                RunSpec(
                    experiment_id=cfg.experiment_id,
                    run_id=run_id,
                    condition=condition,
                    task_name=r["task_name"],
                    global_instance_id=r["global_instance_id"],
                    task_instance_id=r["task_instance_id"],
                    trajectory_index=s,
                    prompt=r["adjudication_prompt"],
                    prompt_hash=prompt_hash(r["adjudication_prompt"]),
                    split="val",
                    requested_seed=SEED_BASE + s,
                    confidence_mode=cfg.confidence.mode,
                    model=cfg.model.identifier,
                    model_revision=cfg.model.revision,
                    temperature=cfg.model.temperature,
                    max_tokens=cfg.model.max_tokens,
                    timeout_seconds=cfg.execution.run_timeout_seconds,
                    run_dir=str(run_dir_for(cfg, base)),
                )
            )
    return specs


def _retrieval_provenance_present(run_dir: str) -> bool:
    """D-33 lightweight coverage check: does this run's events.jsonl contain
    at least one retrieval-provenance event (`retrieval_selected_identities`
    / `evidence_output_hash`)? Presence-only, not a structured extraction -
    consistent with the acceptance rule's "also measured, since near-free"
    framing; a full per-tool-call audit is out of scope for this pilot."""
    path = Path(run_dir) / "events.jsonl"
    if not path.exists():
        return False
    text = path.read_text(errors="ignore")
    return "retrieval_selected_identities" in text or "evidence_output_hash" in text


def _degeneration_failure_rate(traj: pd.DataFrame) -> float:
    """Same definition used throughout this project (phase2b_analyze.py,
    phase2b_verify.py, track_c_preflight.py): failure_class starting with
    `model_context_overflow` or `budget_terminated`."""
    fc = traj["failure_class"].fillna("").astype(str)
    return float(fc.str.startswith(("model_context_overflow", "budget_terminated")).mean())


def _budget_stats(run_dir: str) -> dict:
    """`collect_run_records` only flattens `trajectory_stats`; `budget_stats`
    (peak_input_tokens, runaway_generations, hard_budget_hits - the D-34
    degeneration fields) lives in the same metadata.json under a separate
    key and is read directly here, once per run, for both completed and
    FAILED trajectories (both write a full metadata.json)."""
    meta_path = Path(run_dir) / "metadata.json"
    if not meta_path.exists():
        return {}
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return meta.get("budget_stats") or {}


def analyze_arm2(
    candidates: list[dict], config_path: Path, evaluator: OfficialEvaluator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (per-trajectory frame, per-instance majority-resolved frame)."""
    cfg = load_config(config_path)
    specs = _arm2_specs(candidates, cfg)
    traj = collect_run_records(specs)
    traj = attach_rewards(traj, evaluator, cfg.analysis.binary_reward_threshold)

    budget = traj["run_dir"].map(_budget_stats)
    traj = traj.assign(
        peak_input_tokens=budget.map(lambda d: d.get("peak_input_tokens")),
        runaway_generations=budget.map(lambda d: d.get("runaway_generations")),
        hard_budget_hits=budget.map(lambda d: d.get("hard_budget_hits")),
    )

    by_instance = {(r["task_name"], int(r["task_instance_id"])): r for r in candidates}
    rows = []
    for (task_name, tid), g in traj.groupby(["task_name", "task_instance_id"]):
        cand = by_instance[(task_name, int(tid))]
        g = g.sort_values("trajectory_index")
        completed = g["completed"].fillna(False)
        records = g.to_dict("records")
        picks = [
            (row["answer_canonical"] if bool(done) else None) for done, row in zip(completed, records, strict=True)
        ]
        n_off_menu = sum(
            1
            for done, row in zip(completed, records, strict=True)
            if bool(done) and row.get("answer_canonical") not in cand["candidates"]
        )
        answer, status = _majority([p if p in cand["candidates"] else None for p in picks])
        res = evaluator.evaluate(task_name, int(tid), answer, answer)
        rows.append(
            {
                "pool": cand["pool"],
                "task_name": task_name,
                "task_instance_id": int(tid),
                "n_candidates": len(cand["candidates"]),
                "n_complete": int(completed.sum()),
                "picks": picks,
                "majority_answer": answer,
                "majority_status": status,
                "n_off_menu": n_off_menu,
                "reward": res.reward,
                "peak_input_tokens_max": g["peak_input_tokens"].max(),
                "any_runaway": bool((g["runaway_generations"].fillna(0) > 0).any()),
                "any_hard_budget_hit": bool((g["hard_budget_hits"].fillna(0) > 0).any()),
            }
        )
    return traj, pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------


def verdict_for(merged: pd.DataFrame, arm_reward_col: str, label: str) -> dict:
    diff = paired_bootstrap_difference(
        merged[arm_reward_col].to_numpy(dtype=float),
        merged["plurality_reward"].to_numpy(dtype=float),
        replicates=BOOTSTRAP_REPLICATES,
        seed=BOOTSTRAP_SEED,
    )
    if diff["ci_lo"] is not None and diff["ci_lo"] > 0:
        v = "GO"
    elif diff["ci_hi"] is not None and diff["ci_hi"] < FROZEN_GAP_THIRD:
        v = "NO-GO"
    else:
        v = "INCONCLUSIVE"
    return {"label": label, "n": len(merged), **diff, "verdict": v}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--arm1", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True, help="Arm-2 throwaway config (to rebuild RunSpecs)")
    ap.add_argument(
        "--preflight-root",
        type=Path,
        default=Path("/scratch/11034/atzanakak/biomni_unc_runs/track_c_preflight/results"),
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    candidates = [json.loads(x) for x in args.candidates.read_text().splitlines() if x.strip()]
    floor_ceiling = load_floor_ceiling(args.preflight_root)
    evaluator = load_ground_truth()

    arm1 = analyze_arm1(args.arm1, evaluator)
    arm1 = arm1.merge(floor_ceiling, on=["pool", "task_name", "task_instance_id"], how="left")
    arm1.to_csv(args.out / "arm1_per_instance.csv", index=False)

    traj2, arm2 = analyze_arm2(candidates, args.config, evaluator)
    arm2 = arm2.merge(floor_ceiling, on=["pool", "task_name", "task_instance_id"], how="left")
    traj2.to_csv(args.out / "arm2_per_trajectory.csv", index=False)
    arm2.to_csv(args.out / "arm2_per_instance.csv", index=False)

    n_expected = len(candidates) * N_SAMPLES_PER_ARM
    # Completeness means "dispatch has attempted every planned trajectory and
    # each has a terminal marker" (run_present), NOT "every trajectory
    # succeeded" (completed) - a real Arm-2 run has a nonzero failure rate by
    # this project's own prior findings (context-overflow degeneration), and
    # those failures are legitimate terminal outcomes the majority-resolution
    # rule already accounts for (a missing sample just can't contribute to a
    # 2-of-3 majority), not runs still in flight.
    n_attempted_traj = int(traj2["run_present"].fillna(False).sum())
    n_succeeded_traj = int(traj2["completed"].fillna(False).sum())
    arm2_complete = n_attempted_traj >= n_expected

    report = {
        "n_instances": len(candidates),
        "arm2_trajectories_attempted": n_attempted_traj,
        "arm2_trajectories_succeeded": n_succeeded_traj,
        "arm2_trajectories_expected": n_expected,
        "arm2_status": "COMPLETE" if arm2_complete else "INCOMPLETE",
        "arm2_failure_class_counts": traj2["failure_class"].fillna("none").value_counts().to_dict()
        if "failure_class" in traj2
        else {},
        "arm2_degeneration_failure_rate": _degeneration_failure_rate(traj2),
        "arm2_retrieval_provenance_coverage": float(traj2["run_dir"].map(_retrieval_provenance_present).mean()),
        "arm1_descriptive": {
            "mean_reward": float(arm1["reward"].mean()),
            "mean_plurality_floor": float(arm1["plurality_reward"].mean()),
            "delta_vs_floor": verdict_for(arm1, "reward", "arm1_pooled"),
            "n_no_majority": int((arm1["majority_status"] == "no_majority").sum()),
            "n_all_missing": int((arm1["majority_status"] == "all_missing").sum()),
            "unresolved_rate": float((arm1["n_unresolved"] > 0).mean()),
        },
        "arm2_descriptive": {
            "mean_reward": float(arm2["reward"].mean()),
            "mean_plurality_floor": float(arm2["plurality_reward"].mean()),
            "n_no_majority": int((arm2["majority_status"] == "no_majority").sum()),
            "n_all_missing": int((arm2["majority_status"] == "all_missing").sum()),
            "off_menu_rate": float((arm2["n_off_menu"] > 0).mean()),
            "any_runaway_rate": float(arm2["any_runaway"].mean()),
            "any_hard_budget_hit_rate": float(arm2["any_hard_budget_hit"].mean()),
        },
    }

    if arm2_complete:
        report["arm2_verdict"] = verdict_for(arm2, "reward", "arm2_pooled_PRIMARY")
        for family, tasks in (
            ("evidence_retrievable", EVIDENCE_RETRIEVABLE_TASKS),
            ("domain_judgment", DOMAIN_JUDGMENT_TASKS),
        ):
            sub = arm2[arm2["task_name"].isin(tasks)]
            if len(sub):
                report[f"arm2_verdict_{family}"] = verdict_for(sub, "reward", f"arm2_{family}_secondary")
        for pool in ("phase2b", "phase1_pooled"):
            sub = arm2[arm2["pool"] == pool]
            if len(sub):
                report[f"arm2_verdict_{pool}"] = verdict_for(sub, "reward", f"arm2_{pool}_secondary")
    else:
        report["arm2_verdict"] = None
        report["note"] = (
            f"Arm 2 incomplete ({n_attempted_traj}/{n_expected} trajectories attempted) - "
            "NO VERDICT COMPUTED. Descriptive numbers above are not final."
        )

    (args.out / "track_c_step2_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
