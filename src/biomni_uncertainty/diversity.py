"""Trajectory diversity primitives (Track C).

The Track-C question is whether two trajectories that disagree are doing
*different science* or the same thing twice with a different final token. That
needs a definition of "different" that is structural and reproducible, not a
judgement call, so everything here is a set or sequence comparison over what the
agent actually did:

======================  ====================================================
level                   what is compared
======================  ====================================================
answer                  canonical cluster keys (already computed upstream)
plan                    content words of the **first** ``<think>`` block
tool path               the ordered list of tool names actually invoked
evidence                query arguments issued, and exact code-block hashes
======================  ====================================================

**Why the first ``<think>`` block is the plan.** It is emitted before any tool
runs, so it is the trajectory's own opening analysis conditioned on nothing but
the task prompt. Later reasoning is contaminated by observations, which are
themselves a function of earlier tool choices; comparing whole transcripts would
therefore measure how much the *environment* diverged, not how much the *plan*
did.

**What is deliberately not used.** ``system_prompt.txt`` takes exactly two
distinct values across all 600 Phase-2B trajectories (one per condition), so it
is a static base prompt and carries no per-trajectory retrieval signal. The
``retrieval_end`` event records only *counts* of selected tools, never their
names, so retrieval overlap cannot be measured directly; the counts are carried
as a coarse descriptor and nothing is inferred from them about *which* evidence
was retrieved.

No embedding model and no LLM judge is used. If those become necessary the
report says so explicitly and labels the result exploratory.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Words carrying no discriminative content for "did these two plan differently".
#: Deliberately short and generic - a long hand-tuned list would be a fitted
#: parameter in disguise. Domain terms are never removed.
STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then than that this these those there here of to in on at by for with
    from as is are was were be been being do does did doing have has had having will would shall
    should can could may might must not no nor so such it its i me my we our you your he she they
    them their what which who whom when where why how all any both each few more most other some
    only own same too very just also about into over under again further once
    let need needs let's lets user asking ask question answer answers option options given
    """.split()
)

TOKEN_RE = re.compile(r"[a-z0-9_]+")
THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def tokenize(text: str | None, *, min_len: int = 3) -> frozenset[str]:
    """Lower-cased content-word set. Order-free by construction."""
    if not text:
        return frozenset()
    toks = TOKEN_RE.findall(text.lower())
    return frozenset(t for t in toks if len(t) >= min_len and t not in STOPWORDS)


def jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float | None:
    """|A n B| / |A u B|. ``None`` when either side is empty.

    Returning ``None`` rather than 0.0 matters: an empty tool set means the
    trajectory used no tools, which is *missing* comparability, not *maximal*
    difference. Scoring it 0.0 would silently label every degenerate run as
    maximally independent - the exact error that would manufacture a positive
    Track-C result.
    """
    if not a or not b:
        return None
    return len(set(a) & set(b)) / len(set(a) | set(b))


def sequence_similarity(a: list[str], b: list[str]) -> float | None:
    """Order-sensitive similarity of two tool paths, in [0, 1]. ``None`` if either
    is empty, for the same reason as :func:`jaccard`."""
    if not a or not b:
        return None
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


@dataclass(frozen=True)
class TrajectoryTrace:
    """Everything one trajectory did, reduced to comparable structure."""

    run_id: str
    task_name: str
    task_instance_id: int
    trajectory_index: int
    condition: str
    completed: bool
    failure_class: str | None
    #: ordered tool names as invoked
    tool_seq: tuple[str, ...] = ()
    #: tools whose call returned without error
    tool_seq_ok: tuple[str, ...] = ()
    code_hashes: tuple[str, ...] = ()
    #: content words of every tool-call argument excerpt, pooled
    query_tokens: frozenset[str] = frozenset()
    #: content words of the first <think> block
    plan_tokens: frozenset[str] = frozenset()
    plan_text: str = ""
    n_think_blocks: int = 0
    n_tool_calls: int = 0
    n_failed_tool_calls: int = 0
    retrieval_selected: dict[str, int] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_set(self) -> frozenset[str]:
        return frozenset(self.tool_seq)

    @property
    def has_plan(self) -> bool:
        return bool(self.plan_tokens)

    @property
    def has_tools(self) -> bool:
        return bool(self.tool_seq)


def first_think_block(messages: list[dict]) -> str:
    """The opening reasoning block: the plan, before any observation exists."""
    for m in messages:
        if m.get("type") != "AIMessage":
            continue
        for block in THINK_RE.findall(m.get("content") or ""):
            if block.strip():
                return block.strip()
    return ""


def extract_trace(run_dir: str | Path, meta: dict[str, Any]) -> TrajectoryTrace:
    """Build a trace from one run directory's preserved events and transcript.

    Reads only artifacts; never re-runs anything. A missing or truncated file
    yields empty structure rather than an exception, because failed runs are
    evidence and must stay in the sample.
    """
    d = Path(run_dir)
    tool_seq: list[str] = []
    tool_ok: list[str] = []
    code_hashes: list[str] = []
    query_text: list[str] = []
    retrieval: dict[str, int] = {}
    n_failed = 0

    ev = d / "events.jsonl"
    if ev.exists():
        pending: dict[int, str] = {}
        for line in ev.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            et, p = e.get("event_type"), e.get("payload") or {}
            if et == "tool_call_start":
                name = str(p.get("tool_name") or "")
                tool_seq.append(name)
                pending[e.get("step_index", -1)] = name
                if p.get("argument_excerpt"):
                    query_text.append(str(p["argument_excerpt"]))
            elif et == "tool_call_end":
                if str(p.get("status")) == "error":
                    n_failed += 1
                else:
                    tool_ok.append(str(p.get("tool_name") or ""))
            elif et == "code_execution_start":
                if p.get("code_hash"):
                    code_hashes.append(str(p["code_hash"]))
            elif et == "retrieval_end":
                retrieval = dict(p.get("selected") or {})

    plan_text = ""
    n_think = 0
    tr = d / "transcript.json"
    if tr.exists():
        try:
            msgs = json.loads(tr.read_text(encoding="utf-8", errors="replace"))
            plan_text = first_think_block(msgs)
            n_think = sum(len(THINK_RE.findall(m.get("content") or "")) for m in msgs)
        except (json.JSONDecodeError, TypeError):
            pass

    return TrajectoryTrace(
        run_id=str(meta.get("run_id")),
        task_name=str(meta.get("task_name")),
        task_instance_id=int(meta.get("task_instance_id", -1)),
        trajectory_index=int(meta.get("trajectory_index", -1)),
        condition=str(meta.get("condition")),
        completed=bool(meta.get("completed")),
        failure_class=meta.get("failure_class"),
        tool_seq=tuple(tool_seq),
        tool_seq_ok=tuple(tool_ok),
        code_hashes=tuple(code_hashes),
        query_tokens=tokenize(" ".join(query_text)),
        plan_tokens=tokenize(plan_text),
        plan_text=plan_text,
        n_think_blocks=n_think,
        n_tool_calls=len(tool_seq),
        n_failed_tool_calls=n_failed,
        retrieval_selected=retrieval,
    )


#: Similarity components averaged into the composite workflow distance. Each is
#: reported separately as well; the composite exists only so that one number can
#: be plotted, never so that a component can hide inside it.
SIMILARITY_COMPONENTS: tuple[str, ...] = (
    "plan_jaccard",
    "tool_jaccard",
    "tool_seq_similarity",
    "query_jaccard",
)


def pairwise_diversity(a: TrajectoryTrace, b: TrajectoryTrace) -> dict[str, float | None]:
    """Every structural comparison between two trajectories of one instance.

    ``workflow_distance`` is ``1 - mean(available similarity components)`` and is
    ``None`` when no component is computable - which happens exactly when one of
    the two trajectories produced neither a plan nor a tool call, i.e. when there
    is nothing to compare rather than nothing in common.
    """
    out: dict[str, float | None] = {
        "plan_jaccard": jaccard(a.plan_tokens, b.plan_tokens),
        "plan_text_similarity": (
            difflib.SequenceMatcher(None, a.plan_text, b.plan_text, autojunk=False).ratio()
            if a.plan_text and b.plan_text
            else None
        ),
        "tool_jaccard": jaccard(a.tool_set, b.tool_set),
        "tool_seq_similarity": sequence_similarity(list(a.tool_seq), list(b.tool_seq)),
        "query_jaccard": jaccard(a.query_tokens, b.query_tokens),
        "code_hash_jaccard": jaccard(frozenset(a.code_hashes), frozenset(b.code_hashes)),
        "shared_code_blocks": float(len(set(a.code_hashes) & set(b.code_hashes))),
        "both_used_no_tools": float(not a.has_tools and not b.has_tools),
    }
    comps = [out[k] for k in SIMILARITY_COMPONENTS if out.get(k) is not None]
    out["n_components"] = float(len(comps))
    out["workflow_distance"] = 1.0 - (sum(comps) / len(comps)) if comps else None
    return out


__all__ = [
    "SIMILARITY_COMPONENTS",
    "STOPWORDS",
    "TrajectoryTrace",
    "extract_trace",
    "first_think_block",
    "jaccard",
    "pairwise_diversity",
    "sequence_similarity",
    "tokenize",
]
