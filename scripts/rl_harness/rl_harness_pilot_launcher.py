#!/usr/bin/env python
"""Single reproducible launcher: Biomni harness -> Agent Lightning proxy ->
Biomni-R0 policy -> K rollouts -> OfficialEvaluator reward -> verl GRPO ->
LoRA update.

Runs in the `rl_harness` environment. Every Biomni-touching call happens in a
subprocess against the UNCHANGED `biomni_unc` environment (`BiomniLitAgent`);
this process never imports `biomni_uncertainty` or `biomni`.

Two modes:

  --smoke       Engineering smoke test (default). Tiny model override
                allowed via --model-path/--n-gpus/--lora-rank/--rollout-n/
                --train-batch-size/--total-steps for fast iteration. Always
                draws tasks from the frozen training pool only
                (scripts/rl_harness/rl_harness_dataset.py), never the
                held-out set.

  --dry-run     Build the dataset, agent, and VERL config and print them
                without launching Ray/verl at all (fast sanity check).

This file IS the reproducible pilot launcher required by the harnessed-GRPO
brief: the exact scientific pilot config (D-49 Part B.2: K=4, batch 16
prompts/step, ~25 steps, Biomni-R0-32B, full training pool) is this same
script invoked with its default (non --smoke) arguments -- see the exact
command in DECISIONS.md D-51 / the final handoff. That command is not
executed by this session; launching it requires separate, explicit operator
approval per D-49's frozen gate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from biomni_lit_agent import BiomniLitAgent, BiomniRLConfig  # noqa: E402
from rl_harness_dataset import load_training_tasks  # noqa: E402


def build_verl_config(args: argparse.Namespace) -> dict:
    return {
        "algorithm": {"adv_estimator": "grpo", "use_kl_in_reward": False},
        "data": {
            "train_batch_size": args.train_batch_size,
            "max_prompt_length": args.max_prompt_length,
            "max_response_length": args.max_response_length,
        },
        "actor_rollout_ref": {
            "rollout": {
                "name": "vllm",
                "tensor_model_parallel_size": args.tp,
                "n": args.rollout_n,
                "gpu_memory_utilization": args.gpu_mem_util,
            },
            "actor": {
                "ppo_mini_batch_size": args.train_batch_size,
                "ppo_micro_batch_size_per_gpu": args.micro_batch_size,
                "use_dynamic_bsz": False,
                "optim": {"lr": args.lr},
                "use_kl_loss": False,
                "fsdp_config": {"param_offload": True, "optimizer_offload": True},
            },
            "ref": {
                "log_prob_micro_batch_size_per_gpu": args.micro_batch_size,
                "fsdp_config": {"param_offload": True},
            },
            "model": {
                "path": args.model_path,
                "lora_rank": args.lora_rank,
                "lora_alpha": args.lora_rank * 2,
                "use_remove_padding": False,
                "override_config": {"attn_implementation": "sdpa"},
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
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--experiment-id", default="rl_harness_smoke")
    p.add_argument("--smoke", action="store_true", default=True)
    p.add_argument("--dry-run", action="store_true")

    p.add_argument("--biomni-python", default="/scratch/11034/atzanakak/envs/biomni_unc/bin/python")
    p.add_argument("--config-path", default=str(REPO_ROOT / "configs" / "rl_harness_smoke.yaml"))
    p.add_argument(
        "--groundtruth",
        action="append",
        default=[
            str(REPO_ROOT / "manifests" / "phase1.groundtruth.jsonl"),
            str(REPO_ROOT / "manifests" / "phase2b.groundtruth.jsonl"),
        ],
    )
    p.add_argument("--output-root", default="/scratch/11034/atzanakak/biomni_unc_runs")
    p.add_argument("--checkpoint-dir", default="/scratch/11034/atzanakak/biomni_unc_runs/rl_harness_checkpoints")

    p.add_argument("--model-path", required=True)
    p.add_argument("--n-gpus", type=int, default=2)
    p.add_argument("--tp", type=int, default=2)
    p.add_argument("--lora-rank", type=int, default=16)
    p.add_argument("--rollout-n", type=int, default=4, help="K, GRPO group size")
    p.add_argument("--train-batch-size", type=int, default=1, help="prompts per step")
    p.add_argument("--micro-batch-size", type=int, default=1)
    p.add_argument(
        "--max-prompt-length",
        type=int,
        default=16384,
        help="verl vLLM rollout engine context sizing, NOT Biomni's own per-turn budget "
        "(that's configs/rl_harness_smoke.yaml's trajectory_budget). Biomni's real system "
        "prompt + tool schemas + retrieved context can be tens of thousands of tokens by "
        "later turns; this must cover the largest single HTTP request in the trajectory or "
        "vLLM rejects it with a context-length error, not a silent truncation.",
    )
    p.add_argument("--max-response-length", type=int, default=4096)
    p.add_argument("--gpu-mem-util", type=float, default=0.5)
    p.add_argument("--lr", type=float, default=1e-6)
    p.add_argument("--total-steps", type=int, default=1)
    p.add_argument("--save-freq", type=int, default=1)
    p.add_argument("--n-tasks", type=int, default=1, help="how many training-pool tasks to draw for this run")
    p.add_argument("--n-runners", type=int, default=1)

    args = p.parse_args()

    tasks = load_training_tasks(REPO_ROOT)
    tasks = tasks[: args.n_tasks]
    if not tasks:
        print("No training tasks selected.", file=sys.stderr)
        return 1

    rl_config = BiomniRLConfig(
        biomni_python=args.biomni_python,
        project_root=str(REPO_ROOT),
        config_path=args.config_path,
        groundtruth_paths=tuple(args.groundtruth),
        output_root=args.output_root,
        experiment_id=args.experiment_id,
        max_tokens=2048,
        temperature=0.7,
        # Must exceed configs/rl_harness_smoke.yaml's execution.run_timeout_seconds (3600)
        # -- the subprocess wrapper's hard timeout adds a 120s margin on top of this.
        run_timeout_seconds=3600,
        provenance_log=str(Path(args.output_root) / args.experiment_id / "provenance.jsonl"),
    )
    verl_config = build_verl_config(args)

    print("=== training tasks ===")
    for t in tasks:
        print(f"  {t['task_name']} i{t['task_instance_id']}")
    print("=== verl config ===")
    import json

    print(json.dumps(verl_config, indent=2))

    if args.dry_run:
        print("--dry-run: not launching Ray/verl.")
        return 0

    from agentlightning import Trainer
    from agentlightning.algorithm.verl import VERL

    agent = BiomniLitAgent(rl_config)
    algorithm = VERL(config=verl_config)
    trainer = Trainer(n_runners=args.n_runners, algorithm=algorithm)
    trainer.fit(agent, train_dataset=tasks, val_dataset=tasks[:1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
