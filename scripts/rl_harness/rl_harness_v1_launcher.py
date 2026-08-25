#!/usr/bin/env python
"""Run the Biomni harness through Agent Lightning v1 and native verl 0.9.

This launcher deliberately contains no training-loop implementation.  It
composes Agent Lightning's packaged config, passes in the frozen training
records, and invokes its ``run_ppo`` entrypoint.  Agent Lightning's current
``AgentLightningRayPPOTrainer`` subclasses verl's current ``RayPPOTrainer``;
therefore resource pools, rollout/log-prob masking, GRPO advantages, optimizer
steps, and weight synchronisation remain owned by verl.
"""

from __future__ import annotations

import argparse
import importlib.resources
import json
from pathlib import Path
from typing import Any

from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent

from rl_harness_dataset import load_training_tasks  # noqa: E402


def _groundtruth_map(paths: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in paths:
        with Path(value).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    result.setdefault(json.loads(line)["task_name"], value)
    return result


def build_config(args: argparse.Namespace) -> Any:
    """Compose Agent Lightning's official config then apply only run settings."""
    config_dir = str(importlib.resources.files("agentlightning.verl"))
    with initialize_config_dir(config_dir=config_dir, version_base=None):
        config = compose(config_name="config")
    OmegaConf.set_struct(config, False)
    overrides = {
        "algorithm": {
            "adv_estimator": "grpo",
            "use_kl_in_reward": False,
            "rollout_correction": {"bypass_mode": True, "loss_type": "ppo_clip"},
        },
        "data": {
            "train_batch_size": args.train_batch_size,
            "max_prompt_length": args.max_prompt_length,
            "max_response_length": args.max_response_length,
            "shuffle": True,
            "seed": args.data_seed,
            "dataloader_num_workers": 0,
        },
        "actor_rollout_ref": {
            "model": {
                "path": args.model_path,
                "lora_rank": args.lora_rank,
                "lora_alpha": args.lora_rank * 2,
                "use_remove_padding": False,
                "enable_gradient_checkpointing": True,
                "override_config": {"attn_implementation": "sdpa"},
            },
            "rollout": {
                "name": "vllm",
                "mode": "async",
                # vLLM's explicit default is BF16, but make it part of the
                # launcher contract so model and rollout weights agree.
                "dtype": "bfloat16",
                "tensor_model_parallel_size": args.tp,
                "n": args.rollout_n,
                "max_num_seqs": args.max_num_seqs,
                "gpu_memory_utilization": args.gpu_mem_util,
                "log_prob_micro_batch_size_per_gpu": args.micro_batch_size,
                "checkpoint_engine": {"update_weights_bucket_megabytes": 2048},
            },
            "actor": {
                "ppo_mini_batch_size": args.train_batch_size,
                "ppo_micro_batch_size_per_gpu": args.micro_batch_size,
                "use_dynamic_bsz": False,
                "optim": {"lr": args.lr},
                "use_kl_loss": False,
                # verl 0.9 defaults the FSDP model load itself to FP32.  The
                # 32B Biomni checkpoint cannot initialize that way on one
                # 96-GB GH200; keep the trainable LoRA run in BF16 instead.
                "fsdp_config": {
                    "model_dtype": "bf16",
                    "param_offload": True,
                    "optimizer_offload": True,
                },
            },
            "ref": {
                "log_prob_micro_batch_size_per_gpu": args.micro_batch_size,
                "fsdp_config": {"model_dtype": "bf16", "param_offload": True},
            },
        },
        "trainer": {
            "n_gpus_per_node": args.n_gpus,
            "nnodes": 1,
            "logger": ["console"],
            "project_name": "biomni-rl-harness",
            "experiment_name": args.experiment_id,
            "total_training_steps": args.total_steps,
            "val_before_train": False,
            "critic_warmup": 0,
            "save_freq": args.save_freq,
            "test_freq": -1,
            "default_local_dir": args.checkpoint_dir,
            "resume_mode": "auto",
        },
        "ray_kwargs": {"ray_init": {"object_store_memory": 8 * 1024**3}},
        "reward": {"num_workers": 1},
        "agentlightning": {
            "agl_base_url": args.agl_base_url,
            "agl_key": args.agl_key,
            "rollout_timeout_seconds": args.rollout_timeout_seconds,
            "reward_fillna_value": 0.0,
            "trace_aggregator": {
                "level": "trajectory",
                "trajectory_max_prompt_length": args.max_prompt_length,
                "trajectory_max_response_length": args.max_response_length,
            },
            "async_rollout": {"enabled": False},
            "local": {
                "agent_class": "biomni_local_agent:BiomniLocalRolloutAgent",
                "env_map": {"BIOMNI_TASK_JSON": "input"},
            },
        },
    }
    return OmegaConf.merge(config, OmegaConf.create(overrides))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", default="rl_harness_vista_smoke")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--groundtruth", action="append", required=True)
    parser.add_argument("--agl-base-url", default="http://127.0.0.1:8181")
    parser.add_argument("--agl-key", default="biomni-vista")
    parser.add_argument("--n-gpus", type=int, default=1)
    parser.add_argument("--tp", type=int, default=1)
    parser.add_argument("--lora-rank", type=int, default=8)
    parser.add_argument("--rollout-n", type=int, default=2)
    parser.add_argument("--max-num-seqs", type=int, default=2)
    parser.add_argument("--train-batch-size", type=int, default=1)
    parser.add_argument("--micro-batch-size", type=int, default=1)
    parser.add_argument("--max-prompt-length", type=int, default=65536)
    parser.add_argument("--max-response-length", type=int, default=4096)
    parser.add_argument("--gpu-mem-util", type=float, default=0.82)
    parser.add_argument("--lr", type=float, default=1e-6)
    parser.add_argument("--total-steps", type=int, default=1)
    parser.add_argument("--save-freq", type=int, default=1)
    parser.add_argument("--n-tasks", type=int, default=1)
    parser.add_argument("--data-seed", type=int, default=20260825)
    parser.add_argument("--rollout-timeout-seconds", type=int, default=3720)
    args = parser.parse_args()

    groundtruth = _groundtruth_map(args.groundtruth)
    tasks = load_training_tasks(REPO_ROOT)[: args.n_tasks]
    tasks = [{**task, "groundtruth_path": groundtruth[task["task_name"]]} for task in tasks]
    if not tasks:
        raise SystemExit("no frozen training tasks selected")

    config = build_config(args)
    print("=== frozen training tasks ===")
    for task in tasks:
        print(f"{task['task_name']} i{task['task_instance_id']}")
    print("=== resolved Agent Lightning / verl config ===")
    print(OmegaConf.to_yaml(config, resolve=True))
    if args.dry_run:
        return 0

    from agentlightning.verl.entrypoint import run_ppo

    run_ppo(config, train_dataset=tasks, val_dataset=tasks[:1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
