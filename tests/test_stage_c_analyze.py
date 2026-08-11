"""Stage C — the decision rule and the capsule barrier are pinned by test.

Two jobs:

1. Pin every decision-rule constant against `reports/stage_c_stop_rule.md`, so
   a bar cannot drift after a number exists. This mirrors
   `tests/test_track_c_adjudication_analyze.py`, which pins D-38's `gap/3`.
2. Pin the capsule allowlist, so a future edit cannot quietly hand a verifier
   the reward, the vote count, or the other candidates.
"""

from __future__ import annotations

import os
import re
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import stage_c_analyze as sca  # noqa: E402
import stage_c_capsule as scc  # noqa: E402

STOP_RULE = os.path.join(REPO, "reports", "stage_c_stop_rule.md")


# ---------------------------------------------------------------------------
# the bars come from the frozen file, not from anybody's memory
# ---------------------------------------------------------------------------


def _stop_rule_text() -> str:
    with open(STOP_RULE) as f:
        return f.read()


@pytest.mark.parametrize(
    "name,value",
    [
        ("PLURALITY_FLOOR", 0.4103),
        ("ORACLE_CEILING", 0.6026),
        ("GAP", 0.1923),
        ("NOGO_BAR", 0.0641),
        ("REACHABLE_FLOOR", 0.6809),
        ("REACHABLE_BAR", 0.1064),
    ],
)
def test_constants_match_the_frozen_stop_rule(name, value):
    assert getattr(sca, name) == value
    assert f"{value:.4f}".rstrip("0") in _stop_rule_text() or f"{value}" in _stop_rule_text()


def test_nogo_bar_is_exactly_gap_over_three():
    assert sca.NOGO_BAR == pytest.approx(sca.GAP / 3, abs=5e-5)


def test_population_and_bootstrap_are_frozen():
    assert sca.N_INSTANCES == 78
    assert sca.REACHABLE_N == 47
    assert sca.BOOTSTRAP_REPLICATES == 10000
    assert sca.BOOTSTRAP_SEED == 20260811001
    assert sca.VALIDITY_BAR == 0.95
    assert "20260811001" in _stop_rule_text()


def test_stop_rule_still_declares_two_cells():
    """Guards §3/§7.1: the cell count may never rise above two."""
    text = _stop_rule_text()
    assert "may **not** raise the cell count above two" in text
    assert re.search(r"cell count remains two|count remains \*\*two\*\*", text, re.I)


# ---------------------------------------------------------------------------
# verdict logic
# ---------------------------------------------------------------------------


def test_go_requires_ci_above_zero_and_validity():
    assert sca.verdict(lo=0.01, hi=0.30, validity=1.0) == "GO"
    # same CI, failing validity -> NO-GO, never GO
    assert sca.verdict(lo=0.01, hi=0.30, validity=0.90) == "NO-GO"


def test_nogo_when_upper_bound_below_the_bar():
    assert sca.verdict(lo=-0.20, hi=0.0640, validity=1.0) == "NO-GO"


def test_inconclusive_between_the_bars():
    assert sca.verdict(lo=-0.05, hi=0.15, validity=1.0) == "INCONCLUSIVE"


def test_bar_is_not_widened_at_the_boundary():
    """A CI upper bound exactly at the bar is not a NO-GO; strictly below is."""
    assert sca.verdict(lo=-0.2, hi=sca.NOGO_BAR, validity=1.0) == "INCONCLUSIVE"
    assert sca.verdict(lo=-0.2, hi=sca.NOGO_BAR - 1e-9, validity=1.0) == "NO-GO"


def test_bootstrap_is_deterministic_under_the_frozen_seed():
    d = np.linspace(-0.3, 0.3, 78)
    a = sca.paired_bootstrap(d, sca.BOOTSTRAP_SEED, 2000)
    b = sca.paired_bootstrap(d, sca.BOOTSTRAP_SEED, 2000)
    assert a == b


# ---------------------------------------------------------------------------
# the capsule barrier
# ---------------------------------------------------------------------------


def test_forbidden_capsule_fields_cover_the_four_exclusion_classes():
    f = scc.FORBIDDEN_CAPSULE_FIELDS
    # ground truth
    assert {"reward", "strict_reward", "correct"} <= f
    # vote count / support
    assert {"support", "vote_count", "n_usable", "agreement_fraction"} <= f
    # which sample produced it
    assert {"trajectory_index", "run_id", "position"} <= f
    # D-32 anti-anchoring
    assert {"final_confidence", "confidence_parse_status"} <= f
    # other candidates and hidden reasoning
    assert {"candidates", "transcript", "model_text"} <= f


def _events():
    return [
        {"event_type": "retrieval_end", "payload": {"selected": {"tools": 5, "data_lake": 3}}},
        {
            "event_type": "tool_call_start",
            "step_index": 1,
            "payload": {"tool_name": "query_ensembl", "argument_excerpt": "x", "argument_hash": "h1"},
        },
        {"event_type": "tool_call_end", "step_index": 1, "payload": {"tool_name": "query_ensembl", "status": "ok"}},
        {
            "event_type": "code_execution_start",
            "step_index": 1,
            "payload": {"language": "python", "code_excerpt": "print(1)", "code_hash": "h2"},
        },
        {
            "event_type": "code_execution_end",
            "step_index": 1,
            "payload": {"status": "ok", "error": None, "stdout_excerpt": "BRCA1"},
        },
    ]


def _capsule(**kw):
    base = {
        "task_name": "t",
        "task_prompt": "prompt",
        "committed_answer": "BRCA1",
        "answer_parse_status": "ok",
        "events": _events(),
    }
    base.update(kw)
    return scc.build_capsule(**base)


def test_capsule_carries_the_allowlisted_evidence():
    c = _capsule()
    assert c.committed_answer == "BRCA1"
    assert [t["tool_name"] for t in c.tools_invoked] == ["query_ensembl"]
    assert c.tools_invoked[0]["status"] == "ok"
    assert c.retrieval_selection == {"tools": 5, "data_lake": 3}
    assert c.code_executions[0]["stdout_excerpt"] == "BRCA1"
    assert any(p.get("code_hash") == "h2" for p in c.provenance)


def test_capsule_rejects_forbidden_fields():
    c = _capsule()
    c.assert_no_forbidden_fields()  # must not raise
    assert not set(c.__slots__) & scc.FORBIDDEN_CAPSULE_FIELDS


def test_rendered_capsule_never_contains_reward_or_confidence_words():
    text = scc.render_capsule(_capsule())
    for banned in ("reward", "confidence", "ground truth", "vote"):
        assert banned not in text.lower(), f"{banned!r} leaked into the rendered capsule"


def test_failures_and_empty_returns_are_recorded():
    ev = _events()
    ev[-1] = {
        "event_type": "code_execution_end",
        "step_index": 1,
        "payload": {"status": "error", "error": "boom", "stdout_excerpt": ""},
    }
    c = _capsule(events=ev)
    assert any("error" in f for f in c.failures)


def test_empty_return_is_distinguished_from_a_failure():
    ev = _events()
    ev[-1] = {
        "event_type": "code_execution_end",
        "step_index": 1,
        "payload": {"status": "ok", "error": None, "stdout_excerpt": "   "},
    }
    c = _capsule(events=ev)
    assert any("no output" in f for f in c.failures)


def test_empty_sections_render_as_none_so_absence_does_not_signal():
    c = _capsule(events=[])
    text = scc.render_capsule(c)
    assert text.count("(none)") >= 4


def test_rendering_is_deterministic():
    assert scc.render_capsule(_capsule()) == scc.render_capsule(_capsule())


def test_capsule_respects_the_frozen_length_ceiling():
    ev = []
    for i in range(200):
        ev.append(
            {
                "event_type": "code_execution_start",
                "step_index": i,
                "payload": {"language": "python", "code_excerpt": "x" * 9000, "code_hash": f"h{i}"},
            }
        )
        ev.append(
            {
                "event_type": "code_execution_end",
                "step_index": i,
                "payload": {"status": "ok", "error": None, "stdout_excerpt": "y" * 9000},
            }
        )
    text = scc.render_capsule(_capsule(events=ev))
    assert len(text) <= scc.MAX_CAPSULE_CHARS
    assert scc.TRUNCATION_MARKER in text


def test_execution_count_is_reported_when_executions_are_omitted():
    ev = []
    for i in range(scc.MAX_RENDERED_EXECUTIONS + 5):
        ev.append(
            {
                "event_type": "code_execution_start",
                "step_index": i,
                "payload": {"language": "python", "code_excerpt": "x", "code_hash": f"h{i}"},
            }
        )
        ev.append(
            {
                "event_type": "code_execution_end",
                "step_index": i,
                "payload": {"status": "ok", "error": None, "stdout_excerpt": "y"},
            }
        )
    c = _capsule(events=ev)
    assert c.n_executions_total == scc.MAX_RENDERED_EXECUTIONS + 5
    assert len(c.code_executions) == scc.MAX_RENDERED_EXECUTIONS
    assert "5 further code executions omitted" in scc.render_capsule(c)
