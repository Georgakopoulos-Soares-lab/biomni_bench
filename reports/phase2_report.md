# Phase 2B — prospective evaluation of the online reliability controller

**Written:** 2026-08-10, immediately after the frozen analysis pipeline ran
against the completed run. **Experiment:** `phase2b`. **150 held-out
instances, 600 trajectories, 434 consumed by the controller, 166 hidden
shadows.** Protocol: `reports/phase2_protocol.md` (frozen 2026-08-02, before
any prospective outcome existed). Run launched 2026-08-09, completed
2026-08-10, 8.5 h wall clock, 0 errors, 0 chain-verification failures.

> **Evidence class: PROSPECTIVE.** Every number in §§3–6 comes from the
> controller's actual online decisions, verified against a hash-chained
> decision log. §9 (S5) is explicitly labelled **OFFLINE REPLAY** — it re-plays
> the same trajectories under all 24 orderings and is never conflated with the
> prospective numbers.

> **Headline verdict: both co-primary hypotheses FAIL.** H1 (reward retention)
> fails: the controller scores **3.3 pp below fixed K=4**, 95% CI
> `[−6.7, −0.7]` pp, entirely outside the pre-registered ±5 pp non-inferiority
> margin. H2 (cost reduction) fails: mean K is 2.89 with a 95% CI upper bound
> of **3.03**, just over the 3.0 ceiling. Per `reports/phase2_protocol.md`
> §7.5, **this is the pre-registered falsification case**: "Both fail: Track
> A's premise does not survive prospective test." This report states that
> conclusion plainly and does not soften it.

> **A separate, serious process finding: a real halt condition tripped and
> was not caught in real time**, because of a bug in the gate-verification
> script. See §2. It does **not** explain the H1/H2 failure — §7 shows the
> result is essentially unchanged with the affected task removed — but it is
> reported with equal prominence because catching it late is itself a finding
> about this project's tooling, not just about the controller.

---

## 1. What actually happened, in order

1. Smoke test (`phase2b_smoke`, 6 instances, reported previously) completed
   with 0 apparent gate failures.
2. Per the pre-registered compressed-launch procedure (DEV-2), all fatal gates
   reported PASS, so the full run launched automatically.
3. The full run (150 instances) completed cleanly 8.5 h later: 150/150
   terminated, every decision-log hash chain verifies, every shadow
   trajectory's start time post-dates its instance's terminal decision, no
   forbidden field appears anywhere in a controller input or log record.
4. Building this report's analysis pipeline surfaced that the *residual
   trajectory failure rate* — trajectories that hit the ablation-selected
   guard's own circuit breaker — was **15.5%** (93/600), not the 0% the gate
   script had reported. §2 explains why, and why it does not retract the
   headline verdict.
5. H1 and H2 were then computed exactly as pre-registered. Both fail.

---

## 2. The gate-verification bug, and the halt condition it hid

### 2.1 The bug

`scripts/phase2b_verify.py`'s residual-failure-rate gate checked

```python
m.get("failure_class") in ("model_context_overflow", "budget_terminated")
```

The runner records the fuller string `budget_terminated_consecutive_runaway`
(the ablation-selected Arm-2 repair's circuit breaker — see
`reports/context_overflow_forensics.md` §9, `reports/phase1_repaired_report.md`
§Repair re-run result). `"budget_terminated_consecutive_runaway" ==
"budget_terminated"` is `False`, so the check silently matched **zero**
trajectories in every run it was ever applied to, reporting a spurious 0.0%
in the smoke test, and again in the full run, every time.

### 2.2 What it would have shown, correctly computed

| run | true residual failure rate | vs. 15% threshold |
| --- | ---: | --- |
| smoke (`phase2b_smoke`, 24 trajectories) | **37.5%** (9/24) | would have **BLOCKED** the auto-launch |
| full run (`phase2b`, 600 trajectories) | **15.5%** (93/600) | **exceeds** the halt threshold |

Per `reports/phase2_protocol.md` §11: *"Run-level halt conditions. If any of
these trips, halt, report, and do not analyze as planned."* Under the
corrected gate, the smoke test's true rate should have **blocked the
compressed auto-launch** (DEV-2) before any of the full run's 8.5 GPU-hours
were spent. It did not, because the bug made every gate report PASS
regardless of the actual data.

**This was not caught by any test before launch** because the smoke test
happened to run cleanly enough on the *gate-check side* to look fine, and
`tests/test_phase2b_analyze.py`'s regression test for exactly this failure
mode (`test_halt_condition_matches_the_budget_terminated_prefix_not_exact_string`)
was written *after* the bug was found, not before. The bug is fixed
(`scripts/phase2b_verify.py`, prefix match), the fix is regression-tested, and
this incident is logged as DEV-4 in the protocol and D-26 in `DECISIONS.md`.

### 2.3 Where the failures concentrate, and what that means

| task | trajectories | residual failure rate |
| --- | ---: | ---: |
| **rare_disease_diagnosis** | 100 | **33.0%** |
| patient_gene_detection | 60 | 20.0% |
| lab_bench_dbqa | 60 | 18.3% |
| screen_gene_retrieval | 60 | 18.3% |
| gwas_causal_gene_gwas_catalog | 60 | 16.7% |
| crispr_delivery | 20 | 15.0% |
| lab_bench_seqqa | 60 | 10.0% |
| gwas_causal_gene_opentargets | 60 | 5.0% |
| gwas_variant_prioritization | 60 | 3.3% |
| gwas_causal_gene_pharmaprojects | 60 | 3.3% |
| **all, excluding rare_disease_diagnosis** | 500 | **12.0%** — under threshold |
| **all** | 600 | **15.5%** — over threshold |

`rare_disease_diagnosis` is exactly the task Phase 1.5 already documented as
resistant to the repair (`reports/phase1_repaired_report.md` §8: "10 of its 13
failures persist even with the repair… a residual limitation, not a repair
bug"), and Phase 2B deliberately oversampled it to 16.7% of the sample (D-22),
which is precisely why its known elevated failure rate was enough to pull the
*pooled* rate over 15% for the first time. This is not a new failure mode and
not evidence that the repair itself regressed — it is the foreseeable
consequence of D-22 interacting with a pre-existing, already-documented
limitation, compounded by a monitoring bug that should have surfaced it before
launch and didn't.

**Whether this changes the verdict is answered directly in §7**: recomputing
H1 and H2 on the 125 instances that exclude `rare_disease_diagnosis` gives
almost identical numbers. The halt-condition breach explains *why the
monitoring failed*, not *why the controller underperformed*.

---

## 3. Co-primary hypotheses

Bootstrap: paired, instance-level, 10,000 replicates, seed 20260802 — exactly
as pre-registered, no seed or replicate count chosen after seeing data.

### H1 — reward retention (non-inferiority, margin δ=0.05)

| | value |
| --- | ---: |
| controller reward (abstention scored 0) | 0.573 |
| fixed K=4 reward | 0.607 |
| **paired difference** | **−0.033** |
| 95% CI | **[−0.067, −0.007]** |
| declared when CI lower bound > −0.05 | **−0.067 is not > −0.05 → FAIL** |

### H2 — cost reduction (mean K < 3.0)

| | value |
| --- | ---: |
| controller mean K | 2.893 |
| 95% CI | **[2.760, 3.033]** |
| declared when CI upper bound < 3.0 | **3.033 is not < 3.0 → FAIL** (narrowly) |
| total model tokens, controller vs fixed K=4 | 660,812 vs 836,025 — controller lower ✓ |

The token comparison is the one part of H2 that does clear its bar — the
controller is cheaper in absolute compute even though its *trajectory-count*
CI narrowly fails to clear 3.0. Reported for completeness; H2 as pre-registered
requires both, so it is recorded as FAIL.

**Both co-primary hypotheses fail. Per protocol §7.5, this is the
pre-registered "both fail" outcome: Track A's premise does not survive
prospective test.**

---

## 4. Why: the abstention rule, not the core mechanism, is doing the damage

Three pieces of evidence, all pre-registered analyses, converge on the same
mechanism.

### 4.1 The controller is accurate when it answers

| | value |
| --- | ---: |
| coverage (fraction answered) | 80.7% (121/150) |
| **reward among answered instances** | **0.711** |
| abstention rate | 19.3% (29/150) |

0.711 is *above* fixed K=4's 0.607. The controller is not making worse
decisions when it decides to answer — it is refusing to decide on nearly a
fifth of instances, and every refusal is charged 0 in the primary accounting
(reward_abstain_zero), as the protocol requires (§7.2: "abstention may never
be allowed to silently inflate an accuracy").

### 4.2 Even without the abstention-accounting debate, the matched-compute baseline still wins

The interesting comparison is not really against fixed K=4 (a different cost)
— it is against a baseline that spends **exactly the same** trajectories:

| policy | mean K | reward |
| --- | ---: | ---: |
| controller (mandatory K=2 + abstain) | 2.893 | 0.573 |
| **matched-compute baseline (same cost, non-adaptive)** | 2.893 | **0.592–0.593** |

At identical cost, a policy that spends `m` or `m+1` trajectories on a
uniformly random subset of instances — **using no information at all** —
scores 2 pp higher than the adaptive controller. Paired difference (controller
− matched-compute-expectation): **−0.019, 95% CI [−0.053, +0.015]** — not
significant on its own, but it is the wrong sign for an adaptive method whose
entire premise is that spending compute where uncertainty is high beats
spending it blindly.

### 4.3 The selective-risk table finds the specific weakness: "2 of 4" acceptance is close to worthless

`mandatory_k2` accepts the instant **two** trajectories agree — by
construction, every accepted instance has support exactly 2, whatever K it
stopped at. That erases the one signal that should distinguish a confident
early stop from a reluctant late one:

| stopped at | support | n | accuracy among these |
| --- | ---: | ---: | ---: |
| K=2 (two agreed immediately) | 2 | 65 | **87.7%** |
| K=3 (two agreed on the third try) | 2 | 36 | 61.1% |
| **K=4 (two agreed only among four)** | 2 | 20 | **35.0%** — *below fixed K=1's blind 51.3%* |

An instance where the controller had to go all the way to K=4 and still only
found a bare 2-of-4 plurality is scored as a plain ACCEPT, identical in kind to
an instant 2-of-2 unanimous stop — despite being **worse than guessing with a
single trajectory**. This is not a new discovery: Phase 2A's own offline
selective table (`reports/phase2_offline_replay.md` §9) showed the same
direction on the same policy (0.709 → 0.562 → 0.556 for 2-of-2 / 2-of-3 /
2-of-4), and flagged that state as "worth a rule" without extending the
abstention rule to cover it. The rule as frozen only abstains when **every**
answer is distinct (4-way tie) — it does not abstain on the *weak* 2-of-4
plurality, which prospectively turns out to be the specific failure mode
costing the most. This is the sharpest, most actionable finding in this
report, and it was visible — underweighted, not invisible — in the Phase 2A
data before the prospective run.

**This is analysis, not a retroactive excuse.** §3's verdict stands as
computed. §4 explains the mechanism using pre-registered deliverables
(selective risk/coverage, the matched-compute baseline) precisely so the
"why" is traceable to specific, falsifiable numbers rather than to a post hoc
story.

---

## 5. Paired comparisons against every baseline

| reference | reward Δ | 95% CI | mean K Δ | 95% CI |
| --- | ---: | --- | ---: | --- |
| fixed K=1 | **+0.060** | [+0.007, +0.113] | +1.893 | [+1.760, +2.033] |
| fixed K=2 | −0.007 | [−0.047, +0.033] | +0.893 | [+0.760, +1.033] |
| fixed K=3 | −0.020 | [−0.053, +0.013] | −0.107 | [−0.240, +0.033] |
| **fixed K=4** | **−0.033** | **[−0.067, −0.007]** | −1.107 | [−1.240, −0.967] |
| matched-compute (expectation) | −0.019 | [−0.053, +0.015] | ≈0 (matched by construction) | — |
| matched-compute (one realized draw, seed 20260802) | −0.020 | [−0.053, +0.013] | ≈0 | — |
| Oracle@4 (**UPPER BOUND**) | −0.127 | [−0.180, −0.073] | −1.107 | — |

The controller does beat fixed K=1 and is statistically indistinguishable from
fixed K=2/K=3. It is significantly worse than fixed K=4 and does not clear
the bar against the same-cost non-adaptive baseline.

**Retention** (relative to fixed K=1 as the floor and Oracle@4 as the ceiling):
gain over K=1 is +0.060; that is **64.3%** of fixed K=4's own gain over K=1,
and **32.1%** of the Oracle@4 headroom. Both are markedly lower than Phase
2A's offline estimate for the non-abstaining variant of this policy (100% /
59.1%) — the gap is the abstention cost quantified in §4.1.

---

## 6. Secondary hypotheses

| # | hypothesis | result |
| --- | --- | --- |
| **S1 — safety** | Confidently-wrong rate (≥3-of-4 or 3-of-3 agreement, wrong), as a fraction of all 150 | **Controller: 0.0% (0/150). Fixed K=4: 5.3% (8/150, out of 76 confident calls).** **S1 holds, cleanly.** The controller never made a high-agreement wrong claim in this run; fixed K=4 did, 8 times. |
| **S2 — abstention is well-targeted** | Accuracy among answered > full-coverage accuracy | Answered accuracy **0.711** vs full-coverage accuracy (forced-answer counterfactual on abstained instances, using fixed K=4's own resolved answer there) **0.600**. **S2 holds.** The abstained set really is the harder set — abstention correctly identifies where the controller is weak, even though (§4) the accounting cost of exercising it is what fails H1. |
| **S3 — failure recovery** | Controller resolves more failed-first-trajectory instances to a real answer than fixed K=1 (0% by construction) | 32 of 150 instances had a first trajectory that either did not complete or produced no parseable answer. The controller resolved **53.1%** of those to a real answer, vs 0% for fixed K=1. **S3 holds, applicable and substantial** (this run had far more first-trajectory failures than expected — see §2 — which makes S3's sample larger and its result more, not less, informative). |
| **S4 — `final_confidence == 1.00`** | Materially higher accuracy than the rest, among parseable answers | **89.8% (44/49)** vs **65.1% (267/410)** for the rest. **S4 holds, and holds strongly** — this is the largest and cleanest secondary effect in the whole report. Per D-19/protocol §1, **S4 survives its pre-registered prospective test and becomes a legitimate Phase-3 candidate.** The controller does not use confidence at all, so this is a clean, unexploited signal sitting on top of a controller that already ran. |
| **S5 — ordering robustness** | Primary result unchanged when averaged over all 24 orderings (offline replay of this exact pool) | fixed K=4: 0.613: mandatory-K2-abstain (offline replay): **0.577** — same direction, similar magnitude to the realized-order primary (0.607 vs 0.573). **Confirms the H1 result is not a realized-order artifact.** Explicitly labelled OFFLINE REPLAY; never substituted for the prospective numbers above. |
| **S6 — task stratification** | `rare_disease_diagnosis` reported separately | See §7 and §8. |

---

## 7. Sensitivity: excluding `rare_disease_diagnosis`

Pre-registered by §8/S6 ("`rare_disease_diagnosis` reported separately"), and
directly relevant given §2's halt-condition finding.

| | full sample (n=150) | excluding rare_disease_diagnosis (n=125) |
| --- | ---: | ---: |
| H1 difference | −0.033 | −0.032 |
| H1 95% CI | [−0.067, −0.007] | [−0.064, −0.008] |
| H1 verdict | FAIL | **FAIL** |
| H2 mean K | 2.893 | 2.856 |
| H2 95% CI | [2.760, 3.033] | [2.704, 3.008] |
| H2 verdict | FAIL (narrowly) | **FAIL** (narrowly) |
| controller reward | 0.573 | 0.592 |
| fixed K=4 reward | 0.607 | 0.624 |

**Both hypotheses fail almost identically with the affected task entirely
removed.** The halt-condition breach in §2 is a real process failure and is
reported with full prominence, but it does not explain the substantive
result — the mechanism in §4 does.

---

## 8. Task stratification

`rare_disease_diagnosis` shown separately, never folded into the aggregate
without this row visible.

| task | n | controller reward | controller mean K | coverage | fixed K=4 reward |
| --- | ---: | ---: | ---: | ---: | ---: |
| gwas_causal_gene_opentargets | 15 | 0.867 | 2.20 | 100% | (see `p2b_by_task.csv`) |
| lab_bench_seqqa | 15 | 0.867 | 2.27 | 93% | — |
| gwas_causal_gene_pharmaprojects | 15 | 0.733 | 2.60 | 93% | — |
| lab_bench_dbqa | 15 | 0.667 | 2.73 | 87% | — |
| gwas_causal_gene_gwas_catalog | 15 | 0.600 | 3.20 | 87% | — |
| gwas_variant_prioritization | 15 | 0.533 | 2.73 | 87% | — |
| **rare_disease_diagnosis** | **25** | **0.480** | **3.08** | **60%** | — |
| crispr_delivery | 5 | 0.400 | 2.20 | 100% | — |
| patient_gene_detection | 15 | 0.400 | 3.60 | **60%** | — |
| screen_gene_retrieval | 15 | 0.133 | **3.73** | 67% | — |

Full table with every policy: `p2b_by_task.csv`.
`rare_disease_diagnosis` is not the worst-performing task here —
`screen_gene_retrieval` is, at the highest cost and lowest reward in the
sample, consistent with its Phase 1/2A history. `rare_disease_diagnosis` and
`patient_gene_detection` share the sample's lowest coverage (60%) — the
controller abstains on 40% of both, which is a large share of the sample-wide
19.3% abstention rate concentrated in exactly two tasks. This is directional
only (n=5–25 per task) and is not used to draw a per-task conclusion beyond
what is stated here.

---

## 9. Provenance and integrity

* **Manifest hash verified** against the frozen value
  `7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd` before any
  analysis ran; the script refuses to proceed on a mismatch.
* **All 150 decision-log hash chains verify end to end.**
* **Integrity check: 0/150 mismatches** between the online controller's
  committed terminal decision and an independent offline recomputation of
  `resolve()` from the same stored trajectory metadata — the analysis
  reproduces exactly what the live controller did, not an approximation of it.
* **Leakage check:** the controller's view type and every decision-log record
  were checked against `FORBIDDEN_VIEW_FIELDS`; none present.
* **Shadow isolation:** all 166 shadow trajectories' start timestamps postdate
  their instance's terminal decision commit.

---

## 10. Limitations

1. **This is one prospective run, not a repeated one.** The realized order is
   a single draw; §5's ordering-robustness check (offline replay) is the only
   check against an unlucky draw, and it confirms the direction.
2. **The residual failure rate exceeded the pre-registered halt threshold**
   (§2). The sensitivity analysis (§7) shows this does not explain the
   result, but the correct process discipline — halt, diagnose, decide whether
   to proceed — was not followed in real time because the monitoring tool was
   broken. This is now fixed and regression-tested, but the run cannot be
   retroactively re-launched under a corrected gate; it is reported as it
   happened.
3. **Task cells range from n=5 to n=25.** Every per-task number in §8 is
   directional.
4. **Final-answer correctness is not workflow validity**, as everywhere in
   this project. A correct answer from an invalid analysis scores 1.0 here.
5. **`VERIFY` and `REPAIR` were not implemented.** The controller only ever
   resamples; §4.3's finding about weak 2-of-4 acceptance is a candidate for a
   *repair* action (re-examine, don't just accept) in a future phase, not
   something this controller could do differently within its frozen action set.

---

## 11. Recommendation

Per `reports/phase2_protocol.md` §7.5, stated without hedging: **the
prospective test fails both co-primary hypotheses. Track A's premise —
mandatory verification with agreement-based stopping approaching fixed-K=4
reliability at reduced cost — does not survive prospective test as frozen.**
`reports/phase2_plan.md` §1's decision rule for this outcome selects **Track C
(diversity and difficulty)**.

Stated alongside that, for the record and for whoever picks this up next:

* The failure is **traceable to a specific, fixable mechanism** (§4.3): the
  policy treats a confident 2-of-2 stop and a reluctant 2-of-4 plurality as
  the same action. A frozen-controller redesign that abstains (or escalates to
  `VERIFY`) on the weak state, evaluated in a **new, separately pre-registered
  prospective run**, is the natural next test — not a retroactive fix to this
  one.
* **S4 (`final_confidence == 1.00`) survives its prospective test cleanly**
  (89.8% vs 65.1%, §6) and is a legitimate candidate signal for that redesign.
* **S1 and S3 are genuine wins** worth carrying forward regardless of the
  headline verdict: zero confidently-wrong claims, and real recovery from a
  first-trajectory failure.
* The gate-verification bug (§2) is fixed and regression-tested
  (`tests/test_phase2b_analyze.py`); any future prospective run should re-run
  `phase2b_verify.py` against this fix before trusting a green gate.

---

## 12. Reproduction

```bash
python scripts/phase2b_analyze.py \
    --config configs/phase2b.yaml \
    --manifest manifests/phase2b.jsonl
```

CPU only, ~1 minute, no GPU, no model calls. Deterministic: bootstrap seed
20260802, matched-compute realized draw seed 20260802, decision logs and
trajectory metadata are read-only inputs.

Artifacts: `<output_root>/phase2b/results/tables/*.csv` (14 tables),
`results/figures/p2b_*.png` (3 figures), `results/phase2b_results.json`
(everything in this report as machine-readable JSON).

Tests: `tests/test_phase2b_analyze.py` (13 tests: the matched-compute
baseline's exact expectation formula, the S1 confidently-wrong state
classifier, and a regression test for the §2 gate bug). Full suite: **369
passed.**
