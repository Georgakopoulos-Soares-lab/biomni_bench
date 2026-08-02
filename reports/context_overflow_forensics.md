# Context-overflow forensics

**Experiment analysed:** `phase1` (250 planned runs, 39 GB of preserved traces)
**Evidence:** `<output_root>/phase1/runs/**/{events.jsonl,metadata.json,FAILED,stdout.log}`
**Reproduce:** `python scripts/context_forensics.py --runs-root <output_root>/phase1/runs --out-dir reports/forensics`
**Model calls made:** none. This is a pure re-read of data already on disk.

---

## 0. Headline

The 24% `model_context_overflow` rate is **not a context-budget problem**. It is
a **model-degeneration problem** that a large context window converts into an
expensive one.

Above roughly **32,768 input tokens** — the trained context length of this
model's base, and the `original_max_position_embeddings` value in the serving
override — the model stops emitting stop tokens and produces degenerate
repetition until it hits `max_tokens = 8192`. That 8,192-token blob is appended
to the conversation, which pushes the next call further past the boundary, which
guarantees another one. It is a one-way trapdoor: **62 of the 69 trajectories
that entered it never came back**, and all 62 failures in the pilot went through
it.

The single most important number in this report:

> **No completed trajectory ever exceeded 32,154 input tokens.** The upper half
> of the served 65,536-token window was occupied *exclusively* by trajectories
> that were already degenerating.

Raising the context ceiling would therefore not have saved a single run. It
would have bought more room for the repetition loop to run in.

---

## 1. What was measured, and how

Every run's `events.jsonl` carries an `llm_request_end` event per model call with
the endpoint's own `usage` block (`input_tokens`, `output_tokens`) and
`finish_reason`. Because Biomni's agent loop resends the whole conversation each
step, the sequence of `input_tokens` **is** the context-growth curve, measured by
the server rather than estimated by a tokenizer.

Call 0 of every run is Biomni's tool-retrieval query, which is not part of the
agent conversation. Calls 1.. are the agent loop. The growth ledger attributes
each step's increase:

```
input[i] - input[i-1]  =  output[i-1]        (the model's own text re-entering)
                       +  observation[i]     (tool output appended by the executor)
```

Definitions used throughout:

* **runaway generation** — a call with `finish_reason == "length"`, i.e. the model
  produced the full 8,192-token budget without emitting `</execute>` or
  `</solution>`. Biomni's LLM stops on those two tags, so a healthy step always
  finishes with `"stop"`.
* **failed run** — 60 `model_context_overflow` + 2 `model_timeout`. See §7 for
  why the latter two, previously recorded as "missing", belong here.

---

## 2. It is not the system prompt

`DECISIONS.md` D-04 sized the post-retrieval system prompt at 17k–41k tokens and
raised the served context from 40,960 to 65,536 on that basis. That estimate was
made *before* any GPU time, by assuming the retriever would select 25–100% of the
224 available tools. It does not match what the retriever actually did.

| quantity | offered | median selected | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| tools | 224 | **5** | 26 | 222 |
| data-lake items | 76 | **4** | 75 | 76 |
| libraries | 113 | **3** | 113 | 113 |

Measured post-retrieval system prompt **plus task prompt** (the first agent-loop
call, which contains nothing else):

| p25 | median | p75 | max |
| ---: | ---: | ---: | ---: |
| 1,878 | **2,687** | 8,501 | 44,167 |

The median fixed overhead is **2,687 tokens**, not 17,000–41,000. Retrieval is
doing its job. Trimming tool descriptions, deduplicating static prompt content or
lazily loading dataset descriptions would recover a few hundred tokens from a
median trajectory that peaks at 17,072 — **it is not where the context goes**,
and it is not worth the risk of perturbing agent behaviour.

**The tail is a different story.** Eight runs had a post-retrieval prompt above
25,000 tokens because the retriever selected nearly everything:

| run | prompt tokens | tools | data lake | libraries | outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| `crispr_delivery/i0028/instrumented/t3` | 44,167 | 222 | 76 | 113 | overflow |
| `patient_gene_detection/i0001/instrumented/t2` | 41,880 | 204 | 76 | 113 | overflow |
| `crispr_delivery/i0028/instrumented/t1` | 40,397 | 199 | 76 | 113 | overflow |
| `crispr_delivery/i0022/instrumented/t1` | 36,585 | 170 | 76 | 113 | overflow |
| `crispr_delivery/i0020/standard/t0` | 36,141 | 167 | 76 | 113 | overflow |
| `crispr_delivery/i0020/instrumented/t2` | 36,164 | 166 | 76 | 113 | overflow |
| `crispr_delivery/i0020/instrumented/t3` | 36,164 | 166 | 76 | 113 | overflow |
| `gwas_variant_prioritization/i0179/instrumented/t3` | 32,120 | 154 | 37 | 79 | overflow |

**All eight failed. Seven of the eight degenerated on their very first agent-loop
call** — before a single tool ran, before any history accumulated. This is the
cleanest confound control in the dataset (§4).

This is not a retriever bug; Biomni's own retrieval prompt instructs the model to
"be generous" and "include as many database tools as possible". It is a rare
(8/250) but **100% fatal** tail event, and it needs a cap rather than a rewrite.

---

## 3. It is runaway generation

| group | n | with ≥1 runaway generation | median runaways |
| --- | ---: | ---: | ---: |
| completed | 188 | 7 (**3.7%**) | 0 |
| failed | 62 | 62 (**100%**) | 3 |

Runaway generation is close to a perfect classifier of eventual failure. It also
arrives in **consecutive bursts** — the modal burst length is 3 (37 occurrences),
then 4 (21 occurrences), with one run reaching 18 in a row — which is the
signature of a self-sustaining loop rather than isolated bad luck.

**What the degenerate output looks like.** From
`crispr_delivery/i0014/instrumented/t2/stdout.log`, verbatim, repeating to the
8,192-token limit:

```
</think>
assistant
<think>I need to examine the contents of the CRISPR-related files to understand
what information they contain about delivery methods for colon organoids. Let me
look at the specific files I found:

1. DepMap_CRISPRGeneDependency.csv
2. DepMap_CRISPRGeneEffect.csv

Let me examine these files to see what information they contain about CRISPR
delivery methods.</think>
assistant
<think>I need to examine the contents of the CRISPR-related files ...
```

The model is emitting the `assistant` role token itself and cycling one thought
block verbatim. It has lost the chat-template structure entirely. This is
classic long-context degeneration, not a reasoning failure and not a prompt-format
failure — the same prompt format worked for the preceding 20 steps of the same
trajectory.

---

## 4. The boundary is ~32,768 tokens, and the evidence is causal

Runaway rate per agent-loop call, bucketed by the input length **at the time of
that call** (3,344 calls):

| input tokens | calls | runaway | rate |
| --- | ---: | ---: | ---: |
| 0 – 8,192 | 1,009 | 5 | 0.5% |
| 8,192 – 16,384 | 1,091 | 13 | 1.2% |
| 16,384 – 24,576 | 723 | 45 | 6.2% |
| 24,576 – 32,768 | 335 | 34 | 10.1% |
| **32,768 – 40,960** | 71 | 60 | **84.5%** |
| 40,960 – 49,152 | 59 | 59 | **100%** |
| 49,152 – 65,536 | 56 | 56 | **100%** |

Pooled: **3.1% below 32,768 vs 94.1% above — a 30× jump at the boundary.**

**Why this is not "long trajectories are hard".** Three independent checks:

1. **Position in the loop does not explain it.** Holding step index fixed, the
   split is the same at every depth:

   | step index | ctx < 32,768 | ctx ≥ 32,768 |
   | --- | ---: | ---: |
   | steps 0–4 | 1.3% (n=1193) | **100%** (n=22) |
   | steps 5–9 | 2.4% (n=987) | **100%** (n=8) |
   | steps 10–19 | 6.0% (n=805) | **100%** (n=97) |
   | steps 20+ | 5.8% (n=173) | 81.4% (n=59) |

2. **The eight over-retrieval runs of §2 are a natural experiment.** Their
   context was already past the boundary on call 1, with zero accumulated
   history and zero opportunity for the task to have "gone badly". 7/7 whose
   prompt exceeded 32,768 degenerated immediately.

3. **Completed runs never got there.** Peak input tokens among the 188 completed
   runs: median 17,072, p95 29,932, **max 32,154**. Not one crossed the
   boundary and came back with an answer.

**Leading explanation.** This model's base is Qwen3-32B, whose trained context is
32,768 tokens; the `max_position_embeddings: 40960` in `config.json` is that
context plus one 8,192-token generation, not a 40,960-token context. The serving
override (`DECISIONS.md` D-04) sets `rope_scaling: {yarn, factor: 1.0,
original_max_position_embeddings: 32768}` with `max_position_embeddings:
131072`. At factor 1.0 the YaRN transform is mathematically the identity — D-04's
argument on that point is correct — which means the override **lifted the
position ceiling without providing any actual context extension**. Its real
effect was to convert a hard 400 rejection at 40,960 into silent behavioural
collapse starting at 32,768.

D-04 recorded exactly this as a residual risk ("positions … reached by pure
extrapolation … listed as an experimental parameter"). The risk materialised, and
at a lower boundary than the one D-04 anticipated.

*Caveat, stated plainly:* this analysis establishes the boundary and its
consequences from 3,344 observed calls. It does not isolate *which* of
(a) YaRN/position extrapolation or (b) the RL fine-tune's effective context is
responsible, because the pilot varied neither. That distinction would need a
serving ablation, and it does not change the repair — both point to the same
operating limit.

---

## 5. Where the context actually goes

Median tokens per run, by source:

| group | system prompt + task | model output re-entering context | tool output |
| --- | ---: | ---: | ---: |
| completed | 2,382 | 4,680 | 7,168 |
| failed | 5,678 | **26,071** | 16,906 |

Share of total context, pooled:

| group | prompt | runaway generations | normal generations | tool output |
| --- | ---: | ---: | ---: | ---: |
| completed | 26.9% | 1.5% | 27.7% | 43.9% |
| failed | 18.4% | **38.6%** | 14.8% | 28.2% |

In a healthy trajectory tool output is the largest single consumer (43.9%) and
everything stays small. In a failed one, **the model's own degenerate output is
the largest consumer** — 38.6% of the context is text produced by runaway
generations, more than double the share of all normal generations combined.

Tool output is a real but secondary contributor. The largest single observations
are ~7,000 tokens, all from live biomedical database queries returning raw JSON
(Monarch phenotype searches, DepMap tables). Biomni already summarises some of
these (`'_summary': 'List with 1460 items'`), so the remaining bulk is genuine
evidence, not formatting waste.

---

## 6. What a repair would buy — measured, not assumed

**(a) Bounding runaway output.** If a `finish_reason == "length"` generation had
contributed at most *cap* tokens to the conversation instead of 8,192:

| cap | median peak input, failed runs | failed runs kept under the request ceiling |
| ---: | ---: | ---: |
| 512 | 52,258 → 34,130 | **62 / 62** |
| 1,024 | 52,258 → 35,510 | **62 / 62** |
| 2,048 | 52,258 → 38,216 | **62 / 62** |

Every one of the 62 failures is prevented from reaching the hard ceiling. This
does not by itself make those trajectories *correct* — a degenerating model is
not producing good analysis — but it converts an uncontrolled 400 error into a
controlled state the agent, or a controller, can act on.

**Cost of lowering `max_tokens`**, from 3,072 healthy generations:

| max_tokens | healthy generations truncated |
| ---: | ---: |
| 4,096 | 5 (0.16%) |
| 2,048 | 21 (0.68%) |
| 1,024 | 254 (8.27%) |

Healthy steps are short: median 452 output tokens, p95 1,225, p99 1,786. The
current `max_tokens = 8192` is roughly **18× the median need**, and its only
observed function is to let a degeneration event run to full length.
**`max_tokens = 2048` costs 0.68% of healthy generations and cuts the damage of
each degeneration event by 4×.**

**(b) A hard input-context budget.**

| budget | completed runs cut short | failed runs caught before the hard ceiling |
| ---: | ---: | ---: |
| 24,576 | 37 / 188 (19.7%) | 60 / 62 |
| 28,672 | 12 / 188 (6.4%) | 60 / 62 |
| **32,768** | **0 / 188 (0.0%)** | 60 / 62 |

A 32,768-token input budget is **free**: it does not touch a single trajectory
that produced an answer in the pilot, while catching 60 of 62 failures at a point
where synthesis can still be requested. This is the strongest single result in
the forensics.

**(c) Bounding tool output.** A per-observation cap saves real context —
52% of tool-output tokens at 1,000/observation, 32.5% at 2,000, 8.2% at 4,000 —
but tool output is only 28.2% of a failed run's context. On its own it delays the
boundary rather than avoiding it. It is worth doing at a *generous* cap
(4,000 tokens, 8.2% saved) purely as a guard against the 7,000-token
observations, and **the complete raw output must stay on disk** so no evidence is
destroyed.

**(d) Raising the context ceiling — rejected by the evidence.** No completed run
exceeded 32,154 input tokens. A larger window adds capacity exclusively above the
degeneration boundary, i.e. exclusively to trajectories that have already
stopped producing usable output. It would convert 60 fast failures into 60 slower
and more expensive ones. The brief's instruction not to reach for this first is
confirmed empirically.

---

## 7. Correction: the two "missing runs" are not missing

`reports/phase1_report.md` §5 and `PROJECT_STATUS.md` record 2 runs as
`missing_run` — "no run directory ever created". **This is wrong.** Both
directories exist with full evidence:

* `crispr_delivery/i0014/instrumented/t2`
* `crispr_delivery/i0028/standard/t0`

Each has `events.jsonl`, `stdout.log`, `system_prompt.txt`, a `FAILED` marker
reading `"failure_class": "model_timeout", "note": "killed by dispatcher
wall-clock timeout"`, and archived prior attempts under `attempt1/`, `attempt2/`.
They were classified `missing_run` because `metadata.json` is absent — the runner
never got to write it, since the dispatcher killed the subprocess at its 3,900 s
limit.

Their event logs show **18 consecutive runaway generations at ~206 s each**.
They are the *same* pathology as the other 60, caught by the wall-clock timeout
instead of the context ceiling. Correct accounting:

| | reported | actual |
| --- | ---: | ---: |
| `model_context_overflow` | 60 | 60 |
| `model_timeout` (runaway, killed on wall clock) | 0 | **2** |
| `missing_run` | 2 | **0** |
| failures attributable to the degeneration trapdoor | 60 | **62** |

The aggregator should trust `FAILED` when `metadata.json` is absent. This is a
reporting bug, not a data-loss event — no evidence was lost.

---

## 8. Distribution of the damage

Failure rate by task (62 failures / 250 planned runs):

| task | failed | rate |
| --- | ---: | ---: |
| rare_disease_diagnosis | 13/25 | 52% |
| crispr_delivery | 11/25 | 44% |
| patient_gene_detection | 11/25 | 44% |
| lab_bench_seqqa | 9/25 | 36% |
| gwas_causal_gene_pharmaprojects | 6/25 | 24% |
| screen_gene_retrieval | 6/25 | 24% |
| lab_bench_dbqa | 3/25 | 12% |
| gwas_causal_gene_gwas_catalog | 2/25 | 8% |
| gwas_variant_prioritization | 1/25 | 4% |
| gwas_causal_gene_opentargets | 0/25 | 0% |

`crispr_delivery` is at 44%, higher than the 36% in the Phase-1 report, because
the two reclassified `model_timeout` runs are both in that task.

The loss is **structurally non-random** and concentrated in tasks that require
many database round-trips. Only **19 of 50 instances have all four instrumented
trajectories**; 6 have one or none, where plurality is definitionally identical
to `first` and Oracle@4 headroom is definitionally zero. See
`reports/phase2_entry_assessment.md` §3 for what that does to the Phase-1
conclusions.

**Cost.** 24.9 of 49.4 measured wall-clock hours — **50.4%** — were spent on
trajectories that produced no answer. Fixing this roughly doubles the effective
throughput of the same allocation, which is the practical argument for doing it
before the Phase-2 pilot rather than after.

---

## 9. Proposed repair

Ordered by evidence strength; each is independently testable. The brief's
priority list is reordered because the forensics does not support its top item.

| # | change | evidence | invasiveness |
| --- | --- | --- | --- |
| **R1** | `max_tokens: 8192 → 2048` | §6a: 0.68% of healthy generations truncated; 4× less damage per degeneration event | one config value; no prompt change |
| **R2** | On `finish_reason == "length"`, do not append the blob. Truncate to ~512 tokens, append a corrective instruction, count it. Terminate after N consecutive. | §3, §6a: 62/62 failures kept under the ceiling; breaks the self-sustaining loop | agent-loop adapter; no prompt change |
| **R3** | Soft budget at 24,576 input tokens (inject "produce your best answer now"), hard budget at 32,768 (force synthesis, mark `budget_terminated`) | §6b: 0/188 completed runs disturbed at 32,768 | one adapter; adds a controlled outcome |
| **R4** | Cap retrieval selection (~40 tools / 20 data-lake / 20 libraries) | §2: 8/8 over-retrieval runs failed, 7/8 immediately | one cap; retriever ranking unchanged |
| **R5** | Cap a single model-visible observation at 4,000 tokens, head+tail, with a pointer to the complete artifact on disk | §5, §6c: guards 7,000-token observations; 8.2% of tool context | executor adapter; **full raw output still written to disk** |
| **R6** | Aggregator: trust `FAILED` when `metadata.json` is absent | §7 | aggregation only; no run behaviour |

**Not proposed:** raising the context ceiling (§6d), stronger YaRN scaling (the
model card warns it degrades short trajectories, which is most of this
benchmark), trimming tool/dataset descriptions (§2 — the median prompt is 2,687
tokens; nothing to recover), or any change to the task prompt, the confidence
instruction, temperature, or the retriever's ranking.

R1–R3 address the mechanism. R4–R5 address the two secondary paths into it. R6 is
a reporting fix. **None of them touches the benchmark prompt or the sampling
distribution**, so repaired trajectories remain comparable to Phase-1 ones except
through the failure mode being repaired — which is the point.

`R2` and `R3` also produce something Phase 2 needs and Phase 1 lacks: a
**controlled** terminal state (`budget_terminated`, `degeneration_terminated`)
that a controller can observe online, rather than an endpoint exception that
destroys the trajectory.

### Ablation before committing

Per the brief, a small balanced ablation on ~24 runs before any full rerun:

* 6 overflow-prone cases (2 `rare_disease_diagnosis`, 2 `crispr_delivery`
  including one over-retrieval run, 2 `patient_gene_detection`);
* 6 previously-completed controls from those same task families;
* 6 short/easy controls (`lab_bench_dbqa`, `screen_gene_retrieval`);
* 6 low-overflow GWAS controls (`gwas_causal_gene_opentargets` 0%,
  `gwas_variant_prioritization` 4%).

Arms: **(1)** original config; **(2)** R1+R2+R4+R5 (compaction and bounding);
**(3)** arm 2 + R3 (explicit soft/hard budgets). Accept the least invasive arm
that removes the overflow without moving reward on the controls.

**Estimated cost:** 24 runs × 3 arms = 72 trajectories. At the pilot's measured
468 s per completed trajectory on one TP2 replica at concurrency 8, ≈ 1.2–1.5
node-hours. This is below the 2-node-hour threshold, but it is the first GPU
spend of Phase 1.5, so it is presented for approval rather than launched.

---

## 10. Ablation result and decision — 2026-08-01

All 72 trajectories complete (24/24 each arm). Produced by
`scripts/analyze_ablation.py`; raw output at
`<output_root>/_abl_job/ablation_analysis_output.txt`.

### 10a. Primary outcome — does either arm fix the target failure?

| arm | completed | failed | runs w/ runaway | total runaways | median peak input | max peak input |
| --- | --- | --- | --- | --- | --- | --- |
| arm1 control (unguarded) | 19/24 | 5 | 5/24 | 15 | 19,872 | 52,701 |
| arm2 bounding only (R1,R2,R4,R5) | 22/24 | 2 | 5/24 | 10 | 15,652 | 35,197 |
| arm3 bounding + budgets (+R3) | 23/24 | 1 | 4/24 | 5 | 21,650 | 35,322 |

Both arms cut failures roughly in half-to-quarter and eliminate multi-thousand
runaway generations. Arm 3 is marginally better on this axis alone (1 failure vs
2), consistent with the 6-run validation.

### 10b. The decision axis — the control strata

Per the pre-stated rule, an arm that fixes `overflow_prone` by degrading the
controls has not passed. Mean official reward by stratum (n=6 each):

| stratum | arm1 | arm2 | arm3 |
| --- | --- | --- | --- |
| `overflow_prone` (target) | 0.333 | 0.333 | **0.667** |
| `same_family_control` | 0.167 | **0.333** | **0.000** |
| `short_easy_control` | 0.667 | 0.500 | **0.000** |
| `gwas_control` | 0.667 | **0.833** | 0.667 |
| **pooled control delta vs arm1** | — | **+0.056** | **−0.278** |

Arm 3 wins the target stratum outright — 0/6 failed (vs arm2's 1/6) and reward
doubles. But on `same_family_control` and `short_easy_control`, arm3's reward
collapses to **0.000**, including on `short_easy_control` where it still parsed
5/6 answers — it answered, and was wrong every time. That is consistent with the
2,048-token cap (R1) and hard budget (R3) forcing premature synthesis on tasks
that did not need saving. Arm 2 shows no such collapse; its pooled control delta
is *positive*.

**`budget_terminated_hard_budget` fired once** in the full run (it never fired
in the 6-run validation), on an already-borderline case — not enough on its own
to explain the reward collapse, which is spread across multiple instances in
both affected control strata.

### 10c. Cost

| arm | total wall (h) | median wall (s) | total output tokens |
| --- | --- | --- | --- |
| arm1 | 3.74 | 356 | 365,763 |
| arm2 | 2.23 | 268 | 208,996 |
| arm3 | 3.19 | 385 | 195,433 |

Arm 2 is also the cheapest of the three, despite fixing most of the failures.

### 10d. Decision

**Adopt Arm 2** (`max_tokens: 2048`, truncate-and-nudge on `finish_reason ==
"length"`, retrieval cap, observation cap — R1, R2, R4, R5). **Reject Arm 3's
soft/hard token budgets (R3)** for Phase 2: it fully solves the target failure
but fails the pre-stated "does not harm the controls" bar, and by a large
margin. This reverses the tentative reading in `PROJECT_STATUS.md` after the
6-run validation, where the hard budget never fired and arm 2 was flagged as
*possibly* sufficient — the full ablation confirms it, with the added finding
that arm 3 is actively worse where it wasn't needed.

**Caveat, stated plainly:** n=6 per stratum. A control stratum's mean moves by
0.167 for every single instance that flips. The *direction* — arm3 regressing
controls that arm2 does not — is large and consistent enough across two
independent strata to act on; the exact magnitudes (0.278 pooled delta) should
not be treated as precise, and would benefit from a larger confirmatory run if
Phase 2 stakes rise.

### 10e. A bug found while producing this result

`scripts/analyze_ablation.py` originally read `reward` from each run's raw
`metadata.json`. That field does not exist there: reward is computed only by
`cli aggregate`, against ground truth, into `results/tables/trajectories.csv` —
deliberately, so the execution process never has ground truth in scope (see
`DECISIONS.md`). Every reward cell was silently `nan` and §10b above was
uninterpretable until fixed by joining reward in from the aggregated table by
`run_id`. The script has no test coverage of its own (it is a one-off analysis
script outside `src/biomni_uncertainty/`, unlike the package's aggregation
logic, which is tested) — a gap worth closing before this script is relied on
again.
