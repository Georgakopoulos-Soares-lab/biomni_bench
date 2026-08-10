"""Tests for the Step-2 adjudication-pilot analysis (`scripts/track_c_adjudication_analyze.py`).

Two load-bearing pieces get direct coverage: `_majority` (2-of-3 agreement,
not "any answer present"), since a miscounted majority would silently shift
every downstream reward number; and `verdict_for`'s GO/NO-GO/INCONCLUSIVE
boundaries, copied verbatim from the frozen acceptance rule - a boundary bug
here would misclassify the one number this whole pilot exists to produce.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "track_c_adjudication_analyze", SCRIPTS / "track_c_adjudication_analyze.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["track_c_adjudication_analyze"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _load()


class TestMajority:
    def test_two_of_three_agree_is_a_majority(self, m):
        answer, status = m._majority(["a", "a", "b"])
        assert answer == "a"
        assert status == "majority"

    def test_three_way_split_is_no_majority(self, m):
        answer, status = m._majority(["a", "b", "c"])
        assert answer is None
        assert status == "no_majority"

    def test_all_null_is_all_missing_not_no_majority(self, m):
        answer, status = m._majority([None, None, None])
        assert answer is None
        assert status == "all_missing"

    def test_single_usable_answer_is_not_a_majority(self, m):
        # 1-of-3 real answer, 2 unresolved: a single sample must not be
        # promoted to a "majority" - the rule is 2-of-3 agreement, not
        # "only one candidate remains after filtering failures."
        answer, status = m._majority(["a", None, None])
        assert answer is None
        assert status == "no_majority"

    def test_three_way_agreement_is_still_a_majority(self, m):
        answer, status = m._majority(["a", "a", "a"])
        assert answer == "a"
        assert status == "majority"


class TestVerdict:
    def _merged(self, arm_rewards, floor_rewards):
        return pd.DataFrame({"reward": arm_rewards, "plurality_reward": floor_rewards})

    def test_go_when_arm_strictly_beats_floor_everywhere(self, m):
        # Arm always 1.0, floor always 0.0: Delta's CI cannot include zero.
        merged = self._merged([1.0] * 30, [0.0] * 30)
        v = m.verdict_for(merged, "reward", "test")
        assert v["verdict"] == "GO"
        assert v["ci_lo"] > 0

    def test_no_go_when_arm_never_beats_floor(self, m):
        # Arm always equals floor: Delta is identically zero, whose CI upper
        # bound is 0.0, strictly below the frozen gap/3 bar (0.0641) - NO-GO.
        merged = self._merged([0.5] * 30, [0.5] * 30)
        v = m.verdict_for(merged, "reward", "test")
        assert v["verdict"] == "NO-GO"
        assert v["ci_hi"] < m.FROZEN_GAP_THIRD

    def test_inconclusive_when_ci_straddles_the_bars(self, m):
        # A small, noisy sample where the arm sometimes beats and sometimes
        # matches the floor: neither bar is cleared.
        rng = np.random.default_rng(0)
        floor = rng.integers(0, 2, size=20).astype(float)
        arm = floor.copy()
        # flip a handful of floor-misses to arm-hits, not enough to clear GO
        flip_idx = np.where(floor == 0)[0][:3]
        arm[flip_idx] = 1.0
        merged = self._merged(arm.tolist(), floor.tolist())
        v = m.verdict_for(merged, "reward", "test")
        assert v["verdict"] == "INCONCLUSIVE"

    def test_frozen_gap_third_constant_matches_acceptance_rule(self, m):
        # Copied from reports/track_c_step2_acceptance_rule.md: gap = 0.1923,
        # gap/3 = 0.0641. A drift here would silently change the NO-GO bar.
        assert m.FROZEN_GAP_THIRD == pytest.approx(0.1923 / 3, abs=0.0002)


class TestTaskFamilyStratification:
    def test_families_are_disjoint(self, m):
        assert m.EVIDENCE_RETRIEVABLE_TASKS.isdisjoint(m.DOMAIN_JUDGMENT_TASKS)

    def test_families_cover_exactly_ten_biomnieval1_tasks(self, m):
        # D-37 1b names all 10 BiomniEval1 tasks; the Step-2 stratification
        # must partition them, not silently drop one.
        assert len(m.EVIDENCE_RETRIEVABLE_TASKS) + len(m.DOMAIN_JUDGMENT_TASKS) == 10
