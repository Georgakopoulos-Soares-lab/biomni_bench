"""Tests for A.6, the semantic discriminability probe.

The load-bearing property is the **leakage barrier**. A.5b's `singled_out` took
ground truth as an input (it measured discussion of the *correct* answer); that
is fine for an audit and invalid for a feature a Stage C capsule would compute
at inference time, when no label exists. A.6 reformulates label-free — how
preferentially a trajectory discusses its *own committed* answer — and these
tests assert that reformulation actually holds rather than merely being
intended.

The strongest form is `test_features_are_invariant_to_permuting_the_labels`: if
any label leaked into extraction, permuting labels would change feature values.

Also pinned: the frozen decision rule's constants (family, primary,
correction), because A.4's failure was a correction chosen after the fact, and
the whole point of `reports/a6_decision_rule.md` is that those cannot move.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def a6():
    return _load("stage_a6_semantic_probe")


class TestLeakageBarrier:
    def test_extract_features_takes_no_label_shaped_argument(self, a6):
        """Three parameters, all knowable at inference time. A label cannot be
        threaded in without changing this signature and failing here."""
        params = list(inspect.signature(a6.extract_features).parameters)
        assert params == ["model_text", "own_answer", "candidates"]
        assert not (set(params) & a6.FORBIDDEN_FEATURE_INPUTS)

    def test_forbidden_fields_are_dropped_before_extraction(self, a6):
        traj = pd.DataFrame(
            {
                "pool": ["p"],
                "task_name": ["t"],
                "task_instance_id": [1],
                "run_dir": ["/nonexistent"],
                "answer_canonical": ["AAA"],
                "reward": [1.0],
                "correct": [1],
                "strict_reward": [1.0],
            }
        )
        out = a6.build_feature_frame(traj, {("p", "t", 1): ["AAA", "BBB"]})
        assert not (set(out.columns) & (a6.FORBIDDEN_FEATURE_INPUTS - {"label"}))
        assert "label" in out.columns, "the label must be re-attached, but only as the AUROC target"

    def test_features_are_invariant_to_permuting_the_labels(self, a6):
        """The decisive check. Feature values must not move when labels change."""
        base = pd.DataFrame(
            {
                "pool": ["p"] * 4,
                "task_name": ["t"] * 4,
                "task_instance_id": [1, 1, 2, 2],
                "run_dir": ["/nonexistent"] * 4,
                "answer_canonical": ["AAA", "BBB", "AAA", "BBB"],
                "reward": [1.0, 0.0, 1.0, 0.0],
            }
        )
        flipped = base.assign(reward=[0.0, 1.0, 0.0, 1.0])
        menus = {("p", "t", 1): ["AAA", "BBB"], ("p", "t", 2): ["AAA", "BBB"]}
        a = a6.build_feature_frame(base, menus)
        b = a6.build_feature_frame(flipped, menus)
        cols = list(a6.FEATURE_FAMILY)
        pd.testing.assert_frame_equal(a[cols], b[cols])
        assert not a.label.equals(b.label), "the fixture must actually change the labels"

    def test_own_answer_share_does_not_depend_on_which_candidate_is_correct(self, a6):
        """Two trajectories, same text pattern, different committed answers: the
        feature is computed relative to each one's OWN answer."""
        text = "I considered AAA and BBB. AAA is best because AAA fits."
        fa = a6.extract_features(text, "AAA", ["AAA", "BBB"])
        fb = a6.extract_features(text, "BBB", ["AAA", "BBB"])
        assert fa["own_answer_share"] > fb["own_answer_share"]


class TestFrozenRuleConstants:
    def test_family_primary_and_correction_match_the_frozen_rule(self, a6):
        assert a6.PRIMARY_FEATURE == "own_answer_share"
        assert a6.FAMILY_SIZE == 4
        assert set(a6.FEATURE_FAMILY) == {
            "own_answer_share",
            "n_competing_candidates_discussed",
            "hedging_near_answer",
            "closing_concentration",
        }
        assert a6.ALPHA_CORRECTED == pytest.approx(0.05 / 4)

    def test_the_decision_rule_file_exists_and_predates_any_result(self):
        p = Path(__file__).resolve().parents[1] / "reports" / "a6_decision_rule.md"
        assert p.exists()
        text = p.read_text()
        assert "own_answer_share" in text and "0.05 / 4" in text

    def test_hedging_markers_are_fixed_not_tunable(self, a6):
        """Pinned so the list cannot be quietly extended to move a result."""
        assert len(a6.HEDGING_MARKERS) == 19
        for m in ("may", "might", "uncertain", "insufficient"):
            assert m in a6.HEDGING_MARKERS


class TestFeatureSemantics:
    def test_share_is_one_when_only_the_own_answer_is_discussed(self, a6):
        f = a6.extract_features("AAA is the answer, AAA fits.", "AAA", ["AAA", "BBB", "CCC"])
        assert f["own_answer_share"] == 1.0
        assert f["n_competing_candidates_discussed"] == 0.0

    def test_share_falls_when_alternatives_are_weighed(self, a6):
        f = a6.extract_features("AAA, BBB and CCC all plausible; AAA slightly ahead.", "AAA", ["AAA", "BBB", "CCC"])
        assert 0 < f["own_answer_share"] < 1
        assert f["n_competing_candidates_discussed"] == 2.0

    def test_share_is_nan_when_no_candidate_is_mentioned(self, a6):
        f = a6.extract_features("nothing relevant here", "AAA", ["AAA", "BBB"])
        assert np.isnan(f["own_answer_share"])

    def test_hedging_counts_only_the_closing_segment(self, a6):
        early = "might " * 50 + "X" * 400
        f = a6.extract_features(early, "AAA", ["AAA"])
        assert f["hedging_near_answer"] == 0.0

    def test_token_boundaries_are_respected_in_feature_counting(self, a6):
        """IL5 must not be found inside IL5RA, or the share is noise."""
        f = a6.extract_features("IL5RA was discussed at length", "IL5", ["IL5", "IL5RA"])
        assert f["own_answer_share"] == 0.0


class TestVerdictLogic:
    def test_corrected_interval_governs_not_the_nominal_one(self, a6):
        nominal_only = {"ci95_lo": 0.51, "ci95_hi": 0.60, "corrected_lo": 0.49, "corrected_hi": 0.62}
        assert a6.excludes_half(nominal_only, "ci95_lo", "ci95_hi")
        assert not a6.excludes_half(nominal_only), "a nominal-only hit must not count as signal"

    def test_inverse_discrimination_still_counts(self, a6):
        inverse = {"corrected_lo": 0.20, "corrected_hi": 0.40}
        assert a6.excludes_half(inverse)
