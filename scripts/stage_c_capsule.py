#!/usr/bin/env python3
"""Stage C — the trace capsule and its leakage barrier.

One deterministic capsule per **unique candidate answer**, built by allowlist
in the manner of `policy.TrajectoryView`: a fixed field list, with everything
not named structurally absent rather than filtered out by convention.

Specified in `reports/stage_c_preregistration.md` §3, which is frozen. This
module is the implementation; where the two disagree, the report governs.

The two leaks this format is designed against
---------------------------------------------
**Ground truth and vote count.** Obvious, and handled by the allowlist:
`reward`/`correct` never enter, and neither does support, agreement fraction,
or trajectory index.

**Capsule *length* encoding vote count.** Much less obvious. If a capsule
merged every trajectory holding an answer, a 3-vote candidate would produce a
visibly longer capsule than a 1-vote candidate and the verifier could recover
the plurality baseline from length alone — reproducing the baseline it is being
tested against. Closed by using exactly **one** representative trajectory per
unique answer, chosen by lexicographically smallest `run_id`: deterministic,
independent of arrival order, and independent of how many trajectories agreed.

Serialization constants are fixed here, applied identically to every capsule,
and are format parameters rather than tuned quantities. They exist because two
capsules plus the criteria must fit the served context window with headroom.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Frozen serialization constants. Applied identically to every capsule, for
# every candidate, in every cell. Not tuned against any outcome.
# --------------------------------------------------------------------------

#: Per-execution caps. The event log already caps its excerpts (observed
#: maxima: code 3276, stdout 4000); re-applying a fixed cap here makes the
#: rendering independent of that upstream behaviour.
CODE_EXCERPT_CAP = 1500
STDOUT_EXCERPT_CAP = 2000
ARG_EXCERPT_CAP = 200

#: At most this many code executions are rendered; the remainder are reported
#: as a count, so a long trajectory does not crowd out the criteria.
MAX_RENDERED_EXECUTIONS = 20

#: Hard ceiling on a rendered capsule, as a context-safety net rather than a
#: content budget. Set so that **no capsule in the frozen population is
#: truncated at all** (largest observed: 47,193 chars) while two capsules plus
#: the criteria and scale stay far inside the served 65,536-token context:
#: 2 x 50,000 chars is roughly 26k tokens.
#:
#: Fixed before any BiomniEval1 comparison was scored. An earlier value of
#: 30,000 truncated 40% of capsules and is recorded here because it was the
#: reason the section order below was corrected.
MAX_CAPSULE_CHARS = 50000

TRUNCATION_MARKER = "\n[capsule truncated to the frozen length limit]"

#: Anything a verifier must never be able to read. Strictly extends
#: `policy.FORBIDDEN_VIEW_FIELDS` and follows D-32's `FORBIDDEN_VERIFY_FIELDS`.
#: Enforced by test, not by convention.
FORBIDDEN_CAPSULE_FIELDS = frozenset(
    {
        # ground truth
        "reward",
        "strict_reward",
        "correct",
        "evaluation_status",
        "evaluation_error",
        # vote count / support - the verifier must not be able to reconstruct
        # the plurality baseline it is being compared against
        "support",
        "vote_count",
        "n_usable",
        "agreement_fraction",
        "cluster_size",
        # which sample produced the candidate
        "trajectory_index",
        "run_id",
        "position",
        "experiment_id",
        "run_dir",
        # D-32's anti-anchoring rule
        "final_confidence",
        "final_confidence_0_100",
        "confidence_parse_status",
        # the other candidates
        "candidates",
        "other_candidates",
        # free-form hidden reasoning
        "transcript",
        "model_text",
        "final_response_raw",
        "ai_message_content",
    }
)


@dataclass(frozen=True, slots=True)
class TraceCapsule:
    """One candidate answer as visible to a Stage C verifier.

    Every field is observable without ground truth, without the other
    candidates, and without knowing how many trajectories agreed.
    """

    task_name: str
    task_prompt: str
    committed_answer: str
    answer_parse_status: str
    tools_invoked: list[dict] = field(default_factory=list)
    retrieval_selection: dict = field(default_factory=dict)
    code_executions: list[dict] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    provenance: list[dict] = field(default_factory=list)
    n_executions_total: int = 0

    def assert_no_forbidden_fields(self) -> None:
        leaked = set(asdict(self)) & FORBIDDEN_CAPSULE_FIELDS
        if leaked:
            raise ValueError(f"capsule exposes forbidden fields: {sorted(leaked)}")


def _clip(text: str | None, cap: int) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= cap else s[:cap] + " …[clipped]"


def read_events(run_dir: str | Path) -> list[dict]:
    """Load one trajectory's append-only event log."""
    path = Path(run_dir) / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build_capsule(
    *,
    task_name: str,
    task_prompt: str,
    committed_answer: str,
    answer_parse_status: str,
    events: list[dict],
) -> TraceCapsule:
    """Assemble a capsule from one trajectory's events.

    Reads only event types that carry observable execution evidence. The
    transcript is never opened: `AIMessage` content is the model's free-form
    reasoning and is excluded by §3.2.
    """
    tools: list[dict] = []
    tool_status: dict[int, str] = {}
    execs: list[dict] = []
    failures: list[str] = []
    provenance: list[dict] = []
    retrieval: dict = {}

    for e in events:
        et = e.get("event_type")
        p = e.get("payload") or {}
        if et == "tool_call_start":
            tools.append(
                {
                    "step": e.get("step_index"),
                    "tool_name": p.get("tool_name"),
                    "argument_excerpt": _clip(p.get("argument_excerpt"), ARG_EXCERPT_CAP),
                    "status": None,
                }
            )
            provenance.append({"step": e.get("step_index"), "argument_hash": p.get("argument_hash")})
        elif et == "tool_call_end":
            tool_status[e.get("step_index")] = p.get("status")
        elif et == "retrieval_end":
            # counts only - D-30: the retriever never logs tool identities
            retrieval = dict(p.get("selected") or {})
        elif et == "code_execution_start":
            execs.append(
                {
                    "step": e.get("step_index"),
                    "language": p.get("language"),
                    "code_excerpt": _clip(p.get("code_excerpt"), CODE_EXCERPT_CAP),
                    "status": None,
                    "error": None,
                    "stdout_excerpt": "",
                }
            )
            provenance.append({"step": e.get("step_index"), "code_hash": p.get("code_hash")})
        elif et == "code_execution_end":
            for ex in reversed(execs):
                if ex["step"] == e.get("step_index"):
                    ex["status"] = p.get("status")
                    ex["error"] = p.get("error")
                    ex["stdout_excerpt"] = _clip(p.get("stdout_excerpt"), STDOUT_EXCERPT_CAP)
                    break
            if p.get("status") != "ok":
                failures.append(f"step {e.get('step_index')}: code execution {p.get('status')} — {p.get('error')}")
            elif not (p.get("stdout_excerpt") or "").strip():
                failures.append(f"step {e.get('step_index')}: code execution returned no output")
        elif et == "observation_truncated":
            failures.append(
                f"observation truncated: {p.get('original_chars')} chars returned, {p.get('kept_chars')} kept"
            )

    for t in tools:
        t["status"] = tool_status.get(t["step"])
        if t["status"] not in (None, "ok"):
            failures.append(f"step {t['step']}: tool {t['tool_name']} returned status {t['status']}")

    n_total = len(execs)
    capsule = TraceCapsule(
        task_name=task_name,
        task_prompt=task_prompt,
        committed_answer=committed_answer,
        answer_parse_status=answer_parse_status,
        tools_invoked=tools,
        retrieval_selection=retrieval,
        code_executions=execs[:MAX_RENDERED_EXECUTIONS],
        failures=failures,
        provenance=provenance,
        n_executions_total=n_total,
    )
    capsule.assert_no_forbidden_fields()
    return capsule


def _section(title: str, body: str) -> str:
    """Fixed-key rendering: an empty section is emitted as `(none)` rather than
    omitted, so absence is legible and does not signal through length."""
    return f"## {title}\n{body.strip() or '(none)'}\n"


def render_capsule(c: TraceCapsule) -> str:
    """Deterministic text rendering. Sections always appear, in this order.

    **Order is load-bearing, not cosmetic.** Truncation cuts the tail, so
    anything a criterion depends on must come before the bulky code-and-output
    dump. The `#alignment` criterion is defined over empty, errored and
    truncated returns, so the failure summary is rendered *early*: with the
    failures section last, a capsule at the length ceiling lost precisely the
    evidence one of the three criteria is about. The ceiling now truncates
    nothing in the frozen population, and this ordering keeps it a safety net
    rather than a silent evidence-eater if it ever bites.
    """
    tools = "\n".join(
        f"- {t['tool_name']} (status: {t['status'] or 'unknown'}) args: {t['argument_excerpt']}"
        for t in c.tools_invoked
    )
    retrieval = ", ".join(f"{k}={v}" for k, v in sorted(c.retrieval_selection.items()))
    execs = []
    for ex in c.code_executions:
        execs.append(
            f"### execution {ex['step']} ({ex['language']}, status: {ex['status'] or 'unknown'})\n"
            f"```\n{ex['code_excerpt']}\n```\n"
            f"returned:\n```\n{ex['stdout_excerpt'] or '(no output)'}\n```"
            + (f"\nerror: {ex['error']}" if ex["error"] else "")
        )
    omitted = c.n_executions_total - len(c.code_executions)
    if omitted > 0:
        execs.append(f"[{omitted} further code executions omitted at the frozen rendering limit]")

    prov = ", ".join(
        f"step {p['step']}:{k}={v}" for p in c.provenance for k, v in p.items() if k != "step" and v is not None
    )

    text = (
        f"# Candidate answer\n{c.committed_answer}\n"
        f"(answer parse status: {c.answer_parse_status})\n\n"
        + _section("Failures, empty returns and truncation", "\n".join(f"- {f}" for f in c.failures))
        + "\n"
        + _section("Tools and databases invoked", tools)
        + "\n"
        + _section("Retriever selection (counts only; identities are not logged)", retrieval)
        + "\n"
        + _section("Provenance hashes", prov)
        + "\n"
        + _section("Code and computation", "\n\n".join(execs))
    )
    if len(text) > MAX_CAPSULE_CHARS:
        text = text[: MAX_CAPSULE_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    return text
