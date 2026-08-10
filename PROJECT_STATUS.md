# PROJECT_STATUS

**Last updated:** 2026-08-10 (**All 5 VERIFY prerequisites adjudicated** — D-32/D-33/D-34/D-35. Items 5,1,2,4 PASS/DONE; **item 3 (residual failure) FAILED at 28.1%** — a prospective VERIFY experiment stays BLOCKED on that alone)

## VERIFY prerequisites — all five adjudicated (2026-08-10)

| item | verdict | evidence |
| --- | --- | --- |
| 5 — RESAMPLE/VERIFY definition | ✅ DONE | D-32, `reports/verify_definition.md` |
| 1 — evidence-channel repair | ✅ DONE | D-33, `reports/evidence_channel_repair.md` |
| 2 — retrieval provenance | ✅ DONE | D-33 (same report) |
| 3 — residual failure re-measured | ❌ **FAILED — 28.1% [15.6%, 45.4%]** | D-34, `reports/residual_failure_remeasurement.md` |
| 4 — healthy-control validation | ✅ **PASS** | D-35, `reports/verify_prerequisite_control_validation.md` |

**A prospective VERIFY experiment is BLOCKED**, independent of item 4's
result. Item 4 passing establishes the repaired environment is safe to build
on; it does not touch item 3's already-measured 28.1% residual failure rate,
which remains the open, unresolved blocker. No repair of item 3 was started
automatically — that decision is separate and has not been made.
**Phase:** **PHASE 2B COMPLETE.** Track A does not survive prospective test as
frozen. Full report: `reports/phase2_report.md`. `reports/phase2_plan.md` §1's
decision rule for "both co-primary hypotheses fail" selects **Track C**
(diversity and difficulty) as the pre-registered next step.
Phases 1, 1.5 and 2A are complete, frozen and independently re-verified.

**The open decision recorded below is now closed (D-28):** the Controller-v2
redesign named in `reports/phase2_report.md` §11 was adjudicated offline against
a bar written down before the analysis ran, and **rejected**. Track C stands as
selected. Awaiting operator approval before any Track-C work begins.

## Post-Phase-2B review (2026-08-10) — independent, CPU only, no GPU

Two new reports, written by a session that read the repository rather than the
project history. **No frozen Phase-0/1/1.5/2A/2B artifact was modified.**

| document | contents |
| --- | --- |
| `reports/post_phase2b_assessment.md` | independent re-derivation of every Phase-2B headline number; what was and was not falsified; which Phase-1/1.5/2A claims survive; confirmatory vs post-hoc separation; the pre-stated bar (§5) a redesign had to clear |
| `reports/controller_v2_offline_assessment.md` | 18 parameter-free policies replayed over both available pools; adjudication against that bar; **Recommendation B — move directly to Track C** |
| `scripts/controller_v2_offline.py` + `tests/test_controller_v2_rules.py` | the driver (CPU only, ~40 s) and 13 tests, including that `v1_frozen` reproduces the frozen controller exactly |

**Verification performed.** Full suite **382 passed**, ruff clean. H1/H2,
coverage, the selective table, matched compute, S4 and the sensitivity analysis
all reproduce **exactly** from stored artifacts via an independent script; the
frozen controller re-simulated offline matches the online decision log on
**0/150 mismatches**, all 150 hash chains verify, manifest hash re-verifies.

**The corrected halt gate's failure path is now exercised end to end** — the
check D-27 specified but never ran. `scripts/phase2b_verify.py` post-fix returns
**exit code 1** and `VERDICT: BLOCKED` on `phase2b_smoke` (9/24 = 37.5%) and on
`phase2b` (93/600 = 15.5%); every other gate passes in both. Run read-only
against the frozen run trees via a redirected output root, so no frozen artifact
was touched.

**Why the redesign was rejected** (full reasoning: D-28):

1. The candidate rule (refuse a bare 2-of-4 plurality) is **4.7–5.7 pp worse
   than Controller v1** on both pools — 2-of-4 is 35–42% accurate, not 0%, so
   refusing it trades an expected 0.40 for a certain 0.
2. No rule clears the pre-stated bar: best margin over same-cost blind
   allocation is **+1.2 pp** at the realized order (CI spans 0) against a
   required ≥3 pp, and the whole `phase2b` effect is **two instances of 150**
   (eight of ten tasks tie fixed K=2 exactly).
3. **Structural:** `v1_no_abstain`, `v2_majority_no_abstain` and
   `v2_usable_majority_no_abstain` are the *identical policy* (asserted by
   test). Inside {ACCEPT, CONTINUE, ABSTAIN} with CONTINUE = resample, the
   2-of-2/2-of-4 distinction can only act by spending more (impossible at the
   K=4 ceiling) or by abstaining (net-negative). The hypothesis cannot express
   itself without a `VERIFY`/`REPAIR` action.

**What survives and what it points at.** The only self-funding adaptive
component is **failure-driven continuation** (escalate only when no usable
answer exists: 0.593 at mean K **2.13** vs fixed K=2's 0.580 at 2.00 — an
observation, not a result; the margin is two instances). `final_confidence ==
1.00` remains a validated *signal* (S4) but adds no decision value on top of
consensus history and does **not** enter a controller. The headroom that
remains is not reachable by voting: **30% of instances (45/150) have no correct
trajectory at all**, and on the 51 instances with 2–3 distinct answers the
correct answer is present but **in the minority** (Oracle@4 0.625/0.636 vs
plurality 0.375/0.273). That is the Track-C question, reached from the
controller side.

**Two process gaps found.** Gap 1 is now **audited and documented** (see the next
section); gap 2 is **deliberately not repaired**. Neither affects the Phase-2B
result, which reproduces exactly from artifacts.

* **The code that ran Phase 2B is not in git.** Every run records
  `project_git.commit = 2c0bfc1, dirty = true`. → Audited, D-29,
  `reports/phase2b_provenance.md`.
* **The residual-failure halt condition is still tripped** at 15.5% (12.0%
  excluding `rare_disease_diagnosis`). Roughly one trajectory in seven is dead,
  and the post-hoc decomposition shows **15 of Controller v1's 29 abstentions
  had ≤1 usable trajectory** — i.e. the abstention rule fired mostly on failure,
  not on disagreement. **Not repaired; stands exactly as measured.** Any next
  prospective run needs this under threshold first.

## Track C — first diagnostic (2026-08-10) — **NO-GO for diversity-by-resampling** (D-30)

CPU only, ~4 min, no GPU, no model calls; no prompt, temperature, tool, model or
generation change. Report: `reports/track_c_diversity_diagnostic.md`. Driver:
`scripts/track_c_diversity.py`. Reusable primitives:
`src/biomni_uncertainty/diversity.py`. Tests: `tests/test_diversity.py` (19).
17 tables + 1 figure at `<output_root>/track_c/results/`. The three-way
interpretation rule was fixed in the script's docstring **before** any outcome
association was computed.

**Verdict: Outcome B (correlated upstream, noisy downstream), secondary
component of Outcome C. Do not build a diversity mechanism.**

| finding | value |
| --- | --- |
| **plan Jaccard, disagreeing vs agreeing pairs** | 0.546 vs 0.538, **+0.008 [−0.040, +0.058]** — against a "different question" control of **0.301** |
| composite workflow distance | +0.020 [−0.034, +0.074] (below the pre-registered 0.05 bar) |
| **P(other correct \| this one wrong) by distance quartile** | 0.308 / 0.190 / 0.263 / 0.359 — **non-monotone**; high−low **+0.056 [−0.074, +0.180]** vs a ≥10 pp bar |
| **correct-minority isolation from the wrong plurality** | **−0.037 [−0.131, +0.046]** — wrong sign, 6/4 split, n=10 |
| tool-sequence similarity, disagree vs agree | −0.105 [−0.207, −0.005] — real divergence, but tool choice is barely question-specific (0.442 vs a 0.396 control) and it predicts nothing |

**Failure vs disagreement, kept separate** (150 instances): 82 unanimous,
**53 substantive disagreement (B)**, **15 insufficient evidence (A)**. Stratum A
is an infrastructure problem — the same phenomenon as the 15.5% residual failure
rate — and is excluded from every diversity statistic.

**Three findings that reframe the track:**

* **35.7% of trajectories make zero tool calls**, and are *more* accurate (0.724)
  than tool-using ones (0.652).
* **The evidence channel is substantially broken**: 30.0% of 1,395 tool calls
  error, concentrated where a VERIFY action would live — `query_pubmed` **68.9%**,
  `advanced_web_search_claude` **77.0%**, `query_scholar` **80.0%** — while
  structured databases work (Ensembl 6.6%, ClinVar 6.4%, GWAS Catalog 7.3%).
  Known Phase-0 limitation (E1 environment skipped); its cost is now quantified.
* **Retrieval content was never logged** (counts only, never names) — evidence
  overlap is unmeasurable from these traces. Top instrumentation priority.

**What a VERIFY action must do differently from RESAMPLE** (§11 of the report):
change the plan by construction, not by sampling; check the computation rather
than re-ask for a conclusion; repair or avoid the literature channel; log
retrieval by name; never spend a verification trajectory on stratum A.

## Phase-2B provenance recovery (2026-08-10) — D-29

A pre-registered prospective experiment ran from an uncommitted working tree.
**No commit in this repository is the Phase-2B execution commit**, and none is
claimed to be. Full audit: `reports/phase2b_provenance.md`. Script:
`scripts/phase2b_provenance_audit.py` (CPU only, read-only). Tests:
`tests/test_phase2b_provenance_audit.py` (8). Machine-readable:
`<output_root>/phase2b_provenance/`.

| class | n | what it means |
| --- | ---: | --- |
| **ESTABLISHED** | 14 | run-time version pinned by a cryptographic or behavioural attestation |
| **CHANGED_AFTER** | 3 | known to differ from what ran, change identified |
| **UNPROVEN** | 4 | exact run-time bytes unrecoverable; circumstantial evidence only |

**Attested:** `configs/phase2b.yaml` — stored `config_hash` `ee5f8cd3…`
recomputes bit-exactly (after restoring the three `${ENV}` expansions the
snapshot records; without that step the check false-alarms).
`manifests/phase2b.jsonl` — recomputes to the protocol's frozen `7cb5da3a…`.
`controller.py`/`policy.py` — **434/434 committed decision records reproduce
exactly**, including the free-text `reason` strings, with 150/150 chains
verifying. The untracked driver's output — **600/600 trajectory identities**
(`run_id`, `requested_seed`, `prompt_hash`, `run_dir`) recompute from tracked
code. `biomni_src` clean at `400c1f36…`.

**Changed after the run:** `phase2b_verify.py` (the D-27 gate fix — the buggy
version that produced the false PASS is gone and cannot be exhibited),
`phase2b_analyze.py`, `tests/test_phase2b_analyze.py`. None participates in
trajectory generation or scoring.

**Unrecoverable:** `scripts/phase2b_run.py`, `run_phase2b.sh`,
`phase2b_supervise.sh`, `tests/test_controller.py`. **mtime is circumstantial,
never proof** — asserted by test.

**Logged observation (not a correction to D-27):** the supervisor log ends
2026-08-02 at `WAITING_FOR_SMOKE`; the full run started 2026-08-09 with
`phase2b_supervise.sh` modified 4 minutes earlier. The supervisor that logged on
2026-08-02 did not launch the full run.

The working tree was committed as an explicitly-labelled **post-hoc provenance
recovery snapshot**, not as the execution commit. No frozen artifact was
modified and no history was rewritten.

## Phase 2B result (2026-08-10) — prospective test: BOTH CO-PRIMARY HYPOTHESES FAIL

150 held-out instances, 600 trajectories, run 2026-08-09→10 (8.5 h, 0 errors, 0
chain-verification failures). Full write-up, all numbers, all mechanisms:
`reports/phase2_report.md`.

| hypothesis | result | verdict |
| --- | --- | --- |
| **H1** reward retention (δ=0.05 margin vs fixed K=4) | −0.033, 95% CI [−0.067, −0.007] | **FAIL** |
| **H2** cost reduction (mean K < 3.0) | 2.893, 95% CI [2.760, **3.033**] | **FAIL** (narrowly) |

**Per protocol §7.5, this is the pre-registered falsification outcome.**
Stated plainly, not reframed: the frozen mandatory-K2-plus-abstention
controller does not reproduce fixed-K=4 reliability prospectively.

**Mechanism, not just verdict** (§4 of the report, from pre-registered
deliverables): the controller is accurate when it answers (0.711 among the
80.7% it accepts) but abstains on 19.3% of instances, each scored 0 by the
mandated accounting. The sharper finding: `mandatory_k2` accepts the instant
two trajectories agree, so **every** acceptance has identical support (=2) —
this erases the difference between a confident 2-of-2 stop (87.7% accurate)
and a reluctant 2-of-4 plurality (**35.0% accurate — below fixed K=1's blind
51.3%**), and the rule as frozen does not abstain on that weak state. A
same-cost matched-compute baseline (spend the identical trajectories with no
adaptivity at all) beats the controller outright (0.592–0.593 vs 0.573).

**A separate, serious process finding.** `scripts/phase2b_verify.py`'s
residual-failure-rate gate had an exact-string-match bug
(`"budget_terminated"` vs the runner's actual
`"budget_terminated_consecutive_runaway"`) that silently reported 0.0% in
*every* run. The true rate was **37.5%** in the smoke test and **15.5%** in
the full run — both above the pre-registered 15% halt threshold. Under the
corrected gate, the smoke test's true rate should have **blocked** the
(operator-approved) compressed auto-launch (DEV-2) before the full run's 8.5
GPU-hours were spent. **This does not explain the H1/H2 failure** — recomputed
excluding `rare_disease_diagnosis` (33.0% of the excess failure rate, also the
task deliberately oversampled per D-22), H1/H2 fail almost identically
(−0.032, mean K 2.856). Bug fixed and regression-tested; incident logged in
`reports/phase2_protocol.md` DEV-4, `DECISIONS.md` D-26/D-27.

**What survives.** Two secondary results are genuine, independent of the
headline failure: **S1** — 0% confidently-wrong for the controller vs 5.3% for
fixed K=4 (a real safety property); **S4** — `final_confidence == 1.00`
correct 89.8% (44/49) vs 65.1% (267/410) for the rest, a clean prospective pass
for the hypothesis D-19 explicitly deferred to this phase. Both are candidates
for a redesigned controller, to be tested in a **new, separately
pre-registered** prospective run — never as a retroactive fix to this one.

**Deliverables:** `reports/phase2_report.md`; 14 tables + 3 figures +
`phase2b_results.json` at `<output_root>/phase2b/results/`;
`tests/test_phase2b_analyze.py` (13 tests, including a regression test for the
gate bug); `scripts/phase2b_analyze.py`. Full suite: **369 passed.**

## Phase 2B — frozen protocol (2026-08-02, no inference run)

| item | value |
| --- | --- |
| Experiment ID | `phase2b` (new) |
| Protocol | `reports/phase2_protocol.md` — written before any prospective outcome exists |
| Manifest | `manifests/phase2b.jsonl`, **hash `7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd`** |
| Instances | **150 held-out**, overlap with Phase 1 asserted **= 0** at build time |
| Trajectories | 600 (K=4/instance; ~422 consumed, ~178 hidden shadows) |
| Config | `configs/phase2b.yaml` (serving identical to `phase1_5.yaml`; only benchmark + controller differ) |
| Controller | mandatory K=2 → agreement stop → up to K=4 → abstain when no two of four agree. **No fitted parameter.** |
| Co-primary | H1 non-inferiority vs fixed K=4 at δ=0.05; H2 mean-K CI upper < 3.0. Both required. |
| Power | 0.99 / 0.99 at n=150, simulated from the Phase-2A difference distribution; ≥0.84 even if disagreement is 3× worse |
| Compute | 600 trajectories, **~12–23 h**, 2×12 h jobs on one 4×H100 node, ≈80–96 GPU-hours |

**Held-out pool.** BiomniEval1 is 433 instances, all split `val` (no official
held-out split). Phase 1 used 50, so **383 were never run**; Phase 2B takes 150
and reserves 233. Allocation is deliberately **not** uniform:
`crispr_delivery` takes all 5 that remain in the entire benchmark (pool-limited),
`rare_disease_diagnosis` takes all 25 remaining (the pre-declared high-risk
stratum, n=5 → n=25), and the other 8 tasks take 15 each — 3× Phase 1's cell.
This exhausts the `crispr_delivery` and `rare_disease_diagnosis` pools; that is a
deliberate, reversible-before-launch spend, flagged in the protocol §3.2.

**Shadow isolation** is enforced by ordering plus commitment, not discipline: the
controller's decision is appended to a **hash-chained append-only log and flushed
before the next trajectory is generated**, so a shadow cannot influence an
earlier decision because it did not exist when that decision was committed.
Verified after the fact from timestamps and the chain; a broken chain is a
run-level halt condition.

**Not yet written** (the implementation step that follows approval):
`scripts/run_phase2b.sh`, `configs/phase2b_smoke.yaml`, the online controller
driver, `scripts/phase2b_analyze.py`.

## Reconciliation: Phase-2A 0.577 vs Phase-1 0.620 (2026-08-02) — RESOLVED, not a bug

Phase 1's pooled plurality is 0.620; Phase 2A's fixed K=4 is 0.577, on identical
data. Investigated with `scripts/phase2a_reconcile.py` and written up in
`reports/phase2_offline_replay.md` §1.1.

**Restricting the Phase-2A replay to Phase 1's native trajectory ordering
reproduces 0.6200 bit-exactly** (as does first = 0.4800 and Oracle@4 = 0.6400).
That single fact rules out denominator, replay, failure-handling and aggregation
causes simultaneously. The entire 0.04333 gap is **4 tied instances of 50** whose
lowest-index tiebreak happened to select the correct answer all four times; the
arithmetic closes to five decimals. Across the 24 fixed orderings, K=4 plurality
ranges **0.540–0.620** and only **6 of 24** reach 0.620 — Phase 1 drew one of the
six best. Two of the four "ties" are 4-way ties where every cluster has size 1,
i.e. "plurality" degenerates to returning the first trajectory.

**0.577 is the unbiased estimate for a sequential controller** and is what every
Phase-2A comparison uses. The frozen Phase-1 report is not wrong — it reports one
realization, and it was a lucky one. Locked against regression by two tests. The
consequence is carried into Phase 2B: since a single ordering can move fixed-K=4
by 8 pp, the protocol pre-registers **both** the realized-ordering paired
comparison (primary) and the ordering-averaged one (secondary S5).

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

## Forest Check — 2026-08-10, after the post-Phase-2B review

**1. What scientific uncertainty was resolved?**
Two. First, whether the Phase-2B failure pointed at a fixable rule or at a
fixable *framing*. It is the framing: the 2-of-2 / 2-of-4 distinction cannot act
inside an action set whose only non-terminal move is "resample", and refusing
the weak state is arithmetically worse than accepting it under the mandated
accounting. Second, whether `final_confidence == 1.00` — which passed its
prospective test — should enter a controller. It should not; its value sits
entirely in the state that is already 87.7% accurate.

**2. Did the main research claim change?**
Narrowed again, and honestly. "Cheap intrinsic signals can guide verification
effort" now holds only in the weak form *"continuing after a trajectory dies
pays for itself; continuing after a disagreement does not."* The stronger claim
— that consensus structure can allocate compute profitably — has now failed
prospectively once and offline once, on independent pools.

**3. Is the next task necessary for the central contribution?**
Yes, and it is deliberately the cheap one. The north star asks whether an agent
can recognise unreliable conclusions; the measurement in §7 of the offline
assessment says the recoverable errors are **minority-held**, which no
recognition-and-voting scheme reaches. Testing whether disagreement is
substantive (different plans/tools) or cosmetic (noisy final answers) is the
precondition for Track C being a real research direction rather than a slogan.

**4. Are we overfitting to implementation details or the original pilot?**
This was the live risk and the discipline held: the adjudication bar was written
before the analysis ran, the leading candidate was rejected despite a positive
point estimate, and the cross-pool check (`phase1_pooled` vs `phase2b`) is what
exposed the effect as two instances. The recurring trap — reading a narrow
offline CI as a strong result — was named explicitly and is now on record twice.

**5. What is the simplest decisive next experiment?**
CPU-only trace analysis of the 51 split `phase2b` instances plus the Phase-1/1.5
traces: do disagreeing trajectories differ in plan and tool path, or only in the
final answer? Zero GPU hours, and it determines whether Track C has a mechanism
to build on.

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

**No analysis blockers.** Phase 2B is complete and its follow-up decision is
closed (D-28: Track C, no Controller v2). The project is waiting on **operator
approval** to begin Track C, which is a gate, not a blocker.

**Two blockers on any future prospective run**, both found in the 2026-08-10
review and neither yet closed:

1. **Uncommitted code.** The Phase-2B controller and drivers are untracked; runs
   record `project_git.dirty = true`. Commit before the next prospective run so
   the code that produces a pre-registered result is recoverable from history.
2. **Residual trajectory failure rate 15.5%**, above the 15% halt threshold
   (12.0% excluding `rare_disease_diagnosis`). This is the halt condition the
   D-27 gate bug hid, and it is entangled with controller behaviour: 15 of
   Controller v1's 29 abstentions had ≤1 usable trajectory.

---

## Tests run

| check | result |
| --- | --- |
| `pytest -q` | **409 passed** (382 + 8 phase2b_provenance_audit + 19 diversity) |
| `ruff check src tests scripts` | clean |
| `ruff format --check src tests scripts` | clean except one pre-existing drift in the untouched `tests/test_resumption.py` (a ruff-version line-wrap difference; left alone rather than reformatting a frozen test file) |
| Import check inside the Biomni environment | OK |
| Manifest dry run | OK — 50 instances, 5 per task, stable hash |
| **Phase-2B manifest build** | OK — 150 held-out instances, overlap with Phase 1 **= 0** (asserted), hash `7cb5da3a…`, dataset fingerprint identical to Phase 1 |
| **Phase-2A/Phase-1 reconciliation** | **RESOLVED** — native-ordering replay reproduces Phase-1's 0.6200 bit-exactly; gap is 4 tied instances, not a bug (`scripts/phase2a_reconcile.py`) |
| Mock end-to-end | 20 passed, 13 figures |
| GPU smoke test | passed — 6 runs, aggregation, analysis, 13 figures |
| **GPU pilot (250 runs)** | **complete** — 188/250 completed, full analysis, report written |
| **Repair live validation (6 runs, arm 3)** | **passed** — 6/6 completed where Phase 1 failed 22/30; 87 runaways → 1 |
| **Repair ablation (72 runs, 3 arms)** | **complete** — see `reports/context_overflow_forensics.md` §10. Decision: Arm 2. |
| **Repair re-run, all 62 Phase-1 failures (arm 2)** | **complete** — 42/62 rescued (67.7%); 20/62 hit the `max_consecutive_runaway` circuit breaker, concentrated in `rare_disease_diagnosis` (10/13 still fail). |
| **Pooled reanalysis (230/250, entry-condition check)** | **complete** — oracle headroom 16.0pp, plurality-first +0.14 [0.04,0.26], agreement AUROC 0.815. All go-criteria hold; calibration measurably worse (0.37→0.43 overconfidence gap). |
| **Phase-2A offline replay (32 policies x 50 instances x 24 orderings)** | **complete, CPU only** — mandatory K=2 matches fixed K=4 (0.577) at mean K 2.70; K=1 trigger weak (3/5 folds refuse); abstention rule found. One policy recommended for 2B. |
| **Phase-2B smoke (6 instances, `phase2b_smoke`)** | **completed** 2026-08-02; 6/6 terminated, 0 errors, chain intact. Gate script bug (D-27) means its reported "0 fatal failures" was wrong — true residual failure rate was 37.5%, above threshold. |
| **Phase-2B full prospective run (150 instances, 600 trajectories)** | **completed** 2026-08-10, 8.5 h, 0 errors, all 150 decision chains verify, 0/150 online-vs-recomputed integrity mismatches. **H1 FAIL, H2 FAIL** — see `reports/phase2_report.md`. |

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
| `phase2b` | `configs/phase2b.yaml` | **COMPLETE.** Prospective controller evaluation, 150 held-out instances (`manifests/phase2b.jsonl`, hash `7cb5da3a…`), 600 trajectories, run 2026-08-09→10. **Both co-primary hypotheses FAIL** — `reports/phase2_report.md`. Analysis: `scripts/phase2b_analyze.py`, results at `<output_root>/phase2b/results/`. |
| `phase2b_smoke` | `configs/phase2b_smoke.yaml` | **Complete**, 2026-08-02, 6 instances on reserved pool (+1 reused Phase-1 instance for `rare_disease_diagnosis`, DEV-1 — never pooled into analysis). |
| `track_c_diversity` | — (analysis-only, no config of its own) | **Complete**, 2026-08-10. Structural diversity of the 600 Phase-2B traces at four levels (answer / plan / tool path / evidence), plus a different-question control. **CPU only, ~4 min, no GPU, no model calls, no generation change.** `scripts/track_c_diversity.py`; results at `<output_root>/track_c/results/`. Report: `reports/track_c_diversity_diagnostic.md`. **Verdict: Outcome B — NO-GO for diversity-by-resampling.** |
| `controller_v2_offline` | — (analysis-only, no config of its own) | **Complete**, 2026-08-10. 18 parameter-free policies replayed over `phase2b` (realized order + all 24 orderings) and `phase1_pooled` (all 24). **CPU only, ~40 s, no model calls, no GPU, no held-out instance consumed.** `scripts/controller_v2_offline.py`; results at `<output_root>/controller_v2_offline/results/` (12 tables). Report: `reports/controller_v2_offline_assessment.md`. **Verdict: Recommendation B, no Controller v2.** |

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

6. ~~Reconcile Phase-2A's 0.577 against Phase-1's 0.620.~~ **Done** — resolved,
   not a bug; see the reconciliation section above and
   `reports/phase2_offline_replay.md` §1.1.
7. ~~Commit the Phase-2A milestone.~~ **Done**, `fd91d26`. No Phase-1 or
   Phase-1.5 artifact modified; the frozen `phase1` manifest hash re-verifies.
8. ~~Select held-out instances, freeze and hash the manifest, write
   `reports/phase2_protocol.md` before any prospective outcome exists.~~
   **Done**, 2026-08-02 — 150 instances, hash `7cb5da3a…`, protocol frozen.

9. ~~Write the Phase-2B implementation~~ **Done** — `scripts/phase2b_run.py`
   (online controller driver, hash-chained decision log),
   `configs/phase2b_smoke.yaml`, `scripts/phase2b_verify.py` (gate checks;
   had a bug, see below), `scripts/run_phase2b.sh`,
   `scripts/phase2b_supervise.sh`. 25 controller tests.
10. ~~Run the smoke test~~ **Done**, 2026-08-02. Gate script reported clean;
    was actually wrong (D-27) — true residual failure rate 37.5%, should have
    blocked the next step.
11. ~~Launch the full prospective run~~ **Done**, 2026-08-09→10, 150 instances,
    600 trajectories, 8.5 h, 0 errors.
12. ~~Analysis and `reports/phase2_report.md`~~ **Done**, 2026-08-10.
    **Both co-primary hypotheses FAIL.** No policy tuning occurred after
    outcomes were seen — the frozen controller is reported exactly as it ran.

### VERIFY prerequisites — in progress (2026-08-10, operator-approved)

**Nothing is running. No GPU job, no new manifest, no prompt change, no
diversity mechanism, no VERIFY implementation.** `reports/verify_prerequisites.md`
(D-31) lists five scientific prerequisites for a constructed-verification pilot
to be valid. Working through them in dependency order:

| # | item | status |
| --- | --- | --- |
| **5** | freeze the RESAMPLE-vs-VERIFY definition | **DONE 2026-08-10 — D-32, `reports/verify_definition.md`** (done first, out of numeric order: its audit criteria set item 2's requirements) |
| **1** | repair the literature/evidence channel | **DONE 2026-08-10 — D-33, `reports/evidence_channel_repair.md`** |
| **2** | instrument retrieval identity/content | **DONE 2026-08-10 — D-33** (addressed together with item 1) |
| **3** | re-measure residual failure on the repaired environment | **DONE 2026-08-10 — D-34, `reports/residual_failure_remeasurement.md`. NOT MET: 28.1% [15.6%, 45.4%], not improved** |
| **4** | validate against healthy controls | **DONE 2026-08-10 — D-35, `reports/verify_prerequisite_control_validation.md`. PASS — no material regression; item 3 remains FAILED regardless** |

**Item 5, closed.** VERIFY is a distinct trajectory type + controller action,
gated by five conditions (starts from a specific candidate claim; tests the
claim rather than re-solving the task; differs from the candidate's method **by
construction**, not by temperature; never sees ground truth; cannot copy the
original's reasoning — enforced structurally by a new `VerifyView`/
`FORBIDDEN_VERIFY_FIELDS` barrier *and* by a post-hoc audit). Three modes kept
deliberately minimal: A (computational re-derivation), B (evidence, gated on
item 1's repair), C (adversarial, B's query strategy inverted). The audit is a
**rejection test against D-30's own measured RESAMPLE band** (plan Jaccard
0.540 [0.515, 0.566], tool-seq similarity 0.409 [0.358, 0.463], query Jaccard
0.328 [0.287, 0.372]) — not an arbitrary threshold, per instruction. The
strongest audit (evidence-identity overlap) is left uncalibrated on purpose,
pending item 2's data. `VerifyView`'s forbidden list is **stricter** than
`TrajectoryView`'s: it also excludes the original's stated confidence, to
prevent anchoring a VERIFY verdict on it — relevant because S4 is a live
candidate signal.

**Items 1+2, closed.** Two tools genuinely repaired by installing missing pure
Python packages: `query_pubmed` (68.9% error → **0/8, 100% success** on real
Phase-2B queries after `pip install pymed`) and `query_arxiv` (→ **0/8, 100%**
after `pip install arxiv`). Three excluded on direct evidence: `query_scholar`
(installing `scholarly` does not fix it — a version mismatch with its own
`free_proxy` dependency makes it fail deterministically, 8/8, and the
underlying free-proxy-scraping mechanism is inherently fragile regardless);
`advanced_web_search_claude` (never tested — requires a proprietary Anthropic
API key, rejected per the standing rule against that dependency and the
confound it would introduce); and **`search_google`, a new finding** — D-30
read it as healthy (3.4% error) but direct testing found **0/8 (0%) succeed,
zero exceptions raised**, because the scraper returns empty silently and the
old failure classification only catches exceptions. **VERIFY's evidence route
is therefore `query_pubmed` + `query_arxiv` + the 8 already-healthy structured
databases — no general web-search tool is currently reliable.**

Retrieval provenance instrumented in the same pass: `retrieval_end` now logs
`selected_identities` (actual resource names) alongside counts;
`code_execution_end`/`tool_call_end` now carry a content hash of tool output
(block-level, not call-level — Biomni's execution model doesn't allow finer
attribution, stated not hidden). `diversity.py` exposes
`retrieval_identity_jaccard`/`evidence_output_jaccard`, kept **outside**
`SIMILARITY_COMPONENTS` so D-30's `workflow_distance` is not silently
redefined. **14 new regression tests** (423 total, up from 409) prove the
fields are populated. No frozen artifact touched; environment change only
(3 packages installed) plus source instrumentation.

## Item 3, closed (2026-08-10, D-34) — residual failure re-measured: NOT improved

**First live-GPU step of this engagement**, launched only after explicit
approval given the real cost involved. Job `3388121` (the same job that
served Phase 2B) was still live, so no new allocation was requested. 8 fresh
instances (zero overlap with any prior manifest; `crispr_delivery` and
`rare_disease_diagnosis` excluded — their pools are exhausted by D-22), config
byte-identical to `configs/phase2b.yaml`, 32 real trajectories, ~62 min wall
clock. **Throwaway: no file written to `manifests/` or `configs/`, no
experiment ID registered.**

**Result: `9/32 = 28.1%`, 95% Wilson CI **[15.6%, 45.4%]** — the point
estimate is *above* the historical 15.5%, and the CI's lower bound sits at the
threshold itself. Prerequisite 3 is **NOT met.** Task-matched against Phase
2B's own rates on these same four tasks, every CI overlaps — nothing here is
statistically distinguishable from before at this sample size, in either
direction.

**Mechanism, confirmed identical to Phase 1.5's diagnosis and confirmed
unrelated to D-33's repair.** Every failure carries
`terminated_reason: "consecutive_runaway"` with `peak_input_tokens` at
32,936–40,637 — the model's ~32,768-token trained-context boundary, exactly
the known degeneration mechanism. Only 5/9 failed trajectories even called
`query_pubmed`, none called `query_arxiv`; the single worst instance
(`patient_gene_detection/i0273`, 4/4 trajectories failed, 44% of this
sample's failures) failed identically whether or not it used the repaired
tools — ruling out the evidence-channel repair as a cause. Excluding that one
instance: 5/28 = 17.9% [7.9%, 35.6%] — closer to, still not comfortably under,
threshold.

**No broad Arm-1/2/3-style search proposed**, per instruction — the evidence
confirms an already-diagnosed mechanism rather than pointing at anything new.
**Smallest targeted intervention proposed, not implemented:** screen candidate
instances with one cheap trajectory before committing K=4 in a future
protocol, excluding ones that hit `consecutive_runaway` — a selection-layer
mitigation, since Phase 1.5 already tried and rejected the serving-layer fix
(raising the context ceiling made things worse).

**The gate exercise succeeded cleanly on live, first-time-seen data**: exit
code 1, `VERDICT: BLOCKED`, correctly triggered by the residual-failure gate;
every other gate (chain integrity, shadow isolation, leakage, failure
override, cost accounting) passed — D-32/D-33's changes broke nothing
upstream.

**Consequence: do not launch a real prospective run assuming this number has
improved.** It has not, on the evidence available.

## Item 4, closed (2026-08-10, D-35) — healthy-control validation: PASS

**Second live-GPU step**, approved separately. Same live allocation (job
3388121), no new SLURM request. 6 previously-healthy Phase-2B instances
re-run under the D-33-repaired environment via `scripts/phase2b_run.py` (same
controller-driven flow as item 3, so the same gate applies unmodified),
matching task prompt / trajectory index / `requested_seed` to the historical
baseline. Acceptance rule frozen in a separate file before the first
trajectory. 24 trajectories, ~54 min wall clock, 0 chain failures.

**PASS**, on the pre-declared primary comparison (trajectory index 0, n=6):
mean reward **0.500 → 0.667 (+16.7pp, an improvement)**, completion and
usable-answer **100% → 100%, unchanged**, no new failure. Every quantitative
bar clears with margin on the comparison the rule names primary.

**Supplementary (all 4 indices, n=24):** reward −4.2pp, completion −4.2pp,
usable-answer −8.3pp — all inside the ±10pp bars. One new failure
(`gwas_causal_gene_gwas_catalog/418`, index 2) confirmed the *identical*
mechanism D-34 already characterized (`peak_input_tokens=36,968`,
`consecutive_runaway`), affecting 1 of 6 controls, not "multiple" — combined
with `seed_supported: False` (confirmed both before and now), the defensible
reading is stochastic variation on an already-known mechanism. **Cost is the
exact "1–2 instances dominate" case the rule anticipated**: aggregate tokens
rose 1.36×, but one zero-tool-call trajectory accounts for ~59% of the entire
increase — unexplainable by the repair or the instrumentation, reported
explicitly rather than smoothed over.

**Evidence-channel confirmed live for the first time.** Every `query_pubmed`
error in this run was a model behavioral error (wrong import path, one syntax
mistake) — not `No module named 'pymed'`; that failure mode is gone. Every
other call succeeded. **Retrieval-provenance instrumentation: 15/15
trajectories with any tool call had both new fields populated — 100%
coverage, zero gaps.**

**Gate exercised on both paths, live, for the first time**: BLOCKED
re-confirmed on item 3's data (28.1%, exit 1) immediately before launch; this
run's own gate returned **`VERDICT: ALL GATES PASS`, exit code 0** (1/24 =
4.2%).

**What PASS does not mean, stated without hedging: item 3 remains FAILED.**
D-34's 28.1% was measured on fresh, unscreened, high-base-rate instances;
this validation was deliberately drawn from previously-healthy ones and says
nothing about the population-wide rate. **A prospective VERIFY experiment
remains blocked on item 3 alone**, regardless of item 4's result. No attempt
to repair item 3 was made here.

### Closed 2026-08-10 (D-30): Track C's first diagnostic — NO-GO for diversity

See the Track-C section above. Outcome B: trajectories that disagree have the
same plans as trajectories that agree, and workflow independence does not
predict error correction.

### Closed 2026-08-10 (D-28): Track C, no Controller v2

~~Whether to pursue the §11 redesign as a new prospective run, or take Track C
as literally selected, is the open decision.~~ **Resolved.** The redesign was
adjudicated offline against a bar written down first
(`reports/post_phase2b_assessment.md` §5) and **rejected**
(`reports/controller_v2_offline_assessment.md`, Recommendation B; D-28). Track C
stands as pre-registered. No Controller-v2 was built, no manifest created, no
GPU job launched.

**Awaiting operator approval before any Track-C work begins.** When it does, the
first step is deliberately **CPU-only, not GPU**: on the 51 `phase2b` instances
with 2–3 distinct answers (plus Phase-1/1.5 traces, all preserved), measure
whether disagreement reflects genuinely different plans and tool paths or merely
noisy final answers. If it is noise, independent verification has nothing to
work on and Track C itself needs reframing — and that costs zero GPU hours to
find out. Only after that should any diversity mechanism be built.

Before any *prospective* run of any kind: commit the Phase-2B code (runs record
`project_git.dirty = true`), and bring the residual trajectory failure rate
under the 15% halt threshold (currently 15.5%).

Deferred, not started: expanding the pilot for tighter CIs; transfer to a second
agent; expert workflow annotation; Phase 2C controlled-failure study (does not
proceed on this controller as frozen — see `reports/phase2_report.md` §11);
adding test coverage for `scripts/analyze_ablation.py` and
`scripts/pool_and_analyze_phase1_5.py` (one-off analysis scripts outside `src/`,
flagged as a gap, not closed here). `scripts/phase2a_offline_replay.py` and
`scripts/phase2b_analyze.py` are also outside `src/`, but the logic they drive
lives in `src/biomni_uncertainty/{policy,calibration,controller}.py` and **is**
covered (67 tests across policy/calibration/controller + 13 for
phase2b_analyze's own arithmetic).

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
