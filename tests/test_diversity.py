"""Tests for the Track-C trajectory diversity primitives.

The load-bearing property is how *missing* structure is handled. A trajectory
that made no tool call has an empty tool set; scoring that pair as Jaccard 0.0
would label every degenerate run "maximally independent" and manufacture exactly
the positive Track-C result the diagnostic exists to test for. Every such case
must return ``None`` — not comparable — and drop out of the average instead of
biasing it.
"""

from __future__ import annotations

import json

import pytest

from biomni_uncertainty.diversity import (
    SIMILARITY_COMPONENTS,
    TrajectoryTrace,
    extract_trace,
    first_think_block,
    jaccard,
    pairwise_diversity,
    sequence_similarity,
    tokenize,
)

# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


def test_jaccard_is_the_standard_ratio():
    assert jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(2 / 4)
    assert jaccard({"a"}, {"a"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0


@pytest.mark.parametrize("a, b", [(set(), {"x"}), ({"x"}, set()), (set(), set())])
def test_jaccard_returns_none_when_a_side_is_empty_not_zero(a, b):
    """Not comparable is not the same as maximally different."""
    assert jaccard(a, b) is None


def test_sequence_similarity_is_order_sensitive():
    fwd = ["a", "b", "c"]
    same = sequence_similarity(fwd, ["a", "b", "c"])
    rev = sequence_similarity(fwd, ["c", "b", "a"])
    assert same == 1.0
    assert rev < same


def test_sequence_similarity_returns_none_on_an_empty_path():
    assert sequence_similarity([], ["a"]) is None
    assert sequence_similarity(["a"], []) is None


def test_tokenize_drops_stopwords_and_short_tokens_but_keeps_domain_terms():
    toks = tokenize("The gene TP53 is a known driver of it")
    assert "gene" in toks and "tp53" in toks and "driver" in toks
    assert "the" not in toks and "is" not in toks and "of" not in toks and "it" not in toks


def test_tokenize_is_case_and_order_insensitive():
    assert tokenize("BRCA1 pathway") == tokenize("pathway brca1")


def test_tokenize_handles_none_and_empty():
    assert tokenize(None) == frozenset()
    assert tokenize("") == frozenset()


# --------------------------------------------------------------------------
# Plan extraction
# --------------------------------------------------------------------------


def test_first_think_block_takes_the_opening_reasoning_not_a_later_one():
    msgs = [
        {"type": "HumanMessage", "content": "<think>not the agent</think>"},
        {"type": "AIMessage", "content": "<think>  plan one  </think><execute>x</execute>"},
        {"type": "AIMessage", "content": "<think>plan two</think>"},
    ]
    assert first_think_block(msgs) == "plan one"


def test_first_think_block_skips_empty_blocks_and_tolerates_none():
    msgs = [
        {"type": "AIMessage", "content": "<think>   </think>"},
        {"type": "AIMessage", "content": None},
        {"type": "AIMessage", "content": "<think>real plan</think>"},
    ]
    assert first_think_block(msgs) == "real plan"
    assert first_think_block([]) == ""


# --------------------------------------------------------------------------
# Pairwise
# --------------------------------------------------------------------------


def trace(name: str, *, tools=(), plan="", queries="", codes=()) -> TrajectoryTrace:
    return TrajectoryTrace(
        run_id=name,
        task_name="t",
        task_instance_id=1,
        trajectory_index=0,
        condition="instrumented",
        completed=True,
        failure_class=None,
        tool_seq=tuple(tools),
        code_hashes=tuple(codes),
        query_tokens=tokenize(queries),
        plan_tokens=tokenize(plan),
        plan_text=plan,
    )


def test_identical_trajectories_have_zero_workflow_distance():
    a = trace("a", tools=["query_pubmed", "query_ensembl"], plan="find the causal gene by locus", queries="BRCA1")
    d = pairwise_diversity(a, trace("b", tools=list(a.tool_seq), plan=a.plan_text, queries="BRCA1"))
    assert d["workflow_distance"] == pytest.approx(0.0)
    assert d["n_components"] == len(SIMILARITY_COMPONENTS)


def test_wholly_different_trajectories_have_distance_one():
    a = trace("a", tools=["query_pubmed"], plan="alpha beta gamma", queries="delta")
    b = trace("b", tools=["query_monarch"], plan="epsilon zeta eta", queries="theta")
    assert pairwise_diversity(a, b)["workflow_distance"] == pytest.approx(1.0)


def test_a_pair_with_no_comparable_structure_yields_none_not_maximal_distance():
    """Two trajectories that produced neither a plan nor a tool call are not
    'maximally independent' - they are uncomparable, and must not inflate the
    mean distance that the Track-C conclusion is read off."""
    d = pairwise_diversity(trace("a"), trace("b"))
    assert d["workflow_distance"] is None
    assert d["n_components"] == 0.0


def test_missing_components_are_dropped_rather_than_scored_zero():
    """One side used no tools: tool metrics are None, the plan metric still counts."""
    a = trace("a", tools=["query_pubmed"], plan="same plan words here")
    b = trace("b", plan="same plan words here")
    d = pairwise_diversity(a, b)
    assert d["tool_jaccard"] is None and d["tool_seq_similarity"] is None
    assert d["plan_jaccard"] == 1.0
    assert d["workflow_distance"] == pytest.approx(0.0)  # not dragged up by the missing halves


def test_shared_code_blocks_detect_literal_workflow_duplication():
    a = trace("a", codes=["h1", "h2"])
    b = trace("b", codes=["h2", "h3"])
    d = pairwise_diversity(a, b)
    assert d["shared_code_blocks"] == 1.0
    assert d["code_hash_jaccard"] == pytest.approx(1 / 3)


# --------------------------------------------------------------------------
# Retrieval identity / evidence content (VERIFY prerequisite item 2)
# --------------------------------------------------------------------------


def trace_with_evidence(name: str, *, identities=None, output_hashes=()) -> TrajectoryTrace:
    return TrajectoryTrace(
        run_id=name,
        task_name="t",
        task_instance_id=1,
        trajectory_index=0,
        condition="instrumented",
        completed=True,
        failure_class=None,
        retrieval_selected_identities=identities or {},
        evidence_output_hashes=tuple(output_hashes),
    )


def test_retrieval_identity_jaccard_is_category_qualified():
    """A data-lake entry and a tool that happen to share a bare name must not
    collide - the category prefix is what prevents that."""
    a = trace_with_evidence("a", identities={"tools": ("query_pubmed",), "data_lake": ("query_pubmed",)})
    b = trace_with_evidence("b", identities={"tools": ("query_pubmed",)})
    d = pairwise_diversity(a, b)
    # a has 2 distinct qualified identities, b has 1, intersection is 1 -> 1/2
    assert d["retrieval_identity_jaccard"] == pytest.approx(1 / 2)


def test_retrieval_identity_jaccard_is_none_for_traces_predating_the_instrumentation():
    """Old runs (all of Phase 1 through Phase 2B) have no identity field at all -
    this must read as 'not comparable', not as 'zero overlap', exactly like every
    other empty-side case in this module."""
    a = trace_with_evidence("a")
    b = trace_with_evidence("b", identities={"tools": ("query_pubmed",)})
    d = pairwise_diversity(a, b)
    assert d["retrieval_identity_jaccard"] is None


def test_evidence_output_jaccard_detects_shared_retrieved_content():
    a = trace_with_evidence("a", output_hashes=["h1", "h2"])
    b = trace_with_evidence("b", output_hashes=["h2", "h3"])
    d = pairwise_diversity(a, b)
    assert d["evidence_output_jaccard"] == pytest.approx(1 / 3)


def test_evidence_and_retrieval_metrics_never_enter_workflow_distance():
    """D-30's workflow_distance number must not silently change when this new
    data becomes available - these two metrics were added after it was reported."""
    a = trace_with_evidence("a", identities={"tools": ("x",)}, output_hashes=["h1"])
    b = trace_with_evidence("b", identities={"tools": ("y",)}, output_hashes=["h2"])
    assert "retrieval_identity_jaccard" not in SIMILARITY_COMPONENTS
    assert "evidence_output_jaccard" not in SIMILARITY_COMPONENTS
    d = pairwise_diversity(a, b)
    # both traces have no plan/tools/query/code in the ORIGINAL sense, so the
    # composite must stay None regardless of the new fields being populated.
    assert d["workflow_distance"] is None


# --------------------------------------------------------------------------
# Extraction from artifacts
# --------------------------------------------------------------------------


def test_extract_trace_reads_events_and_transcript(tmp_path):
    events = [
        {
            "event_type": "tool_call_start",
            "step_index": 1,
            "payload": {"tool_name": "query_pubmed", "argument_excerpt": "BRCA1 breast cancer"},
        },
        {"event_type": "code_execution_start", "step_index": 1, "payload": {"code_hash": "abc"}},
        {
            "event_type": "tool_call_end",
            "step_index": 1,
            "payload": {"tool_name": "query_pubmed", "status": "ok", "evidence_output_hash": "outhash1"},
        },
        {"event_type": "tool_call_start", "step_index": 2, "payload": {"tool_name": "query_monarch"}},
        {"event_type": "tool_call_end", "step_index": 2, "payload": {"tool_name": "query_monarch", "status": "error"}},
        {
            "event_type": "retrieval_end",
            "payload": {"selected": {"tools": 7}, "selected_identities": {"tools": ["query_pubmed", "query_monarch"]}},
        },
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    (tmp_path / "transcript.json").write_text(
        json.dumps([{"type": "AIMessage", "content": "<think>the opening plan</think>"}])
    )
    t = extract_trace(
        tmp_path,
        {
            "run_id": "r",
            "task_name": "x",
            "task_instance_id": 1,
            "trajectory_index": 0,
            "condition": "instrumented",
            "completed": True,
            "failure_class": None,
        },
    )
    assert t.tool_seq == ("query_pubmed", "query_monarch")
    assert t.tool_seq_ok == ("query_pubmed",)
    assert t.n_failed_tool_calls == 1
    assert t.code_hashes == ("abc",)
    assert "brca1" in t.query_tokens
    assert t.plan_text == "the opening plan"
    assert t.retrieval_selected == {"tools": 7}
    assert t.retrieval_selected_identities == {"tools": ("query_pubmed", "query_monarch")}
    assert t.evidence_output_hashes == ("outhash1",)


def test_extract_trace_on_a_run_predating_the_instrumentation_yields_empty_identity_fields(tmp_path):
    """Every Phase-1 through Phase-2B run has no `selected_identities` or
    `evidence_output_hash` key at all - old event payloads, not malformed ones.
    This must not raise and must not fabricate data."""
    events = [
        {"event_type": "tool_call_start", "step_index": 1, "payload": {"tool_name": "query_pubmed"}},
        {"event_type": "tool_call_end", "step_index": 1, "payload": {"tool_name": "query_pubmed", "status": "ok"}},
        {"event_type": "retrieval_end", "payload": {"selected": {"tools": 3}}},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    t = extract_trace(
        tmp_path,
        {
            "run_id": "r",
            "task_name": "x",
            "task_instance_id": 1,
            "trajectory_index": 0,
            "condition": "instrumented",
            "completed": True,
            "failure_class": None,
        },
    )
    assert t.retrieval_selected_identities == {}
    assert t.evidence_output_hashes == ()


def test_extract_trace_survives_a_truncated_event_line(tmp_path):
    """Budget-terminated runs really do leave a half-written final line. A failed
    run is evidence and must stay in the sample, so this may not raise."""
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"event_type": "tool_call_start", "step_index": 1, "payload": {"tool_name": "query_pubmed"}})
        + '\n{"event_type": "tool_call_en'
    )
    t = extract_trace(
        tmp_path,
        {
            "run_id": "r",
            "task_name": "x",
            "task_instance_id": 1,
            "trajectory_index": 0,
            "condition": "instrumented",
            "completed": False,
            "failure_class": "budget_terminated_consecutive_runaway",
        },
    )
    assert t.tool_seq == ("query_pubmed",)


def test_extract_trace_on_an_empty_run_dir_returns_empty_structure(tmp_path):
    t = extract_trace(
        tmp_path,
        {
            "run_id": "r",
            "task_name": "x",
            "task_instance_id": 1,
            "trajectory_index": 0,
            "condition": "instrumented",
            "completed": False,
            "failure_class": "model_timeout",
        },
    )
    assert t.tool_seq == () and t.plan_text == "" and not t.has_plan and not t.has_tools
