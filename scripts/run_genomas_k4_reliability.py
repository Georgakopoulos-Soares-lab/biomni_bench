#!/usr/bin/env python3
"""Execute the frozen, single-task GenoMAS Reliability Suite v1 K=4 campaign.

The campaign boundary is declared by arguments and serialized before trajectory
zero starts.  Each run receives a fresh copy of the pinned GenoMAS worktree;
the source, prompts, agents, scoring code, model endpoint, and v1 evaluator
are never modified by this controller.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biomni_uncertainty.adapters.genomas import (  # noqa: E402
    memory_rlimit_preexec_fn,
    normalize_condition_arg,
    validate_cohort_info_contract,
)
from biomni_uncertainty.reliability import evaluate_reliability  # noqa: E402


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def failure_class(log_text: str, returncode: int) -> str | None:
    if returncode == 0:
        return None
    lower = log_text.lower()
    if "timeout" in lower:
        return "timeout"
    if "connection" in lower or "api" in lower:
        return "other_infrastructure_failure"
    if "traceback" in lower or "modulenotfound" in lower:
        return "execution_failure"
    return "agent_control_failure"


def token_and_runtime(log_text: str) -> tuple[int | None, int | None, float | None]:
    def last(pattern: str, cast):
        values = re.findall(pattern, log_text)
        return cast(values[-1]) if values else None
    return (
        last(r"Total Input Tokens:\s*(\d+)", int),
        last(r"Total Output Tokens:\s*(\d+)", int),
        last(r"Total Duration:\s*([0-9.]+)\s*seconds", float),
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--campaign-root", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--data-root", required=True)
    p.add_argument("--reference-root", type=Path, required=True)
    p.add_argument("--endpoint", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--trait", required=True)
    p.add_argument("--condition", default=None,
                    help="Condition name (e.g. Age, Gender). Omit, or pass 'None', for the unconditioned task.")
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--max-time", type=float, default=420)
    p.add_argument("--max-memory-gb", type=float, default=150.0,
                    help="RLIMIT_AS cap on each agent subprocess, so a runaway trajectory "
                         "fails cleanly and locally instead of risking a whole-node OOM "
                         "that could kill the shared vLLM server instead. See "
                         "reports/genomas_fresh_admission_ladder_20260826.md.")
    p.add_argument("--source-commit", required=True)
    p.add_argument("--benchmark-revision", required=True)
    args = p.parse_args()
    args.condition = normalize_condition_arg(args.condition)

    root = args.campaign_root
    worktrees, logs = root / "worktrees", root / "logs"
    root.mkdir(parents=True, exist_ok=False)
    worktrees.mkdir()
    logs.mkdir()
    manifest = {
        "schema_version": "genomas-reliability-campaign-v1",
        "created_at": now(), "protocol": {"k": args.k, "n_bootstrap": 2000,
        "bootstrap_seed": 20260825, "quick_test": True, "max_time_seconds": args.max_time,
        "max_memory_gb_per_trajectory": args.max_memory_gb},
        "task_panel": [{"task_id": args.trait if args.condition is None else f"{args.trait}::{args.condition}",
                        "trait": args.trait, "condition": args.condition}],
        "source": {"path": str(args.source), "commit": args.source_commit},
        "benchmark": {"name": "GenoTEX", "revision": args.benchmark_revision,
                      "input_root": args.data_root, "held_out_reference_root": str(args.reference_root)},
        "serving": {"backend": "vLLM local OpenAI-compatible", "endpoint": args.endpoint,
                    "model": args.model, "temperature": 0.7, "max_tokens": 2048,
                    "seed_support": "not exposed by the admitted transport adapter"},
        "scoring": {"implementation": "GenoMAS/eval.py evaluate_dataset_selection",
                    "scope": "declared single task", "official_reward": "selection accuracy / 100"},
        "admission_record": str(ROOT / "reports" / "genomas_admission.md"),
    }
    (root / "campaign_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    records: list[dict] = []
    runner = ROOT / "scripts" / "genomas_smoke_runner.py"
    scorer = ROOT / "scripts" / "genomas_score_smoke.py"
    task_id = args.trait if args.condition is None else f"{args.trait}::{args.condition}"
    condition_flag = [] if args.condition is None else ["--condition", args.condition]
    for index in range(args.k):
        started = now()
        run_id = f"k4_{index:02d}"
        worktree = worktrees / run_id
        shutil.copytree(args.source, worktree, ignore=shutil.ignore_patterns("output", "__pycache__", ".git"))
        log = logs / f"{run_id}.log"
        command = [sys.executable, str(runner), "--source", str(worktree), "--trait", args.trait,
                   *condition_flag, "--endpoint", args.endpoint, "--model", args.model,
                   "--data-root", args.data_root, "--version", run_id, "--max-time", str(args.max_time)]
        with log.open("w", encoding="utf-8") as handle:
            proc = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, text=True,
                                   preexec_fn=memory_rlimit_preexec_fn(int(args.max_memory_gb * (1024 ** 3))))
        run_log = log.read_text(encoding="utf-8", errors="replace")
        # GenoMAS's own logger (utils/logger.py) writes token/runtime accounting to
        # this file inside the worktree, never to the subprocess stdout/stderr this
        # controller captures above -- reading only `run_log` silently zeroed every
        # cost field in the frozen k4 campaign.
        native_log = worktree / "output" / f"log_{run_id}.txt"
        native_log_text = native_log.read_text(encoding="utf-8", errors="replace") if native_log.is_file() else ""
        pred_dir = worktree / "output" / run_id
        cohort = pred_dir / "preprocess" / args.trait / "cohort_info.json"
        raw_answer = cohort.read_text(encoding="utf-8") if cohort.is_file() else None
        contract = validate_cohort_info_contract(cohort)
        score_path, score_log = root / "scores" / f"{run_id}.json", logs / f"{run_id}.score.log"
        score_path.parent.mkdir(exist_ok=True)
        score_data = None
        if cohort.is_file():
            score_cmd = [sys.executable, str(scorer), "--source", str(worktree), "--pred-dir", str(pred_dir),
                         "--ref-dir", str(args.reference_root), "--trait", args.trait,
                         *condition_flag, "--result", str(score_path)]
            with score_log.open("w", encoding="utf-8") as handle:
                subprocess.run(score_cmd, stdout=handle, stderr=subprocess.STDOUT, text=True)
            score_data = read_json(score_path)
        try:
            reward = score_data["selection"]["selection_metrics"]["average"]["accuracy"] / 100.0
        except (TypeError, KeyError):
            reward = None
        in_tok, out_tok, runtime = token_and_runtime(native_log_text or run_log)
        agent_execution_success = proc.returncode == 0
        native_scorer_success = reward is not None
        completed = agent_execution_success and contract["artifact_contract_valid"] and native_scorer_success
        if completed:
            reason = None
        elif not agent_execution_success:
            reason = f"runner_exit_{proc.returncode}"
        elif not contract["artifact_contract_valid"]:
            reason = contract["artifact_contract_error"]
        else:
            reason = "native_scorer_failure"
        if completed:
            reason_class = None
        elif not agent_execution_success:
            reason_class = failure_class(run_log, proc.returncode)
        elif not contract["artifact_contract_valid"]:
            reason_class = "artifact_contract_failure"
        else:
            reason_class = "native_scorer_failure"
        records.append({
            "run_id": run_id, "agent": "genomas", "agent_commit": args.source_commit,
            "benchmark": "GenoTEX", "benchmark_revision": args.benchmark_revision,
            "task_id": task_id, "trajectory_index": index, "run_index": index,
            "requested_seed": index, "seed_supported": False, "model": args.model,
            "serving_backend": "vLLM local OpenAI-compatible", "temperature": 0.7,
            "top_p": None, "max_tokens": 2048, "start_time": started, "end_time": now(),
            "raw_final_answer": raw_answer, "answer_cluster_key": raw_answer,
            "official_reward": reward, "official_score_status": "ok" if reward is not None else "failed",
            "completed": completed, "failure_reason": reason, "failure_class": reason_class,
            "agent_execution_success": agent_execution_success,
            "artifact_contract_valid": contract["artifact_contract_valid"],
            "artifact_contract_error": contract["artifact_contract_error"],
            "native_scorer_success": native_scorer_success,
            "llm_input_tokens": in_tok, "llm_output_tokens": out_tok, "runtime_seconds": runtime,
            "artifact_path": str(pred_dir), "runner_log": str(log), "native_log": str(native_log),
            "score_path": str(score_path), "score_log": str(score_log), "verbal_confidence": None,
        })
        (root / "records.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    report = evaluate_reliability(records, k=args.k, n_bootstrap=2000, bootstrap_seed=20260825)
    report["campaign_manifest"] = str(root / "campaign_manifest.json")
    report["cost"] = {"input_tokens": sum(r["llm_input_tokens"] or 0 for r in records),
                      "output_tokens": sum(r["llm_output_tokens"] or 0 for r in records),
                      "runtime_seconds": sum(r["runtime_seconds"] or 0 for r in records),
                      "paid_api_cost_usd": 0.0}
    (root / "reliability_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
