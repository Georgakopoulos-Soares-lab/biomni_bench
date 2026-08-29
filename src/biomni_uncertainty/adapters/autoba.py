"""Non-invasive AutoBA/bioTaskBench Reliability Suite v1 helpers.

Mirrors ``adapters/genomas.py``'s pattern: small, independently testable
functions consumed by a campaign-runner script
(``scripts/run_autoba_k4_reliability.py``), never a monolithic "importer"
class. Nothing here edits AutoBA or bioTaskBench source; it only interprets
their unchanged, already-computed outputs (``harness/grader.py::grade_task``
results, the adapter's own subprocess/execution metadata) into the row shape
``src/biomni_uncertainty/reliability.py::evaluate_reliability`` requires.
"""

from __future__ import annotations

import glob
import json
import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Failure-class vocabulary already recognized by reliability.py's
# ``infrastructure_categories`` (see its module docstring / _failure_layers).
_TIMEOUT = "timeout"
_EXECUTION_FAILURE = "execution_failure"
_AGENT_CONTROL_FAILURE = "agent_control_failure"
_NATIVE_SCORER_FAILURE = "native_scorer_failure"


def classify_autoba_failure(
    agent_execution: dict[str, Any],
    *,
    grade_available: bool,
    attempted: bool,
    completed: bool,
) -> str | None:
    """Map one AutoBA trajectory's execution/grading outcome to a failure class.

    ``agent_execution`` is the dict this module's ``run_with_early_completion``
    returns. A trajectory that hit the external timeout without producing a
    gradeable artifact is a genuine ``timeout``, not conflated with a clean
    early exit (``early_exit=True`` is always a real completion path, never a
    failure by itself -- see ``run_with_early_completion``). A trajectory that
    timed out but *did* leave the expected artifact behind is graded, not
    discarded -- bioTaskBench's own ``grader.detect_attempted`` (reused as the
    done-check) already answered "is there an answer to grade."

    ``grade_available=False`` means bioTaskBench's own ``grade_task`` raised
    (the campaign script must catch that and pass ``grade=None``, matching
    ``harness/cli.py``'s own per-task ``except Exception`` handling) -- a
    scorer-side infrastructure problem, kept distinct from the agent simply
    not attempting the task.
    """
    if completed:
        return None
    if agent_execution.get("timed_out") and not attempted:
        return _TIMEOUT
    if not grade_available:
        return _NATIVE_SCORER_FAILURE
    if agent_execution.get("returncode", 0) != 0 and not agent_execution.get("early_exit"):
        return _EXECUTION_FAILURE
    if not attempted:
        return _AGENT_CONTROL_FAILURE
    return _AGENT_CONTROL_FAILURE  # defensive: completed=False must always carry a class, never a silent None.


def answer_cluster_key(task: dict[str, Any], grade: dict[str, Any] | None) -> str | None:
    """Canonicalize one trajectory's scored answer without touching ground truth.

    bioTaskBench's answer is a structured artifact (TSV/JSON/etc.) graded by
    the unchanged native ``grade_task``, not free text -- no LLM-based
    canonicalization is needed or wanted (see reports/autoba_admission.md
    Sec 1). Every criterion type's own ``details`` string already reports a
    deterministic, human-readable summary of what the *agent produced*
    (e.g. ``"value=33689 in full range"``, ``"raw=0.8734 min_acceptable=0.7"``,
    ``"missing columns: [...]"``) computed entirely from the workspace the
    agent wrote to. Pairing each criterion's name with its own ``details``
    string, sorted for order-independence, gives a stable cluster key that
    distinguishes different produced values while ignoring cosmetic,
    ungraded fields (e.g. a free-text ``assembly_id`` column) that no
    criterion ever inspects -- matching the admission report's own
    observation that four trajectories agreed "on every graded field" while
    differing only in one ungraded column.

    Returns ``None`` when there is nothing to key (grading never ran, or ran
    against zero criteria), so ``features.cluster_key_for`` correctly treats
    it as its own unparseable singleton rather than a false empty-string match.
    """
    if not grade or not grade.get("criteria_results"):
        return None
    criteria = task.get("evaluation", {}).get("criteria", [])
    results = grade["criteria_results"]
    if len(criteria) != len(results):
        return None
    pairs = [(c["name"], r.get("details")) for c, r in zip(criteria, results, strict=True)]
    return json.dumps(sorted(pairs), sort_keys=True)


def autoba_row(
    *,
    task_id: str,
    run_index: int,
    task: dict[str, Any],
    grade: dict[str, Any] | None,
    agent_execution: dict[str, Any],
    token_usage: dict[str, Any] | None,
    runtime_s: float | None,
    workspace_dir: str,
    agent_commit: str,
    benchmark_revision: str,
    model: str,
) -> dict[str, Any]:
    """Build one ``evaluate_reliability()``-ready row for a single AutoBA trajectory.

    Required columns per reliability.py: ``task_id``, ``run_index``,
    ``answer_cluster_key``, ``official_reward``. Everything else here is the
    optional provenance/failure-taxonomy columns that module also consumes
    when present (``completed``, ``failure_reason``, ``failure_class``,
    ``agent_execution_success``, ``artifact_contract_valid``,
    ``native_scorer_success``, token/runtime fields).
    """
    grade_available = grade is not None
    attempted = bool(grade.get("attempted")) if grade_available else False
    official_reward = float(grade["score"]) if grade_available and grade.get("score") is not None else None
    agent_execution_success = agent_execution.get("returncode", 1) == 0 or bool(agent_execution.get("early_exit"))
    native_scorer_success = grade_available
    # bioTaskBench has no separate artifact-contract step the way GenoMAS's
    # cohort_info.json shape check does; grading itself is the only structural
    # check on the artifact, so this is true exactly when grading ran at all
    # (whether or not it scored zero) and false only when grading never ran.
    artifact_contract_valid = grade_available
    completed = agent_execution_success and grade_available and attempted
    failure_class = classify_autoba_failure(
        agent_execution, grade_available=grade_available, attempted=attempted, completed=completed
    )
    failure_reason = None
    if failure_class == _TIMEOUT:
        failure_reason = f"external timeout at {agent_execution.get('timeout_seconds')}s with no scored artifact"
    elif failure_class == _NATIVE_SCORER_FAILURE:
        failure_reason = "native grade_task did not run or raised"
    elif failure_class == _EXECUTION_FAILURE:
        failure_reason = f"agent_cmd exited {agent_execution.get('returncode')}"
    elif failure_class == _AGENT_CONTROL_FAILURE:
        failure_reason = "agent produced no attempted artifact before termination"
    return {
        "run_id": f"{task_id}_{run_index:02d}",
        "agent": "autoba",
        "agent_commit": agent_commit,
        "benchmark": "bioTaskBench",
        "benchmark_revision": benchmark_revision,
        "task_id": task_id,
        "run_index": run_index,
        "requested_seed": run_index,
        "seed_supported": False,
        "model": model,
        "serving_backend": "vLLM local OpenAI-compatible",
        "answer_cluster_key": answer_cluster_key(task, grade),
        "official_reward": official_reward,
        "official_score_status": "ok" if official_reward is not None else "failed",
        "completed": completed,
        "failure_reason": failure_reason,
        "failure_class": failure_class,
        "agent_execution_success": agent_execution_success,
        "artifact_contract_valid": artifact_contract_valid,
        "native_scorer_success": native_scorer_success,
        "input_tokens": token_usage.get("input_tokens") if token_usage else None,
        "output_tokens": token_usage.get("output_tokens") if token_usage else None,
        "total_tokens": token_usage.get("total_tokens") if token_usage else None,
        "n_model_calls": token_usage.get("n_model_calls") if token_usage else None,
        "runtime_seconds": runtime_s,
        "early_terminated": bool(agent_execution.get("early_exit")),
        "timed_out": bool(agent_execution.get("timed_out")),
        "workspace_dir": workspace_dir,
        "verbal_confidence": None,
    }


def aggregate_token_usage(calls: list[dict[str, Any] | None]) -> dict[str, Any]:
    """Sum per-call ``response.usage`` records without fabricating missing counts.

    A call whose ``usage`` was unavailable (``None`` -- some serving configs
    omit it) contributes to ``n_calls_missing_usage`` but is never counted as
    zero tokens; the aggregate token fields are ``None`` only when *every*
    call is missing usage, so a partially-instrumented trajectory still
    reports the tokens it did observe, distinguishably from "measured zero."
    """
    known = [c for c in calls if c is not None]
    n_missing = len(calls) - len(known)
    if not known:
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "n_model_calls": len(calls),
            "n_calls_missing_usage": n_missing,
        }
    return {
        "input_tokens": sum(c.get("input_tokens", 0) or 0 for c in known),
        "output_tokens": sum(c.get("output_tokens", 0) or 0 for c in known),
        "total_tokens": sum(c.get("total_tokens", 0) or 0 for c in known),
        "n_model_calls": len(calls),
        "n_calls_missing_usage": n_missing,
    }


def _terminate_group(proc: subprocess.Popen) -> None:
    """Verbatim of ``harness/runner.py::_terminate_group`` (SIGTERM then SIGKILL).

    Reused by value rather than imported, since bioTaskBench's version is a
    module-private (``_``-prefixed) helper of a script we otherwise never
    execute in-process; duplicating four lines here is simpler and more
    robust than depending on another project's private API surface.
    """
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def workspace_fingerprint(task: dict[str, Any], workspace: Path) -> tuple[tuple[str, int, int], ...]:
    """Snapshot ``(path, size, mtime_ns)`` for the task's expected output file(s).

    Ground-truth-free by construction: it only looks at the ``target_file``/
    ``target_pattern`` locations the grader itself will check inside the
    agent's own workspace, and only their filesystem metadata -- never their
    content, and never bioTaskBench's ``expected/`` reference directory.

    Two real failure modes were observed running this against a live
    trajectory before this function existed / before this fix, both fixed
    here rather than left as a known gap:

    1. Bare existence (bioTaskBench's own ``grader.detect_attempted``) is not
       a safe completion signal on its own: a trajectory wrote an early,
       wrong/placeholder file at the expected path, which satisfies
       ``detect_attempted`` immediately, then overwrote it with the real
       answer several rounds later. Fixed by requiring the snapshot to be
       *unchanged* across two consecutive polls, not merely present.
    2. A criterion's ``target_pattern`` is often a loose glob (e.g.
       ``"*.tsv"`` for a generic ``file_check``) that can match an incidental
       scratch file the agent wrote and never touches again, while the
       actual scored deliverable (referenced by an exact ``target_file`` on
       a different criterion, e.g. ``column_check``/``range_check``) had not
       been created yet -- a live run stabilized on such a stray file and
       terminated at score 0.1 with the real target file still missing.
       Fixed by preferring exact ``target_file`` entries whenever the task
       declares any: those are what the substantive scoring criteria
       actually require, unlike a generic presence/executability glob.
       ``target_pattern`` globs are only used as a fallback when a task
       declares no ``target_file`` criterion at all.
    """
    workspace = Path(workspace)
    criteria = task.get("evaluation", {}).get("criteria", [])
    target_files = sorted({c["target_file"] for c in criteria if c.get("target_file")})
    patterns = sorted({c["target_pattern"] for c in criteria if c.get("target_pattern")})
    # All-or-nothing: every distinct expected file (or, absent any exact
    # target_file, every distinct glob pattern) must currently exist, or the
    # task is not "done" yet -- a partially-produced output set is not a
    # completion signal, it's exactly the in-progress state polling exists to
    # keep waiting through.
    if target_files:
        paths = [workspace / f for f in target_files]
    elif patterns:
        matches = [glob.glob(str(workspace / pattern)) for pattern in patterns]
        if not all(matches):
            return ()
        paths = [Path(m[0]) for m in matches]
    else:
        return ()
    stats: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            st = path.stat()
        except OSError:
            return ()  # an expected file is still missing -- not done.
        stats.append((str(path), st.st_size, st.st_mtime_ns))
    return tuple(sorted(stats))


def run_with_early_completion(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    snapshot_fn: Callable[[], tuple],
    timeout_s: float,
    done_stable_s: float = 30.0,
    poll_s: float = 5.0,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Run one subprocess, terminating early once its output has stopped changing.

    Mirrors ``harness/runner.py::_run_agent_command``'s ``done_check`` branch
    (process group + poll loop + SIGTERM/SIGKILL), the mechanism bioTaskBench
    already ships but never wires up for its own ``--agent-cmd`` path (see
    ``run_biotaskbench`` vs. ``run_external_suite`` in that file).
    ``snapshot_fn`` (intended: ``workspace_fingerprint``) must be a pure,
    ground-truth-free fingerprint of the agent's own output files -- this
    function never calls the real scorer and never inspects ground truth; it
    only decides *when* to stop, never *whether the answer is right*.

    "Ready" means the current snapshot is non-empty (something has been
    produced) *and* identical to the immediately preceding poll's snapshot --
    bare presence is not enough, since a file already exists the instant it's
    first created and can still be rewritten many times afterward. A
    flickering or still-changing snapshot resets the stability timer --
    termination requires ``done_stable_s`` of a *continuously unchanged*,
    non-empty snapshot, not merely having been non-empty once.
    """
    start = time.monotonic()
    stdout_f = stdout_path.open("w", encoding="utf-8") if stdout_path else subprocess.DEVNULL
    stderr_f = stderr_path.open("w", encoding="utf-8") if stderr_path else subprocess.DEVNULL
    poll_log: list[dict[str, Any]] = []
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env, stdout=stdout_f, stderr=stderr_f, stdin=subprocess.DEVNULL, start_new_session=True
        )
        stable_since: float | None = None
        previous_snapshot: tuple | None = None
        early_exit = False
        timed_out = False
        while proc.poll() is None:
            elapsed = time.monotonic() - start
            if elapsed >= timeout_s:
                timed_out = True
                _terminate_group(proc)
                break
            snapshot = snapshot_fn()
            ready = bool(snapshot) and snapshot == previous_snapshot
            poll_log.append({"t": elapsed, "ready": ready, "n_files": len(snapshot)})
            previous_snapshot = snapshot
            if ready:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= done_stable_s:
                    early_exit = True
                    _terminate_group(proc)
                    break
            else:
                stable_since = None
            time.sleep(poll_s)
        wall_time = time.monotonic() - start
        returncode = 0 if early_exit else (proc.returncode if proc.returncode is not None else -1)
    finally:
        if stdout_path:
            stdout_f.close()
        if stderr_path:
            stderr_f.close()
    result = {
        "argv": argv,
        "returncode": returncode,
        "timed_out": timed_out,
        "early_exit": early_exit,
        "wall_time_seconds": wall_time,
        "timeout_seconds": timeout_s,
        "done_stable_seconds": done_stable_s,
        "poll_interval_seconds": poll_s,
        "n_polls": len(poll_log),
    }
    if log_path:
        log_path.write_text(json.dumps({**result, "poll_log": poll_log}, indent=2) + "\n", encoding="utf-8")
    return result
