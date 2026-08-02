# PROJECT_STATUS

**Last updated:** 2026-08-01 (Phase-1.5: 72-trajectory ablation COMPLETE, decision made)
**Phase:** **PHASE 1.5 COMPLETE. Repair selected: Arm 2 (bounding guards only).**
Phase 1 is complete, frozen and independently re-verified.

## Ablation verdict (2026-08-01, final)

All 72 trajectories done (arm1 24/24, arm2 24/24, arm3 24/24).
**Recommendation: adopt Arm 2, not Arm 3**, reversing the tentative read from the
6-run live validation below. Full numbers, decision-rule application and the
control-stratum evidence are in `reports/context_overflow_forensics.md` §10.

Headline: Arm 3 (all guards, incl. the 2048-token cap and hard budget) fully
eliminates the target failure (0/6 on `overflow_prone`, reward 0.667 vs
baseline 0.333) but **collapses reward to 0.000 on two control strata**
(`same_family_control`, `short_easy_control`) that were fine at baseline —
pooled control-reward delta **−0.278**. Arm 2 (bounding guards only, no hard
token cap) nearly matches Arm 3 on the target stratum (1/6 vs 0/6 failed) while
the controls **improve slightly** (delta **+0.056**). Per the rule fixed before
any arm ran ("accept the least invasive arm that clears both bars"), Arm 3
fails the control bar and Arm 2 is the correct choice.

Caveat stated plainly: n=6 per stratum, so these means are noisy — a couple of
wrong answers move them a lot. The *direction* (arm3 control regression, arm2
control neutrality-to-improvement) is large enough to act on; the exact deltas
are not to be treated as precise.

A real bug was found and fixed while producing this: `scripts/analyze_ablation.py`
read `reward` from raw per-run `metadata.json`, which never contains it (reward
is only computed by `cli aggregate` against ground truth, into
`results/tables/trajectories.csv`). Every reward cell was silently `nan` and the
decision section was uninterpretable until fixed by joining reward in from the
aggregated table by `run_id`. 274 tests pass; this script has no test coverage
of its own (it's a one-off analysis script, not part of the package) — flagged
as a gap, not fixed, given time constraints.

---

## Phase 1.5 status

**Diagnosis is done and it changes the repair plan.** Context overflow is *not* a
context-budget problem — it is model degeneration above ~32,768 input tokens
(this model's base is trained at 32,768; the serving override lifted the position
ceiling to 65,536 without extending usable context). Past that boundary the model
emits 8,192 tokens of degenerate repetition with no stop tag; the blob is
appended to the conversation, which guarantees the next call repeats it. **62 of
the 69 trajectories that crossed it never returned.**

Decisive numbers (`reports/context_overflow_forensics.md`):

* runaway generations: **100%** of 62 failed runs vs **3.7%** of 188 completed;
* runaway rate per call: **3.1%** below 32,768 input tokens, **94.1%** above;
* **no completed run ever exceeded 32,154 input tokens** — the upper half of the
  served window was used only by already-degenerating trajectories;
* 7/7 runs whose *system prompt alone* exceeded 32,768 degenerated on their first
  call, with zero history — rules out "long trajectories are just hard";
* median post-retrieval system prompt is **2,687 tokens**, not the 17k–41k that
  `DECISIONS.md` D-04 assumed — **prompt trimming has nothing to recover**;
* **50.4%** of measured wall-clock produced no answer.

**Repair, implemented and approved** (`context_overflow_forensics.md` §9;
`src/biomni_uncertainty/budget.py`, 24 tests, off by default so Phase-1 configs
are unchanged): `max_tokens` 8192→2048;
truncate-and-nudge on `finish_reason == "length"` instead of appending the blob;
soft budget at 24,576 / hard at 32,768 input tokens (**0 of 188 completed runs
disturbed**); cap retrieval selection; cap a single model-visible observation at
4,000 tokens with full raw output still on disk; aggregator to trust `FAILED`
when `metadata.json` is absent. **Explicitly rejected: raising the context
ceiling or increasing YaRN scaling** — the evidence says both make it worse.

### Live validation of the repair — 2026-08-01, 6 runs, PASSED

Arm 3 (all guards) run against the live endpoint on the **six worst
overflow-prone instances**, which in Phase 1 failed 22 of their 30 trajectories.
Experiment `abl_arm3`, `<output_root>/abl_arm3/runs/`.

| instance | Phase 1 (unguarded) | Arm 3 (guarded) |
| --- | --- | --- |
| | runs / failed / peak input / runaways | peak input / runaways / answer |
| `crispr_delivery/i0020` | 5 / 4 / 52,603 / 15 | 12,908 / 0 / ok |
| `crispr_delivery/i0028` | 5 / 3 / 56,898 / 23 | 24,253 / 0 / ok |
| `patient_gene_detection/i0161` | 5 / 5 / 56,678 / 17 | 29,420 / 0 / ok |
| `rare_disease_diagnosis/i0021` | 5 / 3 / 54,699 / 10 | 22,518 / 0 / ok |
| `rare_disease_diagnosis/i0099` | 5 / 3 / 57,050 / 10 | 26,841 / 1 / ok |
| `rare_disease_diagnosis/i0103` | 5 / 4 / 50,229 / 12 | 23,288 / 0 / ok |

**6/6 completed with a parseable answer; 0 failures** (Phase 1: 22/30 failed).
Peak input fell from 50k–57k to 12.9k–29.4k, and **87 runaway generations became
1**, which was truncated on the spot. Guards fired 5 runaway truncations, 9
observation truncations, 5 soft-budget nudges, 1 retrieval cap.

**The hard budget never fired.** Every trajectory stayed under 29,420 tokens
without it, meaning the *bounding* guards (R2/R4/R5) did the work on their own.
That is the open question the arm-2-vs-arm-3 comparison exists to settle, and it
now looks like arm 2 may be sufficient — which would be the less invasive repair.

Caveat: this is a **one-armed validation on 6 runs**, not the ablation. It shows
the guards work and do not break the agent; it cannot show they leave
previously-healthy trajectories unchanged. That needs arms 1 and 2.

**Still to run:** the full 3-arm ablation (72 trajectories). Manifest, configs
and run specs are built and frozen; only GPU time is missing.

**Correction to the Phase-1 record:** the 2 "missing runs" are not missing. Both
have full directories and `FAILED` markers reading `model_timeout` — killed on
the dispatcher wall clock after 18 consecutive runaway generations. Correct
accounting: **62 failures, 0 missing**. `crispr_delivery` failure rate is 44%,
not 36%.

---

## Forest Check — 2026-08-01, after the context-overflow forensics

**1. What scientific uncertainty was resolved?**
Whether the 24% data loss was an agent property or a configuration artifact. It
is substantially the latter: the failure begins above the model's trained context,
is reproducible from a bloated system prompt alone with no agent history, and
never occurs in the region where completed trajectories live. This also killed
the expensive repair options (bigger context, prompt rewriting) before any GPU
time was spent on them.

**2. Did the main research claim change?**
No. Oracle headroom, the plurality gain and the agreement AUROC all reproduce
exactly, and the oracle headroom can only grow after repair. One *framing* claim
is retracted: the Phase-1 report's "not a configuration mistake" (§5) is wrong.
Two claims are now flagged as bias-exposed and must be re-measured on repaired
data — `agreement_fraction` AUROC 0.874 (computed over surviving trajectories
only) and the inverted length signals (partly a restatement of the failure being
repaired).

**3. Is the next task necessary for the central contribution?**
Yes. The controller must act after trajectory 1, and every K=1 signal Phase 1
measured is either missing 42% of the time (confidence) or confounded with the
failure being repaired (length, wall time). The controller cannot be designed
against these numbers as they stand.

**4. Are we overfitting to implementation details or the original pilot?**
Live risk. The mitigation is the stopping rule: the repair is capped at the six
changes in §9, none of which touches the task prompt, the confidence instruction,
temperature, or the retriever's ranking. Prompt trimming was on the brief's
priority list and is **not being done**, because the measurement said there was
nothing there. If the repair grows beyond an inference-serving fix, the north
star has been lost.

**5. What is the simplest decisive next experiment?**
The 72-trajectory ablation. It tests the mechanism directly on the cases that
failed, keeps matched controls that previously succeeded, and costs under two
node-hours. Everything larger waits on its result.

---

## Headline result

**GO.** Oracle headroom 20.0 pp (relative error reduction 34.5%). Plurality
beats first-trajectory by +0.16 with a 95% CI `[+0.06, +0.26]` that excludes
zero. Agreement-fraction is the strongest uncertainty signal measured (AUROC
0.874), stronger than verbalized confidence (0.789), which is itself
discriminative but severely miscalibrated (mean stated 0.96 vs actual accuracy
0.59). Full detail: `reports/phase1_report.md`.

The largest data-quality issue is a **24% context-overflow rate** — the
top engineering priority before Phase 2.

---

## Completed

### Phase 0 (steps 1–10) — see prior entries below, all done.

### Phase 1 pilot — run to completion

* Launched 2026-07-31 19:25 CDT, detached (`setsid`, PPID 1). Relaunched
  19:33 at dispatcher concurrency 8 (measured throughput at concurrency 4
  would not finish inside the allocation; 8 gave 379 tok/s vs 190, KV usage
  well under capacity).
* **Finished 2026-08-01 05:38 CDT.** 248/250 runs present, 188/250 (75.2%)
  completed. All 250 runs accounted for (2 truly missing run directories).
* Full pipeline ran automatically: dispatch → aggregate → analyze → 13
  figures + tables, via `scripts/run_detached.sh`.
* **Correction:** "2 truly missing run directories" above is wrong — see the
  Phase-1.5 correction and `reports/phase1_report.md` errata E1.

### Post-pilot bug fixes (found by reading real pilot data, not the smoke test)

1. **Canonicalization gap** — Biomni states gene-symbol answers symbol-first
   ("**PDGFRB** is identified as the most likely causal gene...") far more
   often than label-first ("answer: PDGFRB"); the old parser only matched
   label-first and marked 32 trajectories `ambiguous` (all in the three
   `gwas_causal_gene_*` tasks, 44–52% of those tasks). Fixed with a new
   symbol-first-conclusion regex; **reparsed every stored raw response with
   `scripts/reparse_pilot.py`** (no model calls — data was already on disk):
   31/32 resolved cleanly. This meaningfully moved every headline number
   (first 0.36→0.42, plurality 0.50→0.58, headroom 24pp→20pp). The report
   reflects the **corrected** numbers; the fix and its effect are documented
   in `reports/phase1_report.md` §3 for full transparency.
2. **Context-overflow misclassification** — a second 400-error phrasing
   ("the input (N tokens) is longer than the model's context length") wasn't
   recognised by the classifier; 2 runs were mislabelled `unknown_failure`.
   Fixed and relabelled from the already-recorded error text.
3. **Confidence parse-rate denominator** — the missingness plot divided by
   all planned runs instead of runs that actually requested confidence,
   understating the rate (found on smoke data, fixed before the pilot ran).
4. **`system_prompt.txt` truncation** — the audit copy was cut to 20k of
   ~190k chars by the event-log redactor, hiding the confidence instruction
   from the record (verified functional behavior was unaffected; fixed for
   auditability, mid-pilot).
5. **Resumption append bug** — `events.jsonl` is append-only, so a resumed
   run would have interleaved two attempts. Fixed by archiving a prior
   attempt to `attempt<N>/` before re-running (this mattered in practice: the
   concurrency-4→8 relaunch exercised this path for real).

All five are regression-tested. Full list of earlier (pre-pilot) fixes is
preserved below.

### Reports

* `reports/phase0_environment.md` — complete.
* `reports/phase1_protocol.md` — frozen before the pilot; deviations logged
  (concurrency change, one-replica layout, failure-class addition) rather than
  edited away.
* `reports/phase1_report.md` — **complete, all real numbers**, no
  placeholders remain. Go/No-Go: **GO**.
* `reports/phase2_plan.md` — decision rule; this pilot's outcome selects
  **Track A (adaptive controller)**, with context-overflow fix and
  confidence recalibration flagged as prerequisites.

---

## Current blockers

None. The ablation is complete and the repair is decided (Arm 2). Next actions
below need a decision on scope (re-run all 62 failed Phase-1 trajectories under
the repair, or a subset) before any further GPU time is spent.

---

## Tests run

| check | result |
| --- | --- |
| `pytest -q` | **274 passed** |
| `ruff check src tests scripts` | clean |
| `ruff format --check src tests scripts` | clean |
| Import check inside the Biomni environment | OK |
| Manifest dry run | OK — 50 instances, 5 per task, stable hash |
| Mock end-to-end | 20 passed, 13 figures |
| GPU smoke test | passed — 6 runs, aggregation, analysis, 13 figures |
| **GPU pilot (250 runs)** | **complete** — 188/250 completed, full analysis, report written |
| **Repair live validation (6 runs, arm 3)** | **passed** — 6/6 completed where Phase 1 failed 22/30; 87 runaways → 1 |
| **Repair ablation (72 runs, 3 arms)** | **complete** — see `reports/context_overflow_forensics.md` §10. Decision: Arm 2. |

All bugs found and fixed (pre-pilot + post-pilot + post-ablation) are listed
with detail in `reports/phase0_environment.md` §8, `reports/phase1_report.md`
§3, and `reports/context_overflow_forensics.md` §10e (the `analyze_ablation.py`
reward-join bug).

---

## Active experiment IDs

| id | config | state |
| --- | --- | --- |
| `smoke` | `configs/smoke.yaml` | complete, not pooled with pilot results |
| `phase1` | `configs/phase1.yaml` | **COMPLETE and frozen.** Results at `<output_root>/phase1/results/`. Report: `reports/phase1_report.md` (+ errata). Never re-run. |
| `abl_arm1` | `configs/ablation_arm1.yaml` | ablation control (Phase-1 behaviour). **24/24 complete**, 19 ok / 5 failed |
| `abl_arm2` | `configs/ablation_arm2.yaml` | bounding only, no input budget. **24/24 complete**, 22 ok / 2 failed — **selected repair** |
| `abl_arm3` | `configs/ablation_arm3.yaml` | bounding + soft/hard budgets. **24/24 complete**, 23 ok / 1 failed — rejected, harms control reward |

---

## Known failures (final)

* `model_context_overflow`: 60/250 (24.0%) — dominant failure mode, concentrated
  in `rare_disease_diagnosis` (52%), `patient_gene_detection` (44%),
  `crispr_delivery`/`lab_bench_seqqa` (36% each); zero in two GWAS tasks.
  Flagged as the top Phase-2 engineering priority.
* `confidence_parse_failure`: 17 — model answered but confidence block was
  missing/malformed.
* `agent_parse_failure`: 8 (6 genuinely ambiguous, 2 unparseable) — down from
  40 before the canonicalization fix.
* ~~`missing_run`: 2~~ — **corrected 2026-08-01.** Both runs have full
  directories and `FAILED` markers reading `model_timeout`; they were killed on
  the dispatcher wall clock after 18 consecutive runaway generations. Same
  pathology as the 60 above. Correct total: **62 failures, 0 missing**
  (`reports/context_overflow_forensics.md` §7; aggregator fix R6).

---

## Next actions

**Ablation done, repair selected (Arm 2).** Remaining items need a fresh GPU
allocation for the actual repaired re-run, scoped to the failed instances:

1. **Freeze Arm 2 as the Phase-1.5 repair config.** `configs/ablation_arm2.yaml`
   is already the right settings (R1, R2, R4, R5; no R3 budgets); promote it to
   a named `configs/repair.yaml` (or reuse arm2's config directly) so the
   re-run below points at an unambiguous, documented config rather than an
   "ablation arm" name.
2. **← needs a fresh GPU allocation.** Re-run all 62 Phase-1 `model_context_overflow`
   failures under Arm 2's settings as experiment `phase1_5`, preserving `phase1`
   untouched, with an explicit original→repaired run-id mapping. Include the
   matched previously-completed controls used in the ablation so the same
   "did this help or hurt" check applies at full scale, not just n=6 per stratum.
   ≈2–3 node-hours.
3. Write `reports/phase1_completion_bias_analysis.md` and
   `reports/phase1_repaired_report.md`: observed-completion vs
   intention-to-evaluate vs matched-paired results.
4. Adjudicate entry conditions E1–E6 (`reports/phase2_entry_assessment.md` §6).
   **If the repaired data eliminates the oracle headroom, the plurality gain or
   the predictive value of agreement, Phase 2 does not proceed as planned** —
   that outcome selects Track C, not Track A.
5. Only then: offline policy replay on the repaired K=4 pool (zero new GPU
   time), before any prospective Phase-2 pilot.

Deferred, not started: expanding the pilot for tighter CIs; transfer to a second
agent; expert workflow annotation; adding test coverage for
`scripts/analyze_ablation.py` (flagged in §10e of the forensics report as a gap,
not closed here due to time).

---

## Documents added in Phase 1.5

| document | contents |
| --- | --- |
| `reports/context_overflow_forensics.md` | full diagnosis, counterfactuals, proposed repair R1–R6, ablation design |
| `reports/phase2_entry_assessment.md` | independent verification of every headline number; completion-bias exposure per claim; entry conditions E1–E6 |
| `reports/research_north_star.md` | the central question, the target result, the five questions, standing constraints |
| `scripts/context_forensics.py` | reproduces the forensics from stored traces; no model calls, no GPU |
| `reports/forensics/*` | per-run and per-call token ledgers |
