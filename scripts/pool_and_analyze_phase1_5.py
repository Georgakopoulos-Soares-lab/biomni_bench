#!/usr/bin/env python
"""Pool the 42 rescued phase1_5 trajectories into the Phase-1 K=4 set and
re-run the frozen Phase-1 analysis on the union.

This does NOT edit `phase1` (frozen, never re-run - see CLAUDE.md). It builds a
new spec list: 250 entries total, identical to Phase 1's, except that each of
the 62 originally-failed (task, instance, condition, trajectory_index) slots
whose phase1_5 replacement completed successfully has its `run_dir` swapped to
point at the phase1_5 run instead of the original failed phase1 run. The 20
still-failed slots keep pointing at the original (failed) phase1 run - nothing
to gain by pointing at another failure.

Because `aggregation.collect_run_records` only ever reads `spec.run_dir`, this
reuses the exact tested pipeline (attach_rewards, compute_consistency,
add_behavioral_features, every analysis.* function) with zero new logic for
the statistics themselves - only the input spec list changes.

    python scripts/pool_and_analyze_phase1_5.py \
        --phase1-run-manifest manifests/phase1_runs.jsonl \
        --phase1-5-run-manifest manifests/phase1_5_runs.jsonl \
        --original-map manifests/phase1_5_runs.original_map.json \
        --config configs/phase1.yaml \
        --ground-truth manifests/phase1.groundtruth.jsonl \
        --output-experiment phase1_pooled
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from biomni_uncertainty import analysis as A  # noqa: E402
from biomni_uncertainty import plotting as P  # noqa: E402
from biomni_uncertainty.aggregation import build_tables, status_summary, write_tables  # noqa: E402
from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.evaluation import OfficialEvaluator  # noqa: E402
from biomni_uncertainty.provenance import write_json_atomic  # noqa: E402
from biomni_uncertainty.sampling import RunSpec, is_valid_complete, read_run_manifest, write_run_manifest  # noqa: E402


def key_of(d: dict) -> tuple:
    return (d["task_name"], d["task_instance_id"], d["condition"], d["trajectory_index"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase1-run-manifest", required=True, type=Path)
    ap.add_argument("--phase1-5-run-manifest", required=True, type=Path)
    ap.add_argument("--original-map", required=True, type=Path)
    ap.add_argument("--config", required=True, type=Path, help="cfg.analysis.binary_reward_threshold source")
    ap.add_argument("--ground-truth", required=True, type=Path)
    ap.add_argument("--output-experiment", default="phase1_pooled")
    ap.add_argument("--pooled-manifest-out", type=Path, default=Path("manifests/phase1_pooled_runs.jsonl"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    evaluator = OfficialEvaluator.from_groundtruth_file(args.ground_truth)

    phase1_specs = read_run_manifest(args.phase1_run_manifest)
    phase1_5_specs = read_run_manifest(args.phase1_5_run_manifest)
    original_map: dict[str, str] = json.loads(args.original_map.read_text())
    original_ids = set(original_map.values())

    pooled: dict[tuple, RunSpec] = {key_of(s.to_dict()): s for s in phase1_specs}
    assert len(pooled) == 250, f"expected 250 phase1 slots, got {len(pooled)}"

    rescued, still_failed, unresolved = [], [], []
    for spec in phase1_5_specs:
        d = spec.to_dict()
        k = key_of(d)
        if k not in pooled:
            unresolved.append(spec.run_id)
            continue
        if is_valid_complete(spec.run_dir):
            pooled[k] = spec
            rescued.append(spec.run_id)
        else:
            still_failed.append(spec.run_id)

    print(f"phase1 baseline slots       : {len(phase1_specs)}")
    print(f"phase1_5 attempts           : {len(phase1_5_specs)}")
    print(f"  rescued (swapped in)      : {len(rescued)}")
    print(f"  still failed (kept orig.) : {len(still_failed)}")
    if unresolved:
        print(f"  WARNING unresolved keys   : {len(unresolved)} -> {unresolved}")
    assert len(rescued) + len(still_failed) + len(unresolved) == len(original_ids) == 62

    pooled_specs = sorted(
        pooled.values(), key=lambda s: (s.task_name, s.task_instance_id, s.condition, s.trajectory_index)
    )
    write_run_manifest(pooled_specs, args.pooled_manifest_out)
    print(f"\nwrote {args.pooled_manifest_out} ({len(pooled_specs)} specs)")

    # ---- run the frozen pipeline on the pooled spec list -------------------
    tables = build_tables(pooled_specs, cfg, evaluator)
    out_dir = Path(cfg.experiment.output_root) / args.output_experiment / "results"
    write_tables(tables, out_dir / "tables")
    summary = status_summary(tables["trajectories"])
    write_json_atomic(out_dir / "status_summary.json", summary)
    print("\n" + json.dumps(summary, indent=2, default=str))

    inst = tables["instrumented"]
    instances = tables["instances"]
    rep = cfg.analysis.bootstrap_replicates
    seed = cfg.analysis.bootstrap_seed
    lf = cfg.analysis.primary_length_field

    results = {
        "experiment_id": args.output_experiment,
        "status": summary,
        "trajectories": tables["trajectories"],
        "instrumented": inst,
        "availability": tables["availability"],
    }
    if len(inst):
        results["oracle_at_k"] = A.oracle_at_k(inst, 4)
        results["candidate_generation"] = A.candidate_generation_report(inst, instances)
        results["selectors"] = A.evaluate_selectors(
            inst, length_field=lf, epsilon=cfg.analysis.srlm_epsilon, replicates=rep, seed=seed
        )
        results["calibration"] = A.confidence_calibration(
            inst, n_bins=cfg.analysis.calibration_bins, replicates=rep, seed=seed
        )
        results["signal_auroc"] = A.signal_auroc_table(inst, replicates=rep, seed=seed)
    if len(inst) and len(tables["standard"]):
        results["perturbation"] = A.prompt_perturbation(inst, tables["standard"], replicates=rep, seed=seed)

    figs = P.generate_all(results, out_dir, length_field=lf)
    results["figures"] = figs

    tdir = out_dir / "tables"
    for key in ("oracle_at_k", "signal_auroc", "availability"):
        v = results.get(key)
        if isinstance(v, pd.DataFrame) and len(v):
            v.to_csv(tdir / f"{key}.csv", index=False)
    for key in ("selectors", "candidate_generation"):
        block = results.get(key) or {}
        for name, v in block.items():
            if isinstance(v, pd.DataFrame) and len(v):
                v.to_csv(tdir / f"{key}__{name}.csv", index=False)
    calib = results.get("calibration") or {}
    for name, v in calib.items():
        if isinstance(v, pd.DataFrame) and len(v):
            v.to_csv(tdir / f"calibration__{name}.csv", index=False)

    def jsonify(o):
        import numpy as np

        if isinstance(o, pd.DataFrame):
            return o.to_dict(orient="records")
        if isinstance(o, dict):
            return {k: jsonify(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [jsonify(v) for v in o]
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        return o

    write_json_atomic(out_dir / "analysis.json", jsonify(results))

    print("\n" + "=" * 78)
    print("POOLED HEADLINE (Phase 1 -> Phase 1 pooled with 42 repaired trajectories)")
    print("=" * 78)
    sel = results["selectors"]["summary"].set_index("selector")
    cg = results["candidate_generation"]["summary"]
    cal = results["calibration"]
    print(f"n instrumented trajectories : 188 -> {len(inst)}")
    print(f"n instances with >=1 answer : -> {cg['n_instances']}")
    print(f"first-trajectory reward     : 0.420 -> {sel.loc['first', 'point']:.3f}")
    print(f"plurality reward            : 0.580 -> {sel.loc['plurality', 'point']:.3f}")
    print(f"oracle@4 reward             : 0.620 -> {sel.loc['oracle', 'point']:.3f}")
    print(f"oracle headroom (pp)        : 20.0 -> {cg['oracle_headroom_pp']:.1f}")
    print(f"confidence AUROC            : 0.789 -> {cal.get('auroc')}")
    sig = results["signal_auroc"]
    agree_row = sig[sig["signal"] == "agreement_fraction"]
    if len(agree_row):
        print(f"agreement_fraction AUROC    : 0.874 -> {agree_row.iloc[0]['auroc']}")
    print(f"\nfull results: {out_dir / 'analysis.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
