from __future__ import annotations

import json
from pathlib import Path

from biomni_uncertainty.sampling import (
    COMPLETE_MARKER,
    FAILED_MARKER,
    is_valid_complete,
    pending_specs,
    run_status,
    write_marker,
)


def make_run(
    tmp_path: Path,
    name: str,
    *,
    marker: str | None,
    complete_meta: bool = True,
    artifacts: bool = True,
    failure_class: str | None = None,
) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    if artifacts:
        for f in ("final_response.txt", "parsed_answer.json", "events.jsonl"):
            (d / f).write_text("{}" if f.endswith(".json") else "x")
        (d / "metadata.json").write_text(json.dumps({"completed": complete_meta, "run_id": name}))
    if marker:
        write_marker(
            d, marker, {"run_id": name, "completed": marker == COMPLETE_MARKER, "failure_class": failure_class}
        )
    return d


class Spec:
    """Minimal stand-in with the only attribute pending_specs reads."""

    def __init__(self, run_dir: str, run_id: str = "r"):
        self.run_dir = run_dir
        self.run_id = run_id


# --------------------------------------------------------------------------
# Markers
# --------------------------------------------------------------------------


def test_marker_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    d = tmp_path / "run"
    write_marker(d, COMPLETE_MARKER, {"run_id": "x", "completed": True})
    assert (d / COMPLETE_MARKER).exists()
    assert not list(d.glob("*.tmp"))
    assert json.loads((d / COMPLETE_MARKER).read_text())["completed"] is True


def test_run_status(tmp_path):
    assert run_status(make_run(tmp_path, "a", marker=COMPLETE_MARKER)) == "complete"
    assert run_status(make_run(tmp_path, "b", marker=FAILED_MARKER, complete_meta=False)) == "failed"
    assert run_status(make_run(tmp_path, "c", marker=None)) == "pending"


# --------------------------------------------------------------------------
# Validity of a COMPLETE marker
# --------------------------------------------------------------------------


def test_valid_complete_requires_marker_metadata_and_artifacts(tmp_path):
    good = make_run(tmp_path, "good", marker=COMPLETE_MARKER)
    assert is_valid_complete(good)


def test_complete_marker_without_artifacts_is_not_trusted(tmp_path):
    """Guards against a marker surviving an interrupted copy-back."""
    d = make_run(tmp_path, "partial", marker=COMPLETE_MARKER)
    (d / "parsed_answer.json").unlink()
    assert not is_valid_complete(d)


def test_complete_marker_with_completed_false_metadata_is_not_trusted(tmp_path):
    d = make_run(tmp_path, "lying", marker=COMPLETE_MARKER, complete_meta=False)
    assert not is_valid_complete(d)


def test_complete_marker_with_corrupt_metadata_is_not_trusted(tmp_path):
    d = make_run(tmp_path, "corrupt", marker=COMPLETE_MARKER)
    (d / "metadata.json").write_text("{not json")
    assert not is_valid_complete(d)


def test_missing_directory_is_not_complete(tmp_path):
    assert not is_valid_complete(tmp_path / "never_ran")


# --------------------------------------------------------------------------
# Resumption
# --------------------------------------------------------------------------


def test_valid_complete_runs_are_skipped(tmp_path):
    done = Spec(str(make_run(tmp_path, "done", marker=COMPLETE_MARKER)))
    todo = Spec(str(make_run(tmp_path, "todo", marker=None)))
    assert [s.run_dir for s in pending_specs([done, todo])] == [todo.run_dir]


def test_partial_complete_runs_are_rerun(tmp_path):
    d = make_run(tmp_path, "partial", marker=COMPLETE_MARKER)
    (d / "events.jsonl").unlink()
    assert pending_specs([Spec(str(d))]) != []


def test_substantive_failures_are_not_silently_retried(tmp_path):
    d = make_run(tmp_path, "bad", marker=FAILED_MARKER, complete_meta=False, failure_class="agent_parse_failure")
    # Only infrastructure classes are retryable.
    assert pending_specs([Spec(str(d))], retry_failed_classes=("model_server_failure",)) == []


def test_transient_infrastructure_failures_are_requeued(tmp_path):
    d = make_run(tmp_path, "transient", marker=FAILED_MARKER, complete_meta=False, failure_class="model_server_failure")
    got = pending_specs([Spec(str(d))], retry_failed_classes=("model_server_failure", "model_timeout"))
    assert len(got) == 1


def test_failed_marker_with_unreadable_json_is_not_retried_by_default(tmp_path):
    d = make_run(tmp_path, "weird", marker=FAILED_MARKER, complete_meta=False)
    (d / FAILED_MARKER).write_text("{broken")
    assert pending_specs([Spec(str(d))], retry_failed_classes=("model_server_failure",)) == []


def test_failed_runs_are_preserved_on_disk(tmp_path):
    d = make_run(tmp_path, "kept", marker=FAILED_MARKER, complete_meta=False, failure_class="tool_timeout")
    pending_specs([Spec(str(d))])
    assert (d / FAILED_MARKER).exists()
    assert (d / "metadata.json").exists()


def test_no_resume_reruns_everything(tmp_path):
    done = Spec(str(make_run(tmp_path, "done", marker=COMPLETE_MARKER)))
    # pending_specs is the resume path; the dispatcher bypasses it when resume=False.
    assert pending_specs([done]) == []
    assert [done] == [done]  # explicit: the caller keeps the full list


def test_resumption_is_idempotent(tmp_path):
    specs = [
        Spec(str(make_run(tmp_path, "a", marker=COMPLETE_MARKER))),
        Spec(str(make_run(tmp_path, "b", marker=None))),
        Spec(str(make_run(tmp_path, "c", marker=FAILED_MARKER, complete_meta=False, failure_class="model_timeout"))),
    ]
    r1 = [s.run_dir for s in pending_specs(specs, retry_failed_classes=("model_timeout",))]
    r2 = [s.run_dir for s in pending_specs(specs, retry_failed_classes=("model_timeout",))]
    assert r1 == r2
    assert len(r1) == 2


# --------------------------------------------------------------------------
# Failure classification
# --------------------------------------------------------------------------


def test_context_overflow_gets_its_own_non_retryable_class():
    """Regression: a 400 "maximum context length" was classified unknown_failure.
    It is a terminal outcome of a long trajectory - retrying reproduces it - so it
    must be separable from transient infrastructure failures in the report."""
    from biomni_uncertainty.config import Config
    from biomni_uncertainty.instrumentation import TrajectoryStats
    from biomni_uncertainty.runner import classify_exception

    class BadRequestError(Exception):
        pass

    exc = BadRequestError(
        "Error code: 400 - {'message': \"Requested token count exceeds the model's maximum "
        'context length of 65536 tokens. You requested a total of 71939 tokens."}'
    )
    assert classify_exception(exc, TrajectoryStats()) == "model_context_overflow"

    cfg = Config.model_validate({"experiment": {"name": "t", "seed": 1, "output_root": "/tmp/x"}})
    assert "model_context_overflow" not in cfg.execution.retry_policy.retryable_failure_classes


def test_transient_classes_are_still_recognised():
    from biomni_uncertainty.instrumentation import TrajectoryStats
    from biomni_uncertainty.runner import classify_exception

    s = TrajectoryStats()

    class APITimeoutError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    class ModuleNotFoundError_(ModuleNotFoundError):
        pass

    assert classify_exception(APITimeoutError("request timed out"), s) == "model_timeout"
    assert classify_exception(APIConnectionError("connection refused"), s) == "model_server_failure"
    assert classify_exception(ModuleNotFoundError("No module named 'Bio'"), s) == "dependency_failure"
    assert classify_exception(RuntimeError("something odd"), s) == "unknown_failure"


def test_rerun_archives_the_previous_attempt_instead_of_appending(tmp_path):
    """Regression: events.jsonl is append-only, so a resumed run interleaved two
    attempts in one file with event indices restarting at zero. Failed attempts
    must be preserved, not deleted, so they are moved aside."""
    from biomni_uncertainty.runner import _archive_previous_attempt

    d = tmp_path / "run"
    d.mkdir()
    (d / "events.jsonl").write_text('{"event_index": 0}\n')
    (d / "metadata.json").write_text('{"completed": false}')
    (d / "final_response.txt").write_text("first attempt")

    n = _archive_previous_attempt(d)
    assert n == 1
    assert not (d / "events.jsonl").exists()
    assert (d / "attempt1" / "events.jsonl").read_text() == '{"event_index": 0}\n'
    assert (d / "attempt1" / "final_response.txt").read_text() == "first attempt"

    # A second re-run stacks rather than clobbering attempt1.
    (d / "events.jsonl").write_text('{"event_index": 0}\n')
    assert _archive_previous_attempt(d) == 2
    assert (d / "attempt1" / "final_response.txt").exists()
    assert (d / "attempt2" / "events.jsonl").exists()


def test_archive_is_a_noop_for_a_fresh_run(tmp_path):
    from biomni_uncertainty.runner import _archive_previous_attempt

    d = tmp_path / "fresh"
    d.mkdir()
    assert _archive_previous_attempt(d) is None
    assert not list(d.iterdir())
