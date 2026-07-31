from __future__ import annotations

import math

import pytest

from biomni_uncertainty.confidence import (
    ConfidenceResult,
    confidence_instruction,
    extract_confidence,
)

OPEN = "<BIOMNI_CONFIDENCE>"
CLOSE = "</BIOMNI_CONFIDENCE>"


def block(body: str) -> str:
    return f"{OPEN}\n{body}\n{CLOSE}"


def test_extracts_well_formed_block_and_normalizes():
    text = f"ANSWER: BRCA1\n{block(chr(123) + chr(34) + 'confidence' + chr(34) + ': 73.250}')}"
    r = extract_confidence(text, OPEN, CLOSE)
    assert r.status == "ok"
    assert r.confidence_0_100 == pytest.approx(73.25)
    assert r.confidence == pytest.approx(0.7325)
    assert "BIOMNI_CONFIDENCE" not in r.cleaned_text
    assert r.cleaned_text.strip() == "ANSWER: BRCA1"


def test_boundary_values_accepted():
    for v, expect in ((0, 0.0), (100, 1.0), (0.0, 0.0), (99.999, 0.99999)):
        r = extract_confidence(block(f'{{"confidence": {v}}}'), OPEN, CLOSE)
        assert r.status == "ok"
        assert r.confidence == pytest.approx(expect)


@pytest.mark.parametrize(
    "body,status",
    [
        ("not json at all !!", "malformed_json"),
        ('{"conf": 50}', "missing_field"),
        ('{"confidence": "high"}', "not_numeric"),
        ('{"confidence": true}', "not_numeric"),
        ('{"confidence": 150}', "out_of_range"),
        ('{"confidence": -1}', "out_of_range"),
        ('{"confidence": NaN}', "out_of_range"),
        ('{"confidence": Infinity}', "out_of_range"),
    ],
)
def test_malformed_blocks_are_classified_not_crashing(body, status):
    r = extract_confidence("Answer: A\n" + block(body), OPEN, CLOSE)
    assert r.status == status
    assert r.confidence is None
    # The answer must survive a broken confidence report.
    assert "Answer: A" in r.cleaned_text
    assert OPEN not in r.cleaned_text


def test_missing_block_recorded_not_defaulted():
    r = extract_confidence("Answer: A", OPEN, CLOSE)
    assert r.status == "missing"
    assert r.confidence is None
    assert r.n_blocks == 0


def test_not_requested_is_distinct_from_missing():
    r = extract_confidence("Answer: A", OPEN, CLOSE, requested=False)
    assert r.status == "not_requested"
    assert r.confidence is None


def test_unterminated_block_is_stripped_so_answer_survives():
    r = extract_confidence(f'Answer: A\n{OPEN}\n{{"confidence": 8', OPEN, CLOSE)
    assert r.status == "missing"
    assert r.cleaned_text.strip() == "Answer: A"


def test_multiple_blocks_uses_last_and_flags():
    text = "A\n" + block('{"confidence": 10}') + "\nmore\n" + block('{"confidence": 90}')
    r = extract_confidence(text, OPEN, CLOSE)
    assert r.status == "multiple_blocks"
    assert r.confidence == pytest.approx(0.9)
    assert r.n_blocks == 2
    assert OPEN not in r.cleaned_text


def test_tolerates_loose_formats():
    for body, expected in (
        ("{'confidence': 42}", 0.42),
        ("55", 0.55),
        ('```json\n{"confidence": 33}\n```', 0.33),
        ('{"confidence": "77%"}', 0.77),
    ):
        r = extract_confidence(block(body), OPEN, CLOSE)
        assert r.status == "ok", body
        assert r.confidence == pytest.approx(expected)


def test_instruction_mentions_answer_first_and_both_delimiters():
    text = confidence_instruction(OPEN, CLOSE)
    assert OPEN in text and CLOSE in text
    assert "EXACT format" in text
    # The instruction must place the answer before the confidence report.
    assert text.index("EXACT format") < text.index(OPEN)


def test_case_insensitive_delimiters():
    r = extract_confidence('X\n<biomni_confidence>{"confidence": 20}</biomni_confidence>', OPEN, CLOSE)
    assert r.status == "ok"
    assert r.confidence == pytest.approx(0.2)


def test_result_is_frozen_dataclass():
    r = extract_confidence(block('{"confidence": 1}'), OPEN, CLOSE)
    assert isinstance(r, ConfidenceResult)
    with pytest.raises(AttributeError):  # frozen dataclass
        r.confidence = 0.5  # type: ignore[misc]


def test_none_input_does_not_crash():
    r = extract_confidence(None, OPEN, CLOSE)  # type: ignore[arg-type]
    assert r.status == "missing"
    assert not math.isnan(0.0)
