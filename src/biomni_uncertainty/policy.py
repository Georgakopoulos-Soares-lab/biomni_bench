"""Sequential policy replay over a completed K=4 trajectory pool.

A *policy* watches trajectories arrive one at a time and, after each, decides to
ACCEPT the answer it currently holds, CONTINUE (spend another trajectory), or
ABSTAIN. Replaying policies against an already-generated pool costs no model
calls and answers most of the controller-design question before any GPU time is
spent (`reports/phase2_entry_assessment.md` §7 step 6).

Offline replay is **not prospective evidence** and is labelled as such wherever
it is reported.

## The leakage barrier

The policy only ever sees :class:`TrajectoryView`. That dataclass has a fixed
field list which deliberately excludes ``reward``, ``correct``,
``strict_reward``, ``evaluation_status`` and ``trajectory_index`` — the last
because the native index is not knowable online and would let a policy learn
"index 0 is the one that ran first in Phase 1". Rewards live in a separate
mapping on :class:`InstancePool` that no policy receives. :data:`FORBIDDEN_VIEW_FIELDS`
and the tests in ``tests/test_policy.py`` enforce this rather than trusting it.

A policy at step k receives exactly the first k views of the ordering under
replay. Views k+1..K do not exist yet from its point of view and are not
reachable from its state.

## Answer resolution

Plurality over cluster keys, with unparseable answers as singleton clusters
(D-11) so unrelated failures never manufacture a consensus. Ties break to the
**earliest observed position**, which is the only tiebreak available online.
Within one instance a cluster key maps to exactly one reward, so the reward of a
resolved answer is well defined; :func:`InstancePool.reward_of` asserts it.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, fields
from typing import Any

import numpy as np
import pandas as pd

from biomni_uncertainty.features import UNPARSEABLE_PREFIX

ACCEPT = "ACCEPT"
CONTINUE = "CONTINUE"
ABSTAIN = "ABSTAIN"

#: Anything a policy must never be able to read. Enforced by test, not by hope.
FORBIDDEN_VIEW_FIELDS = frozenset(
    {
        "reward",
        "strict_reward",
        "correct",
        "evaluation_status",
        "evaluation_error",
        "trajectory_index",
        "experiment_id",
        "run_dir",
        "error",
    }
)

#: Tasks whose canonical answer is a set; agreement can be graded there.
SET_VALUED_TASKS = frozenset({"patient_gene_detection"})
SET_SEPARATOR = "|"
PREFIX_SEPARATOR = ";"


# --------------------------------------------------------------------------
# What the controller sees
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrajectoryView:
    """One trajectory as visible to the controller at the moment it finishes.

    Every field is observable online without ground truth. ``position`` is the
    1-based arrival order under the ordering being replayed — not the trajectory's
    native index.
    """

    run_id: str
    position: int
    task_name: str
    completed: bool
    answer_parse_status: str
    cluster_key: str
    canonical_answer: str | None
    final_confidence: float | None
    confidence_parse_status: str
    failure_class: str | None
    total_tokens: float
    total_output_tokens: float
    total_input_tokens: float
    llm_call_count: float
    tool_call_count: float
    failed_tool_call_count: float
    code_execution_count: float
    unique_tool_count: float
    retrieval_count: float
    exception_count: float
    visible_plan_step_count: float
    generated_chars: float
    wall_time_seconds: float

    @property
    def execution_failed(self) -> bool:
        """The run did not finish — endpoint failure, budget termination, timeout."""
        return not self.completed

    @property
    def answer_missing(self) -> bool:
        """The run finished but produced no usable answer (empty/ambiguous/unparseable)."""
        return self.completed and (self.answer_parse_status != "ok" or self.cluster_key.startswith(UNPARSEABLE_PREFIX))

    @property
    def usable(self) -> bool:
        """A completed run that yielded a parseable, clusterable answer."""
        return not self.execution_failed and not self.answer_missing

    @property
    def any_failure(self) -> bool:
        return self.execution_failed or self.answer_missing


VIEW_SOURCE_COLUMNS: tuple[str, ...] = tuple(
    f.name for f in fields(TrajectoryView) if f.name not in ("position", "cluster_key")
)


def view_from_row(row: dict[str, Any], position: int) -> TrajectoryView:
    """Build a view from an aggregated trajectory row, dropping everything else.

    The allowlist is the point: any label column present in ``row`` is simply not
    read, so a leak requires editing :class:`TrajectoryView` itself.
    """

    def num(key: str) -> float:
        v = row.get(key)
        try:
            f = float(v)
        except (TypeError, ValueError):
            return math.nan
        return f

    key = row.get("cluster_key") or row.get("answer_cluster_key")
    if key is None or (isinstance(key, float) and math.isnan(key)) or key == "":
        key = f"{UNPARSEABLE_PREFIX}{row['run_id']}"

    conf = row.get("final_confidence")
    conf_f = (
        float(conf) if isinstance(conf, (int, float)) and not (isinstance(conf, float) and math.isnan(conf)) else None
    )
    fc = row.get("failure_class")
    if isinstance(fc, float) and math.isnan(fc):
        fc = None

    return TrajectoryView(
        run_id=str(row["run_id"]),
        position=position,
        task_name=str(row["task_name"]),
        completed=bool(row["completed"]),
        answer_parse_status=str(row.get("answer_parse_status") or "missing"),
        cluster_key=str(key),
        canonical_answer=(
            None
            if row.get("answer_canonical") is None
            or (isinstance(row.get("answer_canonical"), float) and math.isnan(row.get("answer_canonical")))
            else str(row.get("answer_canonical"))
        ),
        final_confidence=conf_f,
        confidence_parse_status=str(row.get("confidence_parse_status") or "missing"),
        failure_class=None if fc is None else str(fc),
        total_tokens=num("total_tokens"),
        total_output_tokens=num("total_output_tokens"),
        total_input_tokens=num("total_input_tokens"),
        llm_call_count=num("llm_call_count"),
        tool_call_count=num("tool_call_count"),
        failed_tool_call_count=num("failed_tool_call_count"),
        code_execution_count=num("code_execution_count"),
        unique_tool_count=num("unique_tool_count"),
        retrieval_count=num("retrieval_count"),
        exception_count=num("exception_count"),
        visible_plan_step_count=num("visible_plan_step_count"),
        generated_chars=num("generated_chars"),
        wall_time_seconds=num("wall_time_seconds"),
    )


# --------------------------------------------------------------------------
# The hidden side
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class InstancePool:
    """One benchmark instance's K trajectories, with rewards kept apart.

    ``rewards`` is the evaluation-only side of the pool. It is read by the
    replay harness to score an outcome, and by oracle policies which are labelled
    non-deployable upper bounds. It is never reachable from a
    :class:`PolicyState`.
    """

    task_name: str
    task_instance_id: int
    rows: tuple[dict[str, Any], ...]
    rewards: dict[str, float]

    @property
    def key(self) -> tuple[str, int]:
        return (self.task_name, self.task_instance_id)

    @property
    def k(self) -> int:
        return len(self.rows)

    def views(self, ordering: Sequence[int]) -> tuple[TrajectoryView, ...]:
        return tuple(view_from_row(self.rows[j], position=i + 1) for i, j in enumerate(ordering))

    def reward_of(self, cluster_key: str, members: Sequence[TrajectoryView]) -> float:
        """Reward of a resolved cluster; asserts the cluster is reward-consistent."""
        vals = {self.rewards[m.run_id] for m in members if m.cluster_key == cluster_key}
        if not vals:
            raise KeyError(f"no members for cluster {cluster_key!r}")
        if len(vals) > 1:
            raise ValueError(f"cluster {cluster_key!r} has inconsistent rewards {sorted(vals)}")
        return float(next(iter(vals)))


def build_pools(instrumented: pd.DataFrame) -> list[InstancePool]:
    """Group an instrumented trajectory table into per-instance pools.

    Rows are ordered by ``trajectory_index`` so orderings index into a stable
    list; the index itself never reaches a view.
    """
    pools = []
    for (task, tid), g in instrumented.groupby(["task_name", "task_instance_id"], sort=True):
        g = g.sort_values("trajectory_index")
        rows = tuple(g.to_dict("records"))
        rewards = {str(r["run_id"]): float(r["reward"]) for r in rows}
        pools.append(InstancePool(str(task), int(tid), rows, rewards))
    return pools


# --------------------------------------------------------------------------
# Agreement and resolution
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """The answer a policy currently holds, plus how much support it has."""

    cluster_key: str
    canonical_answer: str | None
    members: tuple[TrajectoryView, ...]
    support: int
    k: int
    is_tie: bool
    n_usable: int
    n_failed: int

    @property
    def support_fraction(self) -> float:
        return self.support / self.k

    @property
    def usable_support_fraction(self) -> float:
        """Support as a fraction of K, counting only clusters of usable answers."""
        return 0.0 if not self.rests_on_usable else self.support / self.k

    @property
    def rests_on_usable(self) -> bool:
        return all(m.usable for m in self.members)

    @property
    def valid_agreement(self) -> bool:
        """At least two *usable* trajectories reached the same answer."""
        return self.support >= 2 and self.rests_on_usable


def resolve(views: Sequence[TrajectoryView]) -> Resolution:
    """Plurality over cluster keys; ties break to the earliest observed position.

    A trajectory that died or produced no parseable answer can never *win*. It is
    still a singleton cluster (D-11) and still counts against the support
    fraction, but a real answer beats a non-answer even when the non-answer
    arrived first. Without this an execution failure in slot 1 would win the tie
    against a good analysis in slot 2 and the controller would hand back nothing
    — a distinction it can draw online, with no ground truth.
    """
    if not views:
        raise ValueError("resolve() needs at least one view")
    counts = Counter(v.cluster_key for v in views)
    eligible = {v.cluster_key for v in views if v.usable} or set(counts)
    top = max(counts[k] for k in eligible)
    tied = [k for k in eligible if counts[k] == top]
    first_pos = {}
    for v in views:
        first_pos.setdefault(v.cluster_key, v.position)
    winner = min(tied, key=lambda k: (first_pos[k], k))
    members = tuple(v for v in views if v.cluster_key == winner)
    return Resolution(
        cluster_key=winner,
        canonical_answer=members[0].canonical_answer,
        members=members,
        support=top,
        k=len(views),
        is_tie=len(tied) > 1,
        n_usable=sum(1 for v in views if v.usable),
        n_failed=sum(1 for v in views if v.any_failure),
    )


def _as_set(key: str) -> frozenset[str]:
    return frozenset(p for p in key.split(SET_SEPARATOR) if p)


def answer_similarity(task_name: str, a: TrajectoryView, b: TrajectoryView) -> float:
    """Task-aware similarity in [0,1] between two observed answers.

    Exact cluster identity for single-label tasks. For set-valued tasks
    (``patient_gene_detection``, whose official reward intersects predicted and
    true gene sets) partial overlap is real partial agreement, so Jaccard is
    used. Unusable answers never agree with anything, including each other.
    """
    if not a.usable or not b.usable:
        return 0.0
    if a.cluster_key == b.cluster_key:
        return 1.0
    if task_name not in SET_VALUED_TASKS:
        return 0.0
    sa, sb = _as_set(a.cluster_key), _as_set(b.cluster_key)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def soft_support(task_name: str, views: Sequence[TrajectoryView], res: Resolution) -> float:
    """Graded support for the resolved answer under task-aware similarity."""
    lead = res.members[0]
    return float(sum(answer_similarity(task_name, lead, v) for v in views))


# --------------------------------------------------------------------------
# Policy interface
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyState:
    """Everything a policy may condition on at step k. Nothing else exists."""

    task_name: str
    views: tuple[TrajectoryView, ...]
    k_max: int

    @property
    def k(self) -> int:
        return len(self.views)

    @property
    def last(self) -> TrajectoryView:
        return self.views[-1]

    @property
    def is_final_step(self) -> bool:
        return self.k >= self.k_max

    def resolution(self) -> Resolution:
        return resolve(self.views)


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    reliability: float | None = None


#: A scorer maps a trajectory, or a whole observed prefix, to an out-of-fold
#: calibrated probability that the held answer is correct. Scorers are supplied
#: by the harness and are pre-computed out-of-fold; policies never fit anything
#: themselves, so a policy cannot see its own instance's label through one.
K1Scorer = Callable[[TrajectoryView], float | None]
ResolutionScorer = Callable[["PolicyState", Resolution], float | None]

#: Acceptance thresholds are functions of the trajectory, not constants, so a
#: nested cross-validated threshold (a different value per outer fold) is
#: expressible without a policy ever seeing which fold it is in.
ThresholdFn = Callable[[TrajectoryView], float]


def const_threshold(value: float) -> ThresholdFn:
    """A fixed acceptance threshold, for sweeps and for reporting a frontier."""

    def fn(_: TrajectoryView) -> float:
        return value

    return fn


class Policy:
    """Base class. Subclasses implement :meth:`decide`.

    A policy must not return ``CONTINUE`` on the final step; the replay harness
    raises if it does, and ``tests/test_policy.py`` checks every registered
    policy against that contract.
    """

    name: str = "policy"
    deployable: bool = True
    description: str = ""

    def decide(self, state: PolicyState) -> Decision:  # pragma: no cover - abstract
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} {self.name}>"


class FixedK(Policy):
    """Spend exactly n trajectories, then answer by plurality. The baseline."""

    def __init__(self, n: int):
        self.n = n
        self.name = f"fixed_k{n}"
        self.description = f"always run {n} trajectories, answer by plurality"

    def decide(self, state: PolicyState) -> Decision:
        if state.k < min(self.n, state.k_max):
            return Decision(CONTINUE, f"fixed budget {self.n}, at k={state.k}")
        return Decision(ACCEPT, f"reached fixed budget {self.n}")


class MandatoryK2(Policy):
    """Always take a second opinion; stop as soon as two usable answers agree.

    The honest default: it never accepts a single unverified analysis, so it
    needs no K=1 uncertainty signal at all.
    """

    def __init__(self, *, max_k: int = 4, name: str | None = None):
        self.max_k = max_k
        self.name = name or f"mandatory_k2_upto{max_k}"
        self.description = f"mandatory second trajectory; continue on disagreement up to K={max_k}"

    def decide(self, state: PolicyState) -> Decision:
        cap = min(self.max_k, state.k_max)
        if state.k < 2:
            return Decision(CONTINUE, "mandatory verification: one analysis is never enough")
        res = state.resolution()
        if res.valid_agreement:
            return Decision(ACCEPT, f"valid agreement {res.support}/{res.k}", res.support_fraction)
        if state.k < cap:
            return Decision(CONTINUE, f"no valid agreement at k={state.k}")
        return Decision(ACCEPT, f"budget exhausted at K={cap}, plurality answer", res.support_fraction)


class K1Selective(MandatoryK2):
    """Mandatory-K=2, except a single trajectory may be accepted when a calibrated
    out-of-fold probability clears ``threshold`` and no failure override fires.

    The override is not a tiebreak: an execution failure or an unparseable answer
    blocks acceptance regardless of what the score says.
    """

    def __init__(
        self,
        scorer: K1Scorer,
        threshold: ThresholdFn,
        *,
        max_k: int = 4,
        name: str = "k1_selective",
    ):
        super().__init__(max_k=max_k, name=name)
        self.scorer = scorer
        self.threshold = threshold
        self.description = (
            "accept after one trajectory when OOF-calibrated P(correct) clears the threshold "
            "and no execution/parse failure fires; otherwise mandatory K=2"
        )

    def decide(self, state: PolicyState) -> Decision:
        if state.k == 1:
            v = state.last
            if v.any_failure:
                return Decision(
                    CONTINUE,
                    f"failure override ({'execution' if v.execution_failed else 'no parseable answer'})",
                )
            tau = self.threshold(v)
            p = self.scorer(v)
            if p is not None and p >= tau:
                return Decision(ACCEPT, f"calibrated P(correct)={p:.3f} >= {tau:.3f}", p)
            shown = "unavailable" if p is None else f"{p:.3f}"
            return Decision(CONTINUE, f"calibrated P(correct)={shown} < {tau:.3f}")
        return super().decide(state)


class ConfidenceEscalation(Policy):
    """Confidence-only: accept as soon as the best observed calibrated confidence
    clears ``threshold``. No agreement signal, no failure override — deliberately,
    so its contribution is separable from theirs."""

    def __init__(self, scorer: K1Scorer, threshold: float, *, name: str | None = None):
        self.scorer = scorer
        self.threshold = threshold
        self.name = name or f"confidence_escalation_t{threshold:.2f}"
        self.description = f"accept when calibrated confidence of the best observed trajectory >= {threshold:.2f}"

    def decide(self, state: PolicyState) -> Decision:
        scored = [(self.scorer(v), v) for v in state.views]
        best = max((p for p, _ in scored if p is not None), default=None)
        if best is not None and best >= self.threshold:
            return Decision(ACCEPT, f"confidence {best:.3f} >= {self.threshold:.2f}", best)
        if state.is_final_step:
            return Decision(ACCEPT, "budget exhausted, plurality answer", best)
        return Decision(CONTINUE, f"confidence {'unavailable' if best is None else f'{best:.3f}'} below threshold")


class FailureEscalation(Policy):
    """Failure-only: accept the first trajectory that ran and parsed; spend more
    only to replace a failed one. The pure REPAIR-shaped policy."""

    def __init__(self, *, name: str | None = None):
        self.name = name or "failure_escalation"
        self.description = "accept the first usable trajectory; continue only after an execution/parse failure"

    def decide(self, state: PolicyState) -> Decision:
        if state.last.usable:
            return Decision(ACCEPT, "trajectory completed with a parseable answer")
        if state.is_final_step:
            return Decision(ACCEPT, "budget exhausted after repeated failures, plurality answer")
        return Decision(
            CONTINUE,
            f"failure override ({'execution' if state.last.execution_failed else 'no parseable answer'})",
        )


class CombinedAdaptive(Policy):
    """Failure override, then K=1 selective acceptance, then agreement-based
    stopping. The simplest policy that uses all three signals, and no more."""

    def __init__(
        self,
        scorer: K1Scorer,
        threshold: ThresholdFn,
        *,
        max_k: int = 4,
        name: str = "combined_adaptive",
    ):
        self.scorer = scorer
        self.threshold = threshold
        self.max_k = max_k
        self.name = name
        self.description = "failure override -> calibrated K=1 acceptance -> agreement stopping"

    def decide(self, state: PolicyState) -> Decision:
        cap = min(self.max_k, state.k_max)
        res = state.resolution()
        if state.last.any_failure and state.k < cap:
            return Decision(CONTINUE, "failure override: replace the failed analysis")
        if state.k == 1:
            tau = self.threshold(state.last)
            p = self.scorer(state.last)
            if state.last.usable and p is not None and p >= tau:
                return Decision(ACCEPT, f"calibrated P(correct)={p:.3f} >= {tau:.3f}", p)
            if state.k < cap:
                return Decision(CONTINUE, "single unverified analysis below acceptance threshold")
        if res.valid_agreement:
            return Decision(ACCEPT, f"valid agreement {res.support}/{res.k}", res.support_fraction)
        if state.k < cap:
            return Decision(CONTINUE, f"no valid agreement at k={state.k}")
        return Decision(ACCEPT, f"budget exhausted at K={cap}, plurality answer", res.support_fraction)


class Abstaining(Policy):
    """Wrap a policy: at the moment it would accept, abstain instead when the
    resolved answer's calibrated reliability falls below ``threshold``.

    Escalation to a human is the action; this replay measures only when it fires.
    """

    def __init__(
        self,
        base: Policy,
        resolution_scorer: ResolutionScorer,
        threshold: float,
        *,
        name: str | None = None,
    ):
        self.base = base
        self.resolution_scorer = resolution_scorer
        self.threshold = threshold
        self.deployable = base.deployable
        self.name = name or f"{base.name}__abstain_t{threshold:.2f}"
        self.description = f"{base.name}, abstaining when resolved reliability < {threshold:.2f}"

    def decide(self, state: PolicyState) -> Decision:
        d = self.base.decide(state)
        if d.action != ACCEPT:
            return d
        p = self.resolution_scorer(state, state.resolution())
        if p is not None and p < self.threshold:
            return Decision(ABSTAIN, f"resolved reliability {p:.3f} < {self.threshold:.2f}; escalate", p)
        return Decision(d.action, d.reason, p if p is not None else d.reliability)


class OracleStop(Policy):
    """UPPER BOUND ONLY — reads ground truth. Stops at the first correct
    trajectory, else spends the full budget. Not deployable, never a baseline."""

    deployable = False

    def __init__(self, rewards: dict[str, float], *, name: str = "oracle_stop"):
        self.rewards = rewards
        self.name = name
        self.description = "stop at the first correct trajectory - UPPER BOUND, uses ground truth"

    def decide(self, state: PolicyState) -> Decision:
        if self.rewards.get(state.last.run_id, 0.0) > 0:
            return Decision(ACCEPT, "oracle: this trajectory is correct")
        if state.is_final_step:
            return Decision(ACCEPT, "oracle: no correct trajectory in budget")
        return Decision(CONTINUE, "oracle: this trajectory is wrong")


class OracleAtK(Policy):
    """UPPER BOUND ONLY — spends exactly n and returns the best of them."""

    deployable = False

    def __init__(self, rewards: dict[str, float], n: int):
        self.rewards = rewards
        self.n = n
        self.name = f"oracle_at_k{n}"
        self.description = f"best of {n} trajectories - UPPER BOUND, uses ground truth"

    def decide(self, state: PolicyState) -> Decision:
        if state.k < min(self.n, state.k_max):
            return Decision(CONTINUE, f"oracle budget {self.n}")
        return Decision(ACCEPT, f"oracle best-of-{self.n}")


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayOutcome:
    policy: str
    deployable: bool
    task_name: str
    task_instance_id: int
    ordering: tuple[int, ...]
    #: run_ids of the trajectories actually consumed, in arrival order. Keeps the
    #: stopping prefix auditable and lets reliability be looked up post hoc.
    prefix: tuple[str, ...]
    k_used: int
    action: str
    stop_reason: str
    answered: bool
    reward: float | None
    reward_abstain_zero: float
    reliability: float | None
    support: int
    support_fraction: float
    valid_agreement: bool
    soft_support: float
    n_failed_seen: int
    first_view_failed: bool
    resolved_after_failure: bool
    recovered_failure: bool
    total_tokens: float
    total_output_tokens: float
    llm_calls: float
    tool_calls: float
    wall_time_seconds: float

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["ordering"] = "".join(str(i) for i in self.ordering)
        d["prefix"] = PREFIX_SEPARATOR.join(self.prefix)
        return d


def _oracle_reward(pool: InstancePool, views: Sequence[TrajectoryView]) -> float:
    return max((pool.rewards[v.run_id] for v in views), default=0.0)


def replay_one(policy: Policy, pool: InstancePool, ordering: Sequence[int]) -> ReplayOutcome:
    """Run one policy over one instance under one arrival ordering."""
    views = pool.views(ordering)
    k_max = len(views)
    decision = None
    k = 0
    for k in range(1, k_max + 1):
        state = PolicyState(pool.task_name, views[:k], k_max)
        decision = policy.decide(state)
        if decision.action == CONTINUE:
            if k == k_max:
                raise RuntimeError(
                    f"policy {policy.name!r} returned CONTINUE at the final step k={k}; "
                    "a policy must ACCEPT or ABSTAIN when the budget is exhausted"
                )
            continue
        break

    assert decision is not None
    seen = views[:k]
    res = resolve(seen)

    if isinstance(policy, OracleAtK | OracleStop):
        reward: float | None = _oracle_reward(pool, seen)
    else:
        reward = pool.reward_of(res.cluster_key, res.members)

    answered = decision.action == ACCEPT
    first_failed = views[0].any_failure

    return ReplayOutcome(
        policy=policy.name,
        deployable=policy.deployable,
        task_name=pool.task_name,
        task_instance_id=pool.task_instance_id,
        ordering=tuple(ordering),
        prefix=tuple(v.run_id for v in seen),
        k_used=k,
        action=decision.action,
        stop_reason=decision.reason,
        answered=answered,
        reward=reward if answered else None,
        reward_abstain_zero=float(reward) if answered else 0.0,
        reliability=decision.reliability,
        support=res.support,
        support_fraction=res.support_fraction,
        valid_agreement=res.valid_agreement,
        soft_support=soft_support(pool.task_name, seen, res),
        n_failed_seen=res.n_failed,
        first_view_failed=first_failed,
        # Two levels of "the controller repaired a broken workflow": it ended up
        # holding a real answer, and separately, that answer was right.
        resolved_after_failure=bool(first_failed and answered and res.rests_on_usable),
        recovered_failure=bool(first_failed and answered and (reward or 0.0) > 0),
        total_tokens=float(np.nansum([v.total_tokens for v in seen])),
        total_output_tokens=float(np.nansum([v.total_output_tokens for v in seen])),
        llm_calls=float(np.nansum([v.llm_call_count for v in seen])),
        tool_calls=float(np.nansum([v.tool_call_count for v in seen])),
        wall_time_seconds=float(np.nansum([v.wall_time_seconds for v in seen])),
    )


def all_orderings(k: int) -> list[tuple[int, ...]]:
    """Every arrival ordering of k trajectories. K=4 gives 24 — exhaustive, so
    no trajectory-index artifact can survive averaging over them."""
    return list(itertools.permutations(range(k)))


def replay_policy(policy: Policy, pools: Iterable[InstancePool]) -> pd.DataFrame:
    """Replay one policy over every instance under every ordering."""
    rows = []
    for pool in pools:
        for ordering in all_orderings(pool.k):
            rows.append(replay_one(policy, pool, ordering).to_dict())
    return pd.DataFrame(rows)


def replay_many(policies: Sequence[Policy], pools: Sequence[InstancePool]) -> pd.DataFrame:
    return pd.concat([replay_policy(p, pools) for p in policies], ignore_index=True)


def per_instance(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Average each policy's outcome over all orderings, per instance.

    This is the analysis unit: one row per (policy, instance). Averaging over the
    exhaustive ordering set removes the trajectory-index artifact; keeping the
    instance as the row keeps the bootstrap unit correct (D-13).
    """
    g = outcomes.groupby(["policy", "deployable", "task_name", "task_instance_id"], sort=True)
    out = g.agg(
        n_orderings=("k_used", "size"),
        reward=("reward_abstain_zero", "mean"),
        reward_answered_only=("reward", "mean"),
        coverage=("answered", "mean"),
        abstention_rate=("answered", lambda s: 1.0 - s.mean()),
        mean_k=("k_used", "mean"),
        total_tokens=("total_tokens", "mean"),
        total_output_tokens=("total_output_tokens", "mean"),
        llm_calls=("llm_calls", "mean"),
        tool_calls=("tool_calls", "mean"),
        wall_time_seconds=("wall_time_seconds", "mean"),
        valid_agreement_rate=("valid_agreement", "mean"),
        first_view_failed_rate=("first_view_failed", "mean"),
        resolved_after_failure_rate=("resolved_after_failure", "mean"),
        recovered_failure_rate=("recovered_failure", "mean"),
    ).reset_index()
    for k in (1, 2, 3, 4):
        frac = g["k_used"].apply(lambda s, k=k: float((s == k).mean())).reset_index(name=f"frac_stop_k{k}")
        out = out.merge(frac, on=["policy", "deployable", "task_name", "task_instance_id"])
    return out
