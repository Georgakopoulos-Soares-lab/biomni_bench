# Phase-1 completion bias: what it was, how large, and what repair recovered

**Written:** 2026-08-02, after the phase1_5 repair re-run and the pooled
reanalysis. Companion to `reports/context_overflow_forensics.md` (diagnosis and
repair mechanism) and `reports/phase1_repaired_report.md` (the repaired
headline numbers). This document is specifically about the **bias**, not the
repair or the results — it exists to answer one question precisely: *how much
should the original Phase-1 numbers have been distrusted, and by how much did
repairing the data change that?*

---

## 1. The problem, stated precisely

Phase 1 planned 250 trajectories and completed 188 (75.2%). The missing 62 were
not a random 25% — completion correlated with reward across tasks
(`corr = +0.543`, `reports/phase2_entry_assessment.md` §3). Every headline
number in `phase1_report.md` was therefore computed over a **non-random
subsample enriched for cases the agent found easy**, which biases every
completion-conditioned statistic in a direction that is knowable in sign but
not, without repair, in size.

Three distinct estimators are used below, and this document keeps them
explicitly separate — conflating them is the single easiest way to overstate or
understate what happened:

| estimator | what it computes | data used |
| --- | --- | --- |
| **Observed-completion** | Phase 1's original numbers, as reported | the 188 trajectories that happened to complete |
| **Intention-to-evaluate** | what the planned 250-trajectory experiment would have shown had every run produced an answer | pooled: 188 original + 42 phase1_5 rescues = 230/250 |
| **Matched-paired** | for the 62 originally-failed slots specifically, before vs. after the repair | phase1 (failed) vs phase1_5 (repaired attempt), same slot |

---

## 2. Observed-completion: the bias, quantified

Per-task, instrumented condition, from `phase1/results/tables/instrumented.parquet`
(reproduced from `phase2_entry_assessment.md` §3 for convenience):

| task | completed/20 | completion rate | mean reward (completed only) |
| --- | ---: | ---: | ---: |
| crispr_delivery | 11 | 0.55 | 0.182 |
| patient_gene_detection | 11 | 0.55 | 0.545 |
| rare_disease_diagnosis | 11 | 0.55 | 0.273 |
| lab_bench_seqqa | 12 | 0.60 | 0.833 |
| gwas_causal_gene_pharmaprojects | 14 | 0.70 | 0.571 |
| screen_gene_retrieval | 15 | 0.75 | 0.267 |
| lab_bench_dbqa | 17 | 0.85 | 0.588 |
| gwas_causal_gene_gwas_catalog | 18 | 0.90 | 0.556 |
| gwas_variant_prioritization | 19 | 0.95 | 0.895 |
| gwas_causal_gene_opentargets | 20 | 1.00 | 0.750 |

`corr(completion_rate, mean_reward | completed) = +0.543`. Tasks where the
agent struggled were also the tasks most likely to lose data, which pushes the
observed-completion aggregate reward **upward** relative to the true value —
the opposite direction from what a naive "missing data just adds noise"
assumption would suggest.

**Per-instance**, only 19 of 50 instances (38%) had the full K=4 trajectories
Phase 1 was designed around:

| trajectories completed | instances | first | plurality | oracle |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 0.000 | 0.000 | 0.000 |
| 1 | 5 | 0.200 | 0.200 | 0.200 |
| 2 | 8 | 0.375 | 0.500 | 0.625 |
| 3 | 17 | 0.294 | 0.588 | 0.647 |
| 4 | 19 | 0.632 | 0.737 | 0.737 |

At n_completed ≤ 1, `plurality` and `oracle` are mechanically equal to `first`
— 12% of the sample contributed structurally null evidence to the two central
claims (self-consistency helps; oracle headroom exists) before repair.

---

## 3. Matched-paired: what the repair did to the 62 failed slots specifically

This is the cleanest possible before/after comparison, because "before" is not
noisy data — it is a **guaranteed non-answer** (Phase 1's failure produced no
scoreable output at all). The question is simply: of the 62 slots that
contributed nothing, how many now contribute something, and what does that
something look like?

**42/62 (67.7%) now produce a scored answer.** Mean reward among the 42:
**0.357** (15 correct, 27 wrong) — below the pooled overall mean (0.480),
consistent with this being specifically the hardest-case pool, not a random
sample of the benchmark.

**20/62 (32.3%) still fail**, but the failure mode itself changed:

| | Phase 1 (original) | phase1_5 (repaired attempt) |
| --- | --- | --- |
| failure mechanism | open-ended degeneration, 8,192-token generations appended to context, unbounded | `budget_terminated_consecutive_runaway` — bounded, terminated after 3 consecutive degenerations |
| observable to a controller | no (an endpoint exception destroys the trajectory) | yes (a controlled terminal state) |

Rescue rate by task (from `PROJECT_STATUS.md`, reproduced here as the primary
evidence for the paired comparison):

| task | rescued/attempted |
| --- | --- |
| crispr_delivery | 11/11 (100%) |
| gwas_causal_gene_pharmaprojects | 6/6 (100%) |
| gwas_causal_gene_gwas_catalog | 2/2 (100%) |
| gwas_variant_prioritization | 1/1 (100%) |
| screen_gene_retrieval | 5/6 (83%) |
| patient_gene_detection | 8/11 (73%) |
| lab_bench_seqqa | 6/9 (67%) |
| rare_disease_diagnosis | **3/13 (23%)** |
| lab_bench_dbqa | **0/3 (0%)** |

The matched-paired view is what makes `rare_disease_diagnosis`'s residual
problem legible: this is not "the task is hard" in the way `crispr_delivery`
apparently also was (100% rescued despite a 0.182 observed-completion reward)
— it is specifically resistant to the repair mechanism itself. See §5.

---

## 4. Intention-to-evaluate: the pooled estimate

Pooling the 42 rescues into the original 250-slot design
(`scripts/pool_and_analyze_phase1_5.py`) raises completion from 188/250 (75.2%)
to 230/250 (92.0%) and instances with full K=4 from 19/50 (38%) to 40/50 (80%).

| task | completed/20 (pooled) | completion rate | mean reward |
| --- | ---: | ---: | ---: |
| rare_disease_diagnosis | 13 | 0.65 | 0.25 |
| lab_bench_dbqa | 17 | 0.85 | 0.50 |
| patient_gene_detection | 18 | 0.90 | 0.35 |
| lab_bench_seqqa | 18 | 0.90 | 0.55 |
| screen_gene_retrieval | 19 | 0.95 | 0.25 |
| gwas_causal_gene_opentargets | 20 | 1.00 | 0.75 |
| gwas_causal_gene_pharmaprojects | 20 | 1.00 | 0.55 |
| crispr_delivery | 20 | 1.00 | 0.30 |
| gwas_variant_prioritization | 20 | 1.00 | 0.85 |
| gwas_causal_gene_gwas_catalog | 20 | 1.00 | 0.50 |

`corr(completion_rate, mean_reward) = +0.483` — down from +0.543 but **not
eliminated**. `rare_disease_diagnosis` remains both the lowest-completing and
lowest-reward task; the bias shrank, it did not disappear, because the repair
did not fully resolve that task's failure mode (§3).

Headline claims, observed-completion vs. intention-to-evaluate:

| claim | observed-completion (n=188) | intention-to-evaluate (n=230) | still holds? |
| --- | --- | --- | --- |
| Oracle headroom | 20.0 pp | 16.0 pp | **yes**, 3.2× the 5pp threshold |
| Plurality beats first | +0.16 [+0.06,+0.26] | +0.14 [+0.04,+0.26] | **yes**, CI excludes 0 |
| Agreement predicts correctness | AUROC 0.874 | AUROC 0.815 [0.71,0.91] | **yes**, well above 0.65 |
| Confidence discriminates | AUROC 0.789 | AUROC 0.749 [0.66,0.83] | **yes** |
| Confidence is calibrated | overconfidence gap 0.37 | overconfidence gap **0.43** | **no — worse**, not better |
| Length/effort predicts correctness | `total_output_tokens` flipped-AUROC 0.79 | flipped-AUROC **0.66** | **weakened substantially** — confirms §4 of `phase2_entry_assessment.md`: this was partly circular |

---

## 5. What remains biased even after pooling

* **`rare_disease_diagnosis`** still completes at 0.65 (vs 1.00 for six other
  tasks) and still has the lowest mean reward (0.25). The pooled estimate for
  this task specifically should be read as **still an upper bound relative to
  its true difficulty** — 7 of its 20 instrumented slots remain genuinely
  unobserved. Every pooled aggregate that includes this task inherits a smaller
  version of the original bias.
* **`lab_bench_dbqa`** is 0/3 rescued, but n=3 is too small to distinguish a
  real resistant subgroup from noise (§3 of `PROJECT_STATUS.md` makes the same
  point).
* **Standard-condition (Condition A) pooling.** 10 of the 62 original failures
  were standard-condition runs; phase1_5 repaired some of those too, so the
  Condition-A-vs-B prompt-perturbation comparison in `phase1_repaired_report.md`
  §7 is itself now on pooled, not raw Phase-1, data — this is intentional and
  documented there, not an oversight.

---

## 6. Conclusion

The completion bias was real, measurable, and directionally exactly as
`phase2_entry_assessment.md` predicted before any repair data existed: it
inflated observed reward on struggling tasks and manufactured null evidence for
~12% of instances. Repairing 42 of 62 slots cut it roughly in half
(`corr` 0.543→0.483) without eliminating it, because the repair mechanism
itself has non-uniform effectiveness — it is very good at some failure
signatures (`crispr_delivery`, both GWAS-catalog tasks: 100%) and largely
ineffective at one (`rare_disease_diagnosis`: 23%).

Every headline claim from Phase 1 survives the correction, at smaller and more
honest magnitudes. The one claim that was flagged as "most exposed" —
agreement's predictive value — dropped the most in absolute terms
(0.874→0.815) but remains far above the usable-signal threshold. The one claim
flagged as "partly circular" — length predicts correctness — is now confirmed
to have been substantially inflated by the failure mode itself: its
flipped-AUROC fell from 0.79 to 0.66 once the runs that manufactured that
correlation were repaired.
