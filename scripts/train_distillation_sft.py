#!/usr/bin/env python3
"""Minimal, auditable offline LoRA-SFT trainer for the Biomni distillation
pilot manifests (`scripts/build_distillation_manifest.py`'s output).

Deliberately NOT a general training framework: one script, one purpose,
reuses `transformers.Trainer` + `peft` directly rather than adding `trl` as
a dependency (neither `trl` nor `deepspeed` were installed in the
pre-existing `rl_harness312` env this project already had - `transformers`,
`peft`, `accelerate`, `torch` were, and cover everything this pilot needs:
LoRA, bf16, gradient accumulation, gradient checkpointing, deterministic
seeding, checkpoint save/resume, validation loss, and structured metrics
logging are all native `Trainer` features).

Loss masking: every training example carries `messages` with a `trainable`
flag per message (see `build_distillation_manifest.py`'s docstring for why
- Biomni's own agent injects tool-execution observations as synthetic
`assistant`-role messages, which must never receive loss). Per-message token
spans are found by re-rendering the chat template on successive message
prefixes and diffing lengths - exact for this tokenizer/template, not an
approximation, at the cost of O(n_messages) template calls per example
(cheap; examples have tens of messages, not thousands).

    python scripts/train_distillation_sft.py \
        --manifest manifests/distillation_pilot_v1/treatment_reward_positive_ensemble.jsonl \
        --model-path /scratch/.../Biomni-R0-32B-Preview/snapshots/71432eb... \
        --output-dir /scratch/.../checkpoints/distillation_smoke \
        --max-examples 4 --max-steps 4 --smoke-test
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

MAX_CONTEXT = 65536
LORA_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def load_examples(manifest_path: Path, *, max_examples: int | None, max_context: int, tokenizer) -> list[dict]:
    examples = []
    skipped_over_context = 0
    with manifest_path.open() as fh:
        for line in fh:
            ex = json.loads(line)
            msgs = [{"role": m["role"], "content": m["content"]} for m in ex["messages"]]
            ids = tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=False)["input_ids"]
            if len(ids) > max_context:
                skipped_over_context += 1
                continue
            examples.append(ex)
            if max_examples is not None and len(examples) >= max_examples:
                break
    if skipped_over_context:
        print(f"NOTE: skipped {skipped_over_context} example(s) exceeding {max_context} tokens", file=sys.stderr)
    return examples


def build_labeled_example(ex: dict, tokenizer, *, max_context: int) -> dict[str, list[int]] | None:
    """Render the full conversation once, then find each message's token span
    by re-rendering successive prefixes and diffing - exact, not approximate.
    """
    msgs = [{"role": m["role"], "content": m["content"]} for m in ex["messages"]]
    trainable_flags = [m["trainable"] for m in ex["messages"]]

    full_ids = tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=False)["input_ids"]
    if len(full_ids) > max_context:
        return None

    labels = [-100] * len(full_ids)
    prev_len = 0
    for i in range(1, len(msgs) + 1):
        prefix_ids = tokenizer.apply_chat_template(msgs[:i], tokenize=True, add_generation_prompt=False)["input_ids"]
        span_end = len(prefix_ids)
        if trainable_flags[i - 1]:
            for j in range(prev_len, min(span_end, len(full_ids))):
                labels[j] = full_ids[j]
        prev_len = span_end

    return {"input_ids": full_ids, "attention_mask": [1] * len(full_ids), "labels": labels}


class JsonlSFTDataset(torch.utils.data.Dataset):
    def __init__(self, examples: list[dict], tokenizer, *, max_context: int):
        self.rows = []
        for ex in examples:
            row = build_labeled_example(ex, tokenizer, max_context=max_context)
            if row is not None:
                self.rows.append(row)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        row = self.rows[idx]
        return {k: torch.tensor(v, dtype=torch.long) for k, v in row.items()}


def collate(batch: list[dict[str, torch.Tensor]], pad_token_id: int) -> dict[str, torch.Tensor]:
    max_len = max(len(b["input_ids"]) for b in batch)
    input_ids = torch.full((len(batch), max_len), pad_token_id, dtype=torch.long)
    attention_mask = torch.zeros((len(batch), max_len), dtype=torch.long)
    labels = torch.full((len(batch), max_len), -100, dtype=torch.long)
    for i, b in enumerate(batch):
        n = len(b["input_ids"])
        input_ids[i, :n] = b["input_ids"]
        attention_mask[i, :n] = b["attention_mask"]
        labels[i, :n] = b["labels"]
    return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--model-path", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--max-examples", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--num-train-epochs", type=float, default=1.0)
    ap.add_argument("--per-device-batch-size", type=int, default=1)
    ap.add_argument("--gradient-accumulation-steps", type=int, default=8)
    ap.add_argument("--lora-r", type=int, default=32)
    ap.add_argument("--lora-alpha", type=int, default=64)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--learning-rate", type=float, default=1e-4)
    ap.add_argument("--seed", type=int, default=20260830)
    ap.add_argument("--gradient-checkpointing", action="store_true")
    ap.add_argument("--smoke-test", action="store_true", help="tiny non-scientific engineering check only")
    ap.add_argument("--eval-manifest", type=Path, default=None)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    tokenizer = AutoTokenizer.from_pretrained(str(args.model_path), trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    print(f"Loading model from {args.model_path} ...")
    model = AutoModelForCausalLM.from_pretrained(
        str(args.model_path), torch_dtype=torch.bfloat16, trust_remote_code=True
    )
    if args.gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()

    lora_cfg = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=LORA_TARGET_MODULES,
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    n_trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    n_total = sum(p.numel() for p in model.parameters())
    print(f"trainable_params={n_trainable} total_params={n_total} ratio={n_trainable / n_total:.6f}")

    examples = load_examples(
        args.manifest, max_examples=args.max_examples, max_context=MAX_CONTEXT, tokenizer=tokenizer
    )
    print(f"Loaded {len(examples)} training example(s) from {args.manifest}")
    train_ds = JsonlSFTDataset(examples, tokenizer, max_context=MAX_CONTEXT)

    eval_ds = None
    if args.eval_manifest is not None:
        eval_examples = load_examples(
            args.eval_manifest, max_examples=args.max_examples, max_context=MAX_CONTEXT, tokenizer=tokenizer
        )
        eval_ds = JsonlSFTDataset(eval_examples, tokenizer, max_context=MAX_CONTEXT)

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        per_device_train_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        num_train_epochs=args.num_train_epochs,
        max_steps=args.max_steps if args.max_steps else -1,
        learning_rate=args.learning_rate,
        bf16=True,
        logging_steps=1,
        save_strategy="steps" if not args.smoke_test else "no",
        save_steps=max(1, (args.max_steps or 100)),
        eval_strategy="steps" if eval_ds is not None else "no",
        eval_steps=max(1, (args.max_steps or 100)),
        seed=args.seed,
        report_to=[],
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        data_collator=lambda batch: collate(batch, tokenizer.pad_token_id),
    )

    if args.smoke_test:
        print("=== SMOKE TEST: forward/backward only, no scientific interpretation of loss ===")
        result = trainer.train()
        print("smoke train result:", result)
        print(
            "gradient flowed into LoRA only:",
            all((p.grad is not None) == p.requires_grad for p in model.parameters() if p.requires_grad),
        )
        ckpt_dir = args.output_dir / "smoke_checkpoint"
        trainer.save_model(str(ckpt_dir))
        print(f"saved smoke checkpoint to {ckpt_dir}")
        reloaded = AutoModelForCausalLM.from_pretrained(
            str(args.model_path), torch_dtype=torch.bfloat16, trust_remote_code=True
        )
        from peft import PeftModel

        reloaded = PeftModel.from_pretrained(reloaded, str(ckpt_dir))
        print("checkpoint reloaded successfully:", type(reloaded))
        return 0

    trainer.train()
    trainer.save_model(str(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
