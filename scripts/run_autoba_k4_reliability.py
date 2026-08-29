#!/usr/bin/env python3
"""Execute the frozen, single-task AutoBA Reliability Suite v1 K campaign.

Mirrors ``run_genomas_k4_reliability.py``'s shape: the campaign boundary is
declared by arguments and serialized before trajectory zero starts. Each run
gets a fresh workspace; AutoBA's source, bioTaskBench's tests/grader, the
model endpoint, and the v1 evaluator are never modified by this controller.

Native bioTaskBench inputs are copied the same way its own
``harness/runner.py::_copy_task_inputs`` does (duplicated here rather than
importing that module-private helper from another project -- see
``biomni_uncertainty.adapters.autoba``'s docstring for the same choice about
``_terminate_group``); grading calls the unchanged, pinned
``harness/grader.py::grade_task`` directly.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biomni_uncertainty.adapters.autoba import (  # noqa: E402
    autoba_row,
    run_with_early_completion,
    workspace_fingerprint,
)
from biomni_uncertainty.reliability import evaluate_reliability  # noqa: E402

ADAPTER_SCRIPT = ROOT / "scripts" / "autoba_biotaskbench_agent.py"


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def copy_task_inputs(task: dict, test_dir: Path, workspace_dir: Path) -> None:
    data_dir = test_dir / "data"
    for rel in task.get("context", {}).get("data_files", []):
        src, dst = data_dir / rel, workspace_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dst)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--campaign-root", type=Path, required=True)
    p.add_argument("--biotaskbench-root", type=Path, required=True)
    p.add_argument("--domain", required=True, help="e.g. genome-assembly")
    p.add_argument("--test-id", required=True, help="e.g. assembly-001")
    p.add_argument("--endpoint", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--timeout-seconds", type=float, default=1800.0)
    p.add_argument(
        "--done-stable-seconds",
        type=float,
        default=60.0,
        help="How long the expected artifact must exist, unchanged, before early termination. "
        "Conservative by design: longer than one poll interval so a partially-written file "
        "mid-flush is never mistaken for a finished one.",
    )
    p.add_argument("--poll-seconds", type=float, default=10.0)
    p.add_argument("--source-commit", required=True, help="Pinned AutoBA commit.")
    p.add_argument("--benchmark-revision", required=True, help="Pinned bioTaskBench commit.")
    args = p.parse_args()

    task_dir = args.biotaskbench_root / "tests" / args.domain / args.test_id
    task_path = task_dir / "task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task_id = f"{args.domain}/{args.test_id}"

    root = args.campaign_root
    worktrees, logs = root / "worktrees", root / "logs"
    root.mkdir(parents=True, exist_ok=False)
    worktrees.mkdir()
    logs.mkdir()

    manifest = {
        "schema_version": "autoba-reliability-campaign-v1",
        "created_at": now(),
        "protocol": {
            "k": args.k,
            "n_bootstrap": 2000,
            "bootstrap_seed": 20260825,
            "timeout_seconds": args.timeout_seconds,
            "done_stable_seconds": args.done_stable_seconds,
            "poll_seconds": args.poll_seconds,
        },
        "task_panel": [{"task_id": task_id, "domain": args.domain, "test_id": args.test_id}],
        "source": {"name": "AutoBA", "commit": args.source_commit},
        "benchmark": {"name": "bioTaskBench", "revision": args.benchmark_revision, "root": str(args.biotaskbench_root)},
        "serving": {
            "backend": "vLLM local OpenAI-compatible",
            "endpoint": args.endpoint,
            "model": args.model,
            "seed_support": "not exposed by the admitted transport adapter",
        },
        "scoring": {"implementation": "harness/grader.py::grade_task", "official_reward": "weighted criteria score"},
        "admission_record": str(ROOT / "reports" / "autoba_admission.md"),
    }
    (root / "campaign_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    sys.path.insert(0, str(args.biotaskbench_root))
    from harness import grader  # noqa: E402 - path depends on the --biotaskbench-root argument.

    records: list[dict] = []
    for index in range(args.k):
        run_id = f"k{args.k}_{index:02d}"
        started = now()
        workspace = worktrees / run_id
        workspace.mkdir()
        copy_task_inputs(task, task_dir, workspace)

        env = os.environ.copy()
        env["BIOTASKBENCH_TASK_JSON"] = str(task_path.resolve())
        env["BIOTASKBENCH_TEST_DIR"] = str(task_dir.resolve())
        env["BIOTASKBENCH_WORKSPACE"] = str(workspace.resolve())
        env["AUTOBA_VLLM_ENDPOINT"] = args.endpoint
        env["AUTOBA_MODEL"] = args.model

        stdout_path, stderr_path = logs / f"{run_id}.stdout.log", logs / f"{run_id}.stderr.log"
        early_completion_log = logs / f"{run_id}.early_completion.json"
        agent_execution = run_with_early_completion(
            [sys.executable, str(ADAPTER_SCRIPT)],
            cwd=workspace,
            env=env,
            # workspace is reassigned each loop iteration, but snapshot_fn is only
            # ever invoked synchronously inside this same iteration's blocking call
            # below (never deferred past the next reassignment), so the late-binding
            # B023 warning does not apply to a real bug here.
            snapshot_fn=lambda: workspace_fingerprint(task, workspace),  # noqa: B023
            timeout_s=args.timeout_seconds,
            done_stable_s=args.done_stable_seconds,
            poll_s=args.poll_seconds,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            log_path=early_completion_log,
        )

        try:
            grade = grader.grade_task(task, workspace, task_dir)
        except Exception as exc:  # matches harness/cli.py's own per-task grading guard.
            grade = None
            (logs / f"{run_id}.grade_error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")

        token_usage = read_json(workspace / "token_usage.json")

        row = autoba_row(
            task_id=task_id,
            run_index=index,
            task=task,
            grade=grade,
            agent_execution=agent_execution,
            token_usage=token_usage,
            runtime_s=agent_execution["wall_time_seconds"],
            workspace_dir=str(workspace),
            agent_commit=args.source_commit,
            benchmark_revision=args.benchmark_revision,
            model=args.model,
        )
        row["start_time"] = started
        row["end_time"] = now()
        row["runner_stdout"] = str(stdout_path)
        row["runner_stderr"] = str(stderr_path)
        row["early_completion_log"] = str(early_completion_log)
        records.append(row)
        (root / "records.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
        )

    report = evaluate_reliability(records, k=args.k, n_bootstrap=2000, bootstrap_seed=20260825)
    report["campaign_manifest"] = str(root / "campaign_manifest.json")
    report["cost"] = {
        "input_tokens": sum(r["input_tokens"] or 0 for r in records),
        "output_tokens": sum(r["output_tokens"] or 0 for r in records),
        "runtime_seconds": sum(r["runtime_seconds"] or 0 for r in records),
        "paid_api_cost_usd": 0.0,
    }
    (root / "reliability_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
