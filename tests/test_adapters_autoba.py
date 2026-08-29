import json
import os
import sys
import time

from biomni_uncertainty.adapters.autoba import (
    aggregate_token_usage,
    answer_cluster_key,
    autoba_row,
    classify_autoba_failure,
    run_with_early_completion,
    workspace_fingerprint,
)

TASK = {
    "test_id": "assembly-001",
    "evaluation": {
        "criteria": [
            {"name": "output_exists", "type": "file_check", "target_pattern": "*.tsv", "weight": 0.1},
            {
                "name": "n50_accuracy",
                "type": "range_check",
                "target_file": "assembly_stats.tsv",
                "field": "top_n50",
                "range": [32000, 36000],
                "weight": 0.5,
            },
        ]
    },
}


def _grade(details_a: str, details_b: str, score=1.0, attempted=True) -> dict:
    return {
        "test_id": "assembly-001",
        "attempted": attempted,
        "score": score,
        "criteria_results": [{"score": 1.0, "details": details_a}, {"score": 1.0, "details": details_b}],
    }


def _exec(returncode=0, timed_out=False, early_exit=False, timeout_seconds=1800) -> dict:
    return {
        "returncode": returncode,
        "timed_out": timed_out,
        "early_exit": early_exit,
        "timeout_seconds": timeout_seconds,
    }


# --- answer_cluster_key ---


def test_answer_cluster_key_distinguishes_different_produced_values():
    a = answer_cluster_key(TASK, _grade("matched 1 file(s)", "value=33689 in full range"))
    b = answer_cluster_key(TASK, _grade("matched 1 file(s)", "value=34000 in full range"))
    assert a != b


def test_answer_cluster_key_matches_identical_produced_values():
    a = answer_cluster_key(TASK, _grade("matched 1 file(s)", "value=33689 in full range"))
    b = answer_cluster_key(TASK, _grade("matched 1 file(s)", "value=33689 in full range"))
    assert a == b


def test_answer_cluster_key_binds_each_detail_to_its_own_criterion_by_position():
    # criteria_results is always positionally aligned to task['evaluation']['criteria']
    # (grade_task's own iteration order) -- swapping which detail lands on which
    # criterion is a genuinely different recorded answer, not a reordering.
    a = answer_cluster_key(TASK, {"criteria_results": [{"details": "x"}, {"details": "y"}]})
    b = answer_cluster_key(TASK, {"criteria_results": [{"details": "y"}, {"details": "x"}]})
    assert a != b


def test_answer_cluster_key_none_when_grading_never_ran():
    assert answer_cluster_key(TASK, None) is None


def test_answer_cluster_key_none_on_criteria_count_mismatch():
    assert answer_cluster_key(TASK, {"criteria_results": [{"details": "x"}]}) is None


# --- classify_autoba_failure ---


def test_classify_completed_trajectory_has_no_failure_class():
    assert classify_autoba_failure(_exec(), grade_available=True, attempted=True, completed=True) is None


def test_classify_timeout_with_no_attempt_is_timeout():
    cls = classify_autoba_failure(_exec(timed_out=True), grade_available=True, attempted=False, completed=False)
    assert cls == "timeout"


def test_classify_timeout_with_attempt_is_not_timeout():
    # Timed out externally but the grader saw an attempted artifact -- the
    # trajectory is graded on its merits, not discarded as an infra timeout.
    cls = classify_autoba_failure(_exec(timed_out=True), grade_available=True, attempted=True, completed=False)
    assert cls != "timeout"


def test_classify_scorer_never_ran_is_native_scorer_failure():
    cls = classify_autoba_failure(_exec(), grade_available=False, attempted=False, completed=False)
    assert cls == "native_scorer_failure"


def test_classify_nonzero_returncode_without_early_exit_is_execution_failure():
    cls = classify_autoba_failure(_exec(returncode=1), grade_available=True, attempted=False, completed=False)
    assert cls == "execution_failure"


def test_classify_nonzero_returncode_from_early_exit_is_not_execution_failure():
    # Our own poller kills the process group on early completion; returncode
    # is not naturally 0 in that case, but that's a real completion path.
    cls = classify_autoba_failure(
        _exec(returncode=-15, early_exit=True), grade_available=True, attempted=False, completed=False
    )
    assert cls != "execution_failure"


def test_classify_clean_exit_without_attempt_is_agent_control_failure():
    cls = classify_autoba_failure(_exec(returncode=0), grade_available=True, attempted=False, completed=False)
    assert cls == "agent_control_failure"


# --- autoba_row ---

REQUIRED_COLUMNS = {"task_id", "run_index", "answer_cluster_key", "official_reward"}


def test_autoba_row_has_all_required_reliability_columns():
    row = autoba_row(
        task_id="assembly-001",
        run_index=0,
        task=TASK,
        grade=_grade("a", "b"),
        agent_execution=_exec(),
        token_usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "n_model_calls": 3},
        runtime_s=42.0,
        workspace_dir="/tmp/ws",
        agent_commit="a9f8f12",
        benchmark_revision="c9206d5",
        model="Qwen3-Coder-30B-A3B-Instruct",
    )
    assert REQUIRED_COLUMNS <= set(row)
    assert row["completed"] is True
    assert row["failure_class"] is None
    assert row["official_reward"] == 1.0


def test_autoba_row_marks_incomplete_when_grader_never_ran():
    row = autoba_row(
        task_id="assembly-001",
        run_index=1,
        task=TASK,
        grade=None,
        agent_execution=_exec(returncode=1),
        token_usage=None,
        runtime_s=None,
        workspace_dir="/tmp/ws",
        agent_commit="a9f8f12",
        benchmark_revision="c9206d5",
        model="m",
    )
    assert row["completed"] is False
    assert row["official_reward"] is None
    assert row["answer_cluster_key"] is None
    assert row["failure_class"] in {"execution_failure", "native_scorer_failure"}


def test_autoba_row_never_fabricates_token_counts_when_usage_unavailable():
    row = autoba_row(
        task_id="t",
        run_index=0,
        task=TASK,
        grade=_grade("a", "b"),
        agent_execution=_exec(),
        token_usage=None,
        runtime_s=1.0,
        workspace_dir="/tmp",
        agent_commit="c",
        benchmark_revision="r",
        model="m",
    )
    assert row["input_tokens"] is None
    assert row["output_tokens"] is None


# --- aggregate_token_usage ---


def test_aggregate_token_usage_sums_known_calls():
    calls = [
        {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
    ]
    agg = aggregate_token_usage(calls)
    assert agg == {
        "input_tokens": 15,
        "output_tokens": 3,
        "total_tokens": 18,
        "n_model_calls": 2,
        "n_calls_missing_usage": 0,
    }


def test_aggregate_token_usage_all_missing_is_none_not_zero():
    agg = aggregate_token_usage([None, None])
    assert agg["input_tokens"] is None
    assert agg["output_tokens"] is None
    assert agg["n_model_calls"] == 2
    assert agg["n_calls_missing_usage"] == 2


def test_aggregate_token_usage_partial_availability_sums_only_known():
    calls = [{"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}, None]
    agg = aggregate_token_usage(calls)
    assert agg["input_tokens"] == 10
    assert agg["n_calls_missing_usage"] == 1
    assert agg["n_model_calls"] == 2


def test_aggregate_token_usage_empty_calls():
    agg = aggregate_token_usage([])
    assert agg["input_tokens"] is None
    assert agg["n_model_calls"] == 0


# --- workspace_fingerprint ---

FP_TASK = {
    "evaluation": {
        "criteria": [
            {"name": "output_exists", "type": "file_check", "target_pattern": "*.tsv"},
            {"name": "columns_present", "type": "column_check", "target_file": "out.tsv"},
        ]
    }
}


def test_workspace_fingerprint_empty_when_nothing_written(tmp_path):
    assert workspace_fingerprint(FP_TASK, tmp_path) == ()


def test_workspace_fingerprint_changes_when_file_is_rewritten(tmp_path):
    target = tmp_path / "out.tsv"
    target.write_text("a\n")
    first = workspace_fingerprint(FP_TASK, tmp_path)
    assert first != ()
    target.write_text("a longer rewrite\n")
    second = workspace_fingerprint(FP_TASK, tmp_path)
    assert second != first  # size (and mtime) changed -- not the same answer.


def test_workspace_fingerprint_stable_when_file_untouched(tmp_path):
    (tmp_path / "out.tsv").write_text("a\n")
    assert workspace_fingerprint(FP_TASK, tmp_path) == workspace_fingerprint(FP_TASK, tmp_path)


def test_workspace_fingerprint_ignores_a_stray_file_matching_only_the_loose_pattern(tmp_path):
    # Regression for a real observed failure: a task's generic file_check
    # ("*.tsv") criterion sits alongside range/column checks that require an
    # exact target_file. A stray, differently-named .tsv file satisfying only
    # the loose glob must never look "done" while the actual required file
    # (assembly_stats.tsv) does not exist yet.
    (tmp_path / "some_other_scratch_file.tsv").write_text("not the real answer\n")
    assert workspace_fingerprint(FP_TASK, tmp_path) == ()


def test_workspace_fingerprint_requires_every_declared_target_file(tmp_path):
    # Two distinct required outputs: not "done" until both exist.
    task = {
        "evaluation": {
            "criteria": [
                {"name": "a", "type": "column_check", "target_file": "one.tsv"},
                {"name": "b", "type": "range_check", "target_file": "two.tsv"},
            ]
        }
    }
    (tmp_path / "one.tsv").write_text("x\n")
    assert workspace_fingerprint(task, tmp_path) == ()
    (tmp_path / "two.tsv").write_text("y\n")
    assert workspace_fingerprint(task, tmp_path) != ()


def test_workspace_fingerprint_pattern_fallback_requires_every_pattern_to_match(tmp_path):
    # No exact target_file anywhere -- falls back to glob patterns, but still
    # all-or-nothing across distinct patterns.
    task = {
        "evaluation": {
            "criteria": [
                {"name": "a", "type": "file_check", "target_pattern": "*.tsv"},
                {"name": "b", "type": "file_check", "target_pattern": "*.json"},
            ]
        }
    }
    (tmp_path / "out.tsv").write_text("x\n")
    assert workspace_fingerprint(task, tmp_path) == ()  # no .json yet.
    (tmp_path / "out.json").write_text("{}\n")
    assert workspace_fingerprint(task, tmp_path) != ()


def test_workspace_fingerprint_no_criteria_declare_any_target_is_empty():
    assert workspace_fingerprint({"evaluation": {"criteria": [{"name": "a", "type": "code_executes"}]}}, "/tmp") == ()


# --- run_with_early_completion ---


def _mtime_snapshot(path):
    try:
        st = path.stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return ()


def test_run_with_early_completion_terminates_once_output_is_stable(tmp_path):
    marker = tmp_path / "done.marker"
    # Sleeps far longer than any sane timeout; only early-completion should stop it.
    script = tmp_path / "child.py"
    script.write_text(f"import pathlib, time\npathlib.Path({str(marker)!r}).write_text('x')\ntime.sleep(120)\n")
    result = run_with_early_completion(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=dict(os.environ),
        snapshot_fn=lambda: _mtime_snapshot(marker),
        timeout_s=60.0,
        done_stable_s=0.3,
        poll_s=0.1,
    )
    assert result["early_exit"] is True
    assert result["timed_out"] is False
    assert result["wall_time_seconds"] < 30  # nowhere near the 60s timeout or 120s sleep.


def test_run_with_early_completion_does_not_fire_on_bare_presence(tmp_path):
    # Regression for a real observed failure mode: a target file appears
    # immediately (as a placeholder/wrong-answer write) and is only rewritten
    # with the real answer several seconds later. Bare existence would fire
    # instantly; this must wait for the *rewrite* to stop, not the first write.
    # done_stable_s is deliberately much longer than the rewrite delay: the
    # placeholder alone never sits unchanged long enough to look "done" before
    # it is overwritten, so any early_exit necessarily happened after the
    # rewrite, not merely because a file of some kind existed.
    marker = tmp_path / "out.tsv"
    script = tmp_path / "child.py"
    script.write_text(
        f"import pathlib, time\n"
        f"p = pathlib.Path({str(marker)!r})\n"
        f"p.write_text('placeholder')\n"
        f"time.sleep(0.2)\n"
        f"p.write_text('the real, correct, final answer')\n"
        f"time.sleep(120)\n"
    )
    result = run_with_early_completion(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=dict(os.environ),
        snapshot_fn=lambda: _mtime_snapshot(marker),
        timeout_s=60.0,
        done_stable_s=0.6,
        poll_s=0.05,
    )
    assert result["early_exit"] is True
    # Must have run past the 0.2s rewrite, not stopped at the placeholder.
    assert result["wall_time_seconds"] >= 0.2
    assert marker.read_text() == "the real, correct, final answer"


def test_run_with_early_completion_never_terminates_while_snapshot_keeps_changing(tmp_path):
    # snapshot_fn returns a new, distinct value every call -- consecutive
    # polls are never equal, so "ready" must never fire.
    state = {"n": 0}

    def always_different():
        state["n"] += 1
        return (state["n"],)

    script = tmp_path / "child.py"
    script.write_text("import time\ntime.sleep(2)\n")
    result = run_with_early_completion(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=dict(os.environ),
        snapshot_fn=always_different,
        timeout_s=10.0,
        done_stable_s=1.0,
        poll_s=0.1,
    )
    # The snapshot never stabilizes; the child exits on its own first.
    assert result["early_exit"] is False
    assert result["returncode"] == 0


def test_run_with_early_completion_times_out_when_never_done(tmp_path):
    script = tmp_path / "child.py"
    script.write_text("import time\ntime.sleep(5)\n")
    start = time.monotonic()
    result = run_with_early_completion(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=dict(os.environ),
        snapshot_fn=lambda: (),  # empty snapshot is never "ready", however long it stays constant.
        timeout_s=0.5,
        done_stable_s=5.0,
        poll_s=0.1,
    )
    assert result["timed_out"] is True
    assert result["early_exit"] is False
    assert time.monotonic() - start < 5  # actually killed, not left to run out its sleep.


def test_run_with_early_completion_writes_log(tmp_path):
    script = tmp_path / "child.py"
    script.write_text("pass\n")
    log_path = tmp_path / "early_completion.json"
    run_with_early_completion(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=dict(os.environ),
        snapshot_fn=lambda: (),
        timeout_s=5.0,
        done_stable_s=1.0,
        poll_s=0.1,
        log_path=log_path,
    )
    logged = json.loads(log_path.read_text())
    assert "poll_log" in logged
    assert logged["timed_out"] is False  # child exits cleanly well inside the 5s timeout.
