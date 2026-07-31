from __future__ import annotations

import json
import os
import threading

import pytest

from biomni_uncertainty.events import (
    EVENT_TYPES,
    EventLogger,
    Redactor,
    read_events,
    validate_event,
)

# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def test_every_documented_event_type_is_accepted(tmp_path):
    log = EventLogger("run1", tmp_path / "events.jsonl")
    for et in sorted(EVENT_TYPES):
        log.emit(et, note="x")
    events = read_events(tmp_path / "events.jsonl")
    assert len(events) == len(EVENT_TYPES)
    assert {e["event_type"] for e in events} == EVENT_TYPES


def test_unknown_event_type_is_rejected(tmp_path):
    log = EventLogger("run1", tmp_path / "events.jsonl")
    with pytest.raises(ValueError):
        log.emit("not_a_real_event")


def test_required_fields_and_monotonic_index(tmp_path):
    log = EventLogger("run1", tmp_path / "events.jsonl")
    for i in range(5):
        log.emit("planning_step", step_index=i, duration_seconds=0.5)
    events = read_events(tmp_path / "events.jsonl")
    assert [e["event_index"] for e in events] == [0, 1, 2, 3, 4]
    for e in events:
        assert validate_event(e) == []
        assert e["run_id"] == "run1"
        assert isinstance(e["timestamp"], float)
        assert "payload" in e


def test_validate_event_reports_problems():
    assert "missing field run_id" in validate_event({"event_index": 0, "timestamp": 1.0, "event_type": "retry"})
    assert any(
        "unknown event_type" in p
        for p in validate_event({"run_id": "a", "event_index": 0, "timestamp": 1.0, "event_type": "bogus"})
    )


def test_truncated_tail_line_is_tolerated(tmp_path):
    p = tmp_path / "events.jsonl"
    log = EventLogger("run1", p)
    log.emit("agent_start")
    log.emit("agent_end")
    with open(p, "a") as fh:
        fh.write('{"run_id": "run1", "event_ind')  # killed mid-write
    events = read_events(p)
    assert len(events) == 2


def test_concurrent_emits_do_not_interleave(tmp_path):
    p = tmp_path / "events.jsonl"
    log = EventLogger("run1", p)

    def worker(n):
        for _ in range(25):
            log.emit("llm_request_end", worker=n)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = read_events(p)
    assert len(events) == 100
    assert sorted(e["event_index"] for e in events) == list(range(100))


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "using sk-abcdefghijklmnop1234567890",
        "token hf_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        'api_key: "supersecretvalue123"',
        "Authorization: Bearer abcdefghijklmnop",
        'password="hunter22"',
        'secret = "topsecretstuff"',
    ],
)
def test_secret_patterns_are_redacted(text):
    out = Redactor().text(text)
    assert "[REDACTED]" in out
    for token in ("sk-abcdefghijklmnop1234567890", "supersecretvalue123", "hunter22", "topsecretstuff"):
        assert token not in out


def test_secret_bearing_keys_are_redacted_wholesale():
    payload = {"api_key": "short", "AUTH_TOKEN": "x", "model": "biomni/Biomni-R0-32B-Preview"}
    out = Redactor().payload(payload)
    assert out["api_key"] == "[REDACTED]"
    assert out["AUTH_TOKEN"] == "[REDACTED]"
    assert out["model"] == "biomni/Biomni-R0-32B-Preview"


def test_environment_secret_values_are_redacted_even_without_a_pattern(monkeypatch):
    monkeypatch.setenv("MY_SERVICE_TOKEN", "zzzzz-unusual-value-9876")
    r = Redactor()
    out = r.text("traceback mentions zzzzz-unusual-value-9876 verbatim")
    assert "zzzzz-unusual-value-9876" not in out
    assert "[REDACTED]" in out


def test_placeholder_api_key_is_not_treated_as_a_secret(monkeypatch):
    monkeypatch.setenv("BIOMNI_CUSTOM_API_KEY", "EMPTY")
    r = Redactor()
    assert r.text("api key is EMPTY here") == "api key is EMPTY here"


def test_redaction_applies_to_nested_payloads(tmp_path):
    log = EventLogger("run1", tmp_path / "events.jsonl")
    log.emit("tool_call_start", args={"nested": ["sk-aaaaaaaaaaaaaaaaaaaaaaa", {"api_key": "v"}]})
    raw = (tmp_path / "events.jsonl").read_text()
    assert "sk-aaaaaaaaaaaaaaaaaaaaaaa" not in raw
    assert "[REDACTED]" in raw


def test_long_payloads_are_truncated_not_dropped():
    r = Redactor(max_chars=100)
    out = r.text("a" * 500)
    assert len(out) < 200
    assert "TRUNCATED" in out


def test_no_full_environment_dump_in_events(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_UNIQUE_ENV_MARKER", "marker-value-xyz")
    log = EventLogger("run1", tmp_path / "events.jsonl")
    log.emit("agent_start", endpoint="http://localhost:30000/v1")
    raw = (tmp_path / "events.jsonl").read_text()
    assert "SOME_UNIQUE_ENV_MARKER" not in raw
    assert "PATH" not in json.loads(raw)["payload"]


def test_events_file_is_append_only(tmp_path):
    p = tmp_path / "events.jsonl"
    a = EventLogger("run1", p)
    a.emit("agent_start")
    size_after_first = os.path.getsize(p)
    a.emit("agent_end")
    assert os.path.getsize(p) > size_after_first
    assert len(read_events(p)) == 2
