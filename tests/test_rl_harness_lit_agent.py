"""Tests for `scripts/rl_harness/biomni_lit_agent.py`'s pure logic.

Guarded with `importorskip("agentlightning")`: this file is meaningless
under the standard biomni_unc test environment (agentlightning is
deliberately not installed there -- see the RL-environment isolation
requirement) and must be run under the `rl_harness` venv instead:

    /scratch/11034/atzanakak/envs/rl_harness/bin/python -m pytest -q \
        tests/test_rl_harness_lit_agent.py

Covers: reward-mapping for non-ok evaluator statuses (failure handling),
run_dir determinism (rollout grouping / no collisions), and provenance
logging being append-only (restart/resume: a relaunch after a crash must
never truncate or overwrite prior rollouts' records).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("agentlightning", reason="run this file under the rl_harness venv, not biomni_unc")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "rl_harness"))

from biomni_lit_agent import FROZEN_FAILURE_REWARD, BiomniLitAgent, BiomniRLConfig  # noqa: E402


def _agent(tmp_path, groundtruth_paths=()):
    cfg = BiomniRLConfig(
        biomni_python="/does/not/matter/for/these/tests",
        project_root=str(tmp_path),
        config_path=str(tmp_path / "config.yaml"),
        groundtruth_paths=groundtruth_paths,
        output_root=str(tmp_path / "runs"),
        experiment_id="test_exp",
        provenance_log=str(tmp_path / "runs" / "test_exp" / "provenance.jsonl"),
    )
    return BiomniLitAgent(cfg)


@pytest.mark.parametrize(
    "status,reward,expected",
    [
        ("ok", 1.0, 1.0),
        ("ok", 0.0, 0.0),
        ("unparseable_answer", 0.0, 0.0),
        ("evaluator_failure", None, FROZEN_FAILURE_REWARD),
        ("no_ground_truth", None, FROZEN_FAILURE_REWARD),
        ("no_metadata", None, FROZEN_FAILURE_REWARD),
        ("infra_failure", None, FROZEN_FAILURE_REWARD),
    ],
)
def test_score_trajectory_never_returns_none(tmp_path, status, reward, expected):
    """No status maps to a dropped/None reward -- every rollout scores a
    real float, matching the brief's requirement that context-overflow/
    non-answer trajectories receive the intended frozen treatment."""
    agent = _agent(tmp_path)
    result = agent._score_trajectory(status, reward)
    assert result == expected
    assert isinstance(result, float)


def test_run_dir_is_deterministic_per_rollout_id_and_collision_free(tmp_path):
    agent = _agent(tmp_path)
    task_a = {"task_name": "gwas_causal_gene_opentargets", "task_instance_id": 217}
    task_b = {"task_name": "gwas_causal_gene_opentargets", "task_instance_id": 230}

    same_a_1 = agent._run_dir_for(task_a, "ro-abc")
    same_a_2 = agent._run_dir_for(task_a, "ro-abc")
    diff_rollout = agent._run_dir_for(task_a, "ro-xyz")
    diff_instance = agent._run_dir_for(task_b, "ro-abc")

    assert same_a_1 == same_a_2  # deterministic: a relaunch with the same rollout_id reuses the same path
    assert same_a_1 != diff_rollout  # two rollouts of the same task never collide (GRPO's K copies)
    assert same_a_1 != diff_instance  # two different instances never collide


def test_provenance_log_is_append_only_across_relaunches(tmp_path):
    agent = _agent(tmp_path)
    agent._append_provenance({"rollout_id": "ro-1", "final_reward": 1.0})
    agent._append_provenance({"rollout_id": "ro-2", "final_reward": 0.0})

    # Simulate a process relaunch: a fresh agent instance pointed at the same log.
    agent2 = _agent(tmp_path)
    agent2._append_provenance({"rollout_id": "ro-3", "final_reward": 0.0})

    lines = Path(agent.rl_config.provenance_log).read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert [r["rollout_id"] for r in records] == ["ro-1", "ro-2", "ro-3"]


def test_groundtruth_lookup_is_explicit_not_silently_first_match(tmp_path):
    gt_a = tmp_path / "a.groundtruth.jsonl"
    gt_a.write_text(
        json.dumps({"task_name": "gwas_causal_gene_opentargets", "task_instance_id": 0, "answer": "X"}) + "\n"
    )
    gt_b = tmp_path / "b.groundtruth.jsonl"
    gt_b.write_text(json.dumps({"task_name": "lab_bench_dbqa", "task_instance_id": 0, "answer": "Y"}) + "\n")

    agent = _agent(tmp_path, groundtruth_paths=(str(gt_a), str(gt_b)))
    assert agent._groundtruth_for("gwas_causal_gene_opentargets") == str(gt_a)
    assert agent._groundtruth_for("lab_bench_dbqa") == str(gt_b)
    with pytest.raises(ValueError):
        agent._groundtruth_for("not_a_registered_task")
