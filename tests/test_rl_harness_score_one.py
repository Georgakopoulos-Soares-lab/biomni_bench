"""Reward attachment for RL rollouts: `scripts/rl_harness/rl_score_one.py`'s core logic.

Uses the REAL upstream `BiomniEval1._compute_reward`, same discipline as
`tests/test_evaluation.py`. Confirms the specific claim the harnessed-GRPO
brief asked to be verified: a context-overflow/non-answer trajectory gets a
real, defined, non-dropped reward (0.0), not a missing one.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("biomni.eval.biomni_eval1", reason="pinned Biomni checkout not importable")

from biomni_uncertainty.evaluation import OfficialEvaluator  # noqa: E402

GT_ROW = {"task_name": "gwas_causal_gene_opentargets", "task_instance_id": 0, "answer": "HNF1A"}


def _write_metadata(tmp_path, **overrides):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    metadata = {
        "task_name": GT_ROW["task_name"],
        "task_instance_id": GT_ROW["task_instance_id"],
        "answer_canonical": "HNF1A",
    }
    metadata.update(overrides)
    (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return run_dir


def _write_groundtruth(tmp_path):
    gt_path = tmp_path / "gt.jsonl"
    gt_path.write_text(json.dumps(GT_ROW) + "\n", encoding="utf-8")
    return gt_path


def test_correct_answer_scores_one(tmp_path):
    run_dir = _write_metadata(tmp_path, answer_canonical="HNF1A")
    gt = _write_groundtruth(tmp_path)
    evaluator = OfficialEvaluator.from_groundtruth_file(gt)
    metadata = json.loads((run_dir / "metadata.json").read_text())
    result = evaluator.evaluate(metadata["task_name"], metadata["task_instance_id"], metadata["answer_canonical"])
    assert result.status == "ok"
    assert result.reward == 1.0


def test_wrong_answer_scores_zero_but_is_ok_not_dropped(tmp_path):
    run_dir = _write_metadata(tmp_path, answer_canonical="WRONG_GENE")
    gt = _write_groundtruth(tmp_path)
    evaluator = OfficialEvaluator.from_groundtruth_file(gt)
    metadata = json.loads((run_dir / "metadata.json").read_text())
    result = evaluator.evaluate(metadata["task_name"], metadata["task_instance_id"], metadata["answer_canonical"])
    assert result.status == "ok"
    assert result.reward == 0.0


def test_context_overflow_non_answer_scores_zero_and_is_defined_not_none(tmp_path):
    """The exact claim the harnessed-GRPO brief asked to be verified: a
    trajectory that never produced a parseable answer (budget-terminated,
    degenerate, context overflow) must receive a real, defined reward, not
    disappear from the training batch."""
    run_dir = _write_metadata(tmp_path, answer_canonical=None)
    gt = _write_groundtruth(tmp_path)
    evaluator = OfficialEvaluator.from_groundtruth_file(gt)
    metadata = json.loads((run_dir / "metadata.json").read_text())
    result = evaluator.evaluate(metadata["task_name"], metadata["task_instance_id"], metadata["answer_canonical"])
    assert result.status == "unparseable_answer"
    assert result.reward == 0.0  # defined, not None -- the sample is never dropped


def test_missing_groundtruth_key_is_a_distinct_status_from_a_wrong_answer(tmp_path):
    run_dir = _write_metadata(tmp_path, task_name="not_in_groundtruth", answer_canonical="X")
    gt = _write_groundtruth(tmp_path)
    evaluator = OfficialEvaluator.from_groundtruth_file(gt)
    metadata = json.loads((run_dir / "metadata.json").read_text())
    result = evaluator.evaluate(metadata["task_name"], metadata["task_instance_id"], metadata["answer_canonical"])
    assert result.status == "no_ground_truth"
    assert (
        result.reward is None
    )  # genuinely undefined -- the RL wrapper maps this to the frozen fallback, not to "0 because correct"
