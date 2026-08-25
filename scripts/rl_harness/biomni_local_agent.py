"""Current Agent Lightning local-runner adapter for unchanged Biomni rollouts.

The Agent Lightning controller starts this class once per rollout.  All
Biomni code stays in the dedicated ``biomni_unc`` interpreter; this module
only supplies the controller boundary, terminal OfficialEvaluator reward, and
provenance event.  The controller-provided OpenAI URL is a scoped proxy, so
every model call within a Biomni trajectory is traced under one rollout id.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

FROZEN_FAILURE_REWARD = 0.0


def score_terminal(status: str, reward: float | None) -> float:
    """Keep non-answers and infrastructure failures in the GRPO group as 0."""
    if status in {"ok", "unparseable_answer"} and reward is not None:
        return float(reward)
    return FROZEN_FAILURE_REWARD


class BiomniLocalRolloutAgent:
    """Agent Lightning v1 local-runner entrypoint (constructed with no args)."""

    def _require(self, name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(f"required environment variable is unset: {name}")
        return value

    def _run_json(self, command: list[str], *, timeout: int, cwd: str) -> dict[str, Any]:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        if completed.returncode:
            raise RuntimeError(f"command exited {completed.returncode}: {completed.stdout[-4000:]}")
        for line in reversed(completed.stdout.splitlines()):
            if line.lstrip().startswith("{"):
                return json.loads(line)
        raise RuntimeError(f"command emitted no JSON object: {completed.stdout[-4000:]}")

    def _emit_reward(self, reward: float, *, status: str, error: str | None) -> None:
        httpx.post(
            self._require("AGL_EVENT_URL"),
            json={
                "event_type": "reward",
                "data": {
                    "value": reward,
                    "source": "OfficialEvaluator" if error is None else "fallback",
                    "reason": status,
                },
            },
            headers={"Authorization": f"Bearer {os.environ.get('AGL_KEY', '')}"},
            timeout=30.0,
        ).raise_for_status()

    def _append_provenance(self, record: dict[str, Any]) -> None:
        path = os.environ.get("BIOMNI_RL_PROVENANCE_LOG")
        if not path:
            return
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def run(self) -> None:
        task = json.loads(self._require("BIOMNI_TASK_JSON"))
        project_root = self._require("BIOMNI_RL_PROJECT_ROOT")
        biomni_python = self._require("BIOMNI_RL_PYTHON")
        output_root = self._require("BIOMNI_RL_OUTPUT_ROOT")
        experiment_id = self._require("BIOMNI_RL_EXPERIMENT_ID")
        timeout = int(self._require("BIOMNI_RL_TIMEOUT_SECONDS"))
        event_url = self._require("AGL_EVENT_URL")
        try:
            rollout_id = event_url.split("/api/rollouts/", 1)[1].split("/", 1)[0]
        except IndexError as exc:
            raise RuntimeError(f"could not recover rollout id from {event_url!r}") from exc
        started = time.time()
        run_dir = (
            Path(output_root)
            / experiment_id
            / "runs"
            / task["task_name"]
            / f"i{int(task['task_instance_id']):04d}"
            / rollout_id
        )
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        run_spec = {
            "condition": "instrumented",
            "confidence_mode": "final_only",
            "experiment_id": experiment_id,
            "global_instance_id": task.get("global_instance_id", task["task_instance_id"]),
            "max_tokens": int(os.environ.get("BIOMNI_RL_MAX_TOKENS", "2048")),
            "model": os.environ.get("BIOMNI_RL_MODEL", "biomni/Biomni-R0-32B-Preview"),
            "model_revision": task.get("model_revision"),
            "prompt": task["prompt"],
            "prompt_hash": task["prompt_hash"],
            "requested_seed": int(rollout_id[:8], 16) % 1_000_000,
            "run_dir": str(run_dir),
            "run_id": f"{task['task_name']}-i{int(task['task_instance_id']):04d}-{rollout_id}",
            "split": task.get("split", "train"),
            "task_instance_id": task["task_instance_id"],
            "task_name": task["task_name"],
            "temperature": float(os.environ.get("BIOMNI_RL_TEMPERATURE", "0.7")),
            "timeout_seconds": timeout,
            "trajectory_index": 0,
        }
        spec_path = run_dir.parent / f"{rollout_id}.run_spec.json"
        spec_path.write_text(json.dumps(run_spec, indent=2), encoding="utf-8")

        status = "infra_failure"
        raw_reward: float | None = None
        error: str | None = None
        run_one_result: dict[str, Any] | None = None
        try:
            run_one_result = self._run_json(
                [
                    biomni_python,
                    "-m",
                    "biomni_uncertainty.cli",
                    "run-one",
                    "--config",
                    self._require("BIOMNI_RL_CONFIG_PATH"),
                    "--run-spec",
                    str(spec_path),
                    "--endpoint",
                    self._require("AGL_OPENAI_BASE_URL"),
                ],
                timeout=timeout + 120,
                cwd=project_root,
            )
            score = self._run_json(
                [
                    biomni_python,
                    str(Path(project_root) / "scripts" / "rl_harness" / "rl_score_one.py"),
                    "--run-dir",
                    str(run_dir),
                    "--groundtruth",
                    task["groundtruth_path"],
                ],
                timeout=120,
                cwd=project_root,
            )
            status = str(score["status"])
            raw_reward = score.get("reward")
        except Exception as exc:  # a failed trajectory must still enter the group
            error = repr(exc)

        final_reward = score_terminal(status, raw_reward)
        self._emit_reward(final_reward, status=status, error=error)
        self._append_provenance(
            {
                "rollout_id": rollout_id,
                "task_name": task["task_name"],
                "task_instance_id": task["task_instance_id"],
                "run_dir": str(run_dir),
                "status": status,
                "raw_reward": raw_reward,
                "final_reward": final_reward,
                "error": error,
                "wall_time_seconds": time.time() - started,
                "run_one_result": run_one_result,
            }
        )
