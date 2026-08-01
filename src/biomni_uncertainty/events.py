"""Append-only JSONL trajectory event log with redaction.

One file per run (``events.jsonl``). Each line is a self-contained JSON object;
a truncated tail line (e.g. from a killed process) is tolerated by the reader.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EVENT_TYPES = frozenset(
    {
        "agent_start",
        "agent_end",
        "llm_request_start",
        "llm_request_end",
        "planning_step",
        "tool_call_start",
        "tool_call_end",
        "code_execution_start",
        "code_execution_end",
        "retrieval_start",
        "retrieval_end",
        "retry",
        "parse_error",
        "exception",
        "final_answer",
        "confidence_extracted",
        # Phase-1.5 trajectory-budget guards (see budget.py). These record what a
        # guard did, so a repaired run's behaviour is auditable against a Phase-1
        # run that had no guards at all.
        "budget_warning",
        "budget_terminated",
        "runaway_truncated",
        "observation_truncated",
        "retrieval_capped",
    }
)

REQUIRED_FIELDS = ("run_id", "event_index", "timestamp", "event_type")

DEFAULT_REDACT_PATTERNS = (
    r"(?i)\b(sk-[A-Za-z0-9_\-]{16,})",
    r"(?i)\b(hf_[A-Za-z0-9]{20,})",
    r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([^\s\"',]{8,})",
    r"(?i)(authorization\"?\s*[:=]\s*\"?)(bearer\s+)?([^\s\"',]{8,})",
    r"(?i)(token\"?\s*[:=]\s*\"?)([^\s\"',]{12,})",
    r"(?i)(secret\"?\s*[:=]\s*\"?)([^\s\"',]{8,})",
    r"(?i)(password\"?\s*[:=]\s*\"?)([^\s\"',]{4,})",
)

# Used to decide which *environment variable values* to blacklist. Deliberately
# broad: over-redacting an env value costs nothing.
SECRET_ENV_NAME = re.compile(r"(?i)(key|token|secret|password|passwd|credential)")

# Used to decide which *payload keys* to redact wholesale. Requires the
# credential word to sit on a token boundary, so telemetry names survive:
# "input_tokens" / "max_tokens" do not match (the word is "tokens", plural),
# while "token", "auth_token" and "HF_TOKEN" do. Getting this wrong silently
# destroys the primary length signal, so there is a regression test for it.
SECRET_PAYLOAD_KEY = re.compile(
    r"(?i)(^|[_\-.])(api[_\-]?key|key|secret|password|passwd|credential|credentials"
    r"|authorization|auth|bearer|token)([_\-.]|$)"
)

_REDACTED = "[REDACTED]"


class Redactor:
    """Removes secrets from strings and nested payloads.

    Redaction is applied to *values*; keys whose name looks secret-bearing are
    replaced wholesale so we never depend on the value matching a pattern.
    """

    def __init__(self, patterns: tuple[str, ...] | list[str] = DEFAULT_REDACT_PATTERNS, max_chars: int = 20000):
        self._patterns = [re.compile(p) for p in patterns]
        self.max_chars = max_chars
        # Any environment value that looks like a credential is redacted verbatim,
        # which catches secrets that leak into tracebacks or subprocess output.
        self._literals = sorted(
            {
                v
                for k, v in os.environ.items()
                if SECRET_ENV_NAME.search(k) and isinstance(v, str) and len(v) >= 8 and v.upper() != "EMPTY"
            },
            key=len,
            reverse=True,
        )

    def text(self, value: str) -> str:
        if not isinstance(value, str):
            return value
        out = value
        for lit in self._literals:
            if lit in out:
                out = out.replace(lit, _REDACTED)
        for pat in self._patterns:
            out = pat.sub(lambda m: self._sub(m), out)
        if len(out) > self.max_chars:
            out = out[: self.max_chars] + f"...[TRUNCATED {len(out) - self.max_chars} chars]"
        return out

    @staticmethod
    def _sub(m: re.Match) -> str:
        # Keep any leading "key=" style prefix group, drop the secret itself.
        if m.lastindex and m.lastindex >= 2:
            return f"{m.group(1)}{_REDACTED}"
        return _REDACTED

    def payload(self, value: Any, _depth: int = 0) -> Any:
        if _depth > 12:
            return "[MAX_DEPTH]"
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if isinstance(k, str) and SECRET_PAYLOAD_KEY.search(k):
                    out[k] = _REDACTED
                else:
                    out[k] = self.payload(v, _depth + 1)
            return out
        if isinstance(value, (list, tuple)):
            return [self.payload(v, _depth + 1) for v in value]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return self.text(str(value))


@dataclass
class EventLogger:
    """Thread-safe append-only JSONL writer for one run."""

    run_id: str
    path: Path
    redactor: Redactor = field(default_factory=Redactor)
    _index: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event_type: str,
        *,
        step_index: int | None = None,
        duration_seconds: float | None = None,
        **payload: Any,
    ) -> dict:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown event_type {event_type!r}; allowed: {sorted(EVENT_TYPES)}")
        with self._lock:
            idx = self._index
            self._index += 1
            record = {
                "run_id": self.run_id,
                "event_index": idx,
                "timestamp": time.time(),
                "event_type": event_type,
            }
            if step_index is not None:
                record["step_index"] = step_index
            if duration_seconds is not None:
                record["duration_seconds"] = round(float(duration_seconds), 6)
            record["payload"] = self.redactor.payload(payload)
            line = json.dumps(record, ensure_ascii=False, default=str)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return record


def read_events(path: str | Path) -> list[dict]:
    """Read an events file, skipping a truncated final line."""
    return list(iter_events(path))


def iter_events(path: str | Path) -> Iterator[dict]:
    p = Path(path)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # Truncated tail from a killed process: stop, do not guess.
                return


def validate_event(record: dict) -> list[str]:
    """Return a list of schema problems (empty means valid)."""
    problems = []
    for f in REQUIRED_FIELDS:
        if f not in record:
            problems.append(f"missing field {f}")
    et = record.get("event_type")
    if et is not None and et not in EVENT_TYPES:
        problems.append(f"unknown event_type {et!r}")
    if "event_index" in record and not isinstance(record["event_index"], int):
        problems.append("event_index must be int")
    if "payload" in record and not isinstance(record["payload"], dict):
        problems.append("payload must be an object")
    return problems
