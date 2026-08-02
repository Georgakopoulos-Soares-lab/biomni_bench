# PROJECT_STATUS

**Last updated:** 2026-08-02 (Phase-2A offline replay COMPLETE — awaiting approval to start 2B)
**Phase:** **PHASE 2A COMPLETE.** Track A selected; offline sequential-policy
replay done on the repaired pooled K=4 data, zero GPU time. One policy
recommended for prospective testing. **No GPU job may be launched until the
Phase-2A recommendation is approved.**
Phases 1 and 1.5 are complete, frozen and independently re-verified.

## Phase 2A result (2026-08-02) — offline sequential policy replay

`scripts/phase2a_offline_replay.py` replays 32 sequential policies over all
**24 arrival orderings** of every instance's 4 trajectories (50 instances, 200
trajectories, exhaustive — no ordering artifact). Experiment `phase2a`,
analysis-only, **no model calls**. Full write-up:
`reports/phase2_offline_replay.md`.

| policy | reward | mean K | model tokens |
| --- | ---: | ---: | ---: |
| fixed K=1 | 0.485 | 1.00 | 181,603 |
| fixed K=2 plurality | 0.525 | 2.00 | 363,207 |
| fixed K=3 plurality | 0.555 | 3.00 | 544,810 |
| **fixed K=4 plurality** (principal baseline) | **0.577** | 4.00 | 726,414 |
| **mandatory K=2, continue to 4 on disagreement** | **0.577** | **2.70** | **530,726** |
| K=1 selective (nested threshold) | 0.567 | 2.49 | 490,243 |
| failure-only escalation | 0.527 | 1.17 | 222,684 |
| *Oracle@4 — UPPER BOUND, not deployable* | *0.640* | 4.00 | 726,414 |

**Headline: mandatory-K=2 adaptive continuation reproduces fixed-K=4 exactly at
68% of the trajectories.** Paired instance-level bootstrap: reward difference
**0.000 [0.000, 0.000]**, mean-K difference **−1.297 [−1.483, −1.100]**. The
reward CI is degenerate because the two policies return the *same answer on all
50 instances* and on all 10 tasks — 100% of the fixed-K=4 gain retained, 59.1%
of the Oracle@4 headroom captured.

**Negative result, preserved: the K=1 acceptance trigger is weak.** Under nested
(leak-free) threshold selection, **3 of 5 folds chose "never accept after one
trajectory"**, and the policy that does accept early loses 1.0 reward point for
0.21 fewer trajectories. Mandatory K=2 is retained as the honest policy, exactly
as the brief anticipated. Confidence-only escalation is dominated outright
(costs nearly K=4, scores lower).

**Other findings:**

* **Fixed K=2 plurality cannot beat K=1 by voting** — two trajectories either
  agree (returning K=1's answer) or tie (tiebreak returns the first). Its +0.040
  comes entirely from replacing failed trajectories. Ties need a third opinion.
* **Failure recovery is free and attributable.** 12.5% of replays open on a dead
  or unparseable trajectory; every continuing policy resolves 100% of them to a
  real answer and 37.3% to a correct one. Fixed K=1 recovers 0%.
* **A one-sentence abstention rule.** Abstain when four trajectories give four
  different answers: 14% of cases, correct 11.9% of the time. Dropping it lifts
  accuracy 0.577 → **0.651 at 86% coverage**, with no calibration model needed.
* **Calibration fixes probabilities, not ranking.** Grouped-OOF Platt on
  verbalized confidence: ECE 0.430 → 0.047, Brier 0.424 → 0.253, AUROC
  ≈0.75 → 0.70. Isotonic (exploratory) reaches ECE 0.003.
* **Adaptive allocation works.** Mean K spent ranges 2.10 (`gwas_causal_gene_opentargets`)
  to **3.73 (`rare_disease_diagnosis`)** — the controller buys the most
  verification exactly where the agent is weakest, with no access to labels.

**`rare_disease_diagnosis`, analyzed separately** as the documented high-risk
stratum (not absorbed into any aggregate): it gains the most from verification
(0.25 → 0.50, the largest of any task), costs the most (mean K 3.73/4.00),
carries 10 of the pool's 25 failed trajectories, and has the highest
failure-recovery rate (0.150). Still 10 pp below its own Oracle@4 of 0.60.

**Recommendation: carry ONE policy into Phase 2B, not two** —
mandatory K=2 with agreement stopping, a failure override, and abstention when
no two of four agree. It has **no fitted parameter**, is best-or-tied in 99.9%
of bootstrap resamples and on 10 of 10 tasks, and sits on the reward–cost
frontier. The K=1-selective second candidate is **deliberately not recommended**:
the evidence does not support it. `final_confidence == 1.00` (26/27 correct,
n=27, found post hoc) is logged as a pre-registered *secondary hypothesis* for
2B, not a policy arm.

Three bugs were found and fixed while producing this — most importantly, **a
failed trajectory could win a plurality tie against a real answer**, which zeroed
every failure-recovery replay until caught by a test
(`reports/phase2_offline_replay.md` §13).

## Pooled reanalysis result (2026-08-02, final — entry-condition check)

`scripts/pool_and_analyze_phase1_5.py` built a 250-slot spec list identical to
`phase1_runs.jsonl` except that each of the 62 originally-failed slots whose
phase1_5 repair completed (42 of them) has its `run_dir` swapped to the repaired
run — read-only against both `phase1` and `phase1_5` (neither touched), written
to `manifests/phase1_pooled_runs.jsonl`, output to experiment `phase1_pooled`.
Reuses the exact tested pipeline (`build_tables`, every `analysis.*` function)
with no new statistics code — only the input spec list differs from Phase 1's.

**Completion: 188/250 (75.2%) → 230/250 (92.0%).**

| metric | Phase 1 (n=188) | Pooled (n=200 instrumented) |
| --- | --- | --- |
| First-trajectory reward | 0.420 | 0.480 |
| Plurality reward | 0.580 [0.44, 0.70] | 0.620 [0.48, 0.76] |
| Oracle@4 (upper bound) | 0.620 [0.48, 0.74] | 0.640 [0.50, 0.76] |
| **Oracle headroom** | 20.0 pp (34.5% rel.) | **16.0 pp (30.8% rel.)** |
| Plurality − first (paired) | +0.16 [+0.06, +0.26] | **+0.14 [+0.04, +0.26]** — still excludes 0 |
| Agreement-fraction AUROC | 0.874 [0.80, 0.94] | **0.815 [0.71, 0.91]** |
| Plurality-fraction AUROC | 0.812 | 0.769 [0.66, 0.87] |
| Confidence AUROC | 0.789 [0.69, 0.87] | 0.749 [0.66, 0.83] |
| Confidence overconfidence gap | 0.37 | **0.43 (worse)** |
| Confidence Brier / ECE | 0.367 / 0.370 | 0.424 / 0.430 (both worse) |

**Every headline effect survives** — all three go-criteria (oracle headroom,
plurality-vs-first, usable signal AUROC) still clear their thresholds with real
margin, so this **does not** flip the Track A recommendation to Track C. Effect
sizes shrink somewhat, as expected: the 42 rescued trajectories are
disproportionately the *hardest* cases (mean reward 0.357 among them), so
folding them in dilutes the signal toward a more honest baseline.

**One thing got worse, not better: calibration.** Overconfidence gap widened
(0.37→0.43), Brier and ECE both increased. Consistent with the rescued pool
being hard-and-often-wrong: if the model stayed confidently wrong on them,
calibration necessarily degrades. This is a genuine finding, not noise — the
miscalibration problem is *worse* than Phase 1 showed, not better.

Full numbers: `<output_root>/phase1_pooled/results/analysis.json` and
`results/figures/*.png` (same 13-figure set, regenerated on the pooled data).

## Repair re-run result (2026-08-02, final)

All 62 Phase-1 `model_context_overflow`/`missing_run` failures re-run under the
selected Arm 2 repair, on GPUs 0-1 only (GPUs 2-3 held a separate, unrelated job
throughout — never touched). Experiment `phase1_5`,
`manifests/phase1_5_runs.jsonl`, config `configs/phase1_5.yaml`. Each run keeps
its *exact* original task/instance/condition/trajectory_index and prompt — only
the serving config differs — with an explicit
`manifests/phase1_5_runs.original_map.json` (repaired run_id → original phase1
run_id).

**42/62 rescued (67.7%). 20/62 still fail — all via the guard's own circuit
breaker (`budget_terminated_consecutive_runaway`), not open-ended overflow.**
That is a materially different failure mode than Phase 1's: the guard is doing
its job (bounding cost after 3 consecutive degenerate generations) but cannot
force a correct answer out of a trajectory that keeps re-degenerating no matter
how it's nudged.

Rescue rate is **not uniform**:

| task | rescued / attempted |
| --- | --- |
| `crispr_delivery` | 11/11 (100%) |
| `gwas_causal_gene_pharmaprojects` | 6/6 (100%) |
| `gwas_causal_gene_gwas_catalog` | 2/2 (100%) |
| `gwas_variant_prioritization` | 1/1 (100%) |
| `screen_gene_retrieval` | 5/6 (83%) |
| `patient_gene_detection` | 8/11 (73%) |
| `lab_bench_seqqa` | 6/9 (67%) |
| `rare_disease_diagnosis` | **3/13 (23%)** |
| `lab_bench_dbqa` | **0/3 (0%)** |

`rare_disease_diagnosis` — already the worst-failing task in Phase 1 (52%
failure rate) — remains stubbornly resistant: 10 of its 13 failures persist even
with the repair. This is a **residual limitation**, not a repair bug: the
bounding guards contain the damage (no more indefinite 8k-token runaway blobs)
but this task's reasoning pattern pushes the model into repeated degeneration in
a way R1/R2/R4/R5 alone do not fix. `lab_bench_dbqa` is 0/3 but n=3 is too small
to read as a pattern rather than noise.

Mean reward among the 42 rescued: **0.357** (15 correct, 27 wrong) — expected to
be below the Phase-1 baseline (0.42), since this pool is specifically the
*hardest* cases, not a random sample.

**What this changes for the pooled analysis:** the Phase-1 K=4 instrumented pool
can now be reconstituted with 42 additional real trajectories (was 188/250
complete, now 230/250), which changes oracle-headroom, self-consistency and
signal-AUROC denominators. **Not yet re-run** — see Next Actions.

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

## Forest Check — 2026-08-02, after the Phase-2A offline replay

**1. What scientific uncertainty was resolved?**
Two. First, whether a sequential controller can reach fixed-K=4 reliability at
roughly K=2 compute — the north star's stated target result. It can: 0.577 at
mean K 2.70, the same answers on all 50 instances. Second, whether the K=1
escalation trigger — named in `phase2_entry_assessment.md` §4 as "genuinely
open" — is solvable with the signals available. On this data it is not, and
three of five folds say so unprompted.

**2. Did the main research claim change?**
Sharpened, not changed. The claim is now specifically that **mandatory
verification plus agreement-based early stopping** is where the value is, and
that single-trajectory uncertainty is not. That is a narrower and more defensible
claim than "uncertainty signals guide allocation", and it is the one the data
supports. Two Phase-1 framings weaken further: verbalized confidence survives
only as a rank (calibration is a repair, not an improvement), and every
effort/length signal is unusable once failures are excluded.

**3. Is the next task necessary for the central contribution?**
Yes. Everything above is offline replay against trajectories that already exist;
no policy influenced generation. The contribution claimed in the north star is a
*prospective, cost-aware reliability controller*, and only Phase 2B tests that.

**4. Are we overfitting to implementation details or the original pilot?**
This was the live risk and the mitigation held: the recommended policy has **no
fitted parameter at all**. Everything that *was* fitted — calibration, the K=1
threshold — was evaluated with nested grouped cross-validation and then
**recommended against**, because the honest procedure declined to accept. The
one tempting artifact (confidence==1.00, 26/27 correct) was found post hoc and is
explicitly demoted to a pre-registered secondary hypothesis rather than promoted
into the policy.

**5. What is the simplest decisive next experiment?**
The frozen prospective run on ~100 held-out instances with one policy and hidden
shadow trajectories through K=4. One policy, not two: adding the K=1-selective
arm would spend prospective power on a component already shown to be weak.

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

**One, and it is deliberate: Phase 2A's recommendation is awaiting approval.**
Standing instruction is to present the offline replay results and stop before
launching any new GPU inference. Nothing technical blocks Phase 2B; the gate is a
decision, not an artifact.

---

## Tests run

| check | result |
| --- | --- |
| `pytest -q` | **329 passed** (274 + 40 policy + 15 calibration) |
| `ruff check src tests scripts` | clean |
| `ruff format --check src tests scripts` | clean except one pre-existing drift in the untouched `tests/test_resumption.py` (a ruff-version line-wrap difference; left alone rather than reformatting a frozen test file) |
| Import check inside the Biomni environment | OK |
| Manifest dry run | OK — 50 instances, 5 per task, stable hash |
| Mock end-to-end | 20 passed, 13 figures |
| GPU smoke test | passed — 6 runs, aggregation, analysis, 13 figures |
| **GPU pilot (250 runs)** | **complete** — 188/250 completed, full analysis, report written |
| **Repair live validation (6 runs, arm 3)** | **passed** — 6/6 completed where Phase 1 failed 22/30; 87 runaways → 1 |
| **Repair ablation (72 runs, 3 arms)** | **complete** — see `reports/context_overflow_forensics.md` §10. Decision: Arm 2. |
| **Repair re-run, all 62 Phase-1 failures (arm 2)** | **complete** — 42/62 rescued (67.7%); 20/62 hit the `max_consecutive_runaway` circuit breaker, concentrated in `rare_disease_diagnosis` (10/13 still fail). |
| **Pooled reanalysis (230/250, entry-condition check)** | **complete** — oracle headroom 16.0pp, plurality-first +0.14 [0.04,0.26], agreement AUROC 0.815. All go-criteria hold; calibration measurably worse (0.37→0.43 overconfidence gap). |
| **Phase-2A offline replay (32 policies x 50 instances x 24 orderings)** | **complete, CPU only** — mandatory K=2 matches fixed K=4 (0.577) at mean K 2.70; K=1 trigger weak (3/5 folds refuse); abstention rule found. One policy recommended for 2B. |

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
| `phase1_5` | `configs/phase1_5.yaml` | repair re-run of all 62 Phase-1 failures under Arm 2. **62/62 attempted, 42 ok / 20 failed.** Map to originals: `manifests/phase1_5_runs.original_map.json`. |
| `phase1_pooled` | — (analysis-only, no config of its own) | pooled Phase-1 + phase1_5 spec list, **230/250 complete (92.0%)**. Not a run experiment — `manifests/phase1_pooled_runs.jsonl` + `scripts/pool_and_analyze_phase1_5.py`. Entry-condition check: **PASS**, all go-criteria hold. |
| `phase2a` | — (analysis-only, no config of its own) | offline sequential policy replay on `phase1_pooled`. **No model calls, no GPU.** 32 policies x 50 instances x 24 orderings. `scripts/phase2a_offline_replay.py`; results at `<output_root>/phase2a/results/`. Report: `reports/phase2_offline_replay.md`. |

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

**All write-up items complete.** Ablation (Arm 2 selected) → repair re-run
(42/62 rescued) → pooled reanalysis → formal E1–E6 adjudication → both reports
written. What remains is decisions, not artifacts:

1. ~~Pool the 42 rescued trajectories into the Phase-1 K=4 set.~~ **Done.**
2. ~~Write `reports/phase1_completion_bias_analysis.md` and
   `reports/phase1_repaired_report.md`.~~ **Done**, 2026-08-02. The former
   formalizes observed-completion vs. intention-to-evaluate vs. matched-paired;
   the latter mirrors `phase1_report.md`'s structure with pooled numbers as
   primary and includes the calibration-got-worse and length-signal-was-
   partly-circular findings in full.
3. ~~Adjudicate entry conditions E1–E6.~~ **Done formally** —
   `reports/phase2_entry_assessment.md` §8. **5 of 6 met; E1 (residual failure
   <5%) measured at 8.0–8.3%, not met as literally stated** but does not block
   Track A since E4 (the condition that would flip the recommendation) passed
   cleanly. Recorded honestly rather than rounded to a pass.
4. ~~Open decision on `rare_disease_diagnosis`'s residual failure rate.~~
   **Decided 2026-08-02 (option (a), by direction):** treat it as a documented,
   task-scoped high-risk stress-test stratum, analyze it separately, and do not
   let it imply uniform performance across tasks. Do **not** spend more effort
   trying to fully solve it before Track A. Phase 2A honours this —
   `reports/phase2_offline_replay.md` §10 reports it as its own section.
5. ~~Offline policy replay on the pooled K=4 pool.~~ **Done**, 2026-08-02 —
   experiment `phase2a`, `reports/phase2_offline_replay.md`.

### Next action — **needs approval before anything else happens**

**Present the Phase-2A recommendation and stop.** Per the standing instruction,
no GPU job is launched and Phase 2B is not begun until the offline replay is
approved. The recommendation is a single policy (mandatory K=2 with agreement
stopping, failure override, abstain when no two of four agree).

On approval, Phase 2B in order — each step gated, none started:

1. Select held-out BiomniEval1 instances not used in Phase 1 (~100, balanced
   across task families, retaining the difficult and failure-prone ones).
2. Freeze and hash the manifest before any inference.
3. Write `reports/phase2_protocol.md` **before** viewing any prospective
   outcome: frozen thresholds, stopping rules, primary metrics, analysis plan.
4. Small multi-task GPU smoke test.
5. **Pause again for approval before the full GPU launch.**

Deferred, not started: expanding the pilot for tighter CIs; transfer to a second
agent; expert workflow annotation; Phase 2C controlled-failure study; adding test
coverage for `scripts/analyze_ablation.py` and
`scripts/pool_and_analyze_phase1_5.py` (one-off analysis scripts outside `src/`,
flagged as a gap, not closed here). `scripts/phase2a_offline_replay.py` is also
outside `src/`, but the logic it drives lives in `src/biomni_uncertainty/policy.py`
and `calibration.py` and **is** covered (55 tests).

---

## Documents added in Phase 1.5

| document | contents |
| --- | --- |
| `reports/context_overflow_forensics.md` | full diagnosis, counterfactuals, proposed repair R1–R6, ablation design, §10 ablation result |
| `reports/phase2_entry_assessment.md` | independent verification of every headline number; completion-bias exposure per claim; entry conditions E1–E6 (§6) and their post-repair adjudication (§8) |
| `reports/phase1_completion_bias_analysis.md` | the completion-bias phenomenon on its own terms: observed-completion vs intention-to-evaluate vs matched-paired, quantified |
| `reports/phase1_repaired_report.md` | pooled (230/250) headline numbers, mirrors `phase1_report.md`'s structure, does not replace it |
| `reports/research_north_star.md` | the central question, the target result, the five questions, standing constraints |
| `scripts/context_forensics.py` | reproduces the forensics from stored traces; no model calls, no GPU |
| `reports/forensics/*` | per-run and per-call token ledgers |

## Documents and code added in Phase 2A

| item | contents |
| --- | --- |
| `reports/phase2_offline_replay.md` | the Phase-2A report: method, re-measured K=1 signals, calibration, the K=1 negative result, policy comparison, failure recovery, abstention, task stratification, stability, limitations, bugs, recommendation |
| `src/biomni_uncertainty/policy.py` | sequential policy replay: `TrajectoryView` (the leakage barrier), `InstancePool` (rewards held apart), task-aware resolution and agreement, the policy set, exhaustive-ordering replay |
| `src/biomni_uncertainty/calibration.py` | grouped out-of-fold Platt / isotonic / small-logistic calibration, instance-normalized weights, Brier/ECE/reliability, `within_fold_auroc` |
| `scripts/phase2a_offline_replay.py` | the driver; CPU only, ~1 min, no model calls |
| `tests/test_policy.py`, `tests/test_calibration.py` | 55 tests: replay, ordering, calibration grouping, cost accounting, abstention accounting, failure overrides, leakage prevention |
