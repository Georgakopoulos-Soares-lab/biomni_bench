# Phase 2A — offline sequential policy replay

**Written:** 2026-08-02. **Experiment:** `phase2a` (analysis-only; **zero new model
calls, zero GPU time**).
**Source data:** `phase1_pooled` instrumented table — 200 trajectories, 50
instances, K=4 (`reports/phase1_repaired_report.md`).
**Artifacts:** `<output_root>/phase2a/results/` — `phase2a_results.json`,
18 tables, 5 figures.

> **Comparing this report to `phase1_repaired_report.md`? Read §1.1 first.**
> Fixed K=4 is 0.577 here and pooled plurality is 0.620 there, on the same data.
> The difference is tie-breaking under a single fixed trajectory order, it is
> reconciled to five decimal places in §1.1, and 0.577 is the correct number for
> a sequential controller.

> **Evidence class: OFFLINE REPLAY. This is not prospective evidence.**
> Every policy below is replayed against trajectories that already existed. No
> policy caused a trajectory to be generated, so nothing here measures what a
> controller would do to a live agent. Its purpose is to select **at most two**
> candidate policies for the frozen prospective test in Phase 2B, and to kill the
> ones that do not deserve GPU time.

---

## 1. Executive summary

**The headline result is a cost result, not an accuracy result — and that is the
result the north star asked for.**

| policy | reward | 95% CI | mean K | model tokens | tool calls |
| --- | ---: | --- | ---: | ---: | ---: |
| fixed K=1 | 0.485 | [0.370, 0.600] | 1.00 | 181,603 | 2.42 |
| fixed K=2 plurality | 0.525 | [0.403, 0.643] | 2.00 | 363,207 | 4.84 |
| fixed K=3 plurality | 0.555 | [0.427, 0.678] | 3.00 | 544,810 | 7.26 |
| **fixed K=4 plurality** *(principal baseline)* | **0.577** | [0.440, 0.707] | 4.00 | 726,414 | 9.68 |
| **mandatory K=2, continue to 4 on disagreement** | **0.577** | [0.440, 0.707] | **2.70** | **530,726** | **6.74** |
| K=1 selective (nested threshold) | 0.567 | [0.433, 0.695] | 2.49 | 490,243 | 6.30 |
| failure-only escalation | 0.527 | [0.405, 0.645] | 1.17 | 222,684 | 2.82 |
| *Oracle@4* — **UPPER BOUND, not deployable** | *0.640* | [0.500, 0.780] | 4.00 | 726,414 | 9.68 |

**1. Mandatory K=2 with agreement-based stopping reproduces fixed-K=4 exactly, at
68% of the trajectories.** Paired instance-level bootstrap: reward difference
**0.000, CI [0.000, 0.000]**; mean-K difference **−1.297, CI [−1.483, −1.100]**.
The CI on reward is degenerate because the two policies return the **same answer
on all 50 instances** — not merely the same average. It retains **100% of the
fixed-K=4 gain** over K=1 and captures **59.1%** of the Oracle@4 headroom.

**2. The K=1 acceptance trigger is weak, and the honest answer is to not use it.**
The brief anticipated this outcome and asked for it to be stated plainly if it
occurred. It occurred. Under a properly nested threshold-selection procedure,
**three of five folds selected "never accept after one trajectory."** The policy
that does accept early buys 0.21 fewer trajectories for 1.0 point of reward
(0.567 vs 0.577) — the wrong side of the trade.

**3. Plain fixed K=2 plurality cannot beat K=1, structurally.** With two
trajectories, either they agree (and K=2 returns what K=1 returned) or they tie
(and the tiebreak returns the first). Averaged over all orderings, fixed K=2 is
*mathematically* the K=1 answer plus failure replacement — the +0.040 it does
show comes entirely from replacing failed trajectories, not from voting. **Ties
need a third opinion to break.** This is why "mandatory K=2" must mean *stop
early when two agree*, not *always run two*.

**4. Continuation repairs broken workflows for free.** 12.5% of replays open on a
trajectory that died or produced no parseable answer. Every policy that
continues resolves **100%** of those to a real answer, and **37.3%** to a correct
one. Fixed K=1 recovers 0% by construction.

**5. Abstention has a simple, fold-free, deployable rule.** Abstain when four
trajectories produce four different answers. That state is 14% of replays and is
correct **11.9%** of the time. Abstaining on it alone lifts accuracy from 0.577
to **0.651 at 86% coverage**.

**Recommendation: carry one policy into Phase 2B, not two** — see §11.

---

## 1.1 Reconciliation: why fixed K=4 is 0.577 here and plurality is 0.620 in Phase 1

**Read this before comparing any number in this report to `reports/phase1_repaired_report.md`.**

Phase 1's pooled plurality reward is **0.620**. This report's fixed-K=4 plurality
is **0.577**, on the *same* 50 instances and the *same* 200 trajectories. The
difference is real, intended, and fully accounted for. It is **not** a
denominator, replay, failure-handling or aggregation bug. Reproduce with:

```bash
python scripts/phase2a_reconcile.py \
    --tables   <output_root>/phase1_pooled/results/tables \
    --outcomes <output_root>/phase2a/results/tables/p2a_outcomes.parquet
```

### The single cause: tie-breaking under one fixed trajectory order

Phase 1 scored plurality **once**, in the order the trajectories happened to be
generated (indices 0,1,2,3), breaking ties by lowest trajectory index. Phase 2A
scores every one of the 24 arrival orderings and averages, because a sequential
controller has no privileged order — trajectory "index 0" is just whichever
sample came back first.

Restricting this report's replay to the native ordering `0123` reproduces Phase 1
**exactly**:

| quantity | Phase-1 frozen selector | Phase-2A replay, ordering `0123` | Phase-2A replay, all 24 orderings |
| --- | ---: | ---: | ---: |
| plurality / fixed K=4 | **0.6200** | **0.6200** | 0.5767 |
| first / fixed K=1 | 0.4800 | 0.4800 | 0.4850 |
| Oracle@4 | 0.6400 | 0.6400 | 0.6400 |

Bit-exact agreement on the ordering Phase 1 used is what rules out every
mechanical explanation at once: the same denominator (50 instances, 200
trajectories), the same reward column, the same clustering.

### Which four instances move, and why

Exactly **4 of 50** instances are order-sensitive. All four are **ties**, and in
all four the trajectory sitting at index 0 in Phase 1 carried the correct answer:

| instance | answers (index order) | tie | Phase-1 (index tiebreak) | averaged over orderings |
| --- | --- | --- | ---: | ---: |
| `crispr_delivery/i0028` | e, e, f, f | 2-way split vote | 1.0 | 0.500 |
| `lab_bench_seqqa/i0547` | A, A, B, B | 2-way split vote | 1.0 | 0.500 |
| `rare_disease_diagnosis/i0103` | 108145, 617146, —, — | 4-way, **no consensus at all** | 1.0 | 0.500 |
| `screen_gene_retrieval/i0243` | MAU2, MPP1, —, POLE2 | 4-way, **no consensus at all** | 1.0 | 0.333 |

The arithmetic closes to five decimals:
`(4 − (0.5 + 0.5 + 0.5 + 0.333)) / 50 = 0.04333`, and the observed gap
`0.6200 − 0.5767 = 0.04333`.

### What this means, in both directions

**Phase 1 drew a favourable ordering.** Across the 24 fixed orderings, K=4
plurality ranges from **0.540 to 0.620**, and only **6 of 24** reach 0.620 —
Phase 1 landed on one of the six best. Its tiebreak went 4-for-4 on coin flips.
The frozen report is not wrong; it reports one realization, and it was a lucky
one. **0.577 is the unbiased estimate of what a controller meeting these
instances in arbitrary order would score, and it is the number every comparison
in this report uses.**

**Two of the four are not really "plurality" at all.** In
`rare_disease_diagnosis/i0103` and `screen_gene_retrieval/i0243` every cluster
has size 1 — four trajectories, four different outcomes. "Plurality" there
degenerates into "return the first trajectory": `select_first` wearing a
plurality label. This is precisely the state §9 recommends **abstaining** on, and
seeing it inflate a headline number is a good argument for that rule.

### The other candidate causes, ruled out individually

* **Denominator** — both use 50 instances and 200 trajectories, verified.
* **Replay mechanics** — fixed K=4 consumes all four trajectories in every
  replay; no early stopping is involved, so no stopping rule can be implicated.
* **Failure handling (D-18)** — the new "a non-answer can never win a tie" rule
  changes the *selected answer* on exactly 1 of 50 instances at K=4
  (`rare_disease_diagnosis/i0099`), where all four trajectories score 0, so it
  changes no reward at K=4. It matters at K=2, where it is the entire source of
  fixed-K=2's +0.040 over K=1 (§1, point 3) — not here.
* **Aggregation** — both read the same `instrumented.parquet` and the same
  `reward` column produced by the official evaluator.

### Consequence for Phase 2B

Prospectively there is exactly **one realized arrival order per instance** —
trajectories arrive as they are sampled, and no averaging is possible for the
controller's own run. Since a single ordering can move fixed-K=4 by up to 8
points on 50 instances, the Phase-2B protocol must pre-register both: the
**realized-ordering paired comparison** as primary (it is what actually
happened), and the **ordering-averaged comparison** over the shadow pool as a
pre-specified robustness check. This is carried into
`reports/phase2_protocol.md`.

---

## 2. Method

### 2.1 What a policy is

A policy watches trajectories arrive one at a time and, after each, returns
`ACCEPT`, `CONTINUE`, or `ABSTAIN`. `VERIFY` and `REPAIR` from the Phase-2 action
space are **not** simulable offline (§10.1); the offline analogue of both is
"spend another trajectory", which is what `CONTINUE` means here. That mapping is
stated rather than assumed, because conflating infrastructure retry, workflow
repair and independent verification is exactly the confusion the integrity rules
forbid.

### 2.2 The leakage barrier

The policy only ever receives a `TrajectoryView` (`src/biomni_uncertainty/policy.py`),
a frozen, slotted dataclass with a fixed field list that excludes `reward`,
`correct`, `strict_reward`, `evaluation_status`, `experiment_id` and
`trajectory_index`. Rewards live in a separate mapping on `InstancePool` that no
policy is handed. `trajectory_index` is excluded deliberately: the native index
is not knowable online, and leaving it in would let a policy learn "index 0 ran
first in Phase 1."

This is enforced by test, not by convention — `tests/test_policy.py` asserts that
no forbidden field is reachable from a view, that scorers receive only views,
and that a policy at step k sees exactly the first k arrivals.

### 2.3 Orderings

K=4 has **24 arrival orderings, and all 24 are replayed** for every instance —
exhaustive, not sampled. Every reported statistic is first averaged over the 24
orderings within an instance, so no trajectory-index artifact can survive. This
matters concretely: an instance whose four answers are A, A, B, B is a coin flip
at K=2 depending on arrival order, and only exhaustive averaging turns that into
the correct 0.5.

### 2.4 Answer resolution

Plurality over canonical cluster keys. Unparseable answers are singleton clusters
(D-11), so two unrelated failures never manufacture a consensus. Ties break to
the **earliest arrival**, the only tiebreak available online.

One rule was added here and is a change from the Phase-1 selectors: **a
trajectory that died or produced no parseable answer can never win.** It still
counts against the support fraction, but a real answer beats a non-answer even
when the non-answer arrived first. Without this, an execution failure in slot 1
wins the 1–1 tie against a good analysis in slot 2 and the controller returns
nothing. This is a distinction available online with no ground truth. It was
found by a test that expected failure-only escalation to recover failures and
observed it recovering none (§12).

### 2.5 Cost and statistics

Cost is summed over the trajectories actually consumed: model tokens
(input + output — input dominates, because every tool observation is re-sent),
LLM calls, tool calls, wall time, and K itself.

Resampling unit is the **task instance** (D-13), 10,000 replicates, seed
20260802. Comparisons against a baseline are paired instance-level bootstraps.

---

## 3. K=1 signals, re-measured on the repaired pool

The brief required these to be re-measured rather than inherited, because several
moved materially after the context repair. Two columns are reported: over all 200
trajectories, and **conditional on the trajectory having produced a parseable
answer**. The second is the one that matters — a failed trajectory is caught by
the failure override before any score is consulted, so a signal that works only
by detecting failures is not a signal a controller can use.

| signal | AUROC (all 200) | AUROC (parseable, n=175) |
| --- | ---: | ---: |
| `final_confidence` | 0.749 | **0.779** |
| `total_tokens` (flipped) | 0.706 | 0.672 |
| `total_input_tokens` (flipped) | 0.702 | 0.667 |
| `llm_call_count` (flipped) | 0.689 | 0.659 |
| `code_execution_count` (flipped) | 0.673 | 0.647 |
| `total_output_tokens` (flipped) | 0.658 | 0.598 |
| `wall_time_seconds` (flipped) | 0.634 | 0.586 |
| `visible_plan_step_count` (flipped) | 0.557 | 0.659 |
| `retrieval_count` | 0.500 | 0.500 |

Verbalized confidence is the only K=1 signal that is both directionally sensible
and clears 0.75 among parseable answers. Every effort signal is *inverse* (longer
⇒ more likely wrong) and every one weakens once failures are excluded, which is
the residue of the circularity flagged in `phase2_entry_assessment.md` §3 and
confirmed in `phase1_repaired_report.md` §7. **None of them is used by a primary
policy.** Full table: `p2a_k1_signal_auroc.csv`.

---

## 4. Calibration

Raw verbalized confidence is **never used as a probability** anywhere in Phase 2.
Grouped (`GroupKFold` on the instance, 5 folds) out-of-fold calibration:

| method | role | AUROC within fold | Brier | ECE |
| --- | --- | ---: | ---: | ---: |
| raw verbalized confidence | **not used** — shown to justify calibrating | 0.749 | 0.424 | **0.430** |
| Platt on confidence + missingness indicator | **primary** | 0.700 [0.557, 0.882] | 0.253 | **0.047** |
| isotonic on confidence | secondary / exploratory | 0.700 [0.539, 0.890] | **0.215** | **0.003** |
| logistic on confidence + 3 effort features | secondary / exploratory | 0.732 [0.629, 0.895] | 0.233 | 0.047 |

**Calibration fixes the probabilities; it does not improve the ranking.** ECE
falls from 0.430 to 0.047 (Platt) and 0.003 (isotonic), while AUROC stays at
≈0.70–0.73. That is precisely the north star's "confidence *ranks* but does not
*calibrate*", now quantified out of fold. Missing confidence (27% of
trajectories) is handled by an explicit indicator, never imputed; those
trajectories are 37.0% correct against 52.7% for the rest, and the fitted
indicator coefficient is negative in all five folds.

### 4.1 A methodological trap worth recording

The **pooled** out-of-fold AUROC for the Platt calibrator is **0.515** — near
chance — while the mean **within-fold** AUROC is **0.700**. Both numbers are in
`p2a_k1_calibration.csv`. The pooled number is an artifact, not a finding: each
fold's logistic has its own intercept, so predictions from different folds are
not on a common scale and pooling them scrambles the global ranking. Calibration
metrics (Brier, ECE) are scale-referenced and pool correctly; a *ranking* metric
does not. Reporting only the pooled AUROC here would have produced the false
conclusion "calibrated confidence is worthless." `calibration.within_fold_auroc`
exists for this reason and is regression-tested.

---

## 5. The K=1 acceptance decision — the honest negative

After trajectory 1 there is no agreement signal, and the brief correctly names
this a distinct scientific problem. It was attacked with a **nested** procedure,
because a threshold selected on the same out-of-fold predictions it is applied to
is a tuned parameter wearing an out-of-fold costume:

* **outer fold** — the calibration model is fitted on the outer training
  instances only and applied to the held-out ones;
* **inner grouped CV inside the outer training set** — produces the predictions
  the threshold is selected on.

The acceptance bar is not free either. A K=1 acceptance is only justified if the
accepted population is at least as accurate as mandatory-K=2 would have been on
the same training data. If no threshold clears that bar with at least 10
supporting examples, the procedure returns **"never accept at K=1."**

| fold | mandatory-K=2 train reward | selected threshold | accepts (train) | accepted accuracy |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 0.558 | 0.482 | 97 | 0.567 |
| 1 | 0.588 | 0.578 | 12 | 0.667 |
| 2 | 0.558 | **never accept** | 0 | — |
| 3 | 0.621 | **never accept** | 0 | — |
| 4 | 0.558 | **never accept** | 0 | — |

**Three of five folds refuse to accept after one trajectory.** Where acceptance
does fire, it barely clears its own bar (fold 0: 0.567 accepted accuracy against
a 0.558 target — one instance's worth of margin). The resulting policy accepts at
K=1 on 14% of replays and **loses 1.0 reward point** relative to never doing so.

There is a tempting result underneath this that does **not** survive: among
trajectories with a parseable answer, those stating confidence exactly 1.00 are
correct 26 of 27 times (96.3%), and ≥0.98 are correct 85.2% of 61. That looks
like a decisive K=1 trigger. It is not usable as evidence: the threshold is
chosen *after* seeing that table, n=27, and the nested procedure — which is not
allowed to look — declined to find it in three folds out of five. It is recorded
here as a **hypothesis for Phase 2B to test prospectively**, not as a finding.

---

## 6. Policy comparison

Full table: `p2a_policy_summary.csv`. Paired against the principal baseline:

| policy | Δreward vs fixed K=4 | 95% CI | Δmean K | 95% CI |
| --- | ---: | --- | ---: | --- |
| **mandatory K=2 → up to 4** | **0.000** | [0.000, 0.000] | **−1.297** | [−1.483, −1.100] |
| K=1 selective (nested) | −0.010 | [−0.025, 0.000] | −1.510 | [−1.735, −1.275] |
| combined adaptive (nested) | −0.010 | [−0.025, 0.000] | −1.510 | [−1.735, −1.275] |
| confidence-only escalation (best point) | −0.015 | [−0.040, 0.000] | −0.170 | [−0.390, 0.000] |
| mandatory K=2 → up to 3 | −0.022 | [−0.050, +0.007] | −1.527 | [−1.630, −1.423] |
| failure-only escalation | −0.050 | [−0.095, −0.007] | −2.835 | [−2.915, −2.738] |
| fixed K=2 | −0.052 | [−0.095, −0.008] | −2.000 | — |
| fixed K=1 | −0.092 | [−0.143, −0.040] | −3.000 | — |

And against fixed K=1, the floor:

| policy | Δreward vs fixed K=1 | 95% CI |
| --- | ---: | --- |
| fixed K=4 | +0.092 | [+0.040, +0.143] |
| **mandatory K=2 → up to 4** | **+0.092** | [+0.040, +0.143] |
| K=1 selective (nested) | +0.082 | [+0.032, +0.132] |

**Retention** (`p2a_retention.csv`):

| policy | fraction of fixed-K=4 gain retained | fraction of Oracle@4 headroom captured | reward per trajectory |
| --- | ---: | ---: | ---: |
| **mandatory K=2 → up to 4** | **100.0%** | 59.1% | **0.213** |
| K=1 selective (nested) | 89.1% | 52.7% | 0.228 |
| fixed K=4 | 100.0% | 59.1% | 0.144 |
| *Oracle@4 (upper bound)* | *169%* | *100%* | *0.160* |
| *Oracle stop-when-correct (upper bound)* | *169%* | *100%* | *0.279* |

**Confidence-only and failure-only escalation are both dominated.**
Confidence-only escalation is the clearest negative: it costs almost as much as
fixed K=4 (mean K 3.38–3.83) and scores *lower*. Failure-only escalation is
cheap (mean K 1.17) and does recover failures, but at 0.527 it is 5 points below
the baseline — replacing failures is necessary and not sufficient.

**Against an equal-cost non-adaptive allocation:** interpolating the fixed-K
curve at mean K = 2.70 gives ≈0.546. Mandatory K=2 scores 0.577 at that cost,
**+0.031** — the adaptivity, not the budget, is doing the work.

---

## 7. Where the compute goes

Stopping distribution for mandatory K=2 → up to 4 (fraction of instance × ordering
replays): **K=1 0%, K=2 52.7%, K=3 24.3%, K=4 23.0%.**

The allocation tracks difficulty without ever seeing a label:

| task | mean K spent | reward (mandatory K=2) | reward (fixed K=1) |
| --- | ---: | ---: | ---: |
| gwas_causal_gene_opentargets | 2.10 | 0.80 | 0.75 |
| crispr_delivery | 2.13 | 0.30 | 0.30 |
| gwas_variant_prioritization | 2.30 | 1.00 | 0.85 |
| gwas_causal_gene_pharmaprojects | 2.50 | 0.60 | 0.55 |
| gwas_causal_gene_gwas_catalog | 2.63 | 0.60 | 0.50 |
| lab_bench_dbqa | 2.70 | 0.60 | 0.50 |
| lab_bench_seqqa | 2.77 | 0.70 | 0.55 |
| screen_gene_retrieval | 3.03 | 0.27 | 0.25 |
| patient_gene_detection | 3.13 | 0.40 | 0.35 |
| **rare_disease_diagnosis** | **3.73** | **0.50** | **0.25** |

The easiest task consumes 2.10 trajectories, the hardest 3.73. **This is the
adaptive behaviour the whole project is about, and it is visible here for the
first time.** It should not be over-read: it is 5 instances per task, and the
mechanism is simply that hard instances disagree more.

---

## 8. Failure recovery

25 of 200 trajectories (12.5%) are execution failures or produced no parseable
answer — the residual after the Phase-1.5 repair, concentrated in
`rare_disease_diagnosis` (`phase1_repaired_report.md` §8).

| policy | replays opening on a failure | resolved to a real answer | resolved *correctly* |
| --- | ---: | ---: | ---: |
| fixed K=1 | 12.5% | **0.0%** | **0.0%** |
| fixed K=4 | 12.5% | 100.0% | 37.3% |
| mandatory K=2 → up to 4 | 12.5% | 100.0% | 37.3% |
| failure-only escalation | 12.5% | 100.0% | 37.3% |

Recovery is where the cheapest policy already earns its keep, and it is
attributable: it is the failure override, not the agreement signal, that does
this. It is also the one component of the Phase-2 action space whose offline
analogue is faithful — re-running a dead trajectory really is what the data
contains. `REPAIR` in the fuller sense (fixing the failing workflow rather than
resampling around it) is not tested here.

---

## 9. Abstention and selective risk

Two accountings are always reported, because abstention must never be allowed to
silently inflate accuracy: `reward` charges an abstention as 0, and
`reward_answered_only` is the selective accuracy over answered instances.

The calibrated-probability abstention sweep is in `p2a_selective_*.csv`, but the
**fold-free** version is both more honest and more deployable, because it keys on
the interpretable stopping state rather than on a score whose absolute level
varies by fold:

**Mandatory K=2 → up to 4** (`p2a_selective_by_agreement_mandatory_k2_upto4.csv`):

| stopping state | replays | accuracy | cumulative coverage | cumulative accuracy |
| --- | ---: | ---: | ---: | ---: |
| 2 agreed of 2 | 52.7% | 0.709 | 0.527 | 0.709 |
| 2 agreed of 3 | 24.3% | 0.562 | 0.770 | 0.662 |
| 2 agreed of 4 | 9.0% | 0.556 | 0.860 | 0.651 |
| **no two agreed of 4** | **14.0%** | **0.119** | 1.000 | 0.577 |

**The abstention rule writes itself: abstain when four trajectories produce four
different answers.** It is 14% of cases, it is right 11.9% of the time, and
dropping it moves accuracy from 0.577 to **0.651 at 86% coverage**. No
calibration model is needed to state or to deploy it.

**Confidently wrong.** Defined as: answered, claimed calibrated reliability
≥0.70, and wrong — as a fraction of *all* replays, so abstaining cannot game it
down. Fixed K=4 is **8.0%**; mandatory K=2 is **0.0%**. This must not be read as
mandatory K=2 being safer at matched confidence. It is not: mandatory K=2 stops
at 2-of-2 agreement, whose calibrated reliability is 0.606, so it **never enters
the ≥0.70 band at all**. The correct statement is that it makes no
high-confidence claims, not that its high-confidence claims are better. Fixed
K=4's 8.0% is the more informative number: unanimity at K=4 is right 76.5% of the
time, so roughly one in four confident unanimous answers is wrong.

---

## 10. Task stratification, with `rare_disease_diagnosis` shown separately

Reward by task, all instances (`p2a_by_task.csv`):

| task | fixed K=1 | fixed K=4 | mandatory K=2 | Oracle@4 |
| --- | ---: | ---: | ---: | ---: |
| gwas_variant_prioritization | 0.85 | 1.00 | 1.00 | 1.00 |
| gwas_causal_gene_opentargets | 0.75 | 0.80 | 0.80 | 0.80 |
| lab_bench_seqqa | 0.55 | 0.70 | 0.70 | 0.80 |
| gwas_causal_gene_gwas_catalog | 0.50 | 0.60 | 0.60 | 0.60 |
| gwas_causal_gene_pharmaprojects | 0.55 | 0.60 | 0.60 | 0.60 |
| lab_bench_dbqa | 0.50 | 0.60 | 0.60 | 0.60 |
| **rare_disease_diagnosis** | **0.25** | **0.50** | **0.50** | **0.60** |
| patient_gene_detection | 0.35 | 0.40 | 0.40 | 0.60 |
| crispr_delivery | 0.30 | 0.30 | 0.30 | 0.40 |
| screen_gene_retrieval | 0.25 | 0.27 | 0.27 | 0.40 |

Mandatory K=2 equals fixed K=4 on **every** task — the equality in §1 is not an
aggregate coincidence.

### `rare_disease_diagnosis` — the documented high-risk stratum

Carried forward from `phase2_entry_assessment.md` §8 as a known task-scoped
limitation, analyzed separately here and **not absorbed into an aggregate that
would imply uniform performance**:

* **It benefits most from verification.** 0.25 → 0.50, the largest gain of any
  task, and the only task where the K=1 baseline is beaten two-fold.
* **It costs the most.** Mean K 3.73 of a possible 4.00 — the controller spends
  nearly its whole budget here and stops early almost never.
* **It carries most of the residual failure.** 10 of the 25 failed trajectories
  in the pool are its; its recovered-failure rate (0.150) is the highest measured.
* **It is still the furthest from its own ceiling in absolute terms**: Oracle@4
  is 0.60, so 10 points of headroom remain unreached even at K=4.

The correct summary is that the reliability layer *helps this task most and costs
most on this task* — which is what a compute-allocating controller should do, and
is a reason to keep the stratum rather than a reason to exclude it. It is 5
instances. Nothing here is more than directional.

---

## 11. Stability, and the recommendation

Point estimates on 50 instances rank policies that are 0.5 pp apart, and that
ranking is noise. Over 10,000 instance-level resamples
(`p2a_stability.csv`):

| policy | reward | best in resamples | within 1 instance of best | mean rank | tasks best-or-tied |
| --- | ---: | ---: | ---: | ---: | ---: |
| fixed K=4 | 0.577 | 94.2% | 99.9% | 1.20 | 10 / 10 |
| **mandatory K=2 → up to 4** | **0.577** | **94.2%** | **99.9%** | 2.32 | **10 / 10** |
| K=1 selective (nested) | 0.567 | 11.8% | 94.3% | 3.50 | 8 / 10 |
| combined adaptive (nested) | 0.567 | 11.8% | 94.3% | 4.24 | 8 / 10 |
| fixed K=3 | 0.555 | 6.3% | 47.9% | 4.59 | 7 / 10 |
| mandatory K=2 → up to 3 | 0.555 | 6.3% | 47.9% | 5.29 | 7 / 10 |
| failure-only escalation | 0.527 | 0.3% | 8.1% | 7.28 | 3 / 10 |
| fixed K=2 | 0.525 | 0.1% | 6.7% | 7.57 | 3 / 10 |
| fixed K=1 | 0.485 | 0.0% | 0.1% | 9.00 | 1 / 10 |

(`mean_rank` separates the two 0.577 policies only because ranks break ties by
column order; on reward they are indistinguishable, which is the point.)

Mandatory K=2 tracks fixed K=4 exactly across every resample, because it returns
the same answers. Its advantage is entirely and reliably in cost.

### Recommendation

**Carry one policy into Phase 2B, not two.**

> **P1 — mandatory K=2 with agreement-based stopping, continuing to K=4, with a
> failure override and abstention when no two of four agree.**

Justification against the brief's own selection criteria — simplicity, stability
across resamples and tasks, position on the reward–cost frontier — rather than
point estimate:

* it has **no fitted parameter at all** (agreement is counted, not modelled), so
  there is nothing to overfit on 50 instances and nothing to re-validate;
* it is stable in 99.9% of resamples and matches fixed K=4 on 10 of 10 tasks;
* it sits on the frontier: nothing deployable achieves 0.577 for less;
* its abstention rule is fold-free and stateable in one sentence.

**The second candidate (K=1 selective) is deliberately not recommended.** The
brief allows it "if the evidence supports it." The evidence does not: three of
five folds refuse to accept at K=1, and accepting costs a reward point. Adding it
to Phase 2B would spend prospective statistical power on a component this
analysis already says is weak.

**One thing Phase 2B should still test prospectively**, cheaply, as a
pre-registered secondary hypothesis rather than a policy arm: whether
`final_confidence == 1.00` on a parseable answer supports early acceptance
(§5). It costs nothing to log and it is the only K=1 signal with a plausible
mechanism.

---

## 12. Limitations, and what this does not show

1. **This is offline replay.** No policy influenced generation. A prospective
   controller may change the agent's behaviour in ways no replay can show.
2. **`VERIFY` and `REPAIR` were not tested.** Both collapse to "spend another
   trajectory" against a fixed pool. Independent evidence retrieval and genuine
   workflow repair are Phase 2B/2C work and must not be claimed from this.
3. **50 instances, 5 per task.** One instance moves a rate by 2 pp. Every
   per-task cell is directional only.
4. **Final-answer correctness is not workflow validity.** A correct answer
   reached through a broken analysis scores 1.0 here, as everywhere in this
   project. The reliability layer measured here cannot see that distinction.
5. **The pool is mixed-configuration** — 42 of 250 slots used the repaired
   serving config (`phase1_repaired_report.md` §11.1). This replay inherits that.
6. **Ordering exhaustiveness is not independence.** Averaging over 24 orderings
   removes the index artifact but the 24 replays of one instance share four
   trajectories; that is why the bootstrap unit is the instance.
7. **The prefix reliability model is imperfectly calibrated at 2-of-2** —
   predicted 0.606 against observed 0.709 — because it is linear in (support, k).
   It is used only for the abstention sweep, and §9's recommended rule does not
   depend on it.
8. **`patient_gene_detection` set-valued agreement**: task-aware Jaccard
   similarity is implemented and reported, but only 2 of 200 trajectories predict
   a multi-gene set, so it changes nothing here. It is in place for Phase 2B.

## 13. Bugs found and fixed while producing this

1. **A failed trajectory could win a plurality tie against a real answer.**
   Under the Phase-1 tiebreak (earliest index), a prefix of [dead run, correct
   answer] resolved to the dead run and scored 0. Failure-only escalation scored
   0 on *all 150* replays that opened on a failure, which is what exposed it.
   Fixed in `policy.resolve`; regression-tested. This would have understated
   every continuing policy.
2. **Fixed threshold grids landed entirely outside the calibrated range.** The
   first run swept K=1 acceptance over 0.60–0.90 while the calibrated scores span
   0.325–0.562, so every sweep policy silently degenerated into "never accept"
   and looked identical to the policy it was meant to be compared against. Grids
   are now quantiles of the observed score distribution.
3. **Pooled out-of-fold AUROC misreported calibrator quality** as 0.515 versus a
   true within-fold 0.700 (§4.1).

---

## 14. Reproduction

```bash
python scripts/phase2a_offline_replay.py \
    --tables <output_root>/phase1_pooled/results/tables \
    --out    <output_root>/phase2a/results
```

CPU only, ~1 minute, no GPU, no model calls, no network. Deterministic: bootstrap
seed 20260802, `GroupKFold` is deterministic, orderings are exhaustive.

Tests: `tests/test_policy.py` (40) and `tests/test_calibration.py` (15) cover
policy replay, ordering exhaustiveness, calibration grouping, cost accounting,
abstention accounting, failure overrides and leakage prevention. Suite total
**329 passed**.
