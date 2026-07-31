"""Wrapper around the official ``biomni.eval.BiomniEval1`` evaluator.

Design constraints:

* The official evaluator is the only source of reward. We never re-implement its
  scoring, only its *input contract* (it expects an already-parsed answer).
* Ground truth is loaded from a file that is never handed to the agent.
* An evaluator exception is recorded as ``evaluator_failure``, not silently
  scored 0, so infrastructure failure stays distinguishable from a wrong answer.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _missing(value: Any) -> bool:
    """True for a missing answer.

    Answers arrive through pandas, which represents a missing object as ``NaN``
    rather than ``None``. Treating a NaN as a real answer sends it into the
    official scorer, which raises - and a substantive "the agent produced no
    answer" outcome would then be mislabelled an evaluator failure and dropped
    from the analysis instead of scoring zero.
    """
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


@dataclass(frozen=True)
class EvaluationResult:
    task_name: str
    task_instance_id: int
    reward: float | None
    strict_reward: float | None
    status: str  # "ok" | "unparseable_answer" | "evaluator_failure" | "no_ground_truth"
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class OfficialEvaluator:
    """Task-specific reward via the official BiomniEval1 logic.

    ``BiomniEval1.__init__`` downloads the dataset from the Hub; we bypass that
    by instantiating without ``__init__`` and injecting a locally-held frame,
    which keeps the *scoring* code path (``_compute_reward``) exactly upstream's.
    """

    def __init__(self, ground_truth: dict[tuple[str, int], str], impl: Any | None = None):
        self.ground_truth = ground_truth
        if impl is not None:
            self._impl = impl
        else:
            from biomni.eval.biomni_eval1 import BiomniEval1

            self._impl = BiomniEval1.__new__(BiomniEval1)  # no network, no dataset load
        self._compute = self._impl._compute_reward

    # -- constructors ----------------------------------------------------
    @classmethod
    def from_groundtruth_file(cls, path: str | Path, impl: Any | None = None) -> OfficialEvaluator:
        gt: dict[tuple[str, int], str] = {}
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                gt[(rec["task_name"], int(rec["task_instance_id"]))] = rec["answer"]
        return cls(gt, impl=impl)

    # -- api -------------------------------------------------------------
    def evaluate(
        self,
        task_name: str,
        task_instance_id: int,
        canonical_answer: str | None,
        strict_answer: str | None = None,
    ) -> EvaluationResult:
        key = (task_name, int(task_instance_id))
        if key not in self.ground_truth:
            return EvaluationResult(task_name, int(task_instance_id), None, None, "no_ground_truth")
        gt = self.ground_truth[key]

        if _missing(canonical_answer):
            # A trajectory that produced no parseable answer scores 0 by
            # construction; that is a substantive agent failure, not an
            # evaluator failure, so the reward is defined.
            return EvaluationResult(task_name, int(task_instance_id), 0.0, 0.0, "unparseable_answer")

        try:
            reward = float(self._compute(task_name, canonical_answer, gt))
        except Exception as exc:  # noqa: BLE001 - upstream raises bare Exception subclasses
            return EvaluationResult(task_name, int(task_instance_id), None, None, "evaluator_failure", repr(exc))

        strict = None
        if not _missing(strict_answer):
            try:
                strict = float(self._compute(task_name, strict_answer, gt))
            except Exception:  # noqa: BLE001 - strict reward is diagnostic only
                strict = None

        return EvaluationResult(task_name, int(task_instance_id), reward, strict, "ok")


def binarize(reward: float | None, threshold: float) -> int | None:
    """Binary correctness from a possibly-continuous official reward.

    Every task in the current BiomniEval1 release already returns exactly 0.0 or
    1.0, so this threshold is a no-op for the pilot; it exists so the analysis
    keeps working if a partially-graded task is added.
    """
    if reward is None:
        return None
    return int(reward >= threshold)
