from biomni_uncertainty.adapters.biomni import normalize_biomni_table
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
    assert out["failure_taxonomy"] == {}


def test_agreement_reports_auprc_and_explicit_selection_count():
    rows = [
        {"task_id": "a", "run_index": i, "answer_cluster_key": key, "official_reward": reward, "completed": True}
        for i, (key, reward) in enumerate((("x", 1), ("y", 0), ("y", 0), ("z", 0)))
    ] + [
        {"task_id": "b", "run_index": i, "answer_cluster_key": "q", "official_reward": 1, "completed": True}
        for i in range(4)
    ]
    out = evaluate_reliability(rows, n_bootstrap=10)
    assert out["selection_failure_count"] == 1
    assert out["metrics"]["agreement_to_correctness_auprc"] is not None
    assert out["metrics"]["agreement_risk_coverage"] is not None


def test_failure_layers_absent_when_adapter_reports_no_layer_columns():
    rows = [{"task_id": "a", "run_index": i, "answer_cluster_key": "x", "official_reward": None,
             "completed": False} for i in range(4)]
    out = evaluate_reliability(rows, n_bootstrap=10)
    assert out["failure_accounting"]["failure_layers"] is None


def test_failure_layers_distinguish_artifact_contract_from_scorer_failure():
    rows = [
        {"task_id": "a", "run_index": 0, "answer_cluster_key": "x", "official_reward": None,
         "completed": False, "agent_execution_success": False, "artifact_contract_valid": None,
         "native_scorer_success": None},
        {"task_id": "a", "run_index": 1, "answer_cluster_key": "bad", "official_reward": None,
         "completed": False, "agent_execution_success": True, "artifact_contract_valid": False,
         "native_scorer_success": None},
        {"task_id": "a", "run_index": 2, "answer_cluster_key": "ok", "official_reward": None,
         "completed": False, "agent_execution_success": True, "artifact_contract_valid": True,
         "native_scorer_success": False},
        {"task_id": "b", "run_index": 0, "answer_cluster_key": "ok", "official_reward": 1,
         "completed": True, "agent_execution_success": True, "artifact_contract_valid": True,
         "native_scorer_success": True},
    ]
    out = evaluate_reliability(rows, n_bootstrap=10)
    layers = out["failure_accounting"]["failure_layers"]
    assert layers == {"execution_failure": 1, "artifact_contract_failure": 1,
                       "native_scorer_failure": 1, "scored": 1}
    # Task "a" has zero evaluable rewards, so it must never receive a taxonomy
    # (score-zero) label -- an artifact-contract failure is not a wrong answer.
    assert out["failure_taxonomy"] == {"stable_correct": 1}


def test_biomni_adapter_normalizes_native_table(tmp_path):
    table = tmp_path / "instrumented.csv"
    table.write_text(
        "task_name,task_instance_id,trajectory_index,answer_cluster_key,reward,completed,run_id\n"
        "gene,2,0,TP53,1,True,r0\n",
        encoding="utf-8",
    )
    row = normalize_biomni_table(table)[0]
    assert row["task_id"] == "gene:2"
    assert row["official_pass"] == 1
    assert row["agent"] == "biomni"
