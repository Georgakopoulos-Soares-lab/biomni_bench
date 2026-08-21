# Harnessed GRPO on Biomni-R0 — engineering audit and pre-registration

**Written:** 2026-08-21. **Status: FROZEN** for every scientific section below.
**No RL training has run. No scientific RL result exists.** Engineering smoke
tests, if run after this freeze, are infrastructure validation, never a
prospective scientific result, and are labelled as such wherever they appear.

**Boundary.** D-43/Stage C, D-44–D-46 (the scope study), and D-47–D-48 (the
RL-signal preflight) are closed and are not reopened. D-48's NO-GO on
uncertainty-guided prioritization stands: **this experiment uses uniform
prompt sampling, no adaptive K, no verifier reward, and no new correction
mechanism** — the plain question the preflight's closure licenses asking next.

## 0. The question

> Can plain harnessed GRPO improve Biomni-R0 itself, and does RL training
> change the reliability/uncertainty behaviour characterised in Part I
> (Phase 1 / the scope study)?

Six sub-questions, each mapped to a specific endpoint in §7:

1. Does plain harnessed RL improve held-out Biomni performance?
2. Does it reduce selection failures / Oracle@K headroom?
3. Does it make the model more consistent (higher agreement)?
4. Does agreement remain a strong predictor of correctness after RL?
5. Does calibration improve or deteriorate?
6. Does RL risk making the model more *consistently wrong* — higher
   agreement with no accuracy gain, or a drop in accuracy alongside a rise
   in agreement?

Question 6 is the safety question this design is built to be able to answer,
not just ask: it requires measuring agreement and accuracy **together**,
post-RL, on the same held-out set — a single accuracy number cannot detect it.

---

## PART A — Engineering feasibility audit

### A.1 What is already in this repository — verified, not assumed

`pip list` on both project environments (`biomni_unc`, `sglang_srv`) shows
**no verl, no Agent Lightning, no PEFT, no DeepSpeed, no Ray, no vLLM, no
TRL**. Nothing about RL training exists in this repository as of this freeze.
`flash-attn` is already present in `sglang_srv` (4.0.0b19), which every
mainstream RL training backend wants. Network egress to PyPI and GitHub is
confirmed reachable (200s on both, verified by direct request). Disk: 1.8 PB
free on `/scratch`. **Nothing here blocks starting from zero.**

### A.2 Agent Lightning + verl suitability

**Suitable, with one required mitigation (A.3).** Reasoning:

* **verl** (`volcengine/verl`) implements GRPO natively, and supports **SGLang
  as a rollout backend** — this project's serving stack is already pinned to
  SGLang 0.5.16 everywhere (D-01, D-03, D-04, every phase's server launch).
  Using verl's SGLang backend means the rollout engine is the **same server
  binary** already validated for Biomni-R0 at 65536 context throughout this
  project, not a new inference stack to re-validate.
* **Agent Lightning** (`microsoft/agent-lightning`) is built for exactly the
  integration pattern already in place here: an agent that talks to an
  OpenAI-compatible endpoint via a configurable `base_url`, with **no
  framework rewrite required**. Its proxy sits at the URL the agent already
  points to, transparently records the full multi-turn trace (messages,
  token ids, logprobs) tagged by rollout id, forwards to the real inference
  engine, and hands verl a properly formatted, loss-masked training sequence.
  This is a direct match for `biomni.llm.get_llm(source="Custom",
  base_url=...)` — the **only configuration that changes is the value of
  `base_url`** (pointed at the Agent Lightning proxy instead of directly at
  SGLang); `A1.configure()`'s closures (D-01's "never edit Biomni" boundary)
  are untouched.
* **Multi-turn credit assignment, stated precisely because it is a real design
  choice, not a detail.** A Biomni-R0 trajectory averages **~14 LLM calls**
  (`mean_llm_calls` measured at 15.7 in the capability gate, D-44). Agent
  Lightning's standard scheme treats the **whole multi-turn conversation as
  one training sequence**, masks the loss to the assistant-generated spans
  (each of the ~14 turns), and assigns the **same trajectory-level reward** to
  every masked span as its return. This is the standard, simplest credit
  assignment used by essentially every existing multi-turn agentic-RL
  framework; finer-grained per-turn credit is an open research problem and is
  explicitly **out of scope** — "no new correction mechanism" rules it out
  here regardless.

### A.3 The serious blocker the audit found, and its mitigation

**Full-parameter GRPO fine-tuning of Biomni-R0-32B does not fit in 4×96GB
H100 (384GB total), independent of rollout serving.** Arithmetic, stated
plainly:

| component | size |
| --- | --- |
| policy weights (bf16) | 64 GB |
| AdamW fp32 master weights | 128 GB |
| AdamW fp32 first/second moments (2×) | 256 GB |
| **optimizer + master-weight total** | **448 GB** |

448 GB alone exceeds the cluster's 384 GB, **before** accounting for
activations, gradients, or the rollout engine's own memory (a single 32B
bf16 replica at 65536 context already measures ~85 GB/GPU across 2 GPUs in
this project's own servers — 170 GB for one rollout replica).

**Mitigation, and why it is not a downgrade of the candidate:** train with
**LoRA**, not full-parameter fine-tuning. A rank-16–64 LoRA over
attention/MLP projections on a 32B model is on the order of **100–400M
trainable parameters** — optimizer state for that is a few GB, not hundreds.
The frozen base weights (64 GB bf16) are shared with — and in verl's hybrid-
engine design, can be the **same weights already resident for rollout
serving**, with LoRA adapters hot-swapped in for the policy-gradient forward/
backward pass. **This keeps Biomni-R0-32B as the primary candidate, per the
brief's own instruction, because the blocker has a standard, well-supported
mitigation rather than requiring a smaller model.** Full-parameter fine-tuning
remains infeasible on this hardware and is not proposed.

### A.4 Context-overflow safeguards — preserved, not re-engineered

`src/biomni_uncertainty/budget.py`'s four guards (R2–R5) operate **inside
`runner.py`'s LangGraph instrumentation, upstream of the HTTP call** to
whatever `base_url` is configured:

* R2 — truncates a length-terminated generation before it re-enters the
  conversation;
* R3 — soft/hard input-token budgets that inject a synthesis instruction or
  force-terminate a runaway trajectory;
* R4 — caps the tool retriever's selection (the 32–44k-token system-prompt
  failure mode, D-30);
* R5 — caps a single observation's model-visible size, head+tail, full raw
  output preserved on disk.

**Routing the same HTTP call through an Agent Lightning proxy instead of
directly to SGLang changes nothing about when or whether these guards fire**
— they act before the call leaves the agent process. No re-engineering is
required to preserve them; the audit's job here was to confirm this, not to
build anything new, and it is confirmed by inspection of where R2–R5 execute
relative to the network call.

### A.5 Official evaluator — preserved exactly

Reward is computed by the **existing, unmodified**
`OfficialEvaluator`/`biomni.eval.biomni_eval1.BiomniEval1._compute_reward`,
called after each trajectory completes — exactly as every prior phase. The
only new step is forwarding that scalar to Agent Lightning/verl's reward
channel after computing it; the reward is never recomputed, approximated, or
augmented with a verifier or confidence term, per the brief's explicit
instruction.

### A.6 Realistic throughput and cost estimate

Measured Biomni-R0 wall-time per trajectory (Part I / D-44's capability gate):
**mean ≈ 310–374 s**. At this project's own established concurrency setting
(`execution.max_concurrency: 4`), a training step of `batch_size × G`
rollouts costs roughly:

```
step_wall_seconds ≈ (batch_size × G × 340s) / concurrency
```

For the pilot design frozen in §5 (batch_size 16, G=4 → 64 rollouts/step):
`64 × 340 / 4 ≈ 5,440 s ≈ 1.5 hours of rollout wall-time per step`, before any
backward/optimizer time (small under LoRA — expect minutes, not hours).
**Rollout generation, not the RL update itself, is the dominant cost**,
because Biomni trajectories are long, tool-using, and slow relative to a
single-turn completion. This is stated as a range, not a guarantee — actual
throughput depends on Agent-Lightning/verl overhead and achievable
concurrency, neither measured yet.

### A.7 Train/held-out split — verified and frozen (`scripts/rl_harness_split_audit.py`)

**No new manifest was built.** Both pools are already-frozen, committed
artifacts, verified disjoint by direct computation before this document was
written:

| pool | n | source | role |
| --- | ---: | --- | --- |
| **training** | 200 | `manifests/phase1.jsonl` ∪ `manifests/phase2b.jsonl` | GRPO rollouts + updates |
| **held-out eval** | 120 | `manifests/scope_main.jsonl` | pre/post-RL comparison, never trained on |
| overlap | **0** | — | verified, not assumed |
| reserved, untouched | 100 | never-used pool (D-45) | **not spent by this experiment** |

**Why the training pool reuses already-measured instances.** What matters for
RL is train/eval separation, not previously-measured/never-measured
separation — these 200 instances have generated trajectories for
*measurement* in Phase 1/2B, but **no model weight has ever been updated from
them.** Reusing them for RL rollouts is clean.

**Why the held-out set is exactly the scope-study's 120.** Biomni-R0's Arm A
on this population is **already fully characterised** (D-46, D-48): Pass@1
0.442, plurality 0.617, Oracle@4 0.792, agreement→correctness AUROC 0.896
[0.855, 0.930], selection-failure rate 0.175 [0.108, 0.25], AUROC 0.760
[0.664, 0.844]. **The pre-RL half of every endpoint in §7 is already
computed and requires no new measurement** — only a post-RL K=4 rerun on the
identical 120 instances, using the identical frozen analysis code
(`scripts/scope_main_detection_analysis.py`,
`scripts/rl_signal_preflight_analyze.py`'s reward-vector/selection-failure
logic) already committed and tested.

**The 100 genuinely never-used instances are reserved, not spent.** A
plausible larger follow-up (a bigger RL run, or a confirmatory fresh-eval
check) may need them later; this pilot does not touch them.

---

## PART B — Frozen scientific design

### B.1 Primary hypotheses

> **H-RL2a.** Plain harnessed GRPO, trained on the 200-instance pool with the
> official binary reward only, improves held-out (120-instance) mean reward
> relative to the frozen pre-RL baseline.

> **H-RL2b (safety).** RL does **not** increase agreement/consistency without
> a corresponding accuracy gain — i.e., it does not make the model more
> *consistently wrong*.

### B.2 Configuration — frozen before any training

| parameter | value | note |
| --- | --- | --- |
| base model | `biomni/Biomni-R0-32B-Preview` @ `71432eb3…` | per brief; A.3's LoRA mitigation applies |
| training method | GRPO, LoRA (rank to be fixed at implementation time, standard range 16–64, no accuracy-driven tuning) | full-parameter ruled out, A.3 |
| rollout backend | SGLang, same serving config as every prior phase (bf16, context 65536, D-04's YaRN override) | unchanged |
| trace capture | Agent Lightning proxy at `base_url` | no Biomni code change |
| reward | official binary reward only, via `OfficialEvaluator` | no verifier, no confidence term |
| sampling | **uniform** over the 200-instance training pool | D-48's NO-GO — no uncertainty-guided sampling |
| K (rollout group size, GRPO's G) | **4** | matches Part I's own K=4 convention, for direct metric comparability; not 8, to bound rollout cost (A.6) |
| adaptive K | **none** | fixed at 4 throughout |
| batch size | 16 prompts/step (64 rollouts/step) | smallest batch giving a non-degenerate GRPO group-of-4 gradient per prompt |
| training pool passes | ~2 epochs over the 200-instance pool | ≈ 25 optimizer steps, ≈ 1,600 total training rollouts |
| held-out eval | K=4 on the same 120 instances, pre and post | reuses D-46/48's pre-RL numbers exactly |

**Nothing here is adjusted after seeing a training curve.** A configuration
change after starting is a new experiment, not a continuation.

### B.3 Primary endpoint

```
Δ_reward = (post-RL held-out mean reward, K=4) − (pre-RL held-out mean reward, 0.4417, D-46)
```

Paired, instance-clustered bootstrap (same method as every prior phase),
**10,000 replicates, seed `20260821`** (this study's own fresh seed).

**GO** — Δ_reward's 95% CI lower bound `> 0`, **and** H-RL2b's safety check
(§7.6) does not fire.
**NO-GO** — Δ_reward's CI upper bound `≤ 0`, **or** H-RL2b's safety check
fires (agreement rises with no accuracy gain, or accuracy drops).
**INCONCLUSIVE** — CI spans zero and the safety check does not fire.

### B.4 Explicitly not to be done

No uncertainty-guided sampling (D-48). No adaptive K. No verifier reward, no
confidence penalty (per brief). No new correction mechanism. No touching the
100 reserved never-used instances. No re-tuning the config after seeing a
training-time reward curve. No reopening Stage C, candidate adjudication,
diversity-by-resampling, or the RL-signal preflight's own verdict.

---

## PART C — Pre/post evaluation suite (reuses Part I metrics exactly)

All computed on the **same 120 held-out instances**, pre-RL (already done,
D-46/48) and post-RL (new K=4 rollouts on the identical prompts, identical
scaffold, only the policy weights differ):

| endpoint | pre-RL value (frozen, D-46/48) | method (unchanged) |
| --- | ---: | --- |
| Pass@1 / plurality / Oracle@4 | 0.442 / 0.617 / 0.792 | `selectors.select_plurality`/`select_oracle` |
| selection headroom | 0.175 | Oracle@4 − plurality |
| **agreement→correctness AUROC** | **0.896** [0.855, 0.930] | `analysis.signal_auroc_table`, `agreement_fraction` |
| selection-failure rate / AUROC | 0.175 / 0.760 [0.664, 0.844] | `rl_signal_preflight_analyze.py`'s selector logic |
| mixed-reward rate | 0.558 | D-48 |
| all-wrong rate | 0.208 | D-48 |
| calibration (overconfidence gap, ECE) | Phase 1 baseline: gap 0.37–0.43 | `analysis.confidence_calibration`, unchanged |

**Every one of the six scientific questions in §0 maps to a specific row
above, computed pre/post and compared with the same paired-bootstrap
method:**

1. held-out reward → primary endpoint (B.3);
2. selection-failure rate / Oracle@4 headroom → row 2/3;
3. agreement/consistency → `plurality_fraction`/`pairwise_agreement` mean,
   pre vs post;
4. agreement→correctness AUROC → row 4, pre vs post;
5. calibration → row 7, pre vs post;
6. **the safety check**: flag if agreement rises (row 3) **and** accuracy does
   not (row 1's CI does not exclude zero or is negative) — this is H-RL2b,
   checked explicitly, not inferred from the primary endpoint alone.

---

## What this document does not authorise

**Engineering smoke tests only.** No scientific RL training run is
authorised by this freeze. A smoke test (environment build, a synthetic/
dummy-reward optimizer-step check, a single real trajectory routed through
the Agent Lightning proxy to confirm trace capture and reward attachment) may
proceed and is infrastructure validation, not a result. **The first real
training run requires separate, explicit operator approval**, stated again at
the end of the accompanying status report.

---

*No RL training has occurred. This file is a precommitment, checked against —
never adjusted by — whatever the smoke tests and, subject to separate
approval, the eventual training run produce.*
