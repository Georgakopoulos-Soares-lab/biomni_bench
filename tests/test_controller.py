"""Tests for the online controller and its hash-chained decision log.

Two things are load-bearing and are asserted rather than trusted:

* the log detects tampering and out-of-order commits, because the whole
  shadow-isolation argument rests on a decision being provably fixed before the
  next trajectory existed (D-23);
* a resumed run re-uses committed decisions instead of recomputing them, so a
  run that outlives its Slurm allocation cannot silently diverge from the one
  that started.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict

import pytest

from biomni_uncertainty.config import ControllerCfg
from biomni_uncertainty.controller import (
    ABSTAIN,
    ACCEPT,
    CONTINUE,
    GENESIS_HASH,
    DecisionLog,
    DecisionRecord,
    build_controller,
    decide_step,
    read_progress,
)
from biomni_uncertainty.policy import PolicyState, view_from_row


def view(idx: int, answer: str | None, *, completed: bool = True, parse: str = "ok", position: int = 1):
    return view_from_row(
        {
            "run_id": f"rare_disease_diagnosis-i0007-inst-t{idx}",
            "task_name": "rare_disease_diagnosis",
            "task_instance_id": 7,
            "completed": completed,
            "answer_parse_status": parse,
            "answer_cluster_key": answer,
            "answer_canonical": answer,
            "final_confidence": 0.95,
            "confidence_parse_status": "ok",
            "failure_class": None if completed else "model_context_overflow",
            "total_tokens": 1000.0,
            "total_output_tokens": 500.0,
            "total_input_tokens": 500.0,
            "llm_call_count": 10.0,
            "tool_call_count": 2.0,
            "failed_tool_call_count": 0.0,
            "code_execution_count": 1.0,
            "unique_tool_count": 2.0,
            "retrieval_count": 1.0,
            "exception_count": 0.0,
            "visible_plan_step_count": 3.0,
            "generated_chars": 2000.0,
            "wall_time_seconds": 300.0,
        },
        position=position,
    )


def rec(step: int, action: str, prev: str, **kw) -> DecisionRecord:
    base = {
        "task_name": "rare_disease_diagnosis",
        "task_instance_id": 7,
        "step": step,
        "observed_run_ids": [f"t{i}" for i in range(step)],
        "action": action,
        "reason": "test",
        "support": 1,
        "k_observed": step,
        "valid_agreement": False,
        "resolved_cluster_key": "A",
        "decided_at": 1785700000.0 + step,
        "prev_hash": prev,
    }
    base.update(kw)
    return DecisionRecord(**base)


# --------------------------------------------------------------------------
# The frozen policy
# --------------------------------------------------------------------------


def test_controller_never_accepts_a_single_trajectory():
    c = build_controller(ControllerCfg(enabled=True))
    d = c.decide(PolicyState("rare_disease_diagnosis", (view(0, "A"),), 4))
    assert d.action == CONTINUE


def test_controller_stops_on_valid_agreement():
    c = build_controller(ControllerCfg(enabled=True))
    views = (view(0, "A", position=1), view(1, "A", position=2))
    assert c.decide(PolicyState("rare_disease_diagnosis", views, 4)).action == ACCEPT


def test_controller_continues_on_disagreement():
    c = build_controller(ControllerCfg(enabled=True))
    views = (view(0, "A", position=1), view(1, "B", position=2))
    assert c.decide(PolicyState("rare_disease_diagnosis", views, 4)).action == CONTINUE


def test_controller_abstains_when_all_four_answers_are_distinct():
    c = build_controller(ControllerCfg(enabled=True))
    views = tuple(view(i, k, position=i + 1) for i, k in enumerate("ABCD"))
    d = c.decide(PolicyState("rare_disease_diagnosis", views, 4))
    assert d.action == ABSTAIN
    assert "escalate" in d.reason


def test_controller_accepts_at_the_ceiling_when_two_agree():
    c = build_controller(ControllerCfg(enabled=True))
    views = tuple(view(i, k, position=i + 1) for i, k in enumerate("ABCA"))
    assert c.decide(PolicyState("rare_disease_diagnosis", views, 4)).action == ACCEPT


def test_a_failed_trajectory_does_not_satisfy_verification():
    """[dead, A] holds one usable opinion, not two, so the controller pays for more."""
    c = build_controller(ControllerCfg(enabled=True))
    views = (view(0, None, completed=False, parse="empty", position=1), view(1, "A", position=2))
    assert c.decide(PolicyState("rare_disease_diagnosis", views, 4)).action == CONTINUE


def test_failure_override_cannot_be_switched_off():
    with pytest.raises(ValueError, match="failure_override"):
        build_controller(ControllerCfg(enabled=True, failure_override=False))


def test_abstention_can_be_disabled_and_then_it_answers_instead():
    c = build_controller(ControllerCfg(enabled=True, abstain_on_no_agreement=False))
    views = tuple(view(i, k, position=i + 1) for i, k in enumerate("ABCD"))
    assert c.decide(PolicyState("rare_disease_diagnosis", views, 4)).action == ACCEPT


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------


def test_chain_links_each_record_to_its_predecessor(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl")
    assert log.last_hash == GENESIS_HASH
    a = log.append(rec(1, CONTINUE, GENESIS_HASH))
    b = log.append(rec(2, ACCEPT, a.this_hash))
    assert b.prev_hash == a.this_hash
    ok, why = log.verify()
    assert ok, why


def test_appending_with_a_stale_prev_hash_is_refused(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl")
    log.append(rec(1, CONTINUE, GENESIS_HASH))
    with pytest.raises(ValueError, match="chain break"):
        log.append(rec(2, ACCEPT, GENESIS_HASH))


def test_verify_detects_a_rewritten_decision(tmp_path):
    """The attack the chain exists to stop: changing a decision after the fact."""
    p = tmp_path / "decisions.jsonl"
    log = DecisionLog(p)
    a = log.append(rec(1, CONTINUE, GENESIS_HASH))
    log.append(rec(2, ACCEPT, a.this_hash))
    assert DecisionLog(p).verify()[0]

    lines = p.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["action"] = ACCEPT  # pretend the controller stopped at k=1
    lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    p.write_text("\n".join(lines) + "\n")

    ok, why = DecisionLog(p).verify()
    assert not ok
    assert "hash" in why


def test_verify_rejects_a_decision_committed_after_termination(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl")
    a = log.append(rec(1, CONTINUE, GENESIS_HASH))
    b = log.append(rec(2, ACCEPT, a.this_hash))
    log.append(rec(3, ACCEPT, b.this_hash))
    ok, why = log.verify()
    assert not ok
    assert "already terminated" in why


def test_records_survive_a_reopen(tmp_path):
    p = tmp_path / "decisions.jsonl"
    log = DecisionLog(p)
    a = log.append(rec(1, CONTINUE, GENESIS_HASH))
    log.append(rec(2, ACCEPT, a.this_hash))
    reopened = DecisionLog(p)
    assert reopened.n_steps == 2
    assert reopened.last_hash == log.last_hash
    assert reopened.verify()[0]


def test_hash_covers_every_field_that_matters(tmp_path):
    r = rec(1, CONTINUE, GENESIS_HASH)
    for field, value in [("action", ACCEPT), ("step", 2), ("observed_run_ids", ["x"]), ("support", 9)]:
        altered = DecisionRecord(**{**asdict(r), field: value})
        assert altered.compute_hash() != r.compute_hash(), f"{field} is outside the hash"


# --------------------------------------------------------------------------
# Resumption
# --------------------------------------------------------------------------


def test_a_committed_decision_is_reused_not_recomputed(tmp_path):
    """The core resumption guarantee. A controller that would now decide
    differently must still honour what was committed."""
    log = DecisionLog(tmp_path / "decisions.jsonl")
    c = build_controller(ControllerCfg(enabled=True))
    views = [view(0, "A", position=1)]
    d1, r1, reused = decide_step(c, log, task_name="rare_disease_diagnosis", task_instance_id=7, views=views, max_k=4)
    assert not reused and d1.action == CONTINUE

    class Contrarian:
        name = "contrarian"
        deployable = True

        def decide(self, state):  # would ACCEPT at k=1 - must not be consulted
            raise AssertionError("a committed step must never be re-decided")

    reopened = DecisionLog(tmp_path / "decisions.jsonl")
    d2, r2, reused2 = decide_step(
        Contrarian(), reopened, task_name="rare_disease_diagnosis", task_instance_id=7, views=views, max_k=4
    )
    assert reused2
    assert d2.action == d1.action
    assert r2.this_hash == r1.this_hash


def test_decide_step_commits_before_returning(tmp_path):
    """The decision must be on disk before the caller can generate anything."""
    p = tmp_path / "decisions.jsonl"
    log = DecisionLog(p)
    c = build_controller(ControllerCfg(enabled=True))
    decide_step(c, log, task_name="rare_disease_diagnosis", task_instance_id=7, views=[view(0, "A")], max_k=4)
    assert p.exists()
    assert DecisionLog(p).n_steps == 1, "the decision was not durable when decide_step returned"


def test_progress_is_reconstructed_from_the_log_alone(tmp_path):
    p = tmp_path / "decisions.jsonl"
    log = DecisionLog(p)
    a = log.append(rec(1, CONTINUE, GENESIS_HASH))
    b = log.append(rec(2, CONTINUE, a.this_hash))
    log.append(rec(3, ACCEPT, b.this_hash))

    prog = read_progress(p, "rare_disease_diagnosis", 7)
    assert prog.committed_steps == 3
    assert prog.finished
    assert prog.terminal_action == ACCEPT
    assert prog.terminal_step == 3


def test_an_unfinished_instance_is_reported_unfinished(tmp_path):
    p = tmp_path / "decisions.jsonl"
    DecisionLog(p).append(rec(1, CONTINUE, GENESIS_HASH))
    prog = read_progress(p, "rare_disease_diagnosis", 7)
    assert prog.committed_steps == 1
    assert not prog.finished
    assert prog.terminal_action is None


def test_a_missing_log_is_a_fresh_instance(tmp_path):
    prog = read_progress(tmp_path / "nope.jsonl", "rare_disease_diagnosis", 7)
    assert prog.committed_steps == 0 and not prog.finished


def test_full_sequential_run_then_resume_is_identical(tmp_path):
    """Drive an instance to termination, then replay every step from the log and
    check the controller lands in exactly the same place."""
    p = tmp_path / "decisions.jsonl"
    c = build_controller(ControllerCfg(enabled=True))
    answers = ["A", "B", "A"]  # continue, continue, accept at k=3

    log = DecisionLog(p)
    actions = []
    for k in range(1, 4):
        views = [view(i, answers[i], position=i + 1) for i in range(k)]
        d, _, _ = decide_step(c, log, task_name="rare_disease_diagnosis", task_instance_id=7, views=views, max_k=4)
        actions.append(d.action)
        if d.action != CONTINUE:
            break
    assert actions == [CONTINUE, CONTINUE, ACCEPT]

    replayed = DecisionLog(p)
    assert replayed.verify()[0]
    assert [r.action for r in replayed.records] == actions
    assert read_progress(p, "rare_disease_diagnosis", 7).terminal_step == 3


# --------------------------------------------------------------------------
# Driver helpers (scripts/phase2b_run.py)
# --------------------------------------------------------------------------


def _driver():
    import importlib.util
    import pathlib

    p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "phase2b_run.py"
    spec = importlib.util.spec_from_file_location("phase2b_run", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cfg(tmp_path):
    from biomni_uncertainty.config import Config

    return Config.model_validate(
        {
            "experiment": {"name": "phase2b_t", "seed": 1, "output_root": str(tmp_path)},
            "trajectories": {"instrumented_k": 4, "standard_k": 0, "seed_base": 2000},
            "controller": {"enabled": True},
            "execution": {"data_path": str(tmp_path / "data")},
        }
    )


def _entry():
    from biomni_uncertainty.benchmark import ManifestEntry

    return ManifestEntry(1, 7, "rare_disease_diagnosis", "val", "prompt", "hash")


def test_consumed_and_shadow_land_in_separate_subtrees(tmp_path):
    from biomni_uncertainty.controller import CONDITION_CONSUMED, CONDITION_SHADOW

    d, cfg, e = _driver(), _cfg(tmp_path), _entry()
    consumed = d.spec_for(cfg, e, 2, CONDITION_CONSUMED)
    shadow = d.spec_for(cfg, e, 2, CONDITION_SHADOW)
    assert "/instrumented/" in consumed.run_dir and "/shadow/" in shadow.run_dir
    assert consumed.run_dir != shadow.run_dir
    assert consumed.run_id != shadow.run_id, "a shadow must be distinguishable from a consumed run"


def test_seed_depends_on_index_not_on_role(tmp_path):
    """The same trajectory index must draw the same sample whether the
    controller consumed it or it became a shadow - otherwise the shadow pool is
    not the counterfactual it claims to be."""
    from biomni_uncertainty.controller import CONDITION_CONSUMED, CONDITION_SHADOW

    d, cfg, e = _driver(), _cfg(tmp_path), _entry()
    assert (
        d.spec_for(cfg, e, 3, CONDITION_CONSUMED).requested_seed
        == d.spec_for(cfg, e, 3, CONDITION_SHADOW).requested_seed
    )
    seeds = {d.spec_for(cfg, e, i, CONDITION_CONSUMED).requested_seed for i in range(4)}
    assert len(seeds) == 4, "trajectory indices must request distinct seeds"


def test_deadline_refuses_to_start_a_run_it_cannot_finish():
    d = _driver()
    dl = d.Deadline(stop_at=time.time() + 100, per_run_seconds=3600)
    assert not dl.may_start()
    assert dl.tripped.is_set()


def test_deadline_allows_a_run_that_fits():
    d = _driver()
    dl = d.Deadline(stop_at=time.time() + 7200, per_run_seconds=600)
    assert dl.may_start()
    assert not dl.tripped.is_set()


def test_no_deadline_never_trips():
    d = _driver()
    dl = d.Deadline(stop_at=None, per_run_seconds=3600)
    assert dl.may_start() and not dl.tripped.is_set()
