"""Tests for the Stage A decomposition (A.1-A.5).

Three things here are load-bearing and would otherwise fail silently:

1. **`delta == (capture - harm)/n` must reconcile exactly.** The whole point of
   A.2 is that the reported Delta is *accounted for* by named instance classes;
   an off-by-anything makes the decomposition decorative.
2. **The A.5b enumeration-robustness logic.** On 9 of 10 tasks the prompt
   contains the correct answer, so a naive "the trajectory mentions it" test is
   near-vacuous. A regression that lets a mere mention count as `singled_out`
   would silently manufacture the paper's most consequential claim.
3. **Candidate extraction must find the real list.** The first version of the
   screen_gene_retrieval regex matched the prose instruction rather than the
   `Candidate genes:` line, yielding two garbage candidates and making every
   comparison against "the average wrong candidate" vacuously favourable. That
   bug is pinned here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dec():
    return _load("stage_a_decomposition")


@pytest.fixture(scope="module")
def tri():
    return _load("stage_a_label_triage")


class TestCaptureHarm:
    def test_delta_reconciles_exactly_to_capture_minus_harm(self, dec):
        rng = np.random.default_rng(0)
        for _ in range(200):
            n = int(rng.integers(5, 60))
            base = rng.integers(0, 2, size=n).astype(float)
            sel = rng.integers(0, 2, size=n).astype(float)
            out = dec.capture_harm(sel, base)
            assert out["reconciles"], out
            assert out["delta"] == pytest.approx(out["delta_from_counts"], abs=1e-12)

    def test_the_four_cells_partition_every_instance(self, dec):
        rng = np.random.default_rng(1)
        n = 50
        base = rng.integers(0, 2, size=n).astype(float)
        sel = rng.integers(0, 2, size=n).astype(float)
        o = dec.capture_harm(sel, base)
        assert o["capture"] + o["harm"] + o["neutral_correct"] + o["neutral_wrong"] == n

    def test_identical_selector_and_base_gives_zero_capture_and_zero_harm(self, dec):
        base = np.array([1.0, 0.0, 1.0, 0.0])
        o = dec.capture_harm(base, base)
        assert (o["capture"], o["harm"], o["delta"]) == (0, 0, 0.0)

    def test_interface_and_judgment_harm_sum_to_total_harm(self, dec):
        base = np.array([1.0, 1.0, 1.0, 1.0])
        sel = np.array([0.0, 0.0, 0.0, 0.0])
        classes = ["wrong_in_menu", "off_menu", "no_majority", "trajectory_failure"]
        o = dec.capture_harm(sel, base, classes)
        assert o["harm"] == 4
        assert o["interface_harm"] + o["judgment_harm"] == o["harm"]
        assert o["interface_share_of_harm"] == pytest.approx(3 / 4)


class TestCandidateExtraction:
    def test_screen_gene_retrieval_takes_the_list_not_the_prose_instruction(self, tri):
        """The exact bug that inflated `singled_out` to 11/11 on this task."""
        prompt = (
            "Your task is to identify the gene with the strongest perturbation effect.\n\n"
            "From the following list of candidate genes, select the ONE gene that would "
            "have the strongest perturbation effect in this experimental context:\n\n"
            "Candidate genes: CCZ1, TRMT10C, SMCHD1, ZNF451\n\n"
            "Output only the gene symbol of your choice, e.g., BRCA1"
        )
        got = tri.candidates_from_prompt("screen_gene_retrieval", prompt)
        assert got == ["CCZ1", "TRMT10C", "SMCHD1", "ZNF451"]
        assert not any("select" in c for c in got), "must not capture the prose instruction"

    def test_gwas_causal_gene_list_is_brace_delimited(self, tri):
        prompt = "Genes in locus: {ACTL9},{ADAMTS10},{PRAM1}\n"
        assert tri.candidates_from_prompt("gwas_causal_gene_gwas_catalog", prompt) == [
            "ACTL9",
            "ADAMTS10",
            "PRAM1",
        ]


class TestEnumerationRobustness:
    def test_a_bare_mention_is_not_being_singled_out(self, tri):
        """A model that enumerates the candidate list mentions the right answer
        exactly as often as every wrong one. That must not read as evidence the
        answer was distinguished."""
        text = "Candidates are AAA, BBB, CCC. Let me consider AAA, BBB and CCC in turn."
        counts = {c: tri.count_mentions(text, c) for c in ("AAA", "BBB", "CCC")}
        assert counts["AAA"] == counts["BBB"] == counts["CCC"] == 2
        gt, wrong = counts["AAA"], [counts["BBB"], counts["CCC"]]
        assert not gt > (sum(wrong) / len(wrong)), "equal enumeration must not count as singled out"

    def test_preferential_discussion_does_count_as_singled_out(self, tri):
        text = "Candidates AAA, BBB, CCC. AAA is the strongest: AAA has direct evidence, so AAA."
        gt = tri.count_mentions(text, "AAA")
        wrong = [tri.count_mentions(text, c) for c in ("BBB", "CCC")]
        assert gt > sum(wrong) / len(wrong)

    def test_count_mentions_respects_token_boundaries(self, tri):
        """IL5 must not be found inside IL5RA, or gene-symbol counting is noise."""
        assert tri.count_mentions("the gene IL5RA was considered", "IL5") == 0
        assert tri.count_mentions("the gene IL5 was considered", "IL5") == 1

    def test_observation_blocks_are_stripped_from_model_text(self, tri):
        c = "<think>I will look it up</think><observation>ANSWER: XYZ1</observation><think>done</think>"
        stripped = tri.OBS_RE.sub(" ", c)
        assert "XYZ1" not in stripped, "tool output must not be mistaken for the model's own reasoning"
        assert "I will look it up" in stripped


class TestNormalisation:
    def test_pure_case_and_punctuation_differences_are_normalisation(self, tri):
        assert tri.normalised_equal("brca1", "BRCA1")
        assert tri.normalised_equal(" 'BRCA1'. ", "BRCA1")

    def test_integer_and_string_ids_are_the_same_answer(self, tri):
        assert tri.normalised_equal(616266, "616266")

    def test_genuinely_different_answers_are_not_normalisation(self, tri):
        assert not tri.normalised_equal("APOA1", "APOA4")


class TestDeterminacy:
    def test_every_task_has_a_written_justification(self, tri):
        assert len(tri.TASK_DETERMINACY) == 10
        for task, (verdict, why) in tri.TASK_DETERMINACY.items():
            assert verdict in ("determinate", "requires_external_knowledge")
            assert len(why) > 40, f"{task} needs a real justification, not a label"

    def test_seqqa_is_the_only_self_determining_task(self, tri):
        """Matches D-37's independent mode-A finding; if this changes, one of the
        two analyses has drifted and both must be re-read."""
        determinate = [t for t, (v, _) in tri.TASK_DETERMINACY.items() if v == "determinate"]
        assert determinate == ["lab_bench_seqqa"]
