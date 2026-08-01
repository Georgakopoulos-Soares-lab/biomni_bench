"""Trajectory budget guards for a pinned Biomni ``A1`` agent.

Motivation is measured, not assumed - see ``reports/context_overflow_forensics.md``.
Above roughly 32,768 input tokens this model stops emitting stop tokens and
produces degenerate repetition until it exhausts ``max_tokens``. Biomni's
``generate`` node auto-closes the unterminated ``<think>`` tag, matches it, and
routes straight back to ``generate`` with the whole blob appended to the
conversation - which pushes the next call further past the boundary. 62 of the
69 pilot trajectories that entered that loop never left it.

Everything here is an *adapter* on a live agent instance, consistent with
``DECISIONS.md`` D-01. Four guards, each independently switchable:

``R2`` a generation that stops on ``length`` (no ``</execute>`` / ``</solution>``)
      is truncated before it re-enters the conversation, and replaced with an
      explicit correction. The full text is still written to the event log.
``R3`` a soft input-token budget injects a synthesis request for one call; a hard
      budget forces synthesis and then terminates the trajectory in a *controlled*
      state rather than on an endpoint 400.
``R4`` the tool retriever's selection is capped. Biomni's retrieval prompt asks
      the model to "be generous"; in the pilot 8 runs selected almost everything,
      producing a 32k-44k-token system prompt, and all 8 failed.
``R5`` a single model-visible observation is capped head+tail. The complete raw
      output is untouched on disk and in the event log - no evidence is dropped.

None of these touches the task prompt, the confidence instruction, the sampling
temperature, or the retriever's *ranking*.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from biomni_uncertainty.events import EventLogger

# Fallback chars-per-token used only for the very first call of a run, before a
# measurement exists. Refined from the endpoint's own usage on every later call.
_DEFAULT_CHARS_PER_TOKEN = 3.5

SYNTHESIS_INSTRUCTION = (
    "SYSTEM BUDGET NOTICE: this analysis has reached its context budget. Do not run "
    "any further code. Using only the evidence you have already gathered, produce "
    "your final answer now inside a <solution></solution> block. If the evidence is "
    "insufficient, say so explicitly inside the solution block rather than "
    "continuing to investigate."
)

SOFT_BUDGET_INSTRUCTION = (
    "SYSTEM BUDGET NOTICE: this analysis is approaching its context budget. Begin "
    "converging now: prefer concluding from the evidence you already have over "
    "gathering more, and produce a <solution></solution> block as soon as you "
    "reasonably can."
)

# Deliberately contains no XML tag, in either open or closed form. Biomni's
# generate node matches <think>/<execute>/<solution> with a DOTALL regex over the
# whole message and routes on the first hit, so a tag mentioned here - even an
# empty pair inside an instruction - would be executed as if the model had
# emitted it. There is a regression test for this.
RUNAWAY_CORRECTION = (
    "[The previous response was cut off: it reached the generation limit without "
    "producing a complete execute or solution block, and had begun repeating "
    "itself. Its opening text is shown above for context only.]\n\n"
    "Do not continue that response. Start over with a short, fresh response that "
    "ends with exactly one complete execute block, or one complete solution block "
    "if you are ready to answer, using the required XML tags."
)

# The same tags, neutralised, so a kept excerpt of a degenerate generation cannot
# be routed on either. Biomni auto-closes a dangling <think>, so leaving one in
# the excerpt would match think_match and send the loop straight back to generate.
_TAG_REPLACEMENTS = {
    "<think>": "[think]",
    "</think>": "[/think]",
    "<execute>": "[execute]",
    "</execute>": "[/execute]",
    "<solution>": "[solution]",
    "</solution>": "[/solution]",
}


def neutralize_tags(text: str) -> str:
    """Render Biomni's control tags inert without discarding the text."""
    for tag, plain in _TAG_REPLACEMENTS.items():
        text = text.replace(tag, plain)
    return text


class BudgetExceeded(RuntimeError):
    """Raised to end a trajectory in a controlled state rather than on a 400."""

    def __init__(self, reason: str, detail: dict[str, Any]):
        super().__init__(f"trajectory budget exceeded: {reason}")
        self.reason = reason
        self.detail = detail


@dataclass
class BudgetStats:
    """Counters describing how often each guard fired. Recorded per run."""

    soft_budget_hits: int = 0
    hard_budget_hits: int = 0
    runaway_generations: int = 0
    runaway_truncations: int = 0
    max_consecutive_runaway: int = 0
    observations_truncated: int = 0
    observation_tokens_dropped: int = 0
    retrieval_capped: bool = False
    retrieval_dropped: dict[str, int] = field(default_factory=dict)
    peak_input_tokens: int = 0
    terminated_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "soft_budget_hits": self.soft_budget_hits,
            "hard_budget_hits": self.hard_budget_hits,
            "runaway_generations": self.runaway_generations,
            "runaway_truncations": self.runaway_truncations,
            "max_consecutive_runaway": self.max_consecutive_runaway,
            "observations_truncated": self.observations_truncated,
            "observation_tokens_dropped": self.observation_tokens_dropped,
            "retrieval_capped": self.retrieval_capped,
            "retrieval_dropped": self.retrieval_dropped,
            "peak_input_tokens": self.peak_input_tokens,
            "terminated_reason": self.terminated_reason,
        }


def _content_text(message: Any) -> str:
    """Flatten a LangChain message's content to plain text."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                part = block.get("text") or block.get("content") or ""
                if isinstance(part, str):
                    parts.append(part)
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _usage_from_response(response: Any) -> dict | None:
    """Pull the endpoint's own token usage off an AIMessage."""
    u = getattr(response, "usage_metadata", None)
    if isinstance(u, dict) and u.get("input_tokens"):
        return u
    meta = getattr(response, "response_metadata", None) or {}
    tu = meta.get("token_usage") or meta.get("usage")
    if isinstance(tu, dict) and (tu.get("prompt_tokens") or tu.get("input_tokens")):
        return {
            "input_tokens": tu.get("prompt_tokens") or tu.get("input_tokens"),
            "output_tokens": tu.get("completion_tokens") or tu.get("output_tokens"),
        }
    return None


def _finish_reason(response: Any) -> str | None:
    meta = getattr(response, "response_metadata", None) or {}
    return meta.get("finish_reason")


def head_tail_truncate(text: str, max_chars: int, marker: str) -> str:
    """Keep the head and tail of ``text``, dropping the middle.

    Tool output is usually informative at both ends - a header/schema at the top
    and the actual result or traceback at the bottom - so a head-only cut loses
    more than it saves.
    """
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.6)
    tail = max_chars - head
    dropped = len(text) - max_chars
    return f"{text[:head]}\n\n...[{marker}: {dropped} characters omitted from the middle]...\n\n{text[-tail:]}"


class TrajectoryBudget:
    """Attach/detach the budget guards to a live ``A1`` instance.

    Attach this *after* ``AgentInstrumentation`` so that the instrumentation
    callback still records the endpoint's unmodified usage and finish reason:
    the raw failure signal stays in the event log even when the guard suppresses
    its effect on the conversation.
    """

    def __init__(
        self,
        agent: Any,
        logger: EventLogger,
        stats: BudgetStats,
        *,
        soft_input_tokens: int,
        hard_input_tokens: int,
        max_consecutive_runaway: int,
        runaway_keep_tokens: int,
        max_observation_tokens: int,
        retrieval_max_tools: int | None,
        retrieval_max_data_lake: int | None,
        retrieval_max_libraries: int | None,
    ):
        self.agent = agent
        self.logger = logger
        self.stats = stats
        self.soft = soft_input_tokens
        self.hard = hard_input_tokens
        self.max_consecutive_runaway = max_consecutive_runaway
        self.runaway_keep_tokens = runaway_keep_tokens
        self.max_observation_tokens = max_observation_tokens
        self.retrieval_caps = {
            "tools": retrieval_max_tools,
            "data_lake": retrieval_max_data_lake,
            "libraries": retrieval_max_libraries,
        }

        self._restore: list[tuple[Any, str, Any]] = []
        self._chars_per_token = _DEFAULT_CHARS_PER_TOKEN
        self._consecutive_runaway = 0
        self._synthesis_forced = False

    # -- lifecycle -------------------------------------------------------
    def attach(self) -> None:
        self._patch_llm()
        self._patch_execution()
        self._patch_retrieval()

    def __enter__(self) -> TrajectoryBudget:
        self.attach()
        return self

    def __exit__(self, *exc) -> None:
        self.detach()

    def _swap(self, obj: Any, name: str, new: Any) -> None:
        """Shadow ``obj.name`` with ``new``, recording how to undo it.

        ``agent.llm`` is a pydantic ``ChatOpenAI``, whose ``__setattr__``
        rejects any name that is not a declared model field - so a plain
        ``setattr(llm, "invoke", ...)`` raises. ``invoke`` is a normal function
        on the class (a non-data descriptor), so writing it straight into the
        instance ``__dict__`` shadows it correctly and lookup falls back to the
        class once the entry is removed.
        """
        had_own = name in getattr(obj, "__dict__", {})
        previous = obj.__dict__.get(name) if had_own else None
        self._restore.append((obj, name, (had_own, previous)))
        try:
            setattr(obj, name, new)
        except (ValueError, AttributeError, TypeError):
            object.__setattr__(obj, name, new)

    def detach(self) -> None:
        for obj, name, (had_own, previous) in reversed(self._restore):
            if had_own:
                object.__setattr__(obj, name, previous)
            else:
                # Remove the shadow so attribute lookup resumes on the class.
                obj.__dict__.pop(name, None)
        self._restore.clear()

    # -- token accounting ------------------------------------------------
    def estimate_input_tokens(self, messages: list[Any]) -> int:
        """Estimate the input length of a request before sending it.

        Self-calibrating: the ratio is re-derived from the endpoint's reported
        ``input_tokens`` after every call, so it converges on this model's real
        tokenization of this conversation's content within one step. A tokenizer
        is deliberately not loaded - it would tie the agent environment to the
        model snapshot for a number we can measure directly.
        """
        chars = sum(len(_content_text(m)) for m in messages)
        # Biomni prepends the system prompt inside its generate node, so it is
        # already part of ``messages`` by the time invoke() sees them.
        return int(chars / max(self._chars_per_token, 1.0))

    def _recalibrate(self, messages: list[Any], input_tokens: int) -> None:
        chars = sum(len(_content_text(m)) for m in messages)
        if input_tokens > 0 and chars > 0:
            self._chars_per_token = chars / input_tokens

    # -- R2 + R3: the LLM call -------------------------------------------
    def _patch_llm(self) -> None:
        llm = getattr(self.agent, "llm", None)
        if llm is None or not hasattr(llm, "invoke"):
            return
        original = llm.invoke
        guard = self

        def wrapped(input_, *args, **kwargs):  # noqa: ANN001 - upstream signature
            messages = list(input_) if isinstance(input_, (list, tuple)) else input_
            if isinstance(messages, list):
                messages = guard._apply_input_budget(messages)
                input_ = messages

            response = original(input_, *args, **kwargs)

            usage = _usage_from_response(response)
            if usage and usage.get("input_tokens") and isinstance(messages, list):
                guard._recalibrate(messages, int(usage["input_tokens"]))
                guard.stats.peak_input_tokens = max(guard.stats.peak_input_tokens, int(usage["input_tokens"]))

            return guard._apply_runaway_guard(response)

        self._swap(llm, "invoke", wrapped)

    def _apply_input_budget(self, messages: list[Any]) -> list[Any]:
        """Soft/hard input-token budget (R3).

        The nudge is appended to the message list *for this call only*; it is
        never written into the agent's conversation state, so it does not
        permanently consume context or alter the stored transcript.
        """
        if self.hard <= 0 and self.soft <= 0:
            return messages
        projected = self.estimate_input_tokens(messages)

        if self.hard > 0 and projected >= self.hard:
            if self._synthesis_forced:
                # Synthesis was already requested and the agent kept going.
                self.stats.terminated_reason = "hard_budget"
                self.logger.emit(
                    "budget_terminated",
                    reason="hard_budget",
                    projected_input_tokens=projected,
                    hard_input_tokens=self.hard,
                )
                raise BudgetExceeded(
                    "hard_budget",
                    {"projected_input_tokens": projected, "hard_input_tokens": self.hard},
                )
            self._synthesis_forced = True
            self.stats.hard_budget_hits += 1
            self.logger.emit(
                "budget_warning",
                level="hard",
                action="force_synthesis",
                projected_input_tokens=projected,
                hard_input_tokens=self.hard,
            )
            return messages + [_human(SYNTHESIS_INSTRUCTION)]

        if self.soft > 0 and projected >= self.soft:
            self.stats.soft_budget_hits += 1
            self.logger.emit(
                "budget_warning",
                level="soft",
                action="nudge",
                projected_input_tokens=projected,
                soft_input_tokens=self.soft,
            )
            return messages + [_human(SOFT_BUDGET_INSTRUCTION)]

        return messages

    def _apply_runaway_guard(self, response: Any) -> Any:
        """Truncate an unterminated generation before it re-enters the loop (R2).

        Biomni's ``generate`` node auto-closes a dangling ``<think>`` and routes
        back to ``generate``, so a degenerate blob is otherwise appended verbatim
        and resent. The replacement text deliberately contains no ``<think>``,
        ``<execute>`` or ``<solution>`` tag, so the node takes its parse-error
        branch and asks the model for a clean response instead.
        """
        if _finish_reason(response) != "length":
            self._consecutive_runaway = 0
            return response

        self.stats.runaway_generations += 1
        self._consecutive_runaway += 1
        self.stats.max_consecutive_runaway = max(self.stats.max_consecutive_runaway, self._consecutive_runaway)

        text = _content_text(response)
        # A generation that hit the limit *and* already contains a complete
        # solution block is a real answer that merely ran long: leave it alone.
        if "</solution>" in text or "</execute>" in text:
            self.logger.emit(
                "runaway_truncated",
                action="kept",
                reason="complete_block_present",
                original_chars=len(text),
                consecutive=self._consecutive_runaway,
            )
            return response

        if self.runaway_keep_tokens <= 0:
            return response

        keep_chars = int(self.runaway_keep_tokens * self._chars_per_token)
        excerpt = neutralize_tags(text[:keep_chars])
        replacement = f"{excerpt}\n\n{RUNAWAY_CORRECTION}"
        self.stats.runaway_truncations += 1
        self.logger.emit(
            "runaway_truncated",
            action="truncated",
            original_chars=len(text),
            kept_chars=len(excerpt),
            consecutive=self._consecutive_runaway,
            excerpt_tail=text[-500:],
        )

        if 0 < self.max_consecutive_runaway <= self._consecutive_runaway:
            self.stats.terminated_reason = "consecutive_runaway"
            self.logger.emit(
                "budget_terminated",
                reason="consecutive_runaway",
                consecutive=self._consecutive_runaway,
                max_consecutive_runaway=self.max_consecutive_runaway,
            )
            raise BudgetExceeded(
                "consecutive_runaway",
                {"consecutive": self._consecutive_runaway, "limit": self.max_consecutive_runaway},
            )

        return _replace_content(response, replacement)

    # -- R5: bound one model-visible observation --------------------------
    def _patch_execution(self) -> None:
        if self.max_observation_tokens <= 0:
            return
        import biomni.agent.a1 as a1mod

        original = a1mod.run_with_timeout
        guard = self

        def wrapped(func, args, timeout=600):  # noqa: ANN001 - upstream signature
            result = original(func, args, timeout=timeout)
            if not isinstance(result, str):
                return result
            max_chars = int(guard.max_observation_tokens * guard._chars_per_token)
            if len(result) <= max_chars:
                return result
            trimmed = head_tail_truncate(result, max_chars, "trimmed by the trajectory budget")
            dropped = int((len(result) - len(trimmed)) / max(guard._chars_per_token, 1.0))
            guard.stats.observations_truncated += 1
            guard.stats.observation_tokens_dropped += dropped
            # The full text stays in the event log (AgentInstrumentation records
            # output_bytes plus head and tail excerpts) and in stdout.log.
            guard.logger.emit(
                "observation_truncated",
                original_chars=len(result),
                kept_chars=len(trimmed),
                approx_tokens_dropped=dropped,
            )
            return trimmed

        self._swap(a1mod, "run_with_timeout", wrapped)

    # -- R4: cap the retrieval selection ----------------------------------
    def _patch_retrieval(self) -> None:
        retriever = getattr(self.agent, "retriever", None)
        if retriever is None or not hasattr(retriever, "prompt_based_retrieval"):
            return
        if not any(v for v in self.retrieval_caps.values()):
            return
        original = retriever.prompt_based_retrieval
        guard = self

        def wrapped(query, resources, llm=None, **kw):  # noqa: ANN001 - upstream signature
            out = original(query, resources, llm=llm, **kw)
            if not isinstance(out, dict):
                return out
            dropped = {}
            capped = {}
            for key, items in out.items():
                cap = guard.retrieval_caps.get(key)
                if cap and isinstance(items, list) and len(items) > cap:
                    # The retriever returns its selection in rank order, so a
                    # head slice keeps the items it judged most relevant. Only
                    # the count is changed; the ranking is upstream's.
                    dropped[key] = len(items) - cap
                    capped[key] = items[:cap]
                else:
                    capped[key] = items
            if dropped:
                guard.stats.retrieval_capped = True
                guard.stats.retrieval_dropped = dropped
                guard.logger.emit(
                    "retrieval_capped",
                    caps={k: v for k, v in guard.retrieval_caps.items() if v},
                    dropped=dropped,
                    kept={k: len(v) for k, v in capped.items() if isinstance(v, list)},
                )
            return capped

        self._swap(retriever, "prompt_based_retrieval", wrapped)


def _human(text: str) -> Any:
    from langchain_core.messages import HumanMessage

    return HumanMessage(content=text)


def _replace_content(response: Any, text: str) -> Any:
    """Return ``response`` with its content replaced, preserving metadata."""
    try:
        response.content = text
        return response
    except Exception:  # noqa: BLE001 - message classes vary; fall back to a copy
        try:
            return response.model_copy(update={"content": text})
        except Exception:  # noqa: BLE001
            from langchain_core.messages import AIMessage

            return AIMessage(
                content=text,
                response_metadata=getattr(response, "response_metadata", None) or {},
            )


def budget_from_config(cfg: Any, agent: Any, logger: EventLogger, stats: BudgetStats) -> TrajectoryBudget | None:
    """Build a guard from ``config.trajectory_budget``; ``None`` when disabled."""
    b = getattr(cfg, "trajectory_budget", None)
    if b is None or not b.enabled:
        return None
    return TrajectoryBudget(
        agent,
        logger,
        stats,
        soft_input_tokens=b.soft_input_tokens,
        hard_input_tokens=b.hard_input_tokens,
        max_consecutive_runaway=b.max_consecutive_runaway,
        runaway_keep_tokens=b.runaway_keep_tokens,
        max_observation_tokens=b.max_observation_tokens,
        retrieval_max_tools=b.retrieval_max_tools,
        retrieval_max_data_lake=b.retrieval_max_data_lake,
        retrieval_max_libraries=b.retrieval_max_libraries,
    )


def timed_detach(guard: TrajectoryBudget | None) -> float:
    """Detach a guard, returning elapsed seconds (used only for symmetry in logs)."""
    if guard is None:
        return 0.0
    t0 = time.perf_counter()
    guard.detach()
    return time.perf_counter() - t0
