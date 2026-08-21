"""Pin the harnessed-GRPO pre-registration's frozen split and config against
`reports/rl_harness_preregistration.md`.

Same discipline as every prior pre-registration test in this project: a
decision constant that lives only in a script or a report can drift after a
result exists and nobody notices.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "reports" / "rl_harness_preregistration.md"
SPLIT_AUDIT = ROOT / "reports" / "tables" / "rl_harness" / "split_audit.json"


def test_prereg_freezes_the_split_sizes_and_zero_overlap():
    audit = json.loads(SPLIT_AUDIT.read_text())
    assert audit["train_pool"]["n"] == 200
    assert audit["held_out_eval_pool"]["n"] == 120
    assert audit["overlap"] == 0
    assert audit["reserved_untouched_never_used"] == 100
    text = PREREG.read_text()
    assert "200 instances" in text or "**200**" in text
    assert "120" in text


def test_split_sources_are_the_already_frozen_manifests_not_a_new_one():
    assert audit_sources("train_pool") == ["manifests/phase1.jsonl", "manifests/phase2b.jsonl"]
    assert audit_sources("held_out_eval_pool") == ["manifests/scope_main.jsonl"]


def audit_sources(pool: str) -> list[str]:
    return json.loads(SPLIT_AUDIT.read_text())[pool]["sources"]


def test_split_audit_script_is_reproducible():
    """Re-running the audit script must reproduce the frozen numbers exactly."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "rl_harness_split_audit.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    fresh = json.loads(SPLIT_AUDIT.read_text())
    assert fresh["train_pool"]["n"] == 200
    assert fresh["held_out_eval_pool"]["n"] == 120
    assert fresh["overlap"] == 0


def test_frozen_config_matches_the_preregistration_text():
    text = PREREG.read_text()
    # K/G = 4, matching Part I, not 8
    assert "**4**" in text
    assert "batch_size 16" in text or "batch size | 16" in text
    assert "seed `20260821`" in text
    assert "~25 optimizer steps" in text or "≈ 25 optimizer steps" in text


def test_prereg_forbids_the_closed_branches():
    text = PREREG.read_text()
    for forbidden in (
        "no uncertainty-guided sampling",
        "No adaptive K",
        "no verifier reward",
        "no new correction mechanism",
    ):
        assert forbidden.lower() in text.lower()


def test_prereg_states_the_safety_question_explicitly():
    text = PREREG.read_text()
    assert "consistently wrong" in text.lower()
    assert "H-RL2b" in text


def test_prereg_reuses_pre_rl_numbers_rather_than_recomputing_them():
    """The pre-RL half of every endpoint must cite D-46/D-48's frozen numbers."""
    text = PREREG.read_text()
    assert "0.896" in text  # agreement->correctness AUROC, D-46
    assert "0.442" in text  # Pass@1, D-46
    assert "0.175" in text  # headroom / selection-failure rate


def test_full_parameter_finetuning_blocker_is_stated_with_its_arithmetic():
    text = PREREG.read_text()
    assert "448 GB" in text
    assert "384" in text  # cluster total
    assert "LoRA" in text


def test_no_scientific_rl_result_exists_yet():
    text = PREREG.read_text()
    assert "No RL training has occurred" in text or "No RL training has run" in text
    assert "Engineering smoke tests only" in text
