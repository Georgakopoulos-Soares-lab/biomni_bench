# Phase 1, repaired — pooled headline numbers

**Written:** 2026-08-02. **Not a replacement for `reports/phase1_report.md`**,
which stays frozen as the observed-completion record of what actually ran on
2026-08-01. This document reports the **intention-to-evaluate** estimate: the
same 250-slot design, with the 42 successfully repaired trajectories
(`phase1_5`) pooled in for the slots that originally failed. See
`reports/phase1_completion_bias_analysis.md` for the three-estimator framework
and the full derivation; this document states results only.

**Experiment:** `phase1_pooled` (analysis-only; no new agent runs of its own —
built by `scripts/pool_and_analyze_phase1_5.py` from `phase1` + `phase1_5`).
**Neither `phase1` nor `phase1_5` was modified.**
**Pooled spec manifest:** `manifests/phase1_pooled_runs.jsonl`.

---

## 1. Executive summary

Repairing the 62 originally-failed trajectories and pooling the 42 rescues into
the planned 250-slot design raises completion from 188/250 (75.2%) to 230/250
(**92.0%**). Every headline claim from the observed-completion report survives,
at smaller and more honest magnitudes:

| quantity | observed-completion | intention-to-evaluate (pooled) |
| --- | ---: | ---: |
| First-trajectory reward | 0.420 | 0.480 |
| Plurality reward | 0.580 [0.44, 0.70] | 0.620 [0.48, 0.76] |
| Oracle@4 (upper bound) | 0.620 [0.48, 0.74] | 0.640 [0.50, 0.76] |
| **Oracle headroom** | 20.0 pp (34.5% rel.) | **16.0 pp (30.8% rel.)** |
| Plurality − first (paired) | +0.16 [+0.06, +0.26] | +0.14 [+0.04, +0.26] |
| Agreement-fraction AUROC | 0.874 [0.80, 0.94] | 0.815 [0.71, 0.91] |
| Confidence AUROC | 0.789 [0.69, 0.87] | 0.749 [0.66, 0.83] |
| Confidence overconfidence gap | 0.37 | **0.43 (worse)** |
| Confidence Brier / ECE | 0.367 / 0.370 | 0.424 / 0.430 (both worse) |

**Two results are not a simple "shrink toward null":**

1. **Calibration got measurably worse**, not better. The 42 rescued
   trajectories are disproportionately the hard cases (mean reward 0.357); if
   the model stayed confidently wrong on them, calibration necessarily
   degrades. It did.
2. **Length/effort signals, previously the most suspect claim in the pilot
   (`phase2_entry_assessment.md` §3, "partly circular"), weakened
   substantially** once repaired: `total_output_tokens`' flipped-AUROC fell
   from 0.79 to 0.66. Most of the apparent "longer trajectories fail more"
   signal was the overflow failure itself, not a generalizable property of
   effort.

**Go/No-Go: GO stands.** All three pre-registered stop conditions
(oracle headroom, plurality gain, usable signal) remain clear with real margin.
Formal entry-condition (E1–E6) adjudication: `reports/phase2_entry_assessment.md`
§8.

---

## 2. Scope and what changed from the frozen report

Same benchmark, same 50 instances, same manifest hash. What differs:

* 42 of 250 trajectory slots use a **repaired** run (`configs/phase1_5.yaml`:
  `max_tokens` 2048, runaway truncate-and-nudge, retrieval/observation caps —
  the ablation-selected Arm 2) instead of the original Phase-1 configuration
  (`max_tokens` 8192, no guards).
* 20 of 250 slots remain failed — the repair was attempted on them
  (`phase1_5`) and did not succeed; they keep their original Phase-1 failure
  state (`model_context_overflow`).
* The other 188 of 250 slots are exactly the 188 that completed under Phase
  1's original configuration — they were never targeted by `phase1_5` and are
  unchanged. `phase1_5` targeted only the 62 `model_context_overflow`/
  `missing_run` failures (`reports/context_overflow_forensics.md` §7); the 25
  `confidence_parse_failure`/`agent_parse_failure` cases were never in scope,
  since those are agent-output problems, not the serving failure being
  repaired, and remain exactly as recorded in `phase1_report.md`.

This is **not** a re-run of the whole pilot under repaired settings — that
would confound "did the repair fix the target failure" with "does a different
sampling temperature/config change everything," which is exactly what the
ablation's control strata were designed to rule out separately
(`context_overflow_forensics.md` §10b). Mixing two configurations within one
pooled table is intentional and is the reason `condition`/config provenance is
preserved per-trajectory in `manifests/phase1_pooled_runs.jsonl`.

---

## 3. Completion

| | observed-completion | pooled |
| --- | ---: | ---: |
| Trajectories completed | 188/250 (75.2%) | **230/250 (92.0%)** |
| Instances with full K=4 | 19/50 (38%) | **40/50 (80%)** |
| Instances with 0 completions | 1 | 0 |
| Instances with ≤1 completion | 6 (12%) | 1 (2%) |

Full per-task breakdown and the completion-bias correlation before/after:
`reports/phase1_completion_bias_analysis.md` §2, §4.

---

## 4. Oracle@K and candidate-generation headroom (RQ1)

| K | oracle (all-subsets), observed | oracle, pooled |
| --- | ---: | ---: |
| 1 | 0.425 | 0.480 |
| 2 | 0.547 | ~0.58 (see `oracle_at_k.csv`) |
| 3 | 0.595 | see table |
| 4 | 0.620 | 0.640 |

Diminishing returns remain steep — the qualitative shape that motivates a
sequential (not fixed-K=4) controller is unchanged. Exact pooled K=1..4 values:
`<output_root>/phase1_pooled/results/tables/oracle_at_k.csv`.

Oracle headroom: **16.0 pp**, relative error reduction **30.8%** — both still
comfortably clear the pre-registered go-thresholds (5 pp / ~15%).

---

## 5. Self-consistency (RQ2)

Plurality (0.620) beats first-trajectory (0.480) by **+0.14**, 95% CI
`[+0.04, +0.26]` — excludes zero, same conclusion as the observed-completion
report, smaller point estimate. `agreement_fraction` remains the single
strongest trajectory-level signal measured, AUROC **0.815** `[0.71, 0.91]`,
ahead of verbalized confidence (0.749) and every behavioural signal (§7).

---

## 6. Confidence calibration (RQ3) — the one result that moved the wrong way

| | observed-completion (n=117 valid) | pooled (n=146 valid) |
| --- | ---: | ---: |
| Mean stated confidence | 0.96 | see `calibration__reliability.csv` |
| Accuracy among parseable | 0.59 | — |
| **Overconfidence gap** | 0.37 | **0.43** |
| Brier | 0.367 | 0.424 |
| ECE (5 bins) | 0.370 | 0.430 |
| AUROC | 0.789 [0.69, 0.87] | 0.749 [0.66, 0.83] |
| Confidence parse rate | 117/200 (58.5%) | 146/200 (73.0%) |

Confidence *ranks* trajectories about as well as before (AUROC still clears
0.65 with margin) but is **worse calibrated** in the pooled data. This is a
real finding, not an artifact of the pooling mechanics: it is consistent with
the rescued trajectories being disproportionately hard (§1) — if the model's
stated confidence does not adapt downward on genuinely harder problems, adding
more hard-but-confident cases mechanically widens the gap. Any Phase-2
controller that uses raw stated confidence as a probability, rather than only
as a rank, inherits this — recalibration remains a prerequisite, more clearly
so than the observed-completion report suggested.

---

## 7. Behavioural-signal analysis (RQ4) — length/effort signals were largely an artifact

| signal | observed-completion AUROC (flipped) | pooled AUROC (flipped) |
| --- | ---: | ---: |
| `total_output_tokens` | 0.214 (0.786) | 0.342 (0.658) |
| `wall_time_seconds` | 0.233 (0.767) | 0.366 (0.634) |
| `llm_call_count` | not reported | 0.311 (**0.689**) |
| `tool_call_count` | 0.412 (0.588) | 0.388 (0.612) |
| `failed_tool_call_count` | 0.360 (0.640) | 0.374 (0.626) |
| `visible_plan_step_count` | 0.637 (positive direction) | 0.443 (near-chance, sign-flipped) |

Every length/effort signal weakened after repair. `total_output_tokens` and
`wall_time_seconds` — the two strongest length signals in the observed-
completion report — dropped from a flipped-AUROC around 0.77–0.79 to 0.63–0.66,
confirming the concern raised in `phase2_entry_assessment.md` §3 that these were
"partly circular": overflowed trajectories were both very long (by definition —
they ran until the endpoint terminated them) and always scored 0, so length
predicted failure largely because length **was** the failure signature. With
that mechanism repaired, length is at best weakly informative.

`llm_call_count` (flipped 0.689) is now the only length/effort signal that
still clears the 0.65 usable-signal bar. `visible_plan_step_count` — the one
positive-direction behavioural signal in the observed-completion report
(0.637) — is now essentially uninformative (0.443, direction flipped). Neither
should be used in a Phase-2 controller without independent re-validation on a
larger sample; both moved enough between the two estimates that a single
50-instance pilot cannot be trusted to have located their true value.

---

## 8. Task-level heterogeneity (RQ6)

Reward by task, pooled (also in `reports/phase1_completion_bias_analysis.md`
§4):

| task | completion | mean reward |
| --- | ---: | ---: |
| gwas_variant_prioritization | 100% | 0.85 |
| gwas_causal_gene_opentargets | 100% | 0.75 |
| gwas_causal_gene_pharmaprojects | 100% | 0.55 |
| lab_bench_seqqa | 90% | 0.55 |
| gwas_causal_gene_gwas_catalog | 100% | 0.50 |
| lab_bench_dbqa | 85% | 0.50 |
| patient_gene_detection | 90% | 0.35 |
| crispr_delivery | 100% | 0.30 |
| rare_disease_diagnosis | **65%** | **0.25** |
| screen_gene_retrieval | 95% | 0.25 |

`rare_disease_diagnosis` is now unambiguously both the lowest-completing and
lowest-reward task, and the repair barely moved its completion rate — this is
the clearest single task-level takeaway from the whole repair exercise. See
`context_overflow_forensics.md` and the residual-limitation note in
`PROJECT_STATUS.md`.

---

## 9. Prompt perturbation (RQ7) — unchanged conclusion

| | observed-completion | pooled |
| --- | ---: | ---: |
| Paired instances | fewer (dropout-limited) | **50/50** |
| Reward difference (B − A) | +0.06 [−0.10, +0.22] | **+0.06 [−0.10, +0.22]** |
| Answer-change rate | 0.54 | 0.50 |
| Completion rate, standard | 0.80 | 0.90 |
| Completion rate, instrumented | 0.76 | 0.92 |

Identical conclusion, now on the full pooled sample: no significant effect of
the confidence-elicitation prompt on task reward. Completion rates for both
conditions rose by comparable amounts (confidence elicitation did not make the
repair less effective), consistent with the failure being context-driven and
condition-independent (`phase2_entry_assessment.md` §3).

---

## 10. Selector comparison (RQ5)

`plurality`, `srlm_style` and `rank_combination` remain tied at 0.620 in the
pooled data, exactly as in the observed-completion report — restricting to the
plurality cluster before applying confidence or length still reproduces plain
plurality at this sample size. No selector beats plurality; none should be
presented as doing so until a larger sample separates them.

---

## 11. Limitations specific to this pooled report

1. **This is a mixed-configuration pool**, not a clean re-run. 42/250 slots
   used a different serving configuration than the other 208. The ablation's
   control strata (`context_overflow_forensics.md` §10b) are the evidence that
   this substitution does not itself bias reward on healthy trajectories; this
   report inherits that evidence rather than re-establishing it.
2. **`rare_disease_diagnosis` remains under-observed** (65% complete). Every
   pooled statistic that includes it is still a mild upper bound relative to
   its true difficulty. See §8.
3. **This is still a 50-instance pilot.** Per-task cells hold 5 instances;
   nothing here supports a claim beyond directional evidence.
4. **The learned (exploratory) selector was not re-run** on the pooled data in
   this pass — deferred, not blocking, since it was already labelled
   exploratory and was not part of the primary go/no-go criteria.

---

## 12. Reproduction

```bash
python scripts/pool_and_analyze_phase1_5.py \
    --phase1-run-manifest manifests/phase1_runs.jsonl \
    --phase1-5-run-manifest manifests/phase1_5_runs.jsonl \
    --original-map manifests/phase1_5_runs.original_map.json \
    --config configs/phase1.yaml \
    --ground-truth manifests/phase1.groundtruth.jsonl \
    --output-experiment phase1_pooled
```

Artifacts: `<output_root>/phase1_pooled/results/tables/*.{parquet,csv}`,
`results/figures/*.png` (same 13-figure set as Phase 1, regenerated on pooled
data), `results/analysis.json`.
