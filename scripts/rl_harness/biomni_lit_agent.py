"""Agent Lightning `LitAgent` wrapping the real Biomni harness for GRPO rollouts.

Architecture (see reports/rl_harness_preregistration.md D-49, DECISIONS.md D-50/D-51):

    Biomni task (this file's `task` dict)
    -> subprocess in the UNCHANGED biomni_unc environment
       -> `biomni_uncertainty.cli run-one` (real Biomni harness/tools/context,
          budget guards R2/R4/R5, base_url pointed at the Agent-Lightning-
          proxy-scoped endpoint handed in via `resources["main_llm"]`)
    -> subprocess: `scripts/rl_harness/rl_score_one.py` (real, unmodified
       `OfficialEvaluator`)
    -> `emit_reward(...)` attaches the terminal scalar reward to the spans
       Agent Lightning's LLMProxy already captured for this rollout_id/
       attempt_id (proven in D-50's proxy smoke test)
    -> return value also carries the float, belt-and-suspenders with the
       span-based v1 reward path daemon.py actually reads.

This process (the Agent Lightning Runner) runs under the `rl_harness` venv
and never imports `biomni_uncertainty` or `biomni` directly -- every
Biomni-touching call is a subprocess into the UNCHANGED `biomni_unc`
environment. That is the isolation boundary: verl/vllm/agentlightning never
share a Python environment with Biomni's own pinned stack.

A trajectory that produces no scoreable answer (context overflow, budget
termination, a crashed subprocess) is NEVER dropped from training: it
receives the frozen reward 0.0, exactly like every "unparseable_answer" case
in every prior phase (`evaluation.py`'s `_missing()` path) -- see
`_score_trajectory`'s docstring below for the exact mapping.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentlightning import LitAgent, NamedResources, Rollout, emit_reward

logger = logging.getLogger("biomni_lit_agent")

FROZEN_FAILURE_REWARD = 0.0
"""Reward for any rollout that does not reach an 'ok'/'unparseable_answer'
official-evaluator outcome. Matches this project's own reward convention
(evaluation.py: every task already scores exactly 0.0 or 1.0) rather than
inventing a new value for the RL harness."""


@dataclass(frozen=True)
class BiomniRLConfig:
    biomni_python: str
    project_root: str
    config_path: str
    groundtruth_paths: tuple[str, ...]
    output_root: str
    experiment_id: str = "rl_harness_pilot"
    max_tokens: int = 2048
    temperature: float = 0.7
    run_timeout_seconds: int = 1800
    provenance_log: str | None = None


class BiomniLitAgent(LitAgent[dict[str, Any]]):
    """Wraps the real Biomni harness (via subprocess) as an Agent Lightning rollout."""

    def __init__(self, rl_config: BiomniRLConfig) -> None:
        super().__init__()
        self.rl_config = rl_config
        self._groundtruth_by_task: dict[str, str] = {}
        for path in rl_config.groundtruth_paths:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    self._groundtruth_by_task.setdefault(rec["task_name"], path)

    def _groundtruth_for(self, task_name: str) -> str:
        try:
            return self._groundtruth_by_task[task_name]
        except KeyError as exc:
            raise ValueError(f"No groundtruth file registered for task '{task_name}'") from exc

    def _run_dir_for(self, task: dict[str, Any], rollout_id: str) -> Path:
        return (
            Path(self.rl_config.output_root)
            / self.rl_config.experiment_id
            / "runs"
            / task["task_name"]
            / f"i{int(task['task_instance_id']):04d}"
            / rollout_id
        )

    def _append_provenance(self, record: dict[str, Any]) -> None:
        if not self.rl_config.provenance_log:
            return
        path = Path(self.rl_config.provenance_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    async def _run_one_subprocess(self, run_spec_path: Path, endpoint: str) -> dict[str, Any]:
        cmd = [
            self.rl_config.biomni_python,
            "-m",
            "biomni_uncertainty.cli",
            "run-one",
            "--config",
            self.rl_config.config_path,
            "--run-spec",
            str(run_spec_path),
            "--endpoint",
            endpoint,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.rl_config.project_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=self.rl_config.run_timeout_seconds + 120)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"run-one subprocess exceeded hard timeout for {run_spec_path}") from exc

        text = out.decode(errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"run-one exited {proc.returncode}: {text[-4000:]}")

        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise RuntimeError(f"run-one produced no JSON line on stdout: {text[-4000:]}")

    async def _score_subprocess(self, run_dir: Path, groundtruth: str) -> dict[str, Any]:
        cmd = [
            self.rl_config.biomni_python,
            str(Path(self.rl_config.project_root) / "scripts" / "rl_harness" / "rl_score_one.py"),
            "--run-dir",
            str(run_dir),
            "--groundtruth",
            groundtruth,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=self.rl_config.project_root, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        text = out.decode(errors="replace")
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise RuntimeError(f"rl_score_one produced no JSON line on stdout: {text[-4000:]}")

    def _score_trajectory(self, status: str, reward: float | None) -> float:
        """Map an evaluator outcome to the terminal training reward.

        "ok" and "unparseable_answer" both carry a real, already-defined
        reward from OfficialEvaluator (the second is 0.0 by construction --
        a context-overflow or non-answer trajectory, not an infra failure).
        Anything else ("evaluator_failure", "no_ground_truth", "no_metadata")
        is a genuine anomaly, logged loudly, and still resolves to the same
        frozen 0.0 rather than vanishing from the training batch.
        """
        if status in ("ok", "unparseable_answer") and reward is not None:
            return float(reward)
        logger.warning(
            "Non-ok evaluator status '%s' (reward=%s); using frozen fallback %.1f",
            status,
            reward,
            FROZEN_FAILURE_REWARD,
        )
        return FROZEN_FAILURE_REWARD

    async def rollout_async(self, task: dict[str, Any], resources: NamedResources, rollout: Rollout) -> float:
        rollout_id = rollout.rollout_id
        attempt = getattr(rollout, "attempt", None)
        attempt_id = getattr(attempt, "attempt_id", None) or hashlib.sha256(rollout_id.encode()).hexdigest()[:8]

        started = time.time()
        run_dir = self._run_dir_for(task, rollout_id)
        run_dir.parent.mkdir(parents=True, exist_ok=True)

        main_llm = resources["main_llm"]
        endpoint = main_llm.endpoint.rstrip("/") + "/v1"

        seed = int(hashlib.sha256(f"{rollout_id}|{attempt_id}".encode()).hexdigest()[:8], 16) % 1_000_000

        run_spec = {
            "condition": "instrumented",
            "confidence_mode": "final_only",
            "experiment_id": self.rl_config.experiment_id,
            "global_instance_id": task.get("global_instance_id", task["task_instance_id"]),
            "max_tokens": self.rl_config.max_tokens,
            "model": main_llm.model,
            "model_revision": task.get("model_revision"),
            "prompt": task["prompt"],
            "prompt_hash": task["prompt_hash"],
            "requested_seed": seed,
            "run_dir": str(run_dir),
            "run_id": f"{task['task_name']}-i{int(task['task_instance_id']):04d}-{rollout_id}",
            "split": task.get("split", "val"),
            "task_instance_id": task["task_instance_id"],
            "task_name": task["task_name"],
            "temperature": self.rl_config.temperature,
            "timeout_seconds": self.rl_config.run_timeout_seconds,
            "trajectory_index": 0,
        }
        run_spec_path = run_dir.parent / f"{rollout_id}.run_spec.json"
        run_spec_path.write_text(json.dumps(run_spec, indent=2), encoding="utf-8")

        status = "infra_failure"
        reward_value: float | None = None
        error: str | None = None
        try:
            run_one_result = await self._run_one_subprocess(run_spec_path, endpoint)
            score_result = await self._score_subprocess(run_dir, self._groundtruth_for(task["task_name"]))
            status = score_result["status"]
            reward_value = score_result.get("reward")
        except Exception as exc:  # noqa: BLE001 - any infra failure must still score, not crash training
            error = repr(exc)
            logger.exception(
                "rollout %s (%s/%s) failed before scoring", rollout_id, task["task_name"], task["task_instance_id"]
            )
            run_one_result = None

        final_reward = self._score_trajectory(status, reward_value)
        emit_reward(final_reward)

        self._append_provenance(
            {
                "rollout_id": rollout_id,
                "attempt_id": attempt_id,
                "task_name": task["task_name"],
                "task_instance_id": task["task_instance_id"],
                "run_dir": str(run_dir),
                "endpoint": endpoint,
                "status": status,
                "raw_reward": reward_value,
                "final_reward": final_reward,
                "error": error,
                "wall_time_seconds": time.time() - started,
                "run_one_result": run_one_result,
            }
        )

        return final_reward
