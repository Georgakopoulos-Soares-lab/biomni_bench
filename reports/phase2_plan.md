# Phase 2 — proposed plan (NOT implemented)

**Status:** outline only. Nothing here is built, and nothing here should be built
until `reports/phase1_report.md` is complete. The point of Phase 1 is that the
Phase-2 design is **driven by the Phase-1 results**, not decided in advance.

This document therefore states the *decision rule* — which Phase-2 track each
possible Phase-1 outcome selects — rather than a fixed plan.

---

## 1. Decision rule

| Phase-1 outcome | Phase-2 track |
| --- | --- |
| Meaningful oracle headroom **and** a signal with AUROC ≳0.65 | **Track A — adaptive controller.** The premise holds: better candidates exist and are identifiable. |
| Meaningful oracle headroom, **no** usable signal | **Track B — better candidate selection.** Headroom is real but intrinsic signals do not find it. Invest in verification (independent evidence retrieval, cross-checking) rather than in ranking. |
| **No** oracle headroom (trajectories repeat the same wrong answer) | **Track C — diversity and difficulty.** Selection cannot help. Attack correlated errors: higher temperature, plan-level diversification, prompt variation, tool-set variation. Re-measure headroom before anything else. |
| Signals predict **failure** but not correctness | **Track D — abstention and escalation.** The valuable product is knowing when to stop and ask a human, not picking a better answer. |
| Infrastructure failures dominate | **Track E — fix the environment first.** Install the full Biomni E1 environment, re-run the pilot, and only then interpret anything. |

---

## 2. Candidate components

Listed with what each needs from Phase 1 to be worth building.

### 2.1 Adaptive uncertainty-aware intervention *(needs: headroom + signal)*
Spend compute where uncertainty is high: sample additional trajectories only for
instances whose plurality fraction or confidence falls below a threshold
calibrated on Phase-1 data. Report accuracy **as a function of compute**, against
a fixed-K baseline at matched cost — a selector that only wins by spending more
has not won.

### 2.2 Replanning on plan disagreement *(needs: headroom)*
Detect divergence *early* — at the tool-retrieval or first-plan step rather than
at the final answer — and trigger a replan. Phase 1 records retrieval events and
per-step code execution, so the earliest divergence point is measurable from the
existing traces before any controller is written.

### 2.3 Tool-failure recovery *(needs: Phase-1 tool-failure rates)*
Phase 1 already counts failed executions per trajectory. If tool failure predicts
incorrectness, retry or substitute the failing tool instead of letting the agent
silently reason around the error. Requires the E1 environment so that failures
are genuine tool failures rather than missing imports.

### 2.4 Independent evidence retrieval on conflict *(needs: disagreement structure)*
When trajectories disagree, query an independent source and adjudicate. Only
sensible if the disagreement is substantive rather than formatting noise — which
the Phase-1 canonicalization/parse-status breakdown determines.

### 2.5 Selective abstention / human escalation *(needs: any usable signal)*
Phase 1 already produces the selective accuracy/coverage curve. Phase 2 would
pick an operating point and validate it out of sample. This is the lowest-risk
track: it pays off even when accuracy cannot be improved.

### 2.6 Controlled perturbations *(needs: a working baseline)*
Missing dependencies, decoy files, contradictory evidence, mislabelled samples,
prompt bloat. The purpose is to test whether uncertainty signals **rise** when
the environment is degraded — a stronger test of the signals than correlation
with correctness on clean data, because the ground truth about degradation is
known by construction.

### 2.7 Transfer to a second biomedical agent *(needs: a positive Phase-1 result)*
Nothing about Phase 1 licenses a claim beyond Biomni + Biomni-R0. A second agent
is what turns a finding into a property of biomedical agents.

### 2.8 Full BiomniEval1 *(needs: a headline effect worth powering)*
433 instances instead of 50. Phase-1 interval widths determine whether the full
benchmark would resolve the effect; that calculation should be done from the
Phase-1 numbers, not assumed.

### 2.9 Small closed-model validation subset *(needs: budget approval + data policy)*
Explicitly forbidden in Phase 1. Would require sending benchmark prompts to a
proprietary API, which is a separate decision, not a technical step.

### 2.10 Human expert workflow annotation *(needs: Phase-1 failure examples)*
The most important gap Phase 1 cannot close: **final-answer correctness does not
imply a valid workflow.** An expert rubric over a stratified sample of preserved
traces — correct/incorrect × high/low confidence × with/without tool failure —
would measure how often a correct answer was reached through an invalid analysis.
Phase 1 preserves every raw trace precisely so this is possible later.

---

## 3. What Phase 1 already provides for Phase 2

* Every raw trajectory, event log, transcript and parsed answer, preserved
  including failures.
* A validated run schema, resumption, and a deterministic aggregation/analysis
  pipeline that a Phase-2 arm can reuse unchanged.
* A frozen manifest, so a Phase-2 comparison runs on the same instances.
* Calibrated expectations about cost: measured seconds per trajectory, token
  budgets, context-overflow rate and tool-failure rate.

## 4. What Phase 2 must not inherit uncritically

* The oracle is **not** a method. It never becomes a Phase-2 baseline.
* The SRLM-style selector is a final-confidence approximation, not SRLM.
* A 50-instance pilot cannot license a strong prior. Any Phase-2 threshold
  calibrated on Phase-1 data must be re-validated out of sample.
* `patient_gene_detection` rewards any set intersection; a Phase-2 controller
  must not learn to exploit that.
