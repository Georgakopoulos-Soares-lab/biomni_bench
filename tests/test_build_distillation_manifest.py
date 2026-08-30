"""Sanity checks for scripts/build_distillation_manifest.py.

Uses small synthetic fixtures (not the real data lake, which this host
doesn't always have) so these run anywhere, fast.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "build_distillation_manifest.py"

spec = importlib.util.spec_from_file_location("build_distillation_manifest", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_distillation_manifest"] = mod
spec.loader.exec_module(mod)


REAL_TRAJECTORY_STDOUT = """\
================================ Human Message =================================

What is the answer?
================================== Ai Message ==================================

<think>let me check</think>
<execute>
print("hello")
</execute>
================================== Ai Message ==================================

<observation>hello</observation>
================================== Ai Message ==================================

<think>now I know</think>
<solution>
c
</solution>
"""


def test_parse_stdout_log_masks_observations_not_real_generations(tmp_path):
    p = tmp_path / "stdout.log"
    p.write_text(REAL_TRAJECTORY_STDOUT)
    messages = mod.parse_stdout_log(p)

    assert messages[0]["role"] == "system" and messages[0]["trainable"] is False
    assert messages[1] == {"role": "user", "content": "What is the answer?", "trainable": False}

    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 3
    assert assistant_msgs[0]["trainable"] is True  # real generation with <execute>
    assert assistant_msgs[1]["trainable"] is False  # injected <observation>
    assert "<observation>" in assistant_msgs[1]["content"]
    assert assistant_msgs[2]["trainable"] is True  # real generation with <solution>


def test_select_control_picks_lowest_index_completed_regardless_of_reward():
    group = [
        {"trajectory_index": 2, "completed": True, "correct": False},
        {"trajectory_index": 0, "completed": False, "correct": None},
        {"trajectory_index": 1, "completed": True, "correct": True},
    ]
    chosen = mod.select_control(group)
    assert chosen["trajectory_index"] == 1  # lowest-index among COMPLETED (index 0 failed)


def test_select_treatment_requires_correctness_and_picks_lowest_index():
    group = [
        {"trajectory_index": 0, "completed": True, "correct": False},
        {"trajectory_index": 1, "completed": True, "correct": True},
        {"trajectory_index": 2, "completed": True, "correct": True},
    ]
    chosen = mod.select_treatment(group)
    assert chosen["trajectory_index"] == 1


def test_select_treatment_returns_none_when_nothing_correct():
    group = [
        {"trajectory_index": 0, "completed": True, "correct": False},
        {"trajectory_index": 1, "completed": False, "correct": None},
    ]
    assert mod.select_treatment(group) is None


def test_held_out_overlap_hard_fails(tmp_path):
    scope_main = tmp_path / "scope_main.jsonl"
    scope_main.write_text(json.dumps({"task_name": "crispr_delivery", "task_instance_id": 14}) + "\n")
    try:
        mod.assert_no_held_out_overlap({"crispr_delivery/14"}, scope_main)
        raised = False
    except SystemExit:
        raised = True
    assert raised, "must hard-fail when a generated task_id overlaps the held-out set"


def test_no_overlap_passes_silently(tmp_path):
    scope_main = tmp_path / "scope_main.jsonl"
    scope_main.write_text(json.dumps({"task_name": "crispr_delivery", "task_instance_id": 14}) + "\n")
    mod.assert_no_held_out_overlap({"gwas_causal_gene_gwas_catalog/1"}, scope_main)  # should not raise
