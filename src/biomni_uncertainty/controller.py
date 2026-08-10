"""Online reliability controller and its append-only decision log (Phase 2B).

The offline replay in `biomni_uncertainty.policy` answers "what would a policy
have done". This module is what actually decides, live, while trajectories are
still being generated — and it is built so that the claim "the controller never
saw a future trajectory" is **checkable from artifacts**, not asserted.

## Why the log is hash-chained

Phase 2B generates all K trajectories per instance so that fixed-K and oracle
baselines pair on the same instances. The controller must never see the ones it
did not ask for. "The code does not pass them" is not a guarantee: it is
unverifiable after the fact and it fails silently.

So generation and decision interleave, and each decision is **committed before
the next trajectory exists** (D-23):

1. trajectory *j* is generated; only `1..j` exist on disk;
2. the controller decides from exactly those *j*;
3. the decision is appended to this log, hash-chained to its predecessor, and
   **fsynced**;
4. only then may trajectory *j+1* be generated.

A shadow therefore cannot have influenced an earlier decision because it did not
exist when that decision was committed, and a committed decision cannot be
rewritten afterwards without breaking the chain. Both are verifiable:
:meth:`DecisionLog.verify` checks the chain, and the analysis checks that every
shadow's start timestamp post-dates its instance's terminal decision.

## Why the log is also the resume state

A prospective run that outlives its Slurm allocation must resume without
re-deciding anything. Replaying this log reconstructs the controller's exact
position: decisions already committed are authoritative and are **reused, never
recomputed**, so a resumed run cannot silently diverge from the one that started.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from biomni_uncertainty.config import ControllerCfg
from biomni_uncertainty.policy import (
    ABSTAIN,
    ACCEPT,
    CONTINUE,
    Abstaining,
    Decision,
    MandatoryK2,
    Policy,
    PolicyState,
    Resolution,
    TrajectoryView,
    resolve,
)

DECISION_LOG_NAME = "decisions.jsonl"
GENESIS_HASH = "0" * 64

#: Directory component for evaluation-only trajectories. Keeping shadows under
#: their own condition puts them in a separate subtree while leaving the
#: aggregation path (`collect_run_records`) completely unchanged.
CONDITION_SHADOW = "shadow"
CONDITION_CONSUMED = "instrumented"


# --------------------------------------------------------------------------
# The frozen policy
# --------------------------------------------------------------------------


def _agreement_only_scorer(_state: PolicyState, res: Resolution) -> float:
    """Abstention rule, expressed as a score so the tested wrapper can be reused.

    1.0 when at least two *usable* trajectories agree, 0.0 otherwise. Paired with
    a 0.5 threshold this is exactly "abstain when every valid answer is
    distinct" (`reports/phase2_offline_replay.md` §9) — a counted rule with no
    fitted parameter, not a calibrated probability.
    """
    return 1.0 if res.valid_agreement else 0.0


def build_controller(cfg: ControllerCfg) -> Policy:
    """The frozen Phase-2B controller, built from validated config.

    `mandatory_k2` = never accept one unverified analysis; stop as soon as two
    usable trajectories agree; continue to the ceiling on disagreement; abstain
    at the ceiling when nothing agrees. The failure override lives inside
    `MandatoryK2`/`resolve` (D-18) and is not separately switchable — a
    controller that accepted a dead trajectory would not be this policy.
    """
    if cfg.policy != "mandatory_k2":  # pragma: no cover - Literal-guarded
        raise ValueError(f"unknown controller policy {cfg.policy!r}")
    if not cfg.failure_override:
        raise ValueError("controller.failure_override cannot be disabled: the frozen policy is defined with it (D-18)")
    base = MandatoryK2(max_k=cfg.max_trajectories, name="mandatory_k2")
    if not cfg.abstain_on_no_agreement:
        return base
    return Abstaining(base, _agreement_only_scorer, 0.5, name="mandatory_k2_abstain")


# --------------------------------------------------------------------------
# Decision log
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionRecord:
    """One committed decision. `this_hash` chains it to everything before it."""

    task_name: str
    task_instance_id: int
    step: int  # 1-based: the decision taken after observing `step` trajectories
    observed_run_ids: list[str]
    action: str
    reason: str
    support: int
    k_observed: int
    valid_agreement: bool
    resolved_cluster_key: str | None
    decided_at: float
    prev_hash: str
    this_hash: str = ""

    def payload(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("this_hash")
        return d

    def compute_hash(self) -> str:
        blob = json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DecisionLog:
    """Append-only, hash-chained, fsynced decision log for one instance."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._records: list[DecisionRecord] = []
        if self.path.exists():
            self._records = self._read()

    def _read(self) -> list[DecisionRecord]:
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(DecisionRecord(**json.loads(line)))
        return out

    @property
    def records(self) -> list[DecisionRecord]:
        return list(self._records)

    @property
    def last_hash(self) -> str:
        return self._records[-1].this_hash if self._records else GENESIS_HASH

    @property
    def n_steps(self) -> int:
        return len(self._records)

    def decision_for_step(self, step: int) -> DecisionRecord | None:
        """A previously committed decision, which is authoritative on resume."""
        for r in self._records:
            if r.step == step:
                return r
        return None

    def terminal(self) -> DecisionRecord | None:
        for r in self._records:
            if r.action in (ACCEPT, ABSTAIN):
                return r
        return None

    def append(self, record: DecisionRecord) -> DecisionRecord:
        """Commit a decision. Returns the record with its hash filled in.

        The write is flushed and fsynced before returning, because the whole
        isolation argument rests on this record existing on disk *before* the
        next trajectory is generated.
        """
        if record.prev_hash != self.last_hash:
            raise ValueError(f"decision log chain break: expected prev_hash {self.last_hash}, got {record.prev_hash}")
        sealed = DecisionRecord(**{**asdict(record), "this_hash": record.compute_hash()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(sealed), sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._records.append(sealed)
        return sealed

    def verify(self) -> tuple[bool, str]:
        """Recompute the whole chain. Returns (ok, reason)."""
        prev = GENESIS_HASH
        for i, r in enumerate(self._records):
            if r.prev_hash != prev:
                return False, f"record {i} (step {r.step}) prev_hash mismatch"
            if r.this_hash != r.compute_hash():
                return False, f"record {i} (step {r.step}) content does not match its hash"
            prev = r.this_hash
        steps = [r.step for r in self._records]
        if steps != sorted(steps) or len(set(steps)) != len(steps):
            return False, f"steps out of order or duplicated: {steps}"
        terminal_at = [i for i, r in enumerate(self._records) if r.action in (ACCEPT, ABSTAIN)]
        if terminal_at and terminal_at[0] != len(self._records) - 1:
            return False, "a decision was committed after the controller had already terminated"
        return True, "ok"


# --------------------------------------------------------------------------
# Driving one instance
# --------------------------------------------------------------------------


@dataclass
class InstanceProgress:
    """Where one instance stands. Reconstructed purely from artifacts on resume."""

    task_name: str
    task_instance_id: int
    committed_steps: int = 0
    terminal_action: str | None = None
    terminal_step: int | None = None
    consumed_indices: list[int] = field(default_factory=list)
    shadow_indices: list[int] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.terminal_action is not None


def decide_step(
    controller: Policy,
    log: DecisionLog,
    *,
    task_name: str,
    task_instance_id: int,
    views: list[TrajectoryView],
    max_k: int,
) -> tuple[Decision, DecisionRecord, bool]:
    """Take — or re-use — the decision after observing ``len(views)`` trajectories.

    Returns ``(decision, record, was_reused)``. A step already present in the log
    is **never recomputed**: on resume the committed decision is authoritative,
    which is what makes a resumed run identical to an uninterrupted one. When the
    decision is new it is committed here, fsynced, before the caller is allowed
    to generate anything further.
    """
    step = len(views)
    existing = log.decision_for_step(step)
    if existing is not None:
        return Decision(existing.action, existing.reason), existing, True

    decision = controller.decide(PolicyState(task_name, tuple(views), max_k))
    res = resolve(views)
    sealed = log.append(
        DecisionRecord(
            task_name=task_name,
            task_instance_id=task_instance_id,
            step=step,
            observed_run_ids=[v.run_id for v in views],
            action=decision.action,
            reason=decision.reason,
            support=res.support,
            k_observed=len(views),
            valid_agreement=res.valid_agreement,
            resolved_cluster_key=res.cluster_key,
            decided_at=time.time(),
            prev_hash=log.last_hash,
        )
    )
    return decision, sealed, False


def read_progress(log_path: str | Path, task_name: str, task_instance_id: int) -> InstanceProgress:
    """Reconstruct an instance's controller state from its decision log alone."""
    log = DecisionLog(log_path)
    prog = InstanceProgress(task_name, task_instance_id, committed_steps=log.n_steps)
    term = log.terminal()
    if term is not None:
        prog.terminal_action = term.action
        prog.terminal_step = term.step
    return prog


__all__ = [
    "ABSTAIN",
    "ACCEPT",
    "CONDITION_CONSUMED",
    "CONDITION_SHADOW",
    "CONTINUE",
    "DECISION_LOG_NAME",
    "GENESIS_HASH",
    "DecisionLog",
    "DecisionRecord",
    "InstanceProgress",
    "build_controller",
    "decide_step",
    "read_progress",
]
