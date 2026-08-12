#!/usr/bin/env python3
"""Stage C — SGLang port of LLM-as-a-Verifier (arXiv 2607.05391).

Why this file exists
--------------------
The reference implementation supports any OpenAI-compatible server that
returns token-level logprobs, and names SGLang explicitly. It does **not**
work correctly against SGLang out of the box, and it fails *silently*.

`fine_grained_reward._score_tags_by_prefill` reads the verifier's score by
prefilling `<score_A>` and inspecting the logprob distribution at exactly that
position, constrained to the 20 scale letters via::

    extra_body={"add_generation_prompt": False,
                "continue_final_message": True,
                "structured_outputs": {"choice": letters}}

`structured_outputs` is vLLM's constrained-decoding argument. SGLang's
`ChatCompletionRequest` declares no `model_config`, so pydantic's default
``extra="ignore"`` applies: the field is **dropped without error**. The
request succeeds, no exception is raised, and the reference code believes it
received a distribution renormalized over the scale. Measured against the
project's own served Biomni-R0-32B endpoint:

=====================================  =========================  ============
constraint sent                        on-scale mass, bare prompt  with scale
=====================================  =========================  ============
none                                   0.0401                     0.5995769755
``structured_outputs`` (vLLM shape)    0.0401                     0.5995769755
``regex`` (SGLang shape)               0.9999                     0.9884
=====================================  =========================  ============

The two unconstrained columns differ only in whether the scale description was
in the prompt; what matters is that in **both** cases the `structured_outputs`
row is *bit-identical* to the unconstrained row — SGLang never saw the field.
Unconstrained, this reasoning model puts much of its mass on digit tokens
('2', '1') rather than scale letters, so `extract_score` renormalizes over a
fragment of the distribution and the resulting "fine-grained reward" is
substantially noise. That is precisely the failure mode a port-validation gate
exists to catch, and it would have been invisible: no error, no warning,
plausible-looking floats.

By contrast `google/gemma-4-31B-it` measures 0.99999 on-scale even
*unconstrained* — the format-compliance instability is a property of this
checkpoint, not of the task.

What this module changes
------------------------
The constraint mechanism: `structured_outputs` becomes SGLang's `regex`, so the
returned top-logprobs are the renormalized distribution over the scale itself —
the quantity the method's expectation is defined over. The alphabet is narrowed
from 40 tokens to the 20 bare letters, for the reasons and at the measured cost
documented on `scale_regex`. Prompts, scale, criteria, tournament, aggregation
and the reward definition are untouched.

It also removes the silent-failure path. The reference code returns tag-less
results when the prefill call raises, and `extract_score` then falls back to
0.5 — a tie that is indistinguishable from a verifier that genuinely cannot
separate two candidates. Here a failed or unconstrained prefill raises
`PortValidationError` instead, so a broken backend can never be mistaken for
a null result.

Usage
-----
    import stage_c_verifier_port as port
    port.install()          # patch the reference package in place
    port.self_test(base_url)  # assert the constraint is really honoured
"""

from __future__ import annotations

import math
import os
import sys
import threading
from collections.abc import Sequence
from typing import Any

#: Serialises appends to the per-comparison error log from the reference
#: runner's thread pool.
_ERROR_LOCK = threading.Lock()

# The reference implementation is a pinned external checkout, never edited —
# same discipline as Biomni itself (D-01). We patch at import time instead.
DEFAULT_REF_REPO = "/scratch/11034/atzanakak/repos/llm-as-a-verifier"

#: Minimum share of the returned probability mass that must land on scale
#: tokens at a prefilled score position. With the bare-letter grammar below the
#: constrained support is exactly 20 tokens — equal to the `top_logprobs` cap —
#: so a healthy response returns the *entire* distribution and measures 1.0000.
#: An ignored constraint measured 0.04–0.60 against this project's endpoint.
MIN_ON_SCALE_MASS = 0.99


class PortValidationError(RuntimeError):
    """The verifier backend did not return a usable score distribution.

    Raised instead of silently degrading to a 0.5 tie, so that an
    infrastructure failure can never be reported as a verifier that failed to
    discriminate.
    """


def _ref_repo() -> str:
    return os.environ.get("LLM_VERIFIER_REPO", DEFAULT_REF_REPO)


def reference_commit() -> str:
    """Commit of the pinned reference checkout, for the run's provenance."""
    import subprocess

    r = subprocess.run(["git", "-C", _ref_repo(), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return r.stdout.strip() or "unknown"


def served_model(base_url: str) -> str:
    """The model id the endpoint reports, recorded per cell per the stop rule."""
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"))
    return client.models.list().data[0].id


def _import_reference():
    repo = _ref_repo()
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from llm_verifier import fine_grained_reward as fgr  # noqa: E402

    return fgr


def scale_letters(granularity: int) -> list[str]:
    """The ordered score tokens A..T for the reference scale."""
    return [chr(65 + i) for i in range(granularity)]


def scale_regex(granularity: int) -> str:
    """SGLang `regex` constraining a single position to exactly one bare scale
    letter.

    The reference implementation offers each letter in **two** spellings, bare
    and space-prefixed, because some models put their mass on the spelling with
    a leading space. That doubles the constrained support to 40 tokens while
    the OpenAI `top_logprobs` cap stays at 20, with two consequences:

    * the returned alternatives are a *truncated* view of the constrained
      distribution — measured coverage on real MedAgentBench comparisons ranged
      from 0.762 to 0.9999 — and `extract_score` renormalizes over whatever
      fragment came back;
    * `extract_score` folds the two spellings of one value with ``max``, not a
      sum, so a value split across both spellings is systematically understated.

    Restricting to the 20 bare letters makes the support exactly equal to the
    `top_logprobs` cap, so the full constrained distribution is always returned
    (measured coverage: 1.0000), and makes token-to-value a bijection, which
    removes the max-versus-sum ambiguity entirely.

    Measured cost of the restriction, on 12 real comparisons across 4 tasks and
    all 3 criteria: mean |ΔR| = 0.0005, max |ΔR| = 0.0015. The constraint is
    applied identically to slot A and slot B of every comparison, so it cannot
    bias a pairwise preference in either direction.
    """
    letters = "|".join(scale_letters(granularity))
    return f"({letters})"


def on_scale_mass(alts: Sequence[tuple[str, float]], valid_tokens: dict[str, float]) -> float:
    """Total probability the returned alternatives place on scale tokens.

    `alts` is the (token, logprob) list at the scored position, exactly as
    `call_openai` builds it.
    """
    return sum(math.exp(lp) for tok, lp in alts if tok.strip() in valid_tokens)


def make_score_tags_by_prefill(fgr: Any):
    """Build the SGLang replacement for `_score_tags_by_prefill`.

    Mirrors the reference function's contract — returns
    ``(text, tokens, position_logprobs)`` in `call_gemini` shape — but
    constrains the prefilled position with SGLang's `regex` and refuses to
    return a silently unconstrained distribution.
    """

    def _score_tags_by_prefill(client, model, messages, text, tags, top_logprobs=20):
        valid_tokens = fgr.SCALE["valid_tokens"]
        regex = scale_regex(fgr.GRANULARITY)
        tokens: list[str] = []
        position_logprobs: list[list[tuple[str, float]]] = []

        for tag in tags:
            prefix = (text or "") + f"\n{tag}"
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages + [{"role": "assistant", "content": prefix}],
                    max_tokens=1,
                    temperature=1.0,
                    logprobs=True,
                    top_logprobs=top_logprobs,
                    extra_body={"add_generation_prompt": False, "continue_final_message": True, "regex": regex},
                )
            except Exception as exc:  # noqa: BLE001 - re-raised as our own
                raise PortValidationError(
                    f"constrained prefill call failed for {tag}: {type(exc).__name__}: {exc}"
                ) from exc

            choice = response.choices[0]
            letter = (choice.message.content or "").strip()
            alts: list[tuple[str, float]] = []
            if choice.logprobs and choice.logprobs.content:
                pos = choice.logprobs.content[0]
                alts = [(alt.token, alt.logprob) for alt in (pos.top_logprobs or [])]

            if not alts:
                raise PortValidationError(
                    f"no top_logprobs returned at {tag}; the endpoint must be started so that logprobs are available"
                )

            mass = on_scale_mass(alts, valid_tokens)
            if mass < MIN_ON_SCALE_MASS:
                raise PortValidationError(
                    f"score distribution at {tag} covers only {mass:.4f} of the "
                    f"returned mass (need {MIN_ON_SCALE_MASS}). With the "
                    "bare-letter grammar the constrained support is exactly 20 "
                    "tokens, so a healthy response returns all of it; a "
                    "shortfall means the server did not apply the `regex` "
                    "constraint and the expectation would be taken over a "
                    "fragment of the distribution."
                )

            closing = "</" + tag[1:]
            text = prefix + letter + closing
            tokens += [f"\n{tag}", letter, closing]
            position_logprobs += [[(f"\n{tag}", 0.0)], alts, [(closing, 0.0)]]

        return text, tokens or None, position_logprobs or None

    return _score_tags_by_prefill


def install(error_log: str | None = None):
    """Patch the reference package in place. Returns the module patched.

    `error_log`, when given, is a JSONL path receiving one record per failed
    comparison. The reference runner's own policy (``on_error="tie"``, which
    scores a failed comparison 0.5/0.5) is deliberately left in place so the
    reproduction number stays comparable to the published one — but a tie
    caused by a failure is not a tie caused by an indecisive verifier, and the
    difference is invisible without this log. The failure rate it records is
    reported alongside the score.
    """
    fgr = _import_reference()
    fgr._score_tags_by_prefill = make_score_tags_by_prefill(fgr)

    if error_log is not None:
        original = fgr.score_pair_criterion

        def logged(
            client, problem, trace_a, trace_b, criterion, ground_truth_note, model=fgr.DEFAULT_MODEL, images=None
        ):
            try:
                return original(client, problem, trace_a, trace_b, criterion, ground_truth_note, model, images)
            except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
                import json as _json
                import threading

                rec = {
                    "criterion": criterion.get("id"),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:2000],
                    "problem_chars": len(problem or ""),
                    "trace_a_chars": len(trace_a or ""),
                    "trace_b_chars": len(trace_b or ""),
                }
                with _ERROR_LOCK:
                    with open(error_log, "a") as fh:
                        fh.write(_json.dumps(rec) + "\n")
                del threading
                raise

        fgr.score_pair_criterion = logged

    fgr._stage_c_ported = True
    return fgr


def self_test(base_url: str | None = None, model: str | None = None) -> dict:
    """Prove, against a live endpoint, that the constraint is honoured and
    that an unconstrained call would not have been.

    Returns a dict of the measured on-scale masses. Raises
    `PortValidationError` if the ported path is not actually constrained.
    """
    from openai import OpenAI

    fgr = install()
    base_url = base_url or os.environ["OPENAI_BASE_URL"]
    client = OpenAI(base_url=base_url, api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"))
    model = model or client.models.list().data[0].id
    valid_tokens = fgr.SCALE["valid_tokens"]

    messages = [
        {
            "role": "user",
            "content": (
                "You are an expert evaluator. Task: reverse a string.\n"
                "Trajectory A: def rev(s): return s[::-1]\n"
                "Trajectory B: def rev(s): return s\n"
                f"Rate A.\n{fgr.SCALE['scale_description']}\n"
                "Output exactly:\n<score_A>LETTER_A_TO_T</score_A>\n"
            ),
        }
    ]
    prefix = "Analysis: A reverses the string, B does not.\n<score_A>"

    def _mass(extra):
        r = client.chat.completions.create(
            model=model,
            messages=messages + [{"role": "assistant", "content": prefix}],
            max_tokens=1,
            temperature=1.0,
            logprobs=True,
            top_logprobs=20,
            extra_body=extra,
        )
        pos = r.choices[0].logprobs.content[0]
        alts = [(a.token, a.logprob) for a in (pos.top_logprobs or [])]
        return on_scale_mass(alts, valid_tokens)

    base = {"add_generation_prompt": False, "continue_final_message": True}
    unconstrained = _mass(base)
    vllm_shaped = _mass({**base, "structured_outputs": {"choice": scale_letters(fgr.GRANULARITY)}})
    ported = _mass({**base, "regex": scale_regex(fgr.GRANULARITY)})

    if ported < MIN_ON_SCALE_MASS:
        raise PortValidationError(f"ported constraint not honoured: on-scale mass {ported:.4f}")

    return {
        "model": model,
        "unconstrained": unconstrained,
        "vllm_structured_outputs": vllm_shaped,
        "ported_regex": ported,
    }


if __name__ == "__main__":
    import json

    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OPENAI_BASE_URL")
    print(json.dumps(self_test(url), indent=2))
