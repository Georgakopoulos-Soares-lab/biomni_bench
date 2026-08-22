"""Guard the RL harness's training-task pool against the frozen held-out set.

Pure stdlib logic in `scripts/rl_harness/rl_harness_dataset.py` -- no GPU, no
agentlightning, no verl. Runs in the standard biomni_unc test environment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "rl_harness"))

from rl_harness_dataset import HeldOutOverlapError, load_training_tasks  # noqa: E402


def test_real_manifests_produce_the_frozen_200_with_zero_overlap():
    tasks = load_training_tasks(ROOT)
    assert len(tasks) == 200
    keys = {(t["task_name"], int(t["task_instance_id"])) for t in tasks}
    assert len(keys) == 200  # no duplicates collapsed silently


def test_real_manifests_never_touch_scope_main_or_smoke_manifests():
    tasks = load_training_tasks(ROOT)
    keys = {(t["task_name"], int(t["task_instance_id"])) for t in tasks}
    holdout = {
        (r["task_name"], int(r["task_instance_id"]))
        for r in (json.loads(line) for line in open(ROOT / "manifests" / "scope_main.jsonl", encoding="utf-8"))
    }
    assert keys.isdisjoint(holdout)


def test_a_synthetic_overlap_is_caught_not_silently_ignored(tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    shared_row = {
        "task_name": "gwas_causal_gene_opentargets",
        "task_instance_id": 1,
        "global_instance_id": 1,
        "prompt": "x",
        "prompt_hash": "h",
        "split": "val",
    }
    (manifests / "phase1.jsonl").write_text(json.dumps(shared_row) + "\n", encoding="utf-8")
    (manifests / "phase2b.jsonl").write_text("", encoding="utf-8")
    (manifests / "scope_main.jsonl").write_text(json.dumps(shared_row) + "\n", encoding="utf-8")

    try:
        load_training_tasks(tmp_path)
        raised = False
    except HeldOutOverlapError:
        raised = True
    assert raised


def test_disjoint_synthetic_manifests_load_cleanly(tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    train_row = {
        "task_name": "gwas_causal_gene_opentargets",
        "task_instance_id": 1,
        "global_instance_id": 1,
        "prompt": "x",
        "prompt_hash": "h",
        "split": "val",
    }
    holdout_row = dict(train_row, task_instance_id=2, global_instance_id=2)
    (manifests / "phase1.jsonl").write_text(json.dumps(train_row) + "\n", encoding="utf-8")
    (manifests / "phase2b.jsonl").write_text("", encoding="utf-8")
    (manifests / "scope_main.jsonl").write_text(json.dumps(holdout_row) + "\n", encoding="utf-8")

    tasks = load_training_tasks(tmp_path)
    assert len(tasks) == 1
    assert tasks[0]["task_instance_id"] == 1
