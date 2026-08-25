from biomni_uncertainty.reliability import evaluate_reliability


def test_v1_metrics_and_failure_taxonomy():
    rows = [
        {"task_id": "a", "run_index": i, "answer_cluster_key": "x", "official_reward": 1, "completed": True, "confidence": .9} for i in range(4)
    ] + [
        {"task_id": "b", "run_index": i, "answer_cluster_key": ["x", "y", "y", "z"][i], "official_reward": [1, 0, 0, 0][i], "completed": True, "confidence": .2} for i in range(4)
    ]
    out = evaluate_reliability(rows, n_bootstrap=20)
    assert out["metrics"]["pass_at_1"]["estimate"] == 1.0
    assert out["metrics"]["plurality_accuracy"]["estimate"] == .5
    assert out["metrics"]["oracle_at_k"]["estimate"] == 1.0
    assert out["failure_taxonomy"] == {"stable_correct": 1, "unstable_recoverable": 1}


def test_evaluator_failures_are_not_silently_scored_wrong():
    rows = [{"task_id": "a", "run_index": i, "answer_cluster_key": str(i), "official_reward": None,
             "completed": False, "failure_reason": "official_scorer_error"} for i in range(4)]
    out = evaluate_reliability(rows, n_bootstrap=10)
    assert out["failure_accounting"]["n_evaluator_failures"] == 4
    assert out["metrics"]["pass_at_1"]["estimate"] is None
