# Biomni trajectory-distillation pilot — pre-registration

**Written:** 2026-08-30, following `reports/close_out.md`'s Phase A (held-out
metric harmonization, STRONG) and Phase B (minimal SFT stack). **Frozen
before the real Vanilla-SFT/ensemble-SFT training arms are launched** — this
document freezes design, not results; per `close_out.md`'s stop condition,
training is not launched in the same step that freezes it.

---

## 1. Base checkpoint and native representation (B1)

| item | value | source |
| --- | --- | --- |
| base checkpoint | `biomni/Biomni-R0-32B-Preview` | pinned throughout this project |
| exact revision | `71432eb3d5e583bee757e0f9437a17e711e8e3d1` | `external/BIOMNI_PIN.json` |
| architecture | `Qwen3ForCausalLM` (Qwen3-32B base) | `config.json` |
| weights on disk | 27 safetensors shards, fp32-native, served bf16 | verified: `hf_cache/hub/models--biomni--Biomni-R0-32B-Preview/snapshots/71432eb.../model-*-of-00027.safetensors` |
| tokenizer/chat template | model's own `chat_template.jinja` (native Qwen3 format) | read directly from the cached snapshot, not assumed |
| special tokens | `<|im_start|>`, `<|im_end|>` (template control tokens). Biomni's own in-content tags (`<think>`, `<execute>`, `<observation>`, `<solution>`, `<BIOMNI_CONFIDENCE>`) are **plain text**, not added vocabulary tokens - verified against `special_tokens_map.json`/`added_tokens.json` |
| tool-call serialization | **Biomni does not use the model's native `<tool_call>`/`tool`-role machinery at all.** It is CodeAct-style: the model emits `<execute>...</execute>` Python directly in its own assistant text; `biomni/agent/a1.py`'s `execute()` node runs it and appends the result as a **synthetic `AIMessage`**, `content=f"<observation>{result}</observation>"` (verified at `a1.py` line ~1550, not inferred from console formatting) |
| system prompt representation | Rebuilt **fresh at every LLM call** from RAG-retrieved tool/data-lake/library descriptions (`a1.py::_generate_system_prompt`, prepended as `[SystemMessage(...)] + state["messages"]` - never itself stored in `state["messages"]`). **Not persisted verbatim anywhere on disk** - only a retrieval summary (selected-item counts and short name lists) survives in `events.jsonl`. This is the one part of the native structure this pilot does **not** reconstruct exactly (see §2). |
| assistant-message structure | `<think>{reasoning}</think>\n\n{prose}` inline in the same generated text, exactly matching the chat template's own fallback split logic; optional `<execute>`/`<solution>` tag at the end |
| is `<think>` trainable? | **Yes.** It is genuine Biomni-generated reasoning (not a template artifact) and is exactly the signal ensemble-distillation is trying to transfer - excluding it would train only on final answers, defeating the objective |
| max context supported | 65,536 (D-04's YaRN-scaled serving context; native is 40,960) |

## 2. Trajectory representation decision (B2)

**Chosen: Option 2 - assistant trajectory with tool context.** Not Option 1
(full native), because the system prompt (§1) cannot be reliably
reconstructed without unverified extra engineering (re-invoking
`_generate_system_prompt` with the exact recorded retrieval selections);
not Option 3 (final-turn only), because the conversational
thread reconstructs **reliably** - this was tested, not assumed.

**Evidence** (`stdout.log` parsed via
`scripts/build_distillation_manifest.py::parse_stdout_log`, cross-checked
against `events.jsonl`'s `llm_call_count`, across **12 real trajectories
spanning 6 task families** - `crispr_delivery`, `gwas_causal_gene_gwas_catalog`,
`gwas_causal_gene_opentargets`, `gwas_causal_gene_pharmaprojects`,
`gwas_variant_prioritization`, `lab_bench_dbqa`):

* every trajectory's `stdout.log` parses cleanly into exactly one initial
  "Human Message" (the task prompt) followed by alternating "Ai Message"
  blocks;
* every "Ai Message" block is mechanically classifiable as a real generation
  or an injected observation via the `^<observation>.*</observation>$`
  content pattern (verified against `a1.py`'s exact wrapper string, not a
  heuristic);
* real-generation count was consistently `llm_call_count - 1` across all 12
  samples regardless of task family or trajectory length (4-16 LLM calls) -
  a clean, fully-explained, systematic offset (one internal call, most
  likely a final self-critic/validation step, that never surfaces as a
  conversational turn and is therefore correctly absent from a
  message-based reconstruction).

**Representation, concretely:**

```
[0] system:    fixed placeholder (documented limitation, not a silent
               approximation - every manifest row is explicit about this)
[1] user:      the task prompt (verbatim, from the manifest task definition)
[2] assistant: real generation (trainable=True)
[3] assistant: <observation>...</observation> injected by Biomni's execute()
               node (trainable=False - never receives loss)
[4] assistant: real generation (trainable=True)
...
[n] assistant: final generation containing <solution>...</solution>
               (trainable=True)
```

Roles are **never remapped** (no synthetic `tool` role is introduced) -
`assistant` stays `assistant` throughout, matching Biomni's actual live
runtime exactly, so the trained model sees the same structure at
train time it will see at inference/deployment time inside the unmodified
Biomni harness. Loss masking is carried as a per-message `trainable` boolean
rather than by role, and is applied by finding each message's exact token
span (re-rendering the chat template on successive prefixes and diffing -
exact, not approximate) in `scripts/train_distillation_sft.py::build_labeled_example`.

## 3. Training manifests (B3, B4)

Built by `scripts/build_distillation_manifest.py` (committed), consuming
only the frozen training sources (`phase1_pooled` K=4, `phase2b_primary`
K=2 - trajectory_index ∈ {0,1} only, per `close_out.md`'s frozen rule).
Every example carries: `task_id`, `global_instance_id`, `source_experiment`,
`source_config`, `trajectory_index`, `official_reward`, `completion_status`,
`selection_rule`, `raw_run_path`, `trajectory_hash`, `prompt_hash`,
`target_hash`, `K_source`. **A hard assertion runs before any file is
written**: generated task IDs are intersected against
`manifests/scope_main.jsonl` and the script exits non-zero on any overlap
(`assert_no_held_out_overlap`) - verified empty on this run.

| manifest | file | n examples | selection rule |
| --- | --- | ---: | --- |
| Control (vanilla SFT) | `manifests/distillation_pilot_v1/control_vanilla_sft.jsonl` | **192** | lowest-`trajectory_index` **completed** trajectory, reward-agnostic |
| Treatment (reward-positive ensemble) | `manifests/distillation_pilot_v1/treatment_reward_positive_ensemble.jsonl` | **126** | lowest-`trajectory_index` **officially correct** trajectory; no example emitted if none correct |

`treatment_ids ⊆ control_ids` (verified) - every treatment example's task
also has a control example, as expected (control's eligibility condition is
strictly weaker).

## 4. Exposure matching (B5)

Real tokenizer-measured statistics (Biomni-R0's own tokenizer/template,
`scripts/`'s own analysis, not estimated):

| | control (192 ex) | treatment (126 ex) |
| --- | ---: | ---: |
| total serialized tokens | 2,972,001 | 1,635,971 |
| **total assistant-loss tokens** | **1,500,089** | **761,881** |
| median / p90 / p99 seq len | 14,855 / 23,815 / 30,976 | 12,972 / 22,384 / 27,133 |
| max seq len | 168,118 (1 outlier) | 27,813 |
| fraction exceeding 65,536-token context | 0.52% (1/192) | 0% |

Control has **~2x** treatment's total loss-token exposure - a naive
equal-epoch comparison would confound "does ensemble selection help" with
"the control arm just saw twice as many gradient updates." **Decision,
frozen before training**: match on **total assistant-loss-token exposure**,
not epochs or steps, per the stated default preference. Treatment trains for
1 full epoch (761,881 loss-tokens); control is capped (via `--max-steps`,
computed from its own measured tokens/step at the frozen batch config, §5)
to see the **same** ~761,881 total loss-tokens - i.e., control trains for
approximately `761,881 / 1,500,089 ≈ 0.508` of its own epoch, not a full
pass over its larger corpus. All other hyperparameters (LR, LoRA config,
optimizer, seed) are identical between arms. **The one over-context example**
(168,118 tokens, control) **is excluded**, not truncated - truncating risks
silently cutting off the final `<solution>` tag, corrupting the training
target; exclusion is the honest choice, at a cost of 1/192 (0.5%) examples.

## 5. LoRA SFT implementation (B6)

`scripts/train_distillation_sft.py` (committed). Reuses
`transformers.Trainer` + `peft` directly - **no `trl`, no `deepspeed`
added as new dependencies**; the pre-existing `rl_harness312` environment
(`/scratch/11034/atzanakak/biomni_vista/envs/rl_harness312`, Python 3.12.11,
built for this project's earlier RL-harness work) already has
`transformers 5.10.4`, `peft 0.20.0`, `accelerate 1.14.0`,
`torch 2.11.0+cu130`, all sufficient.

| item | value |
| --- | --- |
| LoRA target modules | `q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj` (all attention + MLP projections) |
| LoRA rank | 32 |
| LoRA alpha | 64 |
| LoRA dropout | 0.05 |
| optimizer | AdamW (`Trainer` default) |
| learning rate | 1e-4 |
| scheduler | `Trainer` default (linear, no warmup override) |
| warmup | 0 (not tuned - first pilot, revisit only if training is visibly unstable) |
| weight decay | `Trainer` default (0.0) |
| effective batch size | 1 (per-device) x 8 (grad-accum) = 8 |
| max sequence length / context | 65,536 (matches serving config, D-04) |
| packing/truncation | **no packing, no truncation** - over-context examples are excluded (§4), never silently cut |
| gradient checkpointing | enabled |
| precision | bf16 |
| deterministic seed | 20260830 |
| checkpoint selection | lowest dev-split loss (§6) |
| early stopping | none in this first pilot (fixed loss-token budget per §4, not adaptive) |

Loss masking is exact per-message token-span masking (§2), not a
regex-over-rendered-string approximation.

## 6. Train/dev split (B8)

`manifests/distillation_pilot_v1/dev_split.json`
(hash `5d5021a6b7ba1b40`, `dev_split.hash`). Deterministic, seed `20260830`,
split by **task instance** (never trajectory), stratified per task family
where feasible (15% per family, minimum 1), same dev IDs used for **both**
control and treatment. **192 training-eligible instances → 162 train / 30
dev.** Verified zero overlap with `manifests/scope_main.jsonl` (assertion
in the split-builder, passed). The dev set is used only for checkpoint
selection and basic optimization sanity checks (§5) - never for
hyperparameter search in this first pilot (no hyperparameter search is
planned; if one becomes necessary, nested cross-validation on this same
162-instance train pool would be required, per `CLAUDE.md`'s D-19
precedent, not `scope_main`). **The 120 `scope_main` tasks are touched by
no training decision anywhere in this pipeline.**

## 7. Smoke test (B7)

Run on the real `rl_harness312` environment against the real cached
Biomni-R0-32B checkpoint on this session's allocated GH200 (97,871 MiB) -
not simulated, not estimated.

**Attempt 1** (2 examples in natural manifest order, `crispr_delivery/20`
10,998 tokens + `crispr_delivery/28` 9,535 tokens, `--gradient-accumulation-steps 2`,
no `expandable_segments`): model loaded (33,030,558,720 total params),
LoRA attached (268,435,456 trainable, 0.8127% - matches the audit's
100-400M estimate), tokenizer/template rendered correctly, **forward+backward
succeeded on example 1** (`loss=0.245`, finite), then **CUDA OOM on example
2's backward pass** - `tried to allocate 5.40 GiB, only 4.90 GiB free,
90.09 GiB already in use`, with PyTorch itself flagging 8.39 GiB
reserved-but-unallocated (fragmentation, not pure over-capacity).

**Attempt 2** (2 shorter real examples, `lab_bench_seqqa/492` +
`lab_bench_seqqa/547`, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
added): **complete success** - both steps ran (`loss=0.153` then `0.1366`,
finite and decreasing), `train_runtime=9.396s`, checkpoint saved to
`/scratch/11034/atzanakak/biomni_vista/checkpoints/distillation_smoke_test2/smoke_checkpoint`,
and **reloaded successfully** as `peft.peft_model.PeftModelForCausalLM`
confirming the manifest → training → checkpoint pipeline works end to end.
No held-out data was read at any point (both attempts used only the
treatment training manifest).

**Checklist against B7's stated purpose:**

| check | result |
| --- | --- |
| model loads | yes |
| LoRA attaches | yes (268.4M/33.03B, 0.81%) |
| tokenizer/template correct | yes |
| forward/backward succeeds | yes, for examples up to ~11K tokens with grad-accum=1 equivalent load; **not yet demonstrated at the corpus's actual median (13-15K) or p90 (22-24K) lengths** |
| loss is finite | yes (0.245; 0.153 -> 0.1366) |
| gradient flows into LoRA only | **guaranteed by construction** (`get_peft_model` freezes all non-LoRA parameters; the exact 268,435,456/33,030,558,720 split confirms it) - **my own runtime `.grad`-based check is unreliable and reported a false negative**, because `Trainer` clears `.grad` after each optimizer step, before my check ran; reporting this as a flaw in my verification code, not a training defect, rather than silently deleting the discrepancy |
| checkpoint saves | yes |
| checkpoint reloads | yes, though the reload in this script loads onto CPU (no `device_map`/`.to("cuda")` was passed for the reload check) - confirms the artifact deserializes correctly, not that a GPU reload succeeds under memory pressure |
| manifest is consumable | yes |
| no held-out data touched | yes |

**A genuine, unresolved risk, stated plainly rather than smoothed over:** the
OOM in attempt 1 occurred on a **9,535-token** example - below this corpus's
own median (13-15K, §4) - under `grad-accum=2` without `expandable_segments`.
The successful attempt 2 changed **two things at once** (much shorter
sequences *and* `expandable_segments`), so it does **not** demonstrate that
the corpus's actual median/p90/p99 lengths (13K-31K tokens) fit safely on
this single 95 GiB GPU even with `expandable_segments` enabled. **This is not
resolved in this session.** Before the real arms are launched, one of the
following must happen first (not yet done):

1. re-run the smoke test at progressively realistic lengths (10K, 15K, 20K,
   30K tokens) with `expandable_segments` enabled, to find the actual safe
   ceiling on one GPU with this exact LoRA config; or
2. plan for ≥2 GPUs (FSDP/sharded LoRA) to remove the memory-margin question
   entirely; or
3. reduce the memory footprint further (lower LoRA rank, smaller
   per-step activation footprint) and re-verify.

**No launch command below should be run without first closing this gap.**

## 8. Evaluation design (B10)

Comparison: **Base Biomni-R0 vs. Vanilla SFT vs. Reward-positive ensemble
SFT**, all evaluated K=4 on the untouched `scope_main` (120 instances,
Arm A only), using **Reliability Suite v1 unchanged**
(`reliability.evaluate_reliability`) - the same canonical metric harmonized
in Phase A, not the legacy pipeline.

**Primary endpoint:** Pass@1 on `scope_main`.

**Secondary endpoints:** K=4 plurality accuracy, Oracle@4, selection
headroom, canonical v1 agreement→correctness AUROC, AUPRC, AURC/risk-coverage,
`stable_correct`/`stable_wrong`/`unstable_recoverable`/`unstable_unrecoverable`
counts, execution/tool failure rate.

**Statistical method:** paired bootstrap over task instances (never
trajectories, per this project's own integrity rule), reporting Δ Pass@1,
Δ plurality accuracy, Δ Oracle@4, Δ v1 AUROC, Δ stable-wrong rate, each with
a 95% CI.

**Named safety check, checked explicitly, not inferred from accuracy
alone:** does either SFT arm raise Pass@1 while also substantially
increasing `stable_wrong` rate or collapsing agreement→correctness AUROC?
An accuracy gain paired with a `stable_wrong` increase is **not** reported
as an unqualified success.

## 9. Compute (B11)

**Real measured numbers, honestly scoped to what they actually demonstrate:**

| quantity | value | note |
| --- | ---: | --- |
| control examples | 192 (191 after excluding the 1 over-context outlier) | §3 |
| ensemble-treatment examples | 126 | §3 |
| control assistant-loss tokens | 1,500,089 | §4, real tokenizer measurement |
| treatment assistant-loss tokens | 761,881 | §4, real tokenizer measurement |
| control total serialized tokens | 2,972,001 | §4 |
| treatment total serialized tokens | 1,635,971 | §4 |
| median / p90 / p99 sequence length | 12,972-14,855 / 22,384-23,815 / 27,133-30,976 | §4, per arm |
| fraction truncated at 65,536 | 0% (excluded, not truncated - §4) | one 168,118-token example dropped |
| trainable parameters | 268,435,456 (0.81% of 33,030,558,720) | measured, this session, real model load |
| smoke throughput (measured, **not representative** - see caveat) | `train_runtime=9.396s` for 2 optimizer steps on ~1-3K-token examples; `0.213 steps/sec`, `0.426 samples/sec` | §7 |
| measured peak VRAM at failure | 90.09 GiB in use, OOM on a 9,535-token example, single 95 GiB GPU | §7 |

**Projected GPU-hours per arm: NOT computed here, deliberately.**
Extrapolating from the smoke test's tiny-example throughput would
understate real cost - attention cost scales worse than linearly with
sequence length, and the smoke examples (~1-3K tokens) are far shorter than
the corpus median (~13-15K). Doing so would repeat exactly the mistake the
original audit's "1-4 H100-hours/arm" estimate made (an estimate from
adjacent numbers, not measurement) - which this section exists to correct,
not reproduce under a new name. **The real projection is blocked on the same
open item as §7**: a throughput/memory measurement at representative
(10K-30K token) sequence lengths. Until that exists, the honest statement is
that per-arm cost is unknown to within better than an order of magnitude,
and total assistant-loss-token volume (761,881 for the exposure-matched
budget, §4) is the only solid input available for a future estimate once
per-token throughput at realistic lengths is measured.

---

## Launch readiness

**Frozen, not launched - and not yet fully launch-ready.** Design, manifests,
split, and engineering pipeline are frozen and validated end-to-end (§§1-8).
Per `close_out.md`'s stop condition, training is not launched in the same
step that freezes it, regardless. But this pilot has one additional,
explicit precondition beyond that stop condition, found only by actually
running the smoke test rather than assuming a config: **§7's memory-margin
question must close first** - a single-GPU launch at this pilot's real
median/p90 sequence lengths is unverified, not merely untried. The exact
command below is what today's frozen config *would* run; it should not be
executed until §7's open item is resolved one way or another (representative-length
validation, multi-GPU, or a reduced-footprint config).
