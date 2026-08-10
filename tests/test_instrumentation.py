"""Tests for the retrieval/evidence-provenance instrumentation added as VERIFY
prerequisite item 2 (`reports/evidence_channel_repair.md`).

Before this change, `retrieval_end` logged only counts of selected resources
and `tool_call_end` carried no link to what a tool actually returned. That made
"did VERIFY obtain independent evidence" unfalsifiable
(`reports/verify_definition.md` SS5.3). These tests prove the new fields are
actually populated, not merely present in the code.

A real `EventLogger` writing to `tmp_path` is used throughout - the same
pattern `tests/test_event_schema.py` uses - so what is asserted is what a real
run directory would contain, not a mock's idea of it.
"""

from __future__ import annotations

import hashlib

import pytest

from biomni_uncertainty.events import EventLogger, read_events
from biomni_uncertainty.instrumentation import AgentInstrumentation, TrajectoryStats, _resource_identity

# --------------------------------------------------------------------------
# _resource_identity: the three resource shapes Biomni's retriever handles
# --------------------------------------------------------------------------


def test_resource_identity_from_a_dict_with_a_name():
    assert _resource_identity({"name": "query_pubmed", "description": "long text..."}) == "query_pubmed"


def test_resource_identity_from_a_plain_string():
    assert _resource_identity("query_ensembl") == "query_ensembl"


class _NamedThing:
    def __init__(self, name):
        self.name = name
        self.description = "irrelevant"


def test_resource_identity_from_an_attribute_bearing_object():
    assert _resource_identity(_NamedThing("query_clinvar")) == "query_clinvar"


def test_resource_identity_falls_back_to_a_content_hash_when_nameless():
    """A nameless resource still needs a stable identity: two occurrences of the
    exact same nameless thing must compare equal, two different ones must not."""
    same_a = _resource_identity({"description": "no name field"})
    same_b = _resource_identity({"description": "no name field"})
    different = _resource_identity({"description": "something else entirely"})
    assert same_a == same_b
    assert same_a != different
    assert same_a.startswith("unnamed:")


# --------------------------------------------------------------------------
# retrieval_end: selected_identities, not just counts
# --------------------------------------------------------------------------


class _FakeRetriever:
    def __init__(self, out: dict):
        self._out = out
        self.calls = 0

    def prompt_based_retrieval(self, query, resources, llm=None, **kw):
        self.calls += 1
        return self._out


class _FakeLLM:
    callbacks: list = []


class _FakeAgent:
    def __init__(self, retriever):
        self.llm = _FakeLLM()
        self.retriever = retriever


def test_retrieval_end_logs_identities_alongside_counts(tmp_path):
    retriever = _FakeRetriever(
        {
            "tools": [{"name": "query_pubmed", "description": "..."}, {"name": "query_ensembl", "description": "..."}],
            "data_lake": ["GRCh38_annotation"],
        }
    )
    agent = _FakeAgent(retriever)
    log = EventLogger("run1", tmp_path / "events.jsonl")
    inst = AgentInstrumentation(agent, log, TrajectoryStats())
    inst._patch_retrieval()

    agent.retriever.prompt_based_retrieval("some query", {"tools": [], "data_lake": []})

    events = read_events(tmp_path / "events.jsonl")
    end = next(e for e in events if e["event_type"] == "retrieval_end")
    assert end["payload"]["selected"] == {"tools": 2, "data_lake": 1}
    assert end["payload"]["selected_identities"] == {
        "tools": ["query_pubmed", "query_ensembl"],
        "data_lake": ["GRCh38_annotation"],
    }


def test_retrieval_identities_survive_an_empty_selection(tmp_path):
    """No resources selected must log an empty identity dict, never crash and
    never be indistinguishable from 'the field was never added'."""
    agent = _FakeAgent(_FakeRetriever({}))
    log = EventLogger("run1", tmp_path / "events.jsonl")
    inst = AgentInstrumentation(agent, log, TrajectoryStats())
    inst._patch_retrieval()

    agent.retriever.prompt_based_retrieval("q", {"tools": [], "data_lake": []})

    end = next(e for e in read_events(tmp_path / "events.jsonl") if e["event_type"] == "retrieval_end")
    assert end["payload"]["selected_identities"] == {}


# --------------------------------------------------------------------------
# code_execution_end / tool_call_end: output_hash / evidence_output_hash
# --------------------------------------------------------------------------


@pytest.fixture
def biomni_a1(monkeypatch):
    """The real `biomni.agent.a1` module, with `run_with_timeout` swapped for a
    scripted stand-in and restored after the test. `_patch_execution` patches
    this module directly (it is the graph's single execution choke point), so
    a fake module would not exercise the real code path."""
    a1 = pytest.importorskip("biomni.agent.a1")
    original = a1.run_with_timeout

    def scripted(func, args, timeout=600):
        return func(*args)

    monkeypatch.setattr(a1, "run_with_timeout", scripted)
    yield a1
    a1.run_with_timeout = original


def test_code_execution_end_and_tool_call_end_carry_the_same_output_hash(tmp_path, biomni_a1):
    agent = _FakeAgent(_FakeRetriever({}))
    log = EventLogger("run1", tmp_path / "events.jsonl")
    inst = AgentInstrumentation(agent, log, TrajectoryStats())
    inst._patch_execution()

    code = "from biomni.tool.literature import query_pubmed\nquery_pubmed('x')"
    result_text = "Title: a paper\nAbstract: findings"
    biomni_a1.run_with_timeout(lambda c: result_text, (code,), timeout=60)

    events = read_events(tmp_path / "events.jsonl")
    exec_end = next(e for e in events if e["event_type"] == "code_execution_end")
    call_end = next(e for e in events if e["event_type"] == "tool_call_end")

    expected_hash = hashlib.sha256(result_text.encode("utf-8")).hexdigest()[:16]
    assert exec_end["payload"]["output_hash"] == expected_hash
    assert call_end["payload"]["evidence_output_hash"] == expected_hash


def test_identical_output_text_produces_the_same_hash_different_text_does_not(tmp_path, biomni_a1):
    agent = _FakeAgent(_FakeRetriever({}))
    log = EventLogger("run1", tmp_path / "events.jsonl")
    inst = AgentInstrumentation(agent, log, TrajectoryStats())
    inst._patch_execution()

    code = "from biomni.tool.literature import query_pubmed\nquery_pubmed('x')"
    biomni_a1.run_with_timeout(lambda c: "same content", (code,), timeout=60)
    biomni_a1.run_with_timeout(lambda c: "same content", (code,), timeout=60)
    biomni_a1.run_with_timeout(lambda c: "different content entirely", (code,), timeout=60)

    hashes = [
        e["payload"]["output_hash"]
        for e in read_events(tmp_path / "events.jsonl")
        if e["event_type"] == "code_execution_end"
    ]
    assert hashes[0] == hashes[1]
    assert hashes[0] != hashes[2]


def test_output_hash_is_none_for_empty_output(tmp_path, biomni_a1):
    """An empty result (nothing retrieved) must not hash to a value that would
    collide with a genuinely-empty different trajectory under a naive Jaccard -
    None means 'nothing to compare', not 'compares as identical to every other
    empty result'."""
    agent = _FakeAgent(_FakeRetriever({}))
    log = EventLogger("run1", tmp_path / "events.jsonl")
    inst = AgentInstrumentation(agent, log, TrajectoryStats())
    inst._patch_execution()

    code = "print('nothing found')"
    biomni_a1.run_with_timeout(lambda c: "", (code,), timeout=60)

    exec_end = next(e for e in read_events(tmp_path / "events.jsonl") if e["event_type"] == "code_execution_end")
    assert exec_end["payload"]["output_hash"] is None
