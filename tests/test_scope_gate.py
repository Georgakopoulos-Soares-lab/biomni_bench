"""Pin the scope study's frozen constants against `reports/scope_study_preflight.md`.

Same discipline `tests/test_track_c_adjudication_analyze.py` applies to D-38's
`gap/3`: a decision constant that lives only in a script can be edited after a
result exists and nobody notices. These tests make that edit fail.

They also assert the two structural properties the gate sample must have -- it
touches no never-used instance, and it is drawn only from already-consumed
Phase-2B instances -- because those are the properties that would be expensive
to discover were false *after* a fresh question had been spent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scope_gate_analyze import (  # noqa: E402
    CONFOUNDED_BARS,
    DEGENERATION_FAILURE_CLASSES,
    FAIL_BARS,
    INFRA_FAILURE_CLASSES,
    INTERPRETATION_RULE,
    SOLVER_A_REFERENCE,
    adjudicate,
)

PREFLIGHT = ROOT / "reports" / "scope_study_preflight.md"
POOL_AUDIT = ROOT / "reports" / "tables" / "scope_study" / "pool_audit.json"
GATE_MANIFEST = ROOT / "manifests" / "scope_gate.jsonl"
GATE_REPORT = ROOT / "manifests" / "scope_gate.report.json"

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

# The frozen tier assignment. Duplicated here on purpose: if someone edits the
# rubric in the report after a result exists, this test is what disagrees.
FROZEN_TIERS = {
    "lab_bench_seqqa": 1,
    "lab_bench_dbqa": 2,
    "gwas_causal_gene_gwas_catalog": 2,
    "gwas_causal_gene_opentargets": 2,
    "gwas_causal_gene_pharmaprojects": 2,
    "gwas_variant_prioritization": 2,
    "patient_gene_detection": 2,
    "screen_gene_retrieval": 3,
}


# --------------------------------------------------------------------------
# decision constants
# --------------------------------------------------------------------------


def test_fail_bars_match_the_preflight_document():
    text = PREFLIGHT.read_text()
    assert FAIL_BARS["completion_rate_lt"] == 0.50
    assert FAIL_BARS["usable_rate_lt"] == 0.40
    assert FAIL_BARS["solution_block_ok_rate_lt"] == 0.50
    assert FAIL_BARS["degeneration_rate_gte"] == 0.40
    assert FAIL_BARS["infra_failure_rate_gte"] == 0.25
    for token in ("< 0.50", "< 0.40", "≥ 0.40", "≥ 0.25"):
        assert token in text


def test_confounded_bars_match_the_preflight_document():
    text = PREFLIGHT.read_text()
    assert CONFOUNDED_BARS["usable_rate_lt"] == 0.65
    assert CONFOUNDED_BARS["degeneration_rate_gte"] == 0.25
    # exactly half of Solver A's matched first-trajectory accuracy
    assert CONFOUNDED_BARS["accuracy_lt"] == pytest.approx(0.5 * SOLVER_A_REFERENCE["accuracy"], abs=1e-4)
    assert CONFOUNDED_BARS["accuracy_lt"] == 0.2708
    assert "< 0.2708" in text
    assert "< 0.65" in text


def test_solver_a_reference_is_the_frozen_first_trajectory_baseline():
    assert SOLVER_A_REFERENCE["n"] == 120
    assert SOLVER_A_REFERENCE["accuracy"] == 0.5417
    assert SOLVER_A_REFERENCE["usable_rate"] == 0.8250
    assert SOLVER_A_REFERENCE["completion_rate"] == 0.8917
    assert "trajectory_index == 0" in SOLVER_A_REFERENCE["population"]


def test_interpretation_rule_is_present_in_both_places():
    assert "normalized headroom recovery" in INTERPRETATION_RULE.lower().replace("does not", "does not")
    assert "capability-confounded" in INTERPRETATION_RULE.lower()
    assert "does not cure" in PREFLIGHT.read_text().lower()


def test_denominator_guard_is_stated_with_both_conditions():
    text = PREFLIGHT.read_text()
    assert "≥ **0.10**" in text  # absolute headroom floor
    assert "at least **5** instances" in text  # headroom count floor
    assert "undefined" in text


# --------------------------------------------------------------------------
# adjudication ordering
# --------------------------------------------------------------------------


def _metrics(**over) -> dict:
    base = {
        "completion_rate": 1.0,
        "usable_rate": 1.0,
        "solution_block_ok_rate": 1.0,
        "degeneration_rate": 0.0,
        "infra_failure_rate": 0.0,
        "accuracy": 0.60,
    }
    base.update(over)
    return base


def test_healthy_candidate_passes():
    verdict, reasons = adjudicate(_metrics())
    assert verdict == "PASS"
    assert reasons == []


@pytest.mark.parametrize(
    "over",
    [
        {"completion_rate": 0.49},
        {"usable_rate": 0.39},
        {"solution_block_ok_rate": 0.49},
        {"degeneration_rate": 0.40},
        {"infra_failure_rate": 0.25},
    ],
)
def test_each_fail_bar_fires_on_its_own(over):
    verdict, reasons = adjudicate(_metrics(**over))
    assert verdict == "FAIL"
    assert reasons


@pytest.mark.parametrize(
    "over",
    [
        {"usable_rate": 0.64},
        {"accuracy": 0.2707},
        {"degeneration_rate": 0.25},
    ],
)
def test_each_confounded_bar_fires_on_its_own(over):
    verdict, reasons = adjudicate(_metrics(**over))
    assert verdict == "CAPABILITY-CONFOUNDED"
    assert reasons


def test_fail_takes_precedence_over_confounded():
    """A candidate tripping both must be FAIL, because only FAIL authorises B2."""
    verdict, _ = adjudicate(_metrics(completion_rate=0.10, usable_rate=0.05, accuracy=0.0))
    assert verdict == "FAIL"


def test_accuracy_alone_never_produces_FAIL():
    """Low accuracy is a capability finding, never a scaffold-incompatibility one.

    This is the guard against reaching B2 for the wrong reason: a solver that
    operates the scaffold perfectly and answers everything wrong is
    CAPABILITY-CONFOUNDED, and the frozen rule does not let a fallback be run.
    """
    verdict, _ = adjudicate(_metrics(accuracy=0.0))
    assert verdict == "CAPABILITY-CONFOUNDED"


def test_bar_boundaries_are_exactly_as_written():
    # strictly-less-than bars do not fire at the bar itself
    assert adjudicate(_metrics(usable_rate=0.65))[0] == "PASS"
    assert adjudicate(_metrics(accuracy=0.2708))[0] == "PASS"
    # greater-or-equal bars do fire at the bar itself
    assert adjudicate(_metrics(degeneration_rate=0.25))[0] == "CAPABILITY-CONFOUNDED"


def test_failure_class_partitions_do_not_overlap():
    assert not set(INFRA_FAILURE_CLASSES) & set(DEGENERATION_FAILURE_CLASSES)


# --------------------------------------------------------------------------
# pool audit and gate-sample structure
# --------------------------------------------------------------------------


def test_pool_audit_confirms_the_two_exhausted_tasks_and_eight_eligible():
    audit = json.loads(POOL_AUDIT.read_text())
    per_task = {r["task_name"]: r for r in audit["per_task"]}
    assert per_task["crispr_delivery"]["never_used"] == 0
    assert per_task["rare_disease_diagnosis"]["never_used"] == 0
    eligible = {t for t, r in per_task.items() if r["eligible_for_scope_study"]}
    assert eligible == ELIGIBLE_TASKS
    assert audit["benchmark_total"] == 433


def test_reserved_pool_is_220_not_the_233_in_the_prose():
    """D-22 and phase2_protocol SS3.1 record 233; 13 more were consumed later."""
    audit = json.loads(POOL_AUDIT.read_text())
    assert audit["never_used_total"] == 220
    assert len(audit["consumed_beyond_phase1_phase2b"]) == 13


def test_design_of_15_per_task_over_8_tasks_is_feasible():
    audit = json.loads(POOL_AUDIT.read_text())
    per_task = {r["task_name"]: r for r in audit["per_task"]}
    for task in ELIGIBLE_TASKS:
        assert per_task[task]["never_used"] >= 15, task


def test_gate_sample_touches_no_never_used_instance():
    audit = json.loads(POOL_AUDIT.read_text())
    never_used = {t: set(v) for t, v in audit["never_used_ids"].items()}
    for line in GATE_MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        assert o["task_instance_id"] not in never_used.get(o["task_name"], set()), o


def test_gate_sample_is_drawn_only_from_consumed_phase2b_instances():
    consumed: dict[str, set[int]] = {}
    for line in (ROOT / "manifests" / "phase2b.jsonl").read_text().splitlines():
        if line.strip():
            o = json.loads(line)
            consumed.setdefault(o["task_name"], set()).add(o["task_instance_id"])
    entries = [json.loads(x) for x in GATE_MANIFEST.read_text().splitlines() if x.strip()]
    assert len(entries) == 24
    for o in entries:
        assert o["task_instance_id"] in consumed[o["task_name"]], o


def test_gate_sample_spans_all_eight_families_evenly():
    entries = [json.loads(x) for x in GATE_MANIFEST.read_text().splitlines() if x.strip()]
    counts: dict[str, int] = {}
    for o in entries:
        counts[o["task_name"]] = counts.get(o["task_name"], 0) + 1
    assert set(counts) == ELIGIBLE_TASKS
    assert set(counts.values()) == {3}


def test_gate_manifest_carries_no_answers():
    """The agent-visible manifest must never contain ground truth."""
    for line in GATE_MANIFEST.read_text().splitlines():
        if line.strip():
            assert "answer" not in json.loads(line)


def test_gate_manifest_hash_is_the_frozen_one():
    report = json.loads(GATE_REPORT.read_text())
    assert report["manifest_hash"] == "dd084f0e81243be40e2cd2f24ffedf76b4eaf608cad3d5f01e3b6eb56286a6d2"
    assert report["never_used_instances_consumed"] == 0
    assert report["seed"] == 20260812
    assert PREFLIGHT.read_text().count(report["manifest_hash"]) == 1


# --------------------------------------------------------------------------
# the frozen verifiability rubric
# --------------------------------------------------------------------------


def test_every_eligible_task_has_exactly_one_tier():
    assert set(FROZEN_TIERS) == ELIGIBLE_TASKS


def test_tier_extremes_are_single_family_and_the_confound_is_flagged():
    """The design cannot separate tier from task identity at either extreme.

    If a future edit ever moves a second family into Tier 1 or Tier 3, this test
    fails and forces the flag in SS3.4 to be revisited rather than silently left
    standing as if it still applied.
    """
    tier1 = [t for t, v in FROZEN_TIERS.items() if v == 1]
    tier3 = [t for t, v in FROZEN_TIERS.items() if v == 3]
    assert tier1 == ["lab_bench_seqqa"]
    assert tier3 == ["screen_gene_retrieval"]
    text = PREFLIGHT.read_text()
    assert "task identity and tier are fully confounded at BOTH extremes" in text


def test_rubric_is_recorded_in_the_preflight_document():
    text = PREFLIGHT.read_text()
    for task in ELIGIBLE_TASKS:
        assert f"`{task}`" in text
    assert "MedAgentBench" in text
    # the secondary must not be promoted
    assert "co-primary" in text
