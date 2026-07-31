# Phase 1 — Frozen protocol

**Frozen:** 2026-07-31, **before** any pilot trajectory was generated.
This document is a pre-registration. Anything changed after results are seen must
be recorded here **as a change**, with a date and a reason — not edited away.

---

## 1. Frozen artifacts

| artifact | value |
| --- | --- |
| benchmark | `biomni/Eval1` → `biomni_eval1_dataset.parquet` |
| dataset fingerprint | `287304c649b14166cce227a9f13239f1…` |
| instance manifest | `manifests/phase1.jsonl` |
| **manifest hash** | `44854f87b3a0d2e0c00bf4fe06c8879e5636b8a470b8803a5b3e6a2db850fff9` |
| ground truth (separate, never given to the agent) | `manifests/phase1.groundtruth.jsonl` |
| run manifest | `manifests/phase1_runs.jsonl` |
| **run manifest hash** | `894aeb948a27becdbd1e0d11210954cef59fb604345cc014e5f9c33b9ddad606` |
| experiment config | `configs/phase1.yaml` |
| Biomni commit | `400c1f366b96a35ca253e13c9b06c5076af41d65` (v0.0.8) |
| model | `biomni/Biomni-R0-32B-Preview` @ `71432eb3d5e583bee757e0f9437a17e711e8e3d1` |

### Sampling procedure (exact)

1. Restrict to `split == "val"` — **the only split in this release**; there is no
   held-out split (`DECISIONS.md` D-02).
2. For each task in alphabetical order, order its instances by
   `sha256(manifest_seed | task_name | task_instance_id)` and take the first 5.
   The key is a hash of the triple, so a task's selection does not depend on
   which other tasks are present.
3. Manifest seed: **20260731**.
4. No redistribution was needed — all 10 tasks have ≥5 instances.
5. **No exclusions.** No model output and no correctness information was used at
   any point in selection.

### Composition

50 instances, exactly 5 per task, across all 10 tasks:
`crispr_delivery`, `gwas_causal_gene_gwas_catalog`, `gwas_causal_gene_opentargets`,
`gwas_causal_gene_pharmaprojects`, `gwas_variant_prioritization`, `lab_bench_dbqa`,
`lab_bench_seqqa`, `patient_gene_detection`, `rare_disease_diagnosis`,
`screen_gene_retrieval`.

Prompt length (chars): min 261, p25 337, median 391, p75 730, max 4680, mean 718.

`hle` is supported by the official evaluator but has **zero instances** in this
release, so it cannot appear.

---

## 2. Conditions

| | Condition A — standard | Condition B — instrumented |
| --- | --- | --- |
| trajectories per instance | 1 | 4 |
| confidence request | none | final-only, inside `<solution>` |
| task prompt | identical | **byte-identical** (elicitation goes in the system prompt) |
| model / temperature / tools / limits | identical | identical |
| total runs | 50 | 200 |

**Total: 250 trajectories.**

Fixed sampling settings for every run:

| setting | value | source |
| --- | --- | --- |
| temperature | **0.7** | Biomni's own default (`biomni.config.BiomniConfig`). The Biomni-R0 model card recommends no other value. |
| `max_tokens` | 8192 | Biomni's own default for custom endpoints |
| context length | 65536 | see §6 |
| requested seeds | 1000+idx (A), 1100+idx (B) | recorded |
| **seed actually honoured** | **NO** | probed against the live endpoint: two identical `seed=12345` requests at temperature 1.0 produced different text. Stored per run as `seed_supported: false`. **Sampling is stochastic and not explicitly seeded.** |

### Confidence elicitation

Requested via a system-prompt suffix (so the benchmark prompt is unchanged), and
emitted **inside** the `<solution>` block because Biomni stops generation at
`</solution>`:

```
<solution>
<task answer in the exact format the task requires>
<BIOMNI_CONFIDENCE>
{"confidence": 73.25}
</BIOMNI_CONFIDENCE>
</solution>
```

Extraction order is fixed: strip the confidence block → extract `<solution>` →
parse the task answer → evaluate only the task answer. Confidence must be
numeric, finite, in [0, 100], and is normalized to [0, 1]. Parse failures are
recorded by status and **never** replaced with a default in the primary analysis.

**Per-step confidence is not collected.** The reason is architectural, not an
omission (`DECISIONS.md` D-08).

---

## 3. Primary metrics (pre-specified)

Unit of analysis is the **task instance**. All intervals are 95% percentile
bootstrap over instances, 2,000 replicates, seed 20260731.

1. First-trajectory reward (instrumented, index 0)
2. Standard-condition reward (Condition A)
3. Plurality reward
4. SRLM-style selector reward
5. Rank-combination selector reward
6. Oracle@4 reward
7. **Oracle headroom** = Oracle@4 − first-trajectory
8. Confidence Brier score
9. Confidence ECE (5 equal-width bins)
10. AUROC of confidence for trajectory correctness
11. Association: plurality fraction ↔ correctness
12. Association: trace length ↔ correctness

Secondary/reported: AUPRC, clipped NLL, reliability diagram with counts, accuracy
at confidence thresholds, selective accuracy/coverage curve, failure rate,
confidence parse rate, per-task results, results split by presence of a tool
failure, results split by consensus size.

Every BiomniEval1 task returns exactly 0.0 or 1.0, so the binary correctness
variable equals the official reward. The threshold (0.5) exists only so the
analysis keeps working if a partially-graded task is added.

**Primary length field:** `total_output_tokens`.

---

## 4. Selectors (pre-specified)

`first`, `random_expected` (+ a sampled baseline via 200 deterministic
resamples), `plurality`, `max_confidence`, `min_length`,
`plurality_then_confidence`, `plurality_then_shortest`, `srlm_style`,
`rank_combination`, `oracle`.

* Tie-breaking is deterministic everywhere: lowest trajectory index. Ties are
  reported, never hidden.
* Trajectories with no parseable answer are **singleton** clusters, so unrelated
  failures cannot manufacture consensus (`DECISIONS.md` D-11).
* `srlm_style` = `argmax over the plurality cluster of log(clamp(conf, ε, 1)) · length`,
  ε = 1e-3. Labelled **"SRLM-style final-confidence approximation"** throughout;
  it is not a reproduction of step-level SRLM.
* `oracle` reads ground truth. It is an **upper bound**, never a method.
* A small L2 logistic regression with `GroupKFold` on the instance is included and
  labelled **exploratory**.

Only `oracle` may read the reward. There is a test asserting that permuting
rewards changes no other selector's choice.

---

## 5. Analysis plan

* Resampling unit: **task instance**. Trajectory-level association analyses use a
  cluster bootstrap over instances; the learned selector uses `GroupKFold`.
* Paired bootstrap for selector differences, over the same instances.
* Oracle@K for K = 1…4, reported **both** as the mean over all size-K subsets
  (primary) and over first-K prefixes, each labelled.
* Calibration: Brier, ECE with 5 equal-width bins, reliability plot with per-bin
  counts. Equal-frequency binning is reported as exploratory only.
* Prompt perturbation: Condition A vs instrumented trajectory 0, on the same
  instances — paired reward difference, answer-change rate, confidence parse
  rate, and changes in output tokens, tool calls, LLM calls and wall time.
* p-values from the bootstrap are descriptive only. A 50-instance pilot cannot
  support inference from them.
* Confirmatory (this document) and exploratory analyses are reported separately.

---

## 6. Experimental parameters that are NOT defaults

Recorded here so they cannot be mistaken for stock settings.

1. **`--dtype bfloat16`.** The weights ship in FP32 (131 GB). Without this,
   SGLang follows `config.json` and allocates FP32 (`DECISIONS.md` D-03).
2. **Context length 65,536** with the model card's YaRN override at `factor = 1.0`.
   Measurement (before any GPU time) showed Biomni's own system prompt is 43,891
   tokens pre-retrieval and 17k–41k post-retrieval, against a native 40,960
   ceiling. `factor = 1.0` makes YaRN the identity on the RoPE frequencies, so
   short-trajectory behaviour is unchanged; the override only lifts the position
   ceiling. Positions above 40,960 are nevertheless reached by extrapolation.
   `finish_reason` is captured per LLM call so truncation surfaces in the results
   (`DECISIONS.md` D-04).

---

## 7. Sample size and power

50 instances; 200 instrumented + 50 standard trajectories. This is a **pilot**.
A difference of one instance moves an instance-level rate by 2 percentage points,
and per-task cells hold 5 instances. Confidence intervals will be wide and
per-task numbers are descriptive only. Nothing here supports a strong claim.

---

## 8. Go / no-go criteria (pre-specified, not significance gates)

**Proceed to Phase 2** if at least one holds:

* **A. Oracle headroom** — Oracle@4 exceeds first-trajectory by ≥5 percentage
  points, or relative error-reduction potential ≥ ~15%.
* **B. Useful signal** — some signal reaches trajectory-level AUROC ≈ 0.65+ with
  reasonable uncertainty, or a pre-specified selector improves practically
  meaningfully over both first-run and plurality.
* **C. Failure detection** — signals reliably flag tool failures, malformed
  workflows or confidently-wrong outputs, even without an accuracy gain.
* **D. Task-specific effect** — a signal works clearly on an important subset.

**Redesign or stop** if: oracle headroom is negligible; trajectories usually
repeat the same wrong answer; confidence is severely miscalibrated *and*
non-predictive; telemetry is too incomplete to interpret; elicitation materially
damages performance; or **infrastructure failures dominate biological reasoning
failures**.

The report must separate failure of candidate generation, failure of trajectory
selection, failure of uncertainty estimation, and infrastructure failure.

---

## 9. Known limitations, stated in advance

1. **50 instances.** A pilot, not an evaluation.
2. **One agent, one model.** No claim of transfer.
3. **Final-answer correctness only.** A correct answer reached through an invalid
   workflow scores identically to a sound one. Workflow validity is not assessed.
4. **Final-only confidence** (D-08).
5. **Seeds are requested but not honoured** by the endpoint. Trajectories are
   independent samples, not reproducible ones.
6. **A lightweight tool environment.** The full Biomni E1 environment (>10 h,
   >30 GB) was not installed. The commonly-imported dependencies were added after
   the smoke test exposed them, but residual tool failures will occur; they are
   counted, reported, and are a pre-specified stop criterion.
7. **Live external databases.** Biomni tools query live resources, so a result can
   depend on when it ran. Recorded separately from LLM usage.
8. **Context extrapolation** above 40,960 positions (§6).
9. **`patient_gene_detection` scores any set intersection**, so a large predicted
   gene set inflates reward. `n_predicted` is retained and this is reported, not
   exploited.
10. **rsID normalization.** The official evaluator is case-sensitive for variants;
    we normalize the `rs` prefix and report `strict_reward` alongside `reward` so
    the credit granted by normalization is measurable (`DECISIONS.md` D-10).

---

## 10. Deviations log

*(append below; do not edit entries)*

| date | change | reason |
| --- | --- | --- |
| — | none yet | — |
