# Phase 2 entry assessment

**Written:** 2026-08-01, before any Phase-1.5 or Phase-2 compute was spent.
**Purpose:** independently verify what Phase 1 established, state precisely which
conclusions survive the completion bias and which do not, and record what must be
true before the Phase-2 controller is built.

---

## 1. Repository state

| check | result |
| --- | --- |
| Working tree | clean at `db148f3` ("Phase 1 complete…") |
| `pytest -q` | **247 passed** |
| Stored results | `<output_root>/phase1/results/` — `analysis.json`, 38 tables, 13 figures |
| Raw traces | 39 GB under `<output_root>/phase1/runs/`, 250 run directories, failures preserved |
| Manifest | `manifests/phase1.jsonl`, hash matches the protocol |

---

## 2. Independent verification of the headline numbers

Recomputed from `results/tables/{instrumented,standard}.parquet` with an
independent implementation (own plurality clustering per D-11, own AUROC, own
instance-level bootstrap at seed 20260731), not by reading `analysis.json`:

| quantity | reported | recomputed | agrees |
| --- | ---: | ---: | :---: |
| First-trajectory reward | 0.420 | 0.420 | ✅ |
| Standard-condition reward | 0.360 | 0.360 | ✅ |
| Plurality reward | 0.580 | 0.580 | ✅ |
| Plurality − first (paired) | +0.16 | +0.160 | ✅ |
| — 95% CI | [+0.06, +0.26] | [+0.060, +0.260] | ✅ |
| Oracle@4 | 0.620 | 0.620 | ✅ |
| Oracle headroom | 20.0 pp | +0.200 | ✅ |
| Relative error reduction | 34.5% | 34.5% | ✅ |
| Confidence: mean stated | 0.96 | 0.960 | ✅ |
| Confidence: accuracy (parseable) | 0.59 | 0.590 | ✅ |
| Confidence: overconfidence gap | 0.37 | 0.370 | ✅ |
| Confidence Brier | 0.367 | 0.367 | ✅ |
| Confidence AUROC | 0.789 | 0.789 | ✅ |
| Agreement-fraction AUROC | 0.874 | 0.874 | ✅ |
| Oracle@K (all subsets) | 0.425 / 0.547 / 0.595 / 0.620 | matches `oracle_at_k.csv` | ✅ |

Run accounting also verified against `status_summary.json`: 250 planned, 248 with
a run directory, 188 completed (75.2%), 60 `model_context_overflow`, 200
instrumented + 50 standard, 25 runs per task.

**Everything the brief asked to be confirmed is confirmed.** Two small
discrepancies and one substantive correction are noted in §5.

---

## 3. Completion bias — the actual problem

The 188 completed trajectories are not a random 75% of the 250 planned. Failure
is concentrated in exactly the tasks where the agent is weakest.

**Per-task, among instrumented runs:**

| task | completed | mean reward (completed) | completion rate |
| --- | ---: | ---: | ---: |
| crispr_delivery | 11/20 | 0.182 | 0.55 |
| patient_gene_detection | 11/20 | 0.545 | 0.55 |
| rare_disease_diagnosis | 11/20 | 0.273 | 0.55 |
| lab_bench_seqqa | 12/20 | 0.833 | 0.60 |
| gwas_causal_gene_pharmaprojects | 14/20 | 0.571 | 0.70 |
| screen_gene_retrieval | 15/20 | 0.267 | 0.75 |
| lab_bench_dbqa | 17/20 | 0.588 | 0.85 |
| gwas_causal_gene_gwas_catalog | 18/20 | 0.556 | 0.90 |
| gwas_variant_prioritization | 19/20 | 0.895 | 0.95 |
| gwas_causal_gene_opentargets | 20/20 | 0.750 | 1.00 |

`corr(completion rate, mean reward among completed) = +0.543`.

**Per-instance, by how many of K=4 completed:**

| completed trajectories | instances | first | plurality | oracle |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 0.000 | 0.000 | 0.000 |
| 1 | 5 | 0.200 | 0.200 | 0.200 |
| 2 | 8 | 0.375 | 0.500 | 0.625 |
| 3 | 17 | 0.294 | 0.588 | 0.647 |
| 4 | 19 | 0.632 | 0.737 | 0.737 |

Only **19 of 50 instances have the full K=4**. Six instances have one or zero,
where *by construction* plurality equals `first` and Oracle@4 headroom is zero —
12% of the sample contributes structurally null evidence to both headline claims.

### What this does to each conclusion

| conclusion | status under completion bias | direction of the bias |
| --- | --- | --- |
| **Oracle headroom is meaningful** | **Robust; the estimate is a lower bound.** Oracle@K is a max over available trajectories. Missing trajectories can only remove candidates, never add wrong ones. Repair can move 0.620 up or leave it, not down. | conservative |
| **Plurality beats first** | **Robust in sign, uncertain in size.** At n_completed ≤ 1 the gap is mechanically 0, which *drags the estimate down*. But the +0.16 is carried disproportionately by the 17 three-completion instances (+0.294) versus the 19 four-completion ones (+0.105) — that spread is not explained and could be noise at n=17. | mixed; needs the repair to resolve |
| **Agreement predicts correctness (AUROC 0.874)** | **Most exposed.** `agreement_fraction` is computed over surviving trajectories. In a 2-of-4 instance, "2/2 agree" scores 1.0 with far less evidence than a genuine 4/4. Whether the signal is this strong at full K is genuinely unknown. | unknown |
| **Confidence is discriminative but miscalibrated** | **Robust in kind, suspect in level.** 117 of 200 confidence values exist; missingness correlates with overflow, which correlates with difficulty. Overconfidence is measured only on trajectories that finished — the harder ones are absent, so 0.37 is plausibly an **under**estimate. | conservative on the gap |
| **Length signals are inverted (AUROC 0.20–0.23)** | **Partly circular, and this is the weakest link.** Overflowed runs ran 3.2× longer and are scored 0. The forensics shows length itself is the proximate cause of failure, so "longer → wrong" is partly a restatement of "longer → crossed the degeneration boundary". After repair this signal must be re-measured before it is used for anything. | inflated |
| **Confidence elicitation does no harm** | **Robust.** Completion rates were 0.80 standard vs 0.76 instrumented; the failure mechanism is context-driven and condition-independent. | none |

### The one claim that changes

The Phase-1 report frames context overflow as "a genuine agent behavior
interacting with a genuine serving limit … not a configuration mistake"
(§5), and the pre-registered stop criterion "infrastructure failures dominate" was
adjudicated **no**.

The forensics does not support the first half of that framing. The overflow is
**upstream of agent behaviour**: 7 of 8 over-retrieval runs degenerated on their
first call with no history at all, and no completed run ever used the upper half
of the served window. The serving configuration — a 65,536-token window over a
model that collapses above ~32,768 — is a **contributing cause**, not a neutral
backdrop. See `reports/context_overflow_forensics.md` §4.

The Go/No-Go verdict itself is unaffected: 188 completed trajectories, 80%
disagreement, an oracle headroom that can only grow, and a signal at AUROC 0.874
all stand. **GO remains correct.** But the sentence "not a configuration mistake"
should be retracted, and Track E ("fix the environment first") is now partly
selected alongside Track A — which is what Phase 1.5 is.

---

## 4. What Phase 1 does not yet answer, that Phase 2 needs

The controller must act after **trajectory 1**, when no agreement signal exists.
Phase 1 measured no signal that solves this:

| single-run signal available at K=1 | AUROC | usable? |
| --- | ---: | --- |
| `final_confidence` | 0.789 | discriminative, but **missing 41.8% of the time** and severely miscalibrated |
| `visible_plan_step_count` | 0.637 | weak, and the only positive behavioural signal |
| `failed_tool_call_count` | 0.360 (flipped 0.64) | weak |
| `total_output_tokens` | 0.214 (flipped 0.79) | **confounded with the failure being repaired** |
| `wall_time_seconds` | 0.233 (flipped 0.77) | same confound |

The apparently strong length signals are the ones the repair will most change,
and the confidence signal is missing precisely when it would matter most. **The
single-trajectory escalation trigger is genuinely open**, exactly as the brief
states. It should not be designed against these numbers until they are
re-measured on repaired data.

Two things the repair adds that Phase 1 could not provide:

* **A controlled terminal state.** `budget_terminated` /
  `degeneration_terminated` are observable online; an endpoint 400 is not. This
  turns 62 destroyed trajectories into 62 informative ones and gives the REPAIR
  and ESCALATE actions something concrete to fire on.
* **Confidence where it is currently missing.** Most of the 82 missing
  confidence values are overflow runs that never reached a final answer.
  Recovering them roughly halves the missingness that would otherwise cripple a
  calibrated-confidence trigger.

---

## 5. Corrections to the Phase-1 record

1. **The two "missing runs" are not missing.** Both
   (`crispr_delivery/i0014/instrumented/t2`,
   `crispr_delivery/i0028/standard/t0`) have full run directories, event logs and
   `FAILED` markers reading `model_timeout` — killed by the dispatcher's 3,900 s
   wall clock after 18 consecutive runaway generations. They were classified
   `missing_run` only because `metadata.json` was never written. They are the
   same pathology as the other 60. Correct total: **62 failures, 0 missing**.
   Forensics §7; fix listed as R6.

2. **`crispr_delivery` failure rate is 44%, not 36%** — both reclassified runs
   fall in that task.

3. **Two AUROC values in the report differ from the tables in the third
   decimal**: `visible_plan_step_count` 0.637 (report) vs 0.635 (table),
   `tool_call_count` 0.412 vs 0.407. Immaterial to every conclusion; noted so the
   record is exact. `signal_auroc.csv` is authoritative.

4. **`DECISIONS.md` D-04's premise is empirically wrong.** It sized the
   post-retrieval system prompt at 17k–41k tokens from assumed selection
   fractions; the retriever actually selects a median of 5/224 tools, giving a
   median prompt of 2,687 tokens. The decision to serve at 65,536 rests on that
   estimate. D-04's *mathematics* (YaRN at factor 1.0 is the identity) is correct;
   its *sizing* is not. A D-17 entry should record this, made after seeing
   results and marked as such.

---

## 6. Entry conditions for Phase 2

Phase 2 should not begin until all of the following hold. Each is checkable.

| # | condition | why |
| --- | --- | --- |
| E1 | Overflow + degeneration failures below ~5% of planned runs in the repair ablation | above that, any controller is trained on a distribution dominated by an artifact |
| E2 | Repaired controls show no material reward change vs their Phase-1 runs | otherwise the repair changed the agent, not just its failure mode |
| E3 | Every originally-failed run and both timeout runs re-run under the frozen repair | intention-to-evaluate results require the full 250 |
| E4 | Oracle headroom, plurality gain and agreement AUROC recomputed on repaired data, all three still positive and CI-clean | the brief's explicit stop condition |
| E5 | Length/effort signals re-measured post-repair | §3 — currently confounded with the repaired failure |
| E6 | A `phase1_5` experiment ID with explicit original→repaired run mapping; `phase1` untouched | provenance; `phase1` is the frozen comparator |

**If E4 fails — if repaired data eliminates the headroom, the plurality gain or
the predictive value of agreement — Phase 2 does not proceed as planned.** Per
`reports/phase2_plan.md` §1, that outcome selects Track C (diversity and
difficulty), not Track A. This is written down now, before the data exists.

---

## 7. Recommended sequence

1. Present the repair proposal (`context_overflow_forensics.md` §9). **← current step**
2. Repair ablation, ~72 trajectories, ≈1.2–1.5 node-hours. Freeze one arm.
3. Re-run all 62 failed runs under the frozen repair as experiment `phase1_5`,
   plus a matched sample of previously-completed controls to quantify
   configuration-induced change. ≈2–3 node-hours.
4. `phase1_completion_bias_analysis.md` and `phase1_repaired_report.md`:
   observed-completion vs intention-to-evaluate vs matched-paired results.
5. Adjudicate E1–E6. Only then build the controller.
6. Offline policy replay on the repaired K=4 pool **before** generating any new
   data — the brief is right that this is nearly free and answers most of the
   controller design question.

Steps 2 and 3 are the only GPU spend before the next decision point, ≈4
node-hours total, and each is presented for approval separately.
