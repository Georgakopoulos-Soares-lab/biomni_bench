"""Verbalized-confidence elicitation and extraction.

Placement matters. Biomni configures its LLM with ``stop_sequences=["</execute>",
"</solution>"]``, so *nothing after* ``</solution>`` is ever generated. The
confidence block therefore has to be emitted **inside** the solution block, after
the task answer. The extractor removes it before task-answer parsing, so the
benchmark answer format is untouched.

Confidence is reported on a 0-100 scale and normalized to [0,1] for analysis.
Missing / malformed blocks are recorded explicitly and never silently defaulted.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Literal

DEFAULT_OPEN = "<BIOMNI_CONFIDENCE>"
DEFAULT_CLOSE = "</BIOMNI_CONFIDENCE>"

ConfidenceStatus = Literal[
    "ok",
    "missing",
    "malformed_json",
    "missing_field",
    "not_numeric",
    "out_of_range",
    "multiple_blocks",
    "not_requested",
]


@dataclass(frozen=True)
class ConfidenceResult:
    """Outcome of extracting a confidence block from a raw response."""

    status: ConfidenceStatus
    confidence_0_100: float | None
    confidence: float | None  # normalized to [0,1]
    cleaned_text: str
    n_blocks: int
    raw_block: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict:
        return asdict(self)


def confidence_instruction(open_delim: str = DEFAULT_OPEN, close_delim: str = DEFAULT_CLOSE) -> str:
    """The system-prompt suffix that requests a final confidence value.

    Deliberately short and explicit that the task format comes first, so the
    benchmark answer stays parseable by the official evaluator's expectations.
    """
    return (
        "\n\n## FINAL CONFIDENCE REPORT (required)\n"
        "When you emit your final <solution> block, you must do TWO things, in this order:\n"
        "1. First, give the answer in the EXACT format the task requires. Do not change, wrap, "
        "or annotate that answer in any way.\n"
        "2. Then, on a new line still inside the same <solution> block, append a confidence report "
        "in exactly this machine-readable form:\n"
        f"{open_delim}\n"
        '{"confidence": <number between 0 and 100>}\n'
        f"{close_delim}\n"
        "The number is your probability, in percent, that your answer is correct: 0 means certainly "
        "wrong, 100 means certainly correct. Be honest and discriminative - use the full range rather "
        "than always reporting a high value.\n"
        "The confidence report is supplemental telemetry. It must come AFTER the task answer and must "
        "never replace or reformat it. Emit it only once, in the final solution block.\n"
    )


def _block_regex(open_delim: str, close_delim: str) -> re.Pattern:
    return re.compile(
        re.escape(open_delim) + r"(.*?)" + re.escape(close_delim),
        re.DOTALL | re.IGNORECASE,
    )


def extract_confidence(
    text: str,
    open_delim: str = DEFAULT_OPEN,
    close_delim: str = DEFAULT_CLOSE,
    *,
    requested: bool = True,
) -> ConfidenceResult:
    """Split ``text`` into (task answer text, confidence value).

    The confidence block is always stripped from ``cleaned_text`` even when its
    contents are malformed, so a broken confidence report cannot corrupt answer
    parsing. If several blocks are present the LAST one is used (it is the final
    self-report) and the status records the anomaly.
    """
    if text is None:
        text = ""
    if not requested:
        return ConfidenceResult("not_requested", None, None, text, 0)

    pat = _block_regex(open_delim, close_delim)
    matches = list(pat.finditer(text))
    cleaned = pat.sub("", text).strip()

    if not matches:
        # Tolerate an unterminated block (generation cut off mid-report) by
        # stripping from the opening delimiter onward, so the answer survives.
        lowered = text.lower()
        pos = lowered.rfind(open_delim.lower())
        if pos != -1:
            cleaned = text[:pos].strip()
        return ConfidenceResult("missing", None, None, cleaned, 0)

    n = len(matches)
    body = matches[-1].group(1).strip()
    raw_block = matches[-1].group(0)
    status_prefix: ConfidenceStatus = "multiple_blocks" if n > 1 else "ok"

    value = _parse_body(body)
    if isinstance(value, str):  # error code
        return ConfidenceResult(value, None, None, cleaned, n, raw_block)

    if n > 1:
        # Value parsed fine but the model emitted more than one block: keep the
        # value, flag the anomaly so it can be reported as a parse irregularity.
        return ConfidenceResult(status_prefix, value, value / 100.0, cleaned, n, raw_block)
    return ConfidenceResult("ok", value, value / 100.0, cleaned, n, raw_block)


def _parse_body(body: str) -> float | ConfidenceStatus:
    """Parse the JSON body of a confidence block; return a float or an error status."""
    obj = None
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        # Tolerate a bare number or a fenced/loose JSON object.
        stripped = body.strip().strip("`").strip()
        m = re.search(r"\{.*\}", stripped, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                try:
                    obj = json.loads(m.group(0).replace("'", '"'))
                except json.JSONDecodeError:
                    obj = None
        if obj is None:
            if re.fullmatch(r"[+-]?\d+(\.\d+)?", stripped):
                obj = {"confidence": float(stripped)}
            else:
                return "malformed_json"

    if not isinstance(obj, dict):
        if isinstance(obj, (int, float)):
            obj = {"confidence": obj}
        else:
            return "malformed_json"

    if "confidence" not in obj:
        return "missing_field"

    raw = obj["confidence"]
    if isinstance(raw, bool):
        return "not_numeric"
    if isinstance(raw, str):
        s = raw.strip().rstrip("%").strip()
        try:
            raw = float(s)
        except ValueError:
            return "not_numeric"
    if not isinstance(raw, (int, float)):
        return "not_numeric"

    val = float(raw)
    if not math.isfinite(val):
        return "out_of_range"
    if val < 0.0 or val > 100.0:
        return "out_of_range"
    return val
