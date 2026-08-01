"""Tests for the Phase-1.5 trajectory-budget guards.

Every case here corresponds to a measurement in
``reports/context_overflow_forensics.md``; the point of the guards is to change
exactly the behaviour that report identified and nothing else.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from biomni_uncertainty.budget import (
    RUNAWAY_CORRECTION,
    SOFT_BUDGET_INSTRUCTION,
    SYNTHESIS_INSTRUCTION,
    BudgetExceeded,
    BudgetStats,
    TrajectoryBudget,
    head_tail_truncate,
)
from biomni_uncertainty.config import Config, TrajectoryBudgetCfg
from biomni_uncertainty.events import EventLogger, validate_event

# --------------------------------------------------------------------------
# Fakes: a minimal stand-in for the parts of A1 the guards touch.
# --------------------------------------------------------------------------


class FakeLLM:
    """Returns queued responses; records the messages it was invoked with."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(list(messages))
        return self._responses.pop(0)


class FakeRetriever:
    def __init__(self, selection):
        self._selection = selection

    def prompt_based_retrieval(self, query, resources, llm=None, **kw):
        return dict(self._selection)


class FakeAgent:
    def __init__(self, llm=None, retriever=None):
        self.llm = llm
        self.retriever = retriever


def ai(content: str, finish_reason: str = "stop", input_tokens: int | None = None) -> AIMessage:
    msg = AIMessage(content=content, response_metadata={"finish_reason": finish_reason})
    if input_tokens is not None:
        msg.usage_metadata = {"input_tokens": input_tokens, "output_tokens": 10, "total_tokens": input_tokens + 10}
    return msg


@pytest.fixture
def logger(tmp_path):
    return EventLogger("test-run", tmp_path / "events.jsonl")


def read_events(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def make_guard(agent, logger, **overrides):
    kwargs = {
        "soft_input_tokens": 24576,
        "hard_input_tokens": 32768,
        "max_consecutive_runaway": 3,
        "runaway_keep_tokens": 512,
        "max_observation_tokens": 4000,
        "retrieval_max_tools": 40,
        "retrieval_max_data_lake": 20,
        "retrieval_max_libraries": 20,
    }
    kwargs.update(overrides)
    return TrajectoryBudget(agent, logger, BudgetStats(), **kwargs)


# --------------------------------------------------------------------------
# R2 - runaway generations
# --------------------------------------------------------------------------


def test_healthy_generation_is_passed_through_untouched(logger):
    """A normal step must be byte-identical to the unguarded behaviour."""
    original = "<think>fine</think><execute>print(1)</execute>"
    llm = FakeLLM([ai(original, finish_reason="stop")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger) as guard:
        out = agent.llm.invoke([HumanMessage(content="q")])
    assert out.content == original
    assert guard.stats.runaway_truncations == 0


def test_runaway_generation_is_truncated_and_corrected(logger):
    """The degenerate blob must not re-enter the conversation verbatim.

    This is the exact Phase-1 mechanism: Biomni's generate node auto-closes a
    dangling <think>, matches it, and routes back to generate with the whole
    8192-token blob appended.
    """
    blob = "<think>" + ("I need to examine the files. " * 2000)
    llm = FakeLLM([ai(blob, finish_reason="length")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger) as guard:
        out = agent.llm.invoke([HumanMessage(content="q")])

    assert len(out.content) < len(blob)
    assert RUNAWAY_CORRECTION in out.content
    assert guard.stats.runaway_generations == 1
    assert guard.stats.runaway_truncations == 1


def test_truncated_runaway_carries_no_tag_that_biomni_would_route_on(logger):
    """The replacement must fall through to Biomni's parse-error branch.

    If the replacement still contained a <think> block, generate() would match it
    and loop straight back - reproducing the failure the guard exists to stop.
    """
    blob = "<think>" + ("repeat " * 5000)
    llm = FakeLLM([ai(blob, finish_reason="length")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger, runaway_keep_tokens=8):
        out = agent.llm.invoke([HumanMessage(content="q")])

    # Biomni auto-closes a dangling <think>, so the kept excerpt must be short
    # enough that no complete think/execute/solution block survives.
    assert "</think>" not in out.content
    assert "<execute>" not in out.content
    assert "<solution>" not in out.content


def test_correction_text_contains_no_routable_tag():
    """Biomni's generate node routes on the first <think>/<execute>/<solution>
    match anywhere in the message, with a DOTALL regex. An empty tag pair inside
    an instruction would therefore be *executed*. Found by this test."""
    import re

    for pattern in (r"<think>.*?</think>", r"<execute>.*?</execute>", r"<solution>.*?</solution>"):
        assert not re.search(pattern, RUNAWAY_CORRECTION, re.DOTALL | re.IGNORECASE)
    # Biomni also auto-closes a dangling opener, so a lone opening tag is unsafe.
    for tag in ("<think>", "<execute>", "<solution>"):
        assert tag not in RUNAWAY_CORRECTION


def test_kept_excerpt_has_its_tags_neutralized(logger):
    """A degenerate blob starts with <think>; Biomni auto-closes it and routes
    back to generate. Neutralizing the tags forces the parse-error branch."""
    blob = "<think>" + ("stuck " * 5000)
    llm = FakeLLM([ai(blob, finish_reason="length")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger, runaway_keep_tokens=256):
        out = agent.llm.invoke([HumanMessage(content="q")])

    assert "<think>" not in out.content
    assert "[think]" in out.content  # text preserved, tag inert
    assert "stuck" in out.content


def test_length_stop_with_a_complete_solution_block_is_kept(logger):
    """A real answer that merely ran long is not degeneration - do not touch it."""
    text = "<think>done</think><solution>BRCA1</solution>"
    llm = FakeLLM([ai(text, finish_reason="length")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger) as guard:
        out = agent.llm.invoke([HumanMessage(content="q")])
    assert out.content == text
    assert guard.stats.runaway_truncations == 0
    assert guard.stats.runaway_generations == 1


def test_consecutive_runaways_terminate_in_a_controlled_state(logger):
    blob = "<think>" + ("x " * 5000)
    llm = FakeLLM([ai(blob, finish_reason="length") for _ in range(3)])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger, max_consecutive_runaway=3) as guard:
        agent.llm.invoke([HumanMessage(content="q")])
        agent.llm.invoke([HumanMessage(content="q")])
        with pytest.raises(BudgetExceeded) as exc:
            agent.llm.invoke([HumanMessage(content="q")])
    assert exc.value.reason == "consecutive_runaway"
    assert guard.stats.terminated_reason == "consecutive_runaway"


def test_runaway_counter_resets_after_a_healthy_generation(logger):
    """Isolated runaways must not accumulate into a spurious termination."""
    blob = "<think>" + ("x " * 5000)
    llm = FakeLLM(
        [
            ai(blob, finish_reason="length"),
            ai("<think>ok</think><execute>1</execute>", finish_reason="stop"),
            ai(blob, finish_reason="length"),
            ai(blob, finish_reason="length"),
        ]
    )
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger, max_consecutive_runaway=3) as guard:
        for _ in range(4):
            agent.llm.invoke([HumanMessage(content="q")])
    assert guard.stats.runaway_generations == 3
    assert guard.stats.max_consecutive_runaway == 2
    assert guard.stats.terminated_reason is None


# --------------------------------------------------------------------------
# R3 - input budget
# --------------------------------------------------------------------------


def test_soft_budget_appends_a_nudge_without_mutating_history(logger):
    """The nudge is per-call: it must never become permanent context."""
    history = [SystemMessage(content="s"), HumanMessage(content="x" * 100_000)]
    llm = FakeLLM([ai("ok", finish_reason="stop")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger, soft_input_tokens=1000, hard_input_tokens=10**9) as guard:
        agent.llm.invoke(history)

    sent = llm.calls[0]
    assert SOFT_BUDGET_INSTRUCTION in sent[-1].content
    assert len(sent) == len(history) + 1
    assert len(history) == 2  # caller's list untouched
    assert guard.stats.soft_budget_hits == 1


def test_hard_budget_forces_synthesis_then_terminates(logger):
    history = [HumanMessage(content="x" * 500_000)]
    llm = FakeLLM([ai("still working", finish_reason="stop"), ai("still working", finish_reason="stop")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger, soft_input_tokens=1000, hard_input_tokens=2000) as guard:
        agent.llm.invoke(history)
        assert SYNTHESIS_INSTRUCTION in llm.calls[0][-1].content
        assert guard.stats.hard_budget_hits == 1
        # Second time past the hard budget: the agent ignored the request.
        with pytest.raises(BudgetExceeded) as exc:
            agent.llm.invoke(history)
    assert exc.value.reason == "hard_budget"


def test_budget_below_threshold_sends_messages_unchanged(logger):
    history = [SystemMessage(content="s"), HumanMessage(content="short")]
    llm = FakeLLM([ai("ok", finish_reason="stop")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger) as guard:
        agent.llm.invoke(history)
    assert llm.calls[0] == history
    assert guard.stats.soft_budget_hits == 0
    assert guard.stats.hard_budget_hits == 0


def test_token_estimate_recalibrates_from_endpoint_usage(logger):
    """The chars-per-token ratio must converge on what the endpoint reports."""
    text = "y" * 40_000
    llm = FakeLLM([ai("ok", finish_reason="stop", input_tokens=10_000)])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger, soft_input_tokens=10**9, hard_input_tokens=10**9) as guard:
        agent.llm.invoke([HumanMessage(content=text)])
        assert guard._chars_per_token == pytest.approx(4.0)
        assert guard.estimate_input_tokens([HumanMessage(content=text)]) == pytest.approx(10_000, rel=0.01)
        assert guard.stats.peak_input_tokens == 10_000


# --------------------------------------------------------------------------
# R4 - retrieval caps
# --------------------------------------------------------------------------


def test_retrieval_selection_is_capped_preserving_rank_order(logger):
    """Phase 1: 8 runs selected up to 222/224 tools; all 8 failed."""
    selection = {
        "tools": [f"tool{i}" for i in range(222)],
        "data_lake": [f"d{i}" for i in range(76)],
        "libraries": [f"l{i}" for i in range(113)],
    }
    agent = FakeAgent(retriever=FakeRetriever(selection))
    with make_guard(agent, logger) as guard:
        out = agent.retriever.prompt_based_retrieval("q", {})

    assert len(out["tools"]) == 40
    assert out["tools"] == [f"tool{i}" for i in range(40)]  # rank order preserved
    assert len(out["data_lake"]) == 20
    assert len(out["libraries"]) == 20
    assert guard.stats.retrieval_capped is True
    assert guard.stats.retrieval_dropped == {"tools": 182, "data_lake": 56, "libraries": 93}


def test_typical_retrieval_selection_is_untouched(logger):
    """The median pilot run selected 5 tools; the cap must be a no-op there."""
    selection = {"tools": ["a", "b", "c", "d", "e"], "data_lake": ["x"], "libraries": ["y"]}
    agent = FakeAgent(retriever=FakeRetriever(selection))
    with make_guard(agent, logger) as guard:
        out = agent.retriever.prompt_based_retrieval("q", {})
    assert out == selection
    assert guard.stats.retrieval_capped is False


# --------------------------------------------------------------------------
# R5 - observation bounding
# --------------------------------------------------------------------------


def test_head_tail_truncate_keeps_both_ends():
    text = "HEAD" + ("m" * 10_000) + "TAIL"
    out = head_tail_truncate(text, 1000, "trimmed")
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")
    assert "omitted from the middle" in out
    assert len(out) < len(text)


def test_head_tail_truncate_is_a_noop_when_short():
    assert head_tail_truncate("short", 1000, "trimmed") == "short"


def test_observation_is_capped_but_full_text_reaches_the_event_log(logger, monkeypatch):
    """`import biomni.agent.a1 as a1mod` resolves through the parent package's
    attribute, so a fake has to be installed for the whole chain."""
    import sys
    import types

    fake_a1 = types.ModuleType("biomni.agent.a1")

    def run_with_timeout(func, args, timeout=600):
        return "RESULT_HEAD" + ("z" * 200_000) + "RESULT_TAIL"

    fake_a1.run_with_timeout = run_with_timeout
    fake_agent_pkg = types.ModuleType("biomni.agent")
    fake_agent_pkg.a1 = fake_a1
    fake_biomni = types.ModuleType("biomni")
    fake_biomni.agent = fake_agent_pkg
    monkeypatch.setitem(sys.modules, "biomni", fake_biomni)
    monkeypatch.setitem(sys.modules, "biomni.agent", fake_agent_pkg)
    monkeypatch.setitem(sys.modules, "biomni.agent.a1", fake_a1)

    agent = FakeAgent()
    guard = make_guard(agent, logger, max_observation_tokens=1000)
    guard.attach()
    try:
        out = fake_a1.run_with_timeout(None, [""])
    finally:
        guard.detach()

    assert len(out) < 200_000
    assert out.startswith("RESULT_HEAD")
    assert out.endswith("RESULT_TAIL")
    assert guard.stats.observations_truncated == 1
    assert fake_a1.run_with_timeout is run_with_timeout  # detached cleanly

    events = read_events(logger.path)
    trunc = [e for e in events if e["event_type"] == "observation_truncated"]
    assert trunc and trunc[0]["payload"]["original_chars"] > 200_000


# --------------------------------------------------------------------------
# Wiring, config and events
# --------------------------------------------------------------------------


def test_all_guards_detach_cleanly(logger):
    llm = FakeLLM([])
    retriever = FakeRetriever({})
    agent = FakeAgent(llm=llm, retriever=retriever)
    original_invoke = llm.invoke
    original_retrieval = retriever.prompt_based_retrieval

    guard = make_guard(agent, logger, max_observation_tokens=0)
    guard.attach()
    assert agent.llm.invoke is not original_invoke
    guard.detach()
    assert agent.llm.invoke == original_invoke
    assert agent.retriever.prompt_based_retrieval == original_retrieval


def test_guard_attaches_to_a_pydantic_chat_model(logger):
    """The real ``agent.llm`` is a pydantic ``ChatOpenAI``.

    Its ``__setattr__`` rejects any name that is not a declared model field, so a
    plain ``setattr(llm, "invoke", ...)`` raises ValueError. The plain-object
    fakes above cannot catch that - only a real chat model can, and this cost a
    live dispatch to find.
    """
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="m", base_url="http://127.0.0.1:1/v1", api_key="EMPTY")
    agent = FakeAgent(llm=llm)
    before = llm.invoke

    guard = make_guard(agent, logger, max_observation_tokens=0)
    guard.attach()
    assert llm.invoke is not before
    guard.detach()
    assert llm.invoke.__func__ is before.__func__
    assert "invoke" not in llm.__dict__  # shadow removed, class lookup resumes


def test_budget_events_pass_schema_validation(logger):
    blob = "<think>" + ("x " * 5000)
    llm = FakeLLM([ai(blob, finish_reason="length")])
    agent = FakeAgent(llm=llm)
    with make_guard(agent, logger, soft_input_tokens=1, hard_input_tokens=10**9):
        agent.llm.invoke([HumanMessage(content="q" * 100)])
    events = read_events(logger.path)
    assert events
    for e in events:
        assert validate_event(e) == []
    assert {"budget_warning", "runaway_truncated"} <= {e["event_type"] for e in events}


def test_disabled_budget_is_the_phase1_default():
    """Phase-1 configs must keep reproducing Phase-1 behaviour exactly."""
    assert TrajectoryBudgetCfg().enabled is False


def test_hard_budget_must_exceed_soft():
    with pytest.raises(ValueError, match="hard_input_tokens must exceed"):
        TrajectoryBudgetCfg(soft_input_tokens=30000, hard_input_tokens=20000)


def test_config_round_trips_the_budget_section(tmp_path):
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        "experiment: {name: t, seed: 1, output_root: ./runs}\n"
        "trajectory_budget:\n"
        "  enabled: true\n"
        "  soft_input_tokens: 24576\n"
        "  hard_input_tokens: 32768\n"
    )
    from biomni_uncertainty.config import load_config

    cfg = load_config(cfg_path)
    assert cfg.trajectory_budget.enabled is True
    assert cfg.trajectory_budget.hard_input_tokens == 32768
    assert "trajectory_budget" in cfg.snapshot()


def test_budget_from_config_returns_none_when_disabled(logger):
    cfg = Config.model_validate({"experiment": {"name": "t", "seed": 1, "output_root": "./runs"}})
    from biomni_uncertainty.budget import budget_from_config

    assert budget_from_config(cfg, FakeAgent(), logger, BudgetStats()) is None
