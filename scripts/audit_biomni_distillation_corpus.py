#!/usr/bin/env python3
"""Phase 1+2 audit for the Biomni trajectory-ensemble distillation pilot.

Answers two questions from committed, on-disk artifacts only:

1. What Biomni-relevant manifests/run trees exist, and which of them are
   locally accessible (raw run directories, aggregated per-trajectory
   tables) from *this* host right now?
2. For every unique (task_name, task_instance_id) instance referenced by any
   manifest, which experiment(s) it appears in, and whether any instance in
   the frozen 120-task held-out set (manifests/scope_main.jsonl) or the
   150-task prospective set (manifests/phase2b.jsonl) also appears in a
   candidate training manifest.

Deliberately stdlib-only (json/csv/pathlib/argparse) so it runs under the
bare system Python (no pandas/pytest), before anyone has run
`module load gcc/14.2.0 python3/3.11.8` to unlock the project's own .venv
(see the audit report, "Environment" section, for why that module load is
required on Vista and was previously undocumented) - Phase 1/2 should not
depend on that step succeeding.

Never reads or writes anything under runs/ except to check existence -
this phase must not touch scientific data (prompt's own Phase 1 rule).

    python scripts/audit_biomni_distillation_corpus.py \
        --repo-root . \
        --output-dir reports/tables/biomni_distillation_audit
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Every task-definition manifest known to exist at audit time (Phase 1 says
# "do not assume filenames" - this list was built by listing manifests/ and
# reading each file's own provenance report, not guessed from naming
# convention). global_instance_id is BiomniEval1's own stable identifier
# for an instance and is authoritative for overlap detection; (task_name,
# task_instance_id) is checked in parallel as an independent cross-check,
# per the prompt's "do not simply assume" instruction.
MANIFEST_SPECS: list[dict[str, Any]] = [
    {
        "manifest": "manifests/phase1.jsonl",
        "experiment": "phase1",
        "solver": "biomni/Biomni-R0-32B-Preview",
        "K": 4,  # instrumented condition; phase1_runs.jsonl also has a K=1 "standard" condition per instance
        "role_claim": "training-eligible (candidate)",
        "role_evidence": "scope_study_preflight.md SS2.3: scope_main's never-used pool is the complement of phase1 (among others); disjoint by construction and audit.",
    },
    {
        "manifest": "manifests/phase2b.jsonl",
        "experiment": "phase2b",
        "solver": "biomni/Biomni-R0-32B-Preview",
        "K": 4,
        "role_claim": "training-eligible (candidate), but CLAUDE.md marks the phase2b run tree/manifest/report FROZEN (do-not-edit, not do-not-read)",
        "role_evidence": "rl_harness_preregistration.md SS A.7: training pool = phase1.jsonl UNION phase2b.jsonl (200), verified disjoint from scope_main.jsonl by scripts/rl_harness_split_audit.py.",
    },
    {
        "manifest": "manifests/phase2b_smoke.jsonl",
        "experiment": "phase2b_smoke",
        "solver": "biomni/Biomni-R0-32B-Preview",
        "K": "unknown (smoke test, not a K=4 protocol run)",
        "role_claim": "NOT training-eligible - launch smoke test, not a scientific sample",
        "role_evidence": "scope_study_preflight.md SS2.2: 'phase2b_smoke (launch smoke test), n=5' consumed instances counted separately from the reserved pool.",
    },
    {
        "manifest": "manifests/ablation.jsonl",
        "experiment": "ablation (abl_arm1/2/3)",
        "solver": "biomni/Biomni-R0-32B-Preview",
        "K": "4, but under THREE non-frozen-protocol configs (different max_tokens/bounding per arm), not phase1's frozen config",
        "role_claim": "NOT training-eligible as-is - same task instances as a phase1 subset, re-run under diagnostic (off-protocol) generation configs",
        "role_evidence": "manifests/ablation.strata.json: every instance carries phase1_failed_runs/phase1_runs_with_runaway fields, i.e. this manifest IS a stratified subset of phase1's own instances, not a fresh draw; configs/ablation_arm*.yaml vary max_tokens/bounding from configs/phase1.yaml.",
    },
    {
        "manifest": "manifests/scope_gate.jsonl",
        "experiment": "scope_gate (scope_gate_b1)",
        "solver": "mistralai/Mistral-Small-3.1-24B-Instruct-2503 (Solver B, NOT Biomni-R0)",
        "K": "unknown (capability-gate scaffold check)",
        "role_claim": "NOT relevant to Biomni distillation - different solver entirely, and reuses already-consumed instances by design",
        "role_evidence": "scope_study_preflight.md: 'a Solver-B scaffold/capability gate run on already-consumed historical questions. Zero fresh scope-study instances are consumed.'",
    },
    {
        "manifest": "manifests/scope_main.jsonl",
        "experiment": "scope_main (Arm A = Biomni-R0, Arm B = Mistral)",
        "solver": "biomni/Biomni-R0-32B-Preview (Arm A) + Mistral (Arm B)",
        "K": 4,
        "role_claim": "HELD-OUT - the canonical 120-task set referenced by prompts/before_distil.md. MUST NOT enter training.",
        "role_evidence": "scope_study_preregistration.md SS2: drawn from the 'never-used' complement of every manifest on disk at freeze time (fbd73a3); rl_harness_preregistration.md SS A.7 independently re-verifies 0 overlap with the 200-instance training pool via scripts/rl_harness_split_audit.py.",
    },
    {
        "manifest": "manifests/smoke.jsonl",
        "experiment": "smoke",
        "solver": "biomni/Biomni-R0-32B-Preview",
        "K": "small smoke K",
        "role_claim": "NOT training-eligible - infrastructure smoke test",
        "role_evidence": "configs/smoke.yaml; 2 instances only.",
    },
]

HELD_OUT_MANIFESTS = {"manifests/scope_main.jsonl"}
CANDIDATE_TRAINING_MANIFESTS = {"manifests/phase1.jsonl", "manifests/phase2b.jsonl"}


def load_instances(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def instance_key(row: dict[str, Any]) -> tuple[str, int]:
    return (row["task_name"], int(row["task_instance_id"]))


def check_local_data_access(repo_root: Path, experiment: str) -> dict[str, Any]:
    """Never assumes; checks the actual filesystem for what's present."""
    runs_dir = repo_root / "runs" / experiment
    result = {
        "runs_dir_exists": runs_dir.exists(),
        "raw_trajectory_dirs_found": 0,
        "aggregated_tables_found": [],
    }
    if runs_dir.exists():
        raw = list(runs_dir.glob("runs/*/i*/*/t*"))
        result["raw_trajectory_dirs_found"] = len(raw)
        tables_dir = runs_dir / "results" / "tables"
        if tables_dir.exists():
            result["aggregated_tables_found"] = sorted(p.name for p in tables_dir.glob("*.csv"))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--output-dir", type=Path, default=Path("reports/tables/biomni_distillation_audit"))
    args = ap.parse_args()

    repo_root = args.repo_root.resolve()
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Phase 1: inventory + local data accessibility -----------------
    inventory_rows = []
    per_manifest_keys: dict[str, set[tuple[str, int]]] = {}
    per_manifest_global_ids: dict[str, set[int]] = {}
    per_manifest_rows: dict[str, list[dict[str, Any]]] = {}

    for spec in MANIFEST_SPECS:
        mpath = repo_root / spec["manifest"]
        if not mpath.exists():
            print(f"WARNING: {spec['manifest']} not found, skipping", file=sys.stderr)
            continue
        rows = load_instances(mpath)
        per_manifest_rows[spec["manifest"]] = rows
        keys = {instance_key(r) for r in rows}
        gids = {int(r["global_instance_id"]) for r in rows}
        per_manifest_keys[spec["manifest"]] = keys
        per_manifest_global_ids[spec["manifest"]] = gids

        access = check_local_data_access(repo_root, spec["experiment"].split(" ")[0])
        task_families = sorted({k[0] for k in keys})

        inventory_rows.append(
            {
                "artifact": spec["manifest"],
                "experiment": spec["experiment"],
                "solver": spec["solver"],
                "n_task_instances": len(rows),
                "n_task_families": len(task_families),
                "task_families": ";".join(task_families),
                "K_declared": spec["K"],
                "role_claim": spec["role_claim"],
                "role_evidence": spec["role_evidence"],
                "raw_run_dirs_locally_present": access["raw_trajectory_dirs_found"],
                "aggregated_tables_locally_present": ";".join(access["aggregated_tables_found"]) or "none",
                "locally_computable_without_remote_data": bool(
                    access["raw_trajectory_dirs_found"] or access["aggregated_tables_found"]
                ),
            }
        )

    with (out_dir / "phase1_artifact_inventory.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(inventory_rows[0].keys()))
        w.writeheader()
        w.writerows(inventory_rows)

    # ---- Phase 2: independent overlap verification ----------------------
    manifest_names = list(per_manifest_keys.keys())
    overlap_rows = []
    contamination_found = []
    for i, a in enumerate(manifest_names):
        for b in manifest_names[i + 1 :]:
            key_overlap = per_manifest_keys[a] & per_manifest_keys[b]
            gid_overlap = per_manifest_global_ids[a] & per_manifest_global_ids[b]
            if key_overlap or gid_overlap:
                is_train_holdout_pair = (a in HELD_OUT_MANIFESTS and b in CANDIDATE_TRAINING_MANIFESTS) or (
                    b in HELD_OUT_MANIFESTS and a in CANDIDATE_TRAINING_MANIFESTS
                )
                row = {
                    "manifest_a": a,
                    "manifest_b": b,
                    "overlap_by_task_key": len(key_overlap),
                    "overlap_by_global_instance_id": len(gid_overlap),
                    "key_gid_agree": key_overlap
                    == {
                        (r["task_name"], int(r["task_instance_id"]))
                        for r in per_manifest_rows[a]
                        if int(r["global_instance_id"]) in gid_overlap
                    },
                    "involves_held_out_vs_training_pool": is_train_holdout_pair,
                }
                overlap_rows.append(row)
                if is_train_holdout_pair and (key_overlap or gid_overlap):
                    contamination_found.append(row)

    with (out_dir / "phase2_manifest_overlaps.csv").open("w", newline="") as fh:
        fieldnames = [
            "manifest_a",
            "manifest_b",
            "overlap_by_task_key",
            "overlap_by_global_instance_id",
            "key_gid_agree",
            "involves_held_out_vs_training_pool",
        ]
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(overlap_rows)

    # ---- Phase 2 split table (task-level) -------------------------------
    split_table = []
    task_to_experiments: dict[tuple[str, int], list[str]] = defaultdict(list)
    for spec in MANIFEST_SPECS:
        mname = spec["manifest"]
        if mname not in per_manifest_rows:
            continue
        for r in per_manifest_rows[mname]:
            task_to_experiments[instance_key(r)].append(spec["experiment"])

    for spec in MANIFEST_SPECS:
        mname = spec["manifest"]
        if mname not in per_manifest_rows:
            continue
        if mname in HELD_OUT_MANIFESTS:
            split_label = "held-out evaluation"
        elif mname in CANDIDATE_TRAINING_MANIFESTS:
            split_label = "training / development (candidate)"
        else:
            split_label = "other (diagnostic / capability-gate / smoke) - excluded"
        for r in per_manifest_rows[mname]:
            key = instance_key(r)
            experiments = task_to_experiments[key]
            training_eligible = (
                "yes"
                if (
                    split_label == "training / development (candidate)"
                    and not any(e == "scope_main (Arm A = Biomni-R0, Arm B = Mistral)" for e in experiments)
                )
                else ("no" if split_label == "held-out evaluation" else "excluded (not training pool)")
            )
            split_table.append(
                {
                    "task_id": f"{key[0]}/{key[1]}",
                    "global_instance_id": r["global_instance_id"],
                    "source_manifest": mname,
                    "split": split_label,
                    "experiments_containing_this_instance": ";".join(sorted(set(experiments))),
                    "training_eligible": training_eligible,
                }
            )

    with (out_dir / "phase2_split_provenance.csv").open("w", newline="") as fh:
        fieldnames = [
            "task_id",
            "global_instance_id",
            "source_manifest",
            "split",
            "experiments_containing_this_instance",
            "training_eligible",
        ]
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(split_table)

    # ---- Summary ----------------------------------------------------------
    summary = {
        "manifests_audited": len(per_manifest_rows),
        "total_unique_task_instances_across_all_manifests": len(
            set().union(*per_manifest_keys.values()) if per_manifest_keys else set()
        ),
        "held_out_120_overlap_with_training_pool": (
            per_manifest_keys.get("manifests/scope_main.jsonl", set())
            & (
                per_manifest_keys.get("manifests/phase1.jsonl", set())
                | per_manifest_keys.get("manifests/phase2b.jsonl", set())
            )
        ).__len__(),
        "contamination_pairs_found": len(contamination_found),
        "contamination_detail": contamination_found,
    }
    with (out_dir / "phase2_contamination_summary.json").open("w") as fh:
        json.dump(summary, fh, indent=2, default=list)

    print(json.dumps(summary, indent=2, default=list))
    print(f"\nWrote: {out_dir}/phase1_artifact_inventory.csv")
    print(f"Wrote: {out_dir}/phase2_manifest_overlaps.csv")
    print(f"Wrote: {out_dir}/phase2_split_provenance.csv")
    print(f"Wrote: {out_dir}/phase2_contamination_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
