"""Pure reward-contract checks for the Agent Lightning v1 local adapter."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "rl_harness"))

from biomni_local_agent import FROZEN_FAILURE_REWARD, score_terminal  # noqa: E402


def test_official_reward_is_preserved_for_scoreable_trajectory() -> None:
    assert score_terminal("ok", 1.0) == 1.0
    assert score_terminal("unparseable_answer", 0.0) == 0.0


def test_unscored_terminal_rollout_stays_in_group_at_frozen_zero() -> None:
    assert score_terminal("infra_failure", None) == FROZEN_FAILURE_REWARD
    assert score_terminal("evaluator_failure", 1.0) == FROZEN_FAILURE_REWARD
