"""Tests for the Stage C SGLang port of LLM-as-a-Verifier.

The port exists because the reference implementation fails *silently* against
SGLang (see `scripts/stage_c_verifier_port.py`). These tests pin the two
properties that failure mode requires:

1. the constrained alphabet is exactly the G score tokens, so the returned
   `top_logprobs` cover the whole constrained support rather than a truncated
   fragment of it;
2. a backend that does not honour the constraint **raises** rather than
   degrading to a flat 0.5 tie, because a tie caused by infrastructure is
   indistinguishable in the final table from a verifier that could not
   separate two candidates.

No network and no GPU: the verifier client is a fake.
"""

from __future__ import annotations

import json
import math
import os
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import stage_c_verifier_port as port  # noqa: E402

# The reference implementation is an external pinned checkout; skip cleanly
# where it is not present (e.g. a laptop running the CPU suite).
if not os.path.isdir(port.DEFAULT_REF_REPO):
    pytest.skip("reference LLM-as-a-Verifier checkout not available", allow_module_level=True)
if port.DEFAULT_REF_REPO not in sys.path:
    sys.path.insert(0, port.DEFAULT_REF_REPO)

fgr = pytest.importorskip(
    "llm_verifier.fine_grained_reward",
    reason="reference LLM-as-a-Verifier checkout not importable",
)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class _Alt:
    def __init__(self, token: str, logprob: float):
        self.token = token
        self.logprob = logprob


class _Pos:
    """One generated position. `token`/`logprob` are read by the reference's
    main generation path; `top_logprobs` by the prefill path."""

    def __init__(self, alts):
        self.top_logprobs = alts
        self.token = alts[0].token if alts else ""
        self.logprob = alts[0].logprob if alts else 0.0


class _Logprobs:
    def __init__(self, alts):
        self.content = [_Pos(alts)]


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, alts):
        self.message = _Message(content)
        self.logprobs = _Logprobs(alts) if alts is not None else None


class _Response:
    def __init__(self, content, alts):
        self.choices = [_Choice(content, alts)]


class FakeClient:
    """Minimal stand-in for the OpenAI client used by the prefill path."""

    def __init__(self, alts, content="A", raise_on_call=False):
        self._alts = alts
        self._content = content
        self._raise = raise_on_call
        self.calls: list[dict] = []

        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if outer._raise:
                    raise RuntimeError("backend exploded")
                return _Response(outer._content, outer._alts)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _uniform_scale_alts(n=20):
    """A proper constrained distribution: all mass on the n scale letters."""
    p = 1.0 / n
    return [_Alt(chr(65 + i), math.log(p)) for i in range(n)]


def _peaked_scale_alts(letter="A", peak=0.99, n=20):
    rest = (1.0 - peak) / (n - 1)
    out = []
    for i in range(n):
        c = chr(65 + i)
        out.append(_Alt(c, math.log(peak if c == letter else rest)))
    return out


# ---------------------------------------------------------------------------
# the constrained alphabet
# ---------------------------------------------------------------------------


def test_scale_regex_has_exactly_g_alternatives_and_no_optional_space():
    """The whole point of the narrowed alphabet: support size == top_logprobs cap.

    With the reference's 40-token alphabet the returned top-20 is a truncated
    view of the constrained distribution, and `extract_score` renormalizes over
    whatever fragment came back.
    """
    rx = port.scale_regex(fgr.GRANULARITY)
    assert rx == "(" + "|".join(chr(65 + i) for i in range(fgr.GRANULARITY)) + ")"
    assert "( )?" not in rx
    assert rx.count("|") == fgr.GRANULARITY - 1


def test_scale_letters_are_the_ordered_score_tokens():
    letters = port.scale_letters(fgr.GRANULARITY)
    assert letters[0] == "A" and letters[-1] == "T"
    assert len(letters) == fgr.GRANULARITY
    # every letter must map to a value the reference scale knows
    assert all(c in fgr.SCALE["valid_tokens"] for c in letters)


# ---------------------------------------------------------------------------
# coverage measurement
# ---------------------------------------------------------------------------


def test_on_scale_mass_counts_only_scale_tokens():
    valid = fgr.SCALE["valid_tokens"]
    alts = [_Alt("A", math.log(0.5)), _Alt("2", math.log(0.3)), _Alt("!", math.log(0.2))]
    mass = port.on_scale_mass([(a.token, a.logprob) for a in alts], valid)
    assert mass == pytest.approx(0.5)


def test_on_scale_mass_accepts_space_prefixed_and_lowercase_spellings():
    valid = fgr.SCALE["valid_tokens"]
    alts = [(" A", math.log(0.4)), ("b", math.log(0.4)), ("2", math.log(0.2))]
    assert port.on_scale_mass(alts, valid) == pytest.approx(0.8)


def test_full_constrained_distribution_measures_one():
    valid = fgr.SCALE["valid_tokens"]
    alts = [(a.token, a.logprob) for a in _uniform_scale_alts()]
    assert port.on_scale_mass(alts, valid) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# the silent-failure path is closed
# ---------------------------------------------------------------------------


def test_unhonoured_constraint_raises_instead_of_tying():
    """This is the regression the port exists to prevent.

    SGLang silently ignores vLLM's `structured_outputs`, leaving the score
    position unconstrained. The reference code would fall through to a 0.5
    tie; the port must refuse.
    """
    off_scale = [("2", math.log(0.6)), ("1", math.log(0.3)), ("A", math.log(0.1))]
    client = FakeClient([_Alt(t, lp) for t, lp in off_scale])
    fn = port.make_score_tags_by_prefill(fgr)
    with pytest.raises(port.PortValidationError, match="covers only"):
        fn(client, "m", [{"role": "user", "content": "x"}], "analysis", ["<score_A>"])


def test_missing_logprobs_raises():
    client = FakeClient(None)
    fn = port.make_score_tags_by_prefill(fgr)
    with pytest.raises(port.PortValidationError, match="no top_logprobs"):
        fn(client, "m", [{"role": "user", "content": "x"}], "analysis", ["<score_A>"])


def test_backend_exception_is_wrapped_not_swallowed():
    client = FakeClient(_uniform_scale_alts(), raise_on_call=True)
    fn = port.make_score_tags_by_prefill(fgr)
    with pytest.raises(port.PortValidationError, match="constrained prefill call failed"):
        fn(client, "m", [{"role": "user", "content": "x"}], "analysis", ["<score_A>"])


# ---------------------------------------------------------------------------
# the happy path still satisfies the reference contract
# ---------------------------------------------------------------------------


def test_prefill_sends_sglang_constraint_arguments():
    client = FakeClient(_uniform_scale_alts())
    fn = port.make_score_tags_by_prefill(fgr)
    fn(client, "m", [{"role": "user", "content": "x"}], "analysis", ["<score_A>"])
    extra = client.calls[0]["extra_body"]
    assert extra["continue_final_message"] is True
    assert extra["add_generation_prompt"] is False
    assert extra["regex"] == port.scale_regex(fgr.GRANULARITY)
    # vLLM's argument must not be sent: SGLang ignores it silently
    assert "structured_outputs" not in extra
    assert client.calls[0]["max_tokens"] == 1
    assert client.calls[0]["logprobs"] is True


def test_returned_shape_is_consumable_by_extract_score():
    """The port must return `(text, tokens, position_logprobs)` in exactly the
    shape `extract_score` expects, or scores silently become 0.5."""
    client = FakeClient(_peaked_scale_alts("A", peak=0.99), content="A")
    fn = port.make_score_tags_by_prefill(fgr)
    text, tokens, pos = fn(client, "m", [{"role": "user", "content": "x"}], "analysis", ["<score_A>"])
    score = fgr.extract_score(text, tokens, pos, "<score_A>")
    assert score != 0.5, "0.5 is the reference's failure sentinel"
    assert score > 0.95, "mass concentrated on A (best) must score near 1.0"


def test_worst_letter_scores_near_zero():
    client = FakeClient(_peaked_scale_alts("T", peak=0.99), content="T")
    fn = port.make_score_tags_by_prefill(fgr)
    text, tokens, pos = fn(client, "m", [{"role": "user", "content": "x"}], "analysis", ["<score_A>"])
    assert fgr.extract_score(text, tokens, pos, "<score_A>") < 0.05


def test_both_score_tags_are_scored_independently():
    client = FakeClient(_uniform_scale_alts())
    fn = port.make_score_tags_by_prefill(fgr)
    fn(client, "m", [{"role": "user", "content": "x"}], "analysis", ["<score_A>", "<score_B>"])
    assert len(client.calls) == 2


# ---------------------------------------------------------------------------
# installation and error logging
# ---------------------------------------------------------------------------


def test_install_replaces_the_reference_prefill_function():
    original = fgr._score_tags_by_prefill
    try:
        port.install()
        assert fgr._score_tags_by_prefill is not original
        assert fgr._stage_c_ported is True
    finally:
        fgr._score_tags_by_prefill = original


def test_error_log_records_failures_and_still_reraises(tmp_path):
    """The reference runner converts a failed comparison into a 0.5/0.5 tie.
    That policy is kept for comparability, so the failure must be recorded
    somewhere or the reported score is silently contaminated.
    """
    log = tmp_path / "errors.jsonl"
    original_prefill = fgr._score_tags_by_prefill
    original_score = fgr.score_pair_criterion
    try:
        port.install(error_log=str(log))

        # all mass off-scale -> the port refuses rather than returning a tie
        client = FakeClient([_Alt("2", math.log(1.0))])
        crit = {"id": "evidence", "name": "Evidence", "description": "d"}
        with pytest.raises(port.PortValidationError):
            fgr.score_pair_criterion(client, "problem", "trace a", "trace b", crit, "note", model="fake-model")

        records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        assert len(records) == 1
        assert records[0]["criterion"] == "evidence"
        assert records[0]["error_type"] == "PortValidationError"
        assert records[0]["trace_a_chars"] == len("trace a")
    finally:
        fgr._score_tags_by_prefill = original_prefill
        fgr.score_pair_criterion = original_score
