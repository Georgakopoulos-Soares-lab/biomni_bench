"""Tests for the official-evaluator wrapper.

These use the REAL upstream ``BiomniEval1._compute_reward``: the wrapper's job is
to feed it a correctly parsed answer, never to re-implement its scoring. If
upstream's semantics change, these tests are supposed to notice.
"""

from __future__ import annotations

import json

import pytest

biomni = pytest.importorskip("biomni.eval.biomni_eval1", reason="pinned Biomni checkout not importable")

from biomni_uncertainty.canonicalization import parse_answer  # noqa: E402
from biomni_uncertainty.evaluation import OfficialEvaluator, binarize  # noqa: E402

GT = {
    ("crispr_delivery", 0): "b",
    ("gwas_causal_gene_opentargets", 0): "HNF1A",
    ("gwas_variant_prioritization", 0): "rs4253311",
    ("lab_bench_dbqa", 0): "C",
    ("patient_gene_detection", 0): "ENSG00000161011",
    ("rare_disease_diagnosis", 0): '{"disease_name": "Gordon syndrome", "OMIM_ID": "114300"}',
    ("screen_gene_retrieval", 0): "SON",
}


@pytest.fixture
def ev() -> OfficialEvaluator:
    return OfficialEvaluator(dict(GT))


def test_uses_the_real_upstream_scoring_function(ev):
    from biomni.eval.biomni_eval1 import BiomniEval1

    assert ev._compute.__func__ is BiomniEval1._compute_reward


@pytest.mark.parametrize("task,answer", list(GT.items()))
def test_ground_truth_scores_one(ev, task, answer):
    name, tid = task
    if name == "patient_gene_detection":
        answer = json.dumps({"causal_gene": [answer]})
    res = ev.evaluate(name, tid, answer)
    assert res.status == "ok"
    assert res.reward == 1.0


@pytest.mark.parametrize("task", sorted(GT))
def test_wrong_answer_scores_zero(ev, task):
    name, tid = task
    wrong = (
        json.dumps({"causal_gene": ["ENSG00000000000"]})
        if name == "patient_gene_detection"
        else (json.dumps({"disease_name": "x", "OMIM_ID": "999999"}) if name == "rare_disease_diagnosis" else "ZZZZZ")
    )
    assert ev.evaluate(name, tid, wrong).reward == 0.0


def test_canonicalized_answers_score_correctly_end_to_end(ev):
    """The whole point of canonicalization: messy agent text -> the reward the
    official evaluator would give the clean answer."""
    cases = [
        (
            "crispr_delivery",
            "The best option is b. Lentivirus/Retrovirus",
            "a. Plasmid Transfection\nb. Lentivirus/Retrovirus\nc. x\nd. x\ne. x\nf. x",
        ),
        ("gwas_causal_gene_opentargets", "Answer: hnf1a", "Genes in locus: {ACADS},{HNF1A},{MLEC}"),
        ("gwas_variant_prioritization", "The top variant is RS4253311.", "Variants: rs7700133, rs4253311"),
        ("lab_bench_dbqa", "Reasoning...\n[ANSWER]c[/ANSWER]", "Options:\nA.x\nB.x\nC.x"),
        ("screen_gene_retrieval", "SON.", "Candidate genes: TMEM37, SON"),
    ]
    for task, text, prompt in cases:
        p = parse_answer(task, text, prompt)
        assert p.status == "ok", (task, p)
        assert ev.evaluate(task, 0, p.canonical).reward == 1.0, task


def test_rare_disease_int_omim_is_fixed_by_canonicalization(ev):
    # Raw int OMIM_ID would score 0 against the string ground truth.
    raw = '{"disease_name": "Gordon syndrome", "OMIM_ID": 114300}'
    assert ev.evaluate("rare_disease_diagnosis", 0, raw).reward == 0.0
    canonical = parse_answer("rare_disease_diagnosis", raw, "").canonical
    assert ev.evaluate("rare_disease_diagnosis", 0, canonical).reward == 1.0


def test_variant_case_normalization_is_visible_in_strict_reward(ev):
    p = parse_answer("gwas_variant_prioritization", "RS4253311", "Variants: rs4253311")
    res = ev.evaluate("gwas_variant_prioritization", 0, p.canonical, p.raw)
    assert res.reward == 1.0
    # The official evaluator is case-sensitive, so the un-normalized token fails.
    assert res.strict_reward == 0.0


def test_unparseable_answer_scores_zero_with_a_distinct_status(ev):
    res = ev.evaluate("crispr_delivery", 0, None)
    assert res.reward == 0.0
    assert res.status == "unparseable_answer"


def test_missing_ground_truth_is_reported_not_scored(ev):
    res = ev.evaluate("crispr_delivery", 999, "b")
    assert res.status == "no_ground_truth"
    assert res.reward is None


def test_evaluator_exception_is_classified_not_scored_zero():
    class Boom:
        def _compute_reward(self, *a):
            raise RuntimeError("upstream blew up")

    ev = OfficialEvaluator({("crispr_delivery", 0): "b"}, impl=Boom())
    res = ev.evaluate("crispr_delivery", 0, "b")
    assert res.status == "evaluator_failure"
    assert res.reward is None  # NOT 0.0 - infrastructure failure stays distinct
    assert "upstream blew up" in res.error


def test_unknown_task_is_an_evaluator_failure(ev):
    ev.ground_truth[("never_seen_task", 0)] = "x"
    res = ev.evaluate("never_seen_task", 0, "x")
    assert res.status == "evaluator_failure"


def test_patient_gene_set_intersection_semantics(ev):
    # Upstream scores 1.0 for ANY intersection, so a large predicted set inflates
    # reward. We must reproduce that faithfully and flag it in the analysis.
    many = json.dumps({"causal_gene": ["ENSG00000000001", "ENSG00000161011", "ENSG00000000002"]})
    assert ev.evaluate("patient_gene_detection", 0, many).reward == 1.0


def test_from_groundtruth_file(tmp_path):
    p = tmp_path / "gt.jsonl"
    p.write_text(
        json.dumps({"task_name": "crispr_delivery", "task_instance_id": 0, "global_instance_id": 7, "answer": "b"})
        + "\n"
    )
    ev = OfficialEvaluator.from_groundtruth_file(p)
    assert ev.evaluate("crispr_delivery", 0, "b").reward == 1.0


def test_binarize():
    assert binarize(1.0, 0.5) == 1
    assert binarize(0.0, 0.5) == 0
    assert binarize(0.5, 0.5) == 1
    assert binarize(None, 0.5) is None


def test_all_release_tasks_have_a_scoring_branch(ev):
    """Every task in the release must be scorable; a silent ValueError would
    otherwise appear as a uniform zero."""
    from biomni_uncertainty.canonicalization import KNOWN_TASKS

    for task in KNOWN_TASKS:
        ev.ground_truth[(task, 42)] = "x"
        res = ev.evaluate(task, 42, "x")
        assert res.status == "ok", f"{task} has no branch in the official evaluator"
