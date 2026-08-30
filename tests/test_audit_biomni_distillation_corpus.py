"""Sanity checks for scripts/audit_biomni_distillation_corpus.py.

Runs the real script against the real committed manifests (not fixtures) -
this is a read-only inventory/provenance script, so exercising it against
the actual repository state is the point: the check that matters is "does
scope_main really have zero overlap with the training pool," not a mock.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "audit_biomni_distillation_corpus.py"


def _run(tmp_path: Path) -> dict:
    out_dir = tmp_path / "audit_out"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(REPO_ROOT), "--output-dir", str(out_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    summary = json.loads(result.stdout.split("\n\n")[0])
    return summary, out_dir


def test_held_out_set_has_zero_overlap_with_training_pool(tmp_path):
    summary, _ = _run(tmp_path)
    assert summary["held_out_120_overlap_with_training_pool"] == 0
    assert summary["contamination_pairs_found"] == 0
    assert summary["contamination_detail"] == []


def test_scope_main_is_exactly_120_instances(tmp_path):
    summary, out_dir = _run(tmp_path)
    import csv

    with (out_dir / "phase2_split_provenance.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    held_out_rows = [r for r in rows if r["source_manifest"] == "manifests/scope_main.jsonl"]
    assert len(held_out_rows) == 120
    assert all(r["split"] == "held-out evaluation" for r in held_out_rows)
    assert all(r["training_eligible"] == "no" for r in held_out_rows)


def test_ablation_is_a_subset_of_phase1_not_a_fresh_pool(tmp_path):
    """Confirms the finding in the audit report: ablation.jsonl's 24
    instances are a stratified re-draw of phase1's own 50, not new tasks -
    load-bearing for excluding ablation from the clean training corpus.
    """
    _, out_dir = _run(tmp_path)
    import csv

    with (out_dir / "phase2_manifest_overlaps.csv").open() as fh:
        rows = {(r["manifest_a"], r["manifest_b"]): r for r in csv.DictReader(fh)}
    row = rows[("manifests/phase1.jsonl", "manifests/ablation.jsonl")]
    assert int(row["overlap_by_task_key"]) == 24
    assert row["key_gid_agree"] == "True"


def test_inventory_flags_every_manifest_as_locally_inaccessible_for_raw_data(tmp_path):
    """Documents the environment finding: on this host, no manifest's raw
    per-trajectory run trees are present except the 8 stub phase2b examples,
    which this script does not count as usable (agent_start-only, see
    report SS5). If this ever flips to True it means the data lake became
    reachable and Phase 3-6 should be re-run for real.
    """
    _, out_dir = _run(tmp_path)
    import csv

    with (out_dir / "phase1_artifact_inventory.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    phase1_row = next(r for r in rows if r["artifact"] == "manifests/phase1.jsonl")
    assert phase1_row["locally_computable_without_remote_data"] == "False"
