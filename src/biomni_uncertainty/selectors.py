"""Trajectory selectors.

Every selector picks ONE of an instance's K candidate trajectories using only
signals available at inference time. The single exception is ``oracle``, which
is an upper bound and is labelled as such everywhere it appears.

A selector returns a :class:`Selection` recording what was chosen, why, whether
a tie had to be broken, and how missing features were handled.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from biomni_uncertainty.features import UNPARSEABLE_PREFIX, consensus

# Deterministic fallback everywhere: lowest trajectory_index.
TIEBREAK = "lowest_trajectory_index"


@dataclass(frozen=True)
class Candidate:
    """One trajectory as seen by a selector."""

    run_id: str
    trajectory_index: int
    cluster_key: str
    canonical_answer: str | None
    confidence: float | None  # normalized [0,1]; None when missing/malformed
    length: float | None  # primary length field (default: total output tokens)
    reward: float | None  # ground truth - ONLY read by the oracle selector
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Selection:
    selector: str
    run_id: str | None
    canonical_answer: str | None
    reward: float | None
    reason: str
    tie_broken: bool
    tied_run_ids: tuple[str, ...] = ()
    missing_feature_handling: str = "none"

    def to_dict(self) -> dict:
        return asdict(self)


def _sorted(cands: list[Candidate]) -> list[Candidate]:
    return sorted(cands, key=lambda c: c.trajectory_index)


def _plurality_cluster(cands: list[Candidate]) -> tuple[list[Candidate], bool, tuple[str, ...]]:
    keys = [c.cluster_key for c in _sorted(cands)]
    order = [c.trajectory_index for c in _sorted(cands)]
    res = consensus(keys, order)
    members = [c for c in _sorted(cands) if c.cluster_key == res.plurality_key]
    return members, res.is_tie, res.tied_keys


def _argbest(
    pool: list[Candidate],
    key: Callable[[Candidate], float | None],
    *,
    maximize: bool,
) -> tuple[Candidate | None, bool, tuple[str, ...], int]:
    """Best candidate by ``key``, ignoring candidates whose key is missing.

    Returns ``(winner, tie_broken, tied_run_ids, n_missing)``.
    """
    scored = [(c, key(c)) for c in _sorted(pool)]
    usable = [(c, v) for c, v in scored if v is not None and not (isinstance(v, float) and math.isnan(v))]
    n_missing = len(scored) - len(usable)
    if not usable:
        return None, False, (), n_missing
    best = max(v for _, v in usable) if maximize else min(v for _, v in usable)
    tied = [c for c, v in usable if v == best]
    return tied[0], len(tied) > 1, tuple(c.run_id for c in tied), n_missing


def _sel(
    name: str, c: Candidate | None, reason: str, tie: bool = False, tied: tuple = (), missing: str = "none"
) -> Selection:
    if c is None:
        return Selection(name, None, None, None, reason, tie, tied, missing)
    return Selection(name, c.run_id, c.canonical_answer, c.reward, reason, tie, tied, missing)


# --------------------------------------------------------------------------
# Selectors
# --------------------------------------------------------------------------


def select_first(cands: list[Candidate]) -> Selection:
    """Trajectory index 0 (or the lowest index present)."""
    c = _sorted(cands)[0]
    return _sel("first", c, "lowest trajectory_index")


def random_expected(cands: list[Candidate]) -> float | None:
    """Expected reward of picking uniformly at random among K candidates.

    Reported as a mean rather than a single sampled draw; a concrete sampled
    baseline is produced separately by :func:`random_sampled`.
    """
    vals = [c.reward for c in cands if c.reward is not None]
    return float(np.mean(vals)) if vals else None


def random_sampled(cands: list[Candidate], rng: np.random.Generator) -> Selection:
    """One concrete uniform draw. Used with repeated deterministic resampling."""
    pool = _sorted(cands)
    c = pool[int(rng.integers(len(pool)))]
    return _sel("random_sampled", c, "uniform draw over K candidates")


def select_plurality(cands: list[Candidate]) -> Selection:
    """Largest agreement cluster; ties broken by lowest trajectory index."""
    members, tie, tied_keys = _plurality_cluster(cands)
    c = members[0]
    return _sel(
        "plurality",
        c,
        f"largest agreement cluster (size {len(members)}/{len(cands)})",
        tie,
        tuple(m.run_id for m in members) if tie else (),
    )


def select_max_confidence(cands: list[Candidate]) -> Selection:
    """Highest valid final confidence.

    When no candidate has a valid confidence the selector falls back to the
    first trajectory, and the fallback is recorded rather than silently applied.
    """
    c, tie, tied, n_missing = _argbest(cands, lambda x: x.confidence, maximize=True)
    if c is None:
        fb = _sorted(cands)[0]
        return _sel(
            "max_confidence",
            fb,
            "no valid confidence for any candidate; fell back to first trajectory",
            missing="all_missing_fallback_first",
        )
    return _sel(
        "max_confidence",
        c,
        f"highest confidence ({c.confidence})",
        tie,
        tied,
        missing=f"{n_missing}_candidates_missing_confidence" if n_missing else "none",
    )


def select_min_length(
    cands: list[Candidate], length_key: Callable[[Candidate], float | None] | None = None
) -> Selection:
    """Smallest trace length (default: total output tokens)."""
    key = length_key or (lambda c: c.length)
    c, tie, tied, n_missing = _argbest(cands, key, maximize=False)
    if c is None:
        fb = _sorted(cands)[0]
        return _sel("min_length", fb, "no length available; fell back to first", missing="all_missing_fallback_first")
    return _sel(
        "min_length",
        c,
        f"shortest trace ({key(c)})",
        tie,
        tied,
        missing=f"{n_missing}_candidates_missing_length" if n_missing else "none",
    )


def select_plurality_then_confidence(cands: list[Candidate]) -> Selection:
    members, _, _ = _plurality_cluster(cands)
    c, tie, tied, n_missing = _argbest(members, lambda x: x.confidence, maximize=True)
    if c is None:
        return _sel(
            "plurality_then_confidence",
            members[0],
            "plurality cluster; no valid confidence inside it, fell back to lowest index",
            missing="all_missing_fallback_first_in_cluster",
        )
    return _sel(
        "plurality_then_confidence",
        c,
        f"plurality cluster (size {len(members)}), highest confidence ({c.confidence})",
        tie,
        tied,
        missing=f"{n_missing}_in_cluster_missing_confidence" if n_missing else "none",
    )


def select_plurality_then_shortest(cands: list[Candidate]) -> Selection:
    members, _, _ = _plurality_cluster(cands)
    c, tie, tied, n_missing = _argbest(members, lambda x: x.length, maximize=False)
    if c is None:
        return _sel(
            "plurality_then_shortest",
            members[0],
            "plurality cluster; no length inside it, fell back to lowest index",
            missing="all_missing_fallback_first_in_cluster",
        )
    return _sel(
        "plurality_then_shortest",
        c,
        f"plurality cluster (size {len(members)}), shortest trace ({c.length})",
        tie,
        tied,
        missing=f"{n_missing}_in_cluster_missing_length" if n_missing else "none",
    )


def srlm_score(confidence: float | None, length: float | None, epsilon: float) -> float | None:
    """SRLM-style final-confidence approximation.

    ``score = log(clamp(confidence, epsilon, 1.0)) * length``

    ``log(.) <= 0`` and ``length >= 0``, so the score is non-positive and the
    MAXIMUM (closest to zero) marks high confidence and/or a short trace. This
    is an approximation built from final-answer confidence only; it is not a
    reproduction of step-level SRLM, which needs per-step confidences that this
    agent architecture does not expose (see DECISIONS.md).
    """
    if confidence is None or length is None:
        return None
    if isinstance(confidence, float) and math.isnan(confidence):
        return None
    if isinstance(length, float) and math.isnan(length):
        return None
    c = min(max(float(confidence), epsilon), 1.0)
    return math.log(c) * float(length)


def select_srlm_style(cands: list[Candidate], epsilon: float = 1e-3) -> Selection:
    members, _, _ = _plurality_cluster(cands)
    c, tie, tied, n_missing = _argbest(members, lambda x: srlm_score(x.confidence, x.length, epsilon), maximize=True)
    if c is None:
        return _sel(
            "srlm_style",
            members[0],
            "plurality cluster; SRLM-style score undefined for all members, fell back to lowest index",
            missing="all_missing_fallback_first_in_cluster",
        )
    return _sel(
        "srlm_style",
        c,
        f"plurality cluster (size {len(members)}), max SRLM-style score "
        f"({srlm_score(c.confidence, c.length, epsilon):.3f})",
        tie,
        tied,
        missing=f"{n_missing}_in_cluster_missing_score" if n_missing else "none",
    )


def select_rank_combination(cands: list[Candidate]) -> Selection:
    """Within the plurality cluster: equal-weight sum of descending-confidence
    rank and ascending-length rank. Lower combined rank wins.

    Candidates missing a signal receive the worst rank for that signal, which is
    recorded; they are not dropped, so the cluster's size stays interpretable.
    """
    members, _, _ = _plurality_cluster(cands)
    n = len(members)
    if n == 1:
        return _sel("rank_combination", members[0], "plurality cluster has a single member")

    def ranks(values: list[float | None], *, ascending: bool) -> list[float]:
        usable = [
            (i, v) for i, v in enumerate(values) if v is not None and not (isinstance(v, float) and math.isnan(v))
        ]
        out = [float(n)] * n  # worst rank for missing
        if not usable:
            return out
        order = sorted(usable, key=lambda iv: iv[1], reverse=not ascending)
        # average ranks for ties
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and order[j + 1][1] == order[i][1]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k][0]] = avg
            i = j + 1
        return out

    conf_rank = ranks([m.confidence for m in members], ascending=False)
    len_rank = ranks([m.length for m in members], ascending=True)
    combined = [conf_rank[i] + len_rank[i] for i in range(n)]
    n_missing = sum(1 for m in members if m.confidence is None or m.length is None)

    best = min(combined)
    tied_idx = [i for i, v in enumerate(combined) if v == best]
    winner = members[tied_idx[0]]  # members are index-sorted -> deterministic
    return _sel(
        "rank_combination",
        winner,
        f"plurality cluster (size {n}), min combined rank ({best:.1f})",
        len(tied_idx) > 1,
        tuple(members[i].run_id for i in tied_idx) if len(tied_idx) > 1 else (),
        missing=f"{n_missing}_members_missing_a_signal" if n_missing else "none",
    )


def _is_number(v: object) -> bool:
    """A usable numeric value: not None, not NaN."""
    return isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))


def select_oracle(cands: list[Candidate]) -> Selection:
    """UPPER BOUND ONLY - reads ground truth. Never a deployable method."""
    # A NaN reward (evaluator failure, or a run with no record) must be excluded
    # rather than compared: NaN != NaN leaves the tie list empty and crashes.
    scored = [c for c in _sorted(cands) if _is_number(c.reward)]
    if not scored:
        return _sel("oracle", None, None, "no candidate has a reward")
    best = max(c.reward for c in scored)
    tied = [c for c in scored if c.reward == best]
    return _sel(
        "oracle",
        tied[0],
        f"best available reward ({best}) - UPPER BOUND, uses ground truth",
        len(tied) > 1,
        tuple(c.run_id for c in tied) if len(tied) > 1 else (),
    )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

DEPLOYABLE_SELECTORS = (
    "first",
    "plurality",
    "max_confidence",
    "min_length",
    "plurality_then_confidence",
    "plurality_then_shortest",
    "srlm_style",
    "rank_combination",
)

PRIMARY_SELECTORS = ("first", "plurality", "srlm_style", "rank_combination")


def run_all_selectors(cands: list[Candidate], *, epsilon: float = 1e-3) -> dict[str, Selection]:
    """Apply every selector to one instance's candidate set."""
    if not cands:
        raise ValueError("run_all_selectors requires at least one candidate")
    out = {
        "first": select_first(cands),
        "plurality": select_plurality(cands),
        "max_confidence": select_max_confidence(cands),
        "min_length": select_min_length(cands),
        "plurality_then_confidence": select_plurality_then_confidence(cands),
        "plurality_then_shortest": select_plurality_then_shortest(cands),
        "srlm_style": select_srlm_style(cands, epsilon=epsilon),
        "rank_combination": select_rank_combination(cands),
        "oracle": select_oracle(cands),
    }
    return out


def candidates_from_frame(df: Any, *, length_field: str = "total_output_tokens") -> list[Candidate]:
    """Build candidates for one instance from a trajectory-level frame slice."""
    out = []
    for r in df.sort_values("trajectory_index").to_dict("records"):
        key = r.get("cluster_key") or r.get("answer_cluster_key")
        if key is None or (isinstance(key, float) and math.isnan(key)):
            key = f"{UNPARSEABLE_PREFIX}{r['run_id']}"
        conf = r.get("final_confidence")
        length = r.get(length_field)
        reward = r.get("reward")
        answer = r.get("answer_canonical")
        out.append(
            Candidate(
                run_id=r["run_id"],
                trajectory_index=int(r["trajectory_index"]),
                cluster_key=str(key),
                # pandas turns a missing object into NaN; normalize back to None
                # so downstream comparisons stay well defined.
                canonical_answer=None if isinstance(answer, float) and math.isnan(answer) else answer,
                confidence=float(conf) if _is_number(conf) else None,
                length=float(length) if _is_number(length) else None,
                reward=float(reward) if _is_number(reward) else None,
            )
        )
    return out
