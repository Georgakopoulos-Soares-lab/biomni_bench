"""Pin the matched scope study's frozen population and constants.

The manifest here is the only artifact in the project that spends fresh
benchmark instances, and it is spent once. These tests exist so that a later
edit to the manifest, the arm configs or the pre-registered bars fails loudly
instead of quietly invalidating 960 trajectories.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "reports" / "scope_study_preregistration.md"
MANIFEST = ROOT / "manifests" / "scope_main.jsonl"
GROUND_TRUTH = ROOT / "manifests" / "scope_main.groundtruth.jsonl"
REPORT = ROOT / "manifests" / "scope_main.report.json"
POOL_AUDIT = ROOT / "reports" / "tables" / "scope_study" / "pool_audit.json"

FROZEN_MANIFEST_HASH = "89bf418928b4846f93cdaf7e3d009cffd8e0c514586fda05effd473353441457"

ELIGIBLE_TASKS = {
    "gwas_causal_gene_gwas_catalog",
    "gwas_causal_gene_opentargets",
    "gwas_causal_gene_pharmaprojects",
    "gwas_variant_prioritization",
    "lab_bench_dbqa",
    "lab_bench_seqqa",
    "patient_gene_detection",
    "screen_gene_retrieval",
}


def _entries(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


# --------------------------------------------------------------------------
# population
# --------------------------------------------------------------------------


def test_manifest_hash_is_the_frozen_one():
    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == FROZEN_MANIFEST_HASH
    assert FROZEN_MANIFEST_HASH in PREREG.read_text()
    assert json.loads(REPORT.read_text())["manifest_hash"] == FROZEN_MANIFEST_HASH


def test_manifest_is_120_instances_15_per_eligible_family():
    e = _entries(MANIFEST)
    assert len(e) == 120
    counts: dict[str, int] = {}
    for o in e:
        counts[o["task_name"]] = counts.get(o["task_name"], 0) + 1
    assert set(counts) == ELIGIBLE_TASKS
    assert set(counts.values()) == {15}


def test_every_instance_was_never_used_before_this_study():
    """The load-bearing guard: fresh instances are spent exactly once."""
    never_used = {t: set(v) for t, v in json.loads(POOL_AUDIT.read_text())["never_used_ids"].items()}
    for o in _entries(MANIFEST):
        assert o["task_instance_id"] in never_used.get(o["task_name"], set()), o


def test_no_overlap_with_any_other_manifest():
    mine = {(o["task_name"], o["task_instance_id"]) for o in _entries(MANIFEST)}
    for mf in sorted((ROOT / "manifests").glob("*.jsonl")):
        if mf.name in {"scope_main.jsonl"} or mf.name.endswith(".groundtruth.jsonl") or "_runs" in mf.name:
            continue
        other = {(o["task_name"], o["task_instance_id"]) for o in _entries(mf)}
        assert not (mine & other), f"overlap with {mf.name}: {sorted(mine & other)[:5]}"


def test_ground_truth_is_separate_and_the_manifest_carries_no_answers():
    for o in _entries(MANIFEST):
        assert "answer" not in o
    gt = _entries(GROUND_TRUTH)
    assert len(gt) == 120
    assert all("answer" in o for o in gt)


def test_one_hundred_instances_remain_after_this_study():
    r = json.loads(REPORT.read_text())
    assert r["never_used_remaining_total"] == 100
    assert r["seed"] == 20260813


# --------------------------------------------------------------------------
# the two arms differ only where they must
# --------------------------------------------------------------------------


def _cfg(name: str) -> dict:
    return yaml.safe_load((ROOT / "configs" / name).read_text())


def test_arms_are_identical_except_model_identity_and_serving_override():
    a, b = _cfg("scope_main_a.yaml"), _cfg("scope_main_b.yaml")
    assert a["experiment"]["name"] == "scope_main_a"
    assert b["experiment"]["name"] == "scope_main_b"
    for section in ("confidence", "trajectories", "execution", "logging", "analysis"):
        assert a[section] == b[section], section
    assert a["benchmark"] == b["benchmark"]
    differing = {k for k in a["model"] if a["model"][k] != b["model"][k]}
    assert differing == {"identifier", "revision", "json_model_override_args"}, differing


def test_both_arms_run_k4_instrumented_only():
    for name in ("scope_main_a.yaml", "scope_main_b.yaml"):
        t = _cfg(name)["trajectories"]
        assert t["instrumented_k"] == 4
        assert t["standard_k"] == 0


def test_both_arms_serve_the_same_context_length():
    """The override differs *so that* the served context matches."""
    a, b = _cfg("scope_main_a.yaml"), _cfg("scope_main_b.yaml")
    assert a["model"]["context_length"] == b["model"]["context_length"] == 65536


def test_arm_a_override_sets_a_top_level_max_position_embeddings():
    """D-43 lost a server start to a nested max_position_embeddings."""
    ov = json.loads(_cfg("scope_main_a.yaml")["model"]["json_model_override_args"])
    assert "max_position_embeddings" in ov
    assert "max_position_embeddings" not in ov.get("rope_scaling", {})
    assert _cfg("scope_main_b.yaml")["model"]["json_model_override_args"] is None


def test_arm_models_are_the_frozen_identities():
    a, b = _cfg("scope_main_a.yaml")["model"], _cfg("scope_main_b.yaml")["model"]
    assert a["identifier"] == "biomni/Biomni-R0-32B-Preview"
    assert a["revision"] == "71432eb3d5e583bee757e0f9437a17e711e8e3d1"
    assert b["identifier"] == "mistralai/Mistral-Small-3.1-24B-Instruct-2503"
    assert b["revision"] == "68faf511d618ef198fef186659617cfd2eb8e33a"


# --------------------------------------------------------------------------
# pre-registered decision constants
# --------------------------------------------------------------------------


def test_prereg_fixes_every_bar_it_needs_to():
    t = PREREG.read_text()
    assert "lower bound > 0.5" in t  # detection bar
    assert "lower bound > 0**" in t  # correction bar
    assert "upper bound < −0.15**" in t  # capability-confound bar
    assert "10,000 replicates, resampling the instance, seed 20260813" in t


def test_prereg_states_the_h1_verdict_table_and_the_stop_semantics():
    t = PREREG.read_text()
    for v in ("REPLICATED", "NOT REPLICATED", "MIXED"):
        assert v in t
    assert "Resuming an interrupted dispatch is infrastructure recovery, not a re-run" in t
    assert "No K>4" in t


def test_prereg_keeps_the_secondaries_secondary():
    t = PREREG.read_text()
    assert "never promoted to co-primary" in t
    assert "fully confounded at both extremes" in t
    assert "MedAgentBench" in t


def test_resume_launcher_refuses_dirty_trees_and_commit_drift():
    s = (ROOT / "scripts" / "scope_main_run.sh").read_text()
    assert "REFUSING: dirty tree" in s
    assert "REFUSING: HEAD moved since launch" in s
    assert "REFUSING: $MANIFEST changed since launch" in s
    assert "--allow-commit-drift" in s
