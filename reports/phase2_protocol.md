# Phase 2B — frozen prospective protocol

**Status: PRE-REGISTRATION. Written 2026-08-02, before any Phase-2B inference.**
**No prospective outcome has been observed. No GPU job has been launched.**

This document freezes the controller, the sample, the outcomes, the statistical
plan and the stopping rules *before* any prospective data exists. Anything
changed after the run starts is logged as a **deviation**, in the section
provided for it, and never edited away — the same rule that governed
`reports/phase1_protocol.md`.

| artifact | value |
| --- | --- |
| Experiment ID | `phase2b` (new; `phase1`, `phase1_5`, `phase1_pooled`, `phase2a` untouched) |
| Manifest | `manifests/phase2b.jsonl` |
| **Manifest hash** | `7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd` |
| Ground truth | `manifests/phase2b.groundtruth.jsonl` (separate file, never agent-visible) |
| Dataset fingerprint | `287304c649b14166cce227a9f13239f104df1ca93ea53582c11b4d745b2c423f` (identical to Phase 1 — same benchmark file) |
| Config | `configs/phase2b.yaml` |
| Build report | `manifests/phase2b.report.json` |
| Instances | **150**, none used in Phase 1 (overlap asserted = 0) |
| Trajectories | **600** (K=4 per instance; the controller consumes a prefix, the rest are hidden shadows) |
| Prior evidence | `reports/phase2_offline_replay.md` (offline replay — **not** prospective) |

---

## 1. Hypotheses

The offline replay says mandatory verification with agreement-based early
stopping matches fixed-K=4 accuracy at ~68% of the cost. That is a retrospective
claim about trajectories that already existed. Phase 2B asks whether it holds
when a controller actually decides, online, what to spend.

**Co-primary hypotheses.** Both must pass for the headline claim; neither alone
is sufficient.

* **H1 — reward retention (non-inferiority).** The adaptive controller is not
  materially less accurate than fixed K=4.
  *Non-inferiority margin* **δ = 0.05** (5 pp = 1 instance in 20).
  *Declared* when the lower bound of the 95% paired bootstrap CI on
  `reward(adaptive) − reward(fixed K=4)` exceeds **−0.05**.
* **H2 — cost reduction.** The controller spends materially less than K=4.
  *Declared* when the upper bound of the 95% bootstrap CI on mean trajectories
  per instance is below **3.0**, and the point estimate of total model tokens is
  below that of fixed K=4.

**Why δ = 0.05.** It is the scale of the pre-registered Phase-1 go-threshold
(5 pp oracle headroom); it is well inside the fixed-K=4 − fixed-K=1 gain
(9.2 pp offline), so a policy that gave up δ would still be giving up more than
half the reason to sample more than once; and §4 shows it is achievable at
n=150. It was fixed before the sample was drawn.

**Secondary hypotheses**, pre-specified, not gating:

* **S1 — safety.** The confidently-wrong rate (answered, held an answer with
  ≥3-of-4 or 3-of-3 agreement, and was wrong) is not higher than fixed K=4's.
* **S2 — abstention.** Abstaining when no two of four trajectories agree raises
  accuracy among answered instances above the full-coverage accuracy.
* **S3 — failure recovery.** Among instances whose first trajectory fails to
  complete or produces no parseable answer, the controller resolves materially
  more to a real answer than fixed K=1 (which resolves 0 by construction).
* **S4 — `final_confidence == 1.00`.** Among trajectories with a parseable
  answer, those stating confidence exactly 1.00 are correct at a materially
  higher rate than the rest. **This is a hypothesis, not a policy component**
  (D-19): it was found post hoc in Phase 2A (26/27, n=27) and the nested
  selection procedure declined to use it in 3 of 5 folds. The controller does
  **not** read confidence. If S4 survives here it becomes a Phase-3 candidate.
* **S5 — ordering robustness.** The primary result is unchanged when fixed-K
  baselines are averaged over all 24 orderings of the shadow pool instead of
  evaluated at the realized order (§7.3).
* **S6 — task stratification**, with `rare_disease_diagnosis` reported
  separately and never absorbed into an aggregate (§8).

---

## 2. The controller — frozen

`configs/phase2b.yaml`, block `controller:`. **It has no fitted parameter.**
Agreement is counted, not modelled; there is no threshold, no calibration model
and no learned component, so there is nothing here that could have been tuned on
Phase-1 data and nothing that needs out-of-sample re-validation.

```
policy                   : mandatory_k2
min_trajectories         : 2
max_trajectories         : 4
failure_override         : true
abstain_on_no_agreement  : true
generate_shadows         : true
```

### 2.1 Decision rule, stated exhaustively

At each step the controller holds the trajectories observed so far and takes
exactly one action.

| state | action |
| --- | --- |
| k = 1 | **CONTINUE**. A single unverified analysis is never returned, whatever it says. |
| k ≥ 2, two or more *usable* trajectories share a canonical answer | **ACCEPT** that answer. |
| k ≥ 2, no valid agreement, k < 4 | **CONTINUE**. |
| k = 4, at least two usable trajectories agree | **ACCEPT** the plurality answer. |
| k = 4, every usable answer is distinct | **ABSTAIN** → escalate to human review. |
| k = 4, no usable trajectory at all | **ABSTAIN** → escalate. |

**Usable** = the run completed *and* produced a parseable, clusterable answer. A
trajectory that is not usable never counts toward agreement and never wins a tie
(D-18). This is the failure override, and it is why `[failed, A]` at k=2 holds
only *one* opinion and continues.

**Actions in the Phase-2 action space that this controller does not take.**
`VERIFY` (independent evidence retrieval) and `REPAIR` (fixing a broken workflow
rather than resampling around it) are **not implemented** in Phase 2B. Sampling
another trajectory is *resampling*, and it is labelled as such. Conflating it
with verification or repair is explicitly forbidden (`CLAUDE.md`). Phase 2C is
where controlled failure and genuine repair are tested.

### 2.2 What the controller may see

Only the fields on `policy.TrajectoryView`: completion status, answer parse
status, canonical answer/cluster key, verbalized confidence (logged, **not
used**), failure class, and observable cost/effort counters. It may **never**
see ground truth, a future trajectory, a shadow trajectory, or the native
trajectory index. Enforced by the frozen field list plus
`FORBIDDEN_VIEW_FIELDS`, and by `tests/test_policy.py`.

---

## 3. Sample: 150 held-out instances

### 3.1 What is genuinely held out

BiomniEval1 has **433 instances**, all in split `val` — there is no official
held-out split (`manifests/phase1.report.json`, `held_out_split_available:
false`). Phase 1 consumed 5 per task = 50. **383 instances have never been run.**

| task | in benchmark | used by Phase 1 | held out | **Phase-2B** | reserved |
| --- | ---: | ---: | ---: | ---: | ---: |
| crispr_delivery | 10 | 5 | 5 | **5** | 0 |
| gwas_causal_gene_gwas_catalog | 50 | 5 | 45 | **15** | 30 |
| gwas_causal_gene_opentargets | 50 | 5 | 45 | **15** | 30 |
| gwas_causal_gene_pharmaprojects | 50 | 5 | 45 | **15** | 30 |
| gwas_variant_prioritization | 43 | 5 | 38 | **15** | 23 |
| lab_bench_dbqa | 50 | 5 | 45 | **15** | 30 |
| lab_bench_seqqa | 50 | 5 | 45 | **15** | 30 |
| patient_gene_detection | 50 | 5 | 45 | **15** | 30 |
| **rare_disease_diagnosis** | 30 | 5 | 25 | **25** | 0 |
| screen_gene_retrieval | 50 | 5 | 45 | **15** | 30 |
| **total** | **433** | **50** | **383** | **150** | **233** |

Selection within a task reuses Phase 1's deterministic keyed-hash ordering
(`benchmark._rng_order`) under a **new** seed (20260802) — same procedure, new
draw. Overlap with Phase 1 is asserted to be 0 at build time and the build
aborts if it is not.

### 3.2 Why the allocation is not uniform

It is not balanced because the benchmark does not permit balance and forcing it
would cost information:

* **`crispr_delivery` is pool-limited.** Five instances remain in the entire
  benchmark. Take all five or drop the task; there is no third option, and no
  future phase can ever give this task a large sample.
* **`rare_disease_diagnosis` is deliberately over-sampled** — all 25 remaining.
  It is the pre-declared high-risk stratum: lowest reward, highest residual
  failure rate, and the task where the controller offline spends the most
  (mean K 3.73 of 4.00) and recovers the most failures. Phase 1 could only
  report it at n=5, where a per-task rate has ±20 pp precision. At n=25 that is
  ±10 pp, and it is the stratum whose behaviour the controller most needs to
  demonstrate. **This exhausts the pool** — it is a deliberate spend, flagged
  here so it can be reversed before the run rather than regretted after.
* **15 elsewhere** — three times Phase 1's per-task cell, and comfortably within
  every remaining pool.

**Consequence, stated in advance.** `rare_disease_diagnosis` is 16.7% of this
sample against 6.9% of BiomniEval1. The pooled reward will therefore sit *below*
what the benchmark's natural composition would give. This is a level effect, not
a contrast effect: **every primary comparison is paired on the same instances**,
so it does not bias H1 or H2. A benchmark-composition-weighted reward is
reported as a secondary descriptive figure.

---

## 4. Sample-size justification

Simulated from the Phase-2A per-(instance × ordering) difference distribution
between the adaptive policy and fixed K=4 — which is the empirical model of what
a single prospective realization looks like. That distribution is `−1` on 8 of
1200 replays, `+1` on 8, and `0` on the remaining 1184 (sd 0.116).

| n | P(declare H1: non-inferiority at δ=0.05) | P(declare H2: mean-K CI upper < 3.0) |
| ---: | ---: | ---: |
| 50 | 0.73 | 0.69 |
| 100 | 0.89 | 0.92 |
| 120 | 0.96 | 0.97 |
| **150** | **0.99** | **0.99** |

Sensitivity — the table above assumes the prospective disagreement rate between
adaptive and fixed-K=4 matches the offline 1.3%. If it is worse:

| disagreement rate | power for H1 at n=150 | at n=120 |
| --- | ---: | ---: |
| 1.3% (as observed offline) | 0.99 | 0.96 |
| 2.7% (2× worse) | 0.93 | 0.84 |
| 4.0% (3× worse) | 0.84 | 0.72 |
| 8.0% (6× worse) | 0.59 | 0.47 |

n=150 stays adequately powered up to a 3× degradation. Beyond ~6×, power
collapses — but a controller disagreeing with fixed-K=4 on 8% of instances would
already contradict the Phase-2A premise, and that contradiction is itself the
finding. **n=150 is chosen: it is the strongest sample the remaining benchmark
supports at 4 trajectories per instance within the compute budget (§9).**

---

## 5. Shadow trajectories

Every instance gets **4 trajectories generated**. The controller consumes a
prefix; the remainder exist so that fixed-K and oracle baselines are computable
*on the same instances* rather than estimated from a separate run.

### 5.1 How the controller is prevented from seeing them

Enforcement is **ordering plus commitment**, not discipline:

1. Trajectory *j* is generated. Only trajectories `1..j` exist on disk.
2. The controller is invoked with exactly those `j` and returns an action.
3. **The decision is appended to a hash-chained, append-only decision log and
   flushed before any further generation begins.** Each record carries the
   previous record's hash, so a decision cannot be rewritten after later
   trajectories exist without breaking the chain.
4. Only then may trajectory *j+1* be generated.
5. When the controller terminates (ACCEPT or ABSTAIN) at depth *k*, trajectories
   `k+1..4` are generated as **shadows**, written under a separate
   `shadow/` subtree, tagged `role=shadow`, and never passed to the controller
   process.

A shadow therefore cannot influence an earlier decision because it **did not
exist** when that decision was committed. This is checkable after the fact from
timestamps and the hash chain, and the check is part of the analysis.

### 5.2 What shadows are used for

Only after the run, only by the analysis: paired fixed-K=1/2/3/4, Oracle@1–4,
the matched-compute baseline, and the ordering-robustness check (S5). They never
enter a reward the controller is credited with.

---

## 6. Baselines

All computed on the **same 150 instances**, from the union of consumed and
shadow trajectories.

| baseline | definition |
| --- | --- |
| fixed K=1 | first trajectory in generation order |
| fixed K=2, K=3 | plurality over the first 2 / 3, D-18 tiebreak |
| **fixed K=4 plurality** | **the principal comparator** — plurality over all four |
| **matched-compute non-adaptive** | §6.1 — a real allocation, not an interpolation |
| Oracle@1–4 | best available reward among the first n — **UPPER BOUND, never a baseline** |
| Oracle stop-when-correct | stops at the first correct trajectory — **UPPER BOUND** |

### 6.1 The matched-compute baseline

Interpolating the fixed-K curve, as Phase 2A did, is an estimate of a policy
nobody can run. This is a policy that can actually be run.

Let the controller consume **B** trajectories over **N = 150** instances. Define
`m = floor(B/N)` and `r = B − mN`. The matched-compute allocation spends `m+1`
trajectories on a uniformly random subset of `r` instances and `m` on the other
`N − r`. It uses **exactly B trajectories** — the same budget, allocated without
looking at anything.

Its per-instance value is the exact expectation over that randomization,

```
value_i = (1 − r/N) · reward_i(fixed K=m) + (r/N) · reward_i(fixed K=m+1)
```

which is a well-defined per-instance quantity, so it pairs cleanly in the
bootstrap and needs no Monte-Carlo noise. A concrete realized draw at seed
20260802 is also reported for readers who prefer one.

**B is read from the run, not chosen.** `m` and `r` are a deterministic function
of the controller's realized cost, computed before any reward is examined. This
is recorded here so that the baseline cannot be retuned once rewards are known.
(Predicted from Phase 2A at this sample's composition: mean K ≈ 2.81, so
`m = 2`, `r/N ≈ 0.81`.)

---

## 7. Statistical plan

### 7.1 Units and resampling

The resampling unit is the **task instance** (D-13); the four trajectories of an
instance are not independent observations. Paired instance-level percentile
bootstrap, **10,000 replicates, seed 20260802**. Every comparison against a
baseline is paired on the instance.

### 7.2 Primary analysis

1. `reward(adaptive) − reward(fixed K=4)`, paired, 95% CI → **H1** if lower
   bound > −0.05.
2. Mean trajectories per instance, 95% CI → **H2** if upper bound < 3.0.
3. Reported alongside, not gating: total model tokens, tool calls, wall time,
   the fraction stopping at K=2/3/4, the abstention rate, and both reward
   accountings (abstention charged as 0; and accuracy among answered).

Reward is the **official** `BiomniEval1._compute_reward` via
`evaluation.OfficialEvaluator`, never re-implemented.

**Abstention is always scored two ways** and both are reported side by side:
`reward` charges an abstention as 0, `reward_answered_only` is the accuracy over
answered instances with coverage stated. Abstention may never be allowed to
silently inflate an accuracy.

### 7.3 The ordering question — pre-registered because Phase 2A found it matters

Prospectively there is exactly **one realized arrival order per instance**. Phase
2A's §1.1 showed a single ordering can move fixed-K=4 by up to 8 pp on 50
instances (range 0.540–0.620 across the 24 orderings), because ties break by
arrival. Therefore:

* **Primary:** baselines evaluated at the **realized generation order**. This is
  what actually happened and it is the honest paired comparison.
* **Secondary (S5):** baselines averaged over all 24 orderings of the shadow
  pool. The adaptive controller has only its realized path, so its
  ordering-averaged counterpart is the offline replay of the same policy on the
  Phase-2B pool, reported as such and labelled a replay.

Both are pre-registered here so that neither can be selected after the fact.

### 7.4 Multiplicity and interpretation

Two co-primary hypotheses, both required — no alpha adjustment is needed for a
conjunction. Secondary hypotheses are exploratory in the multiplicity sense and
are labelled so; no secondary result is presented as confirmatory. The bootstrap
"p-value" reported by `analysis.paired_bootstrap_difference` is descriptive
only, as in Phase 1.

### 7.5 What would falsify the Phase-2A recommendation

Stated in advance, so the outcome cannot be reframed:

* **H1 fails** (lower CI bound ≤ −0.05): mandatory K=2 loses real accuracy
  prospectively. The offline equality was an artifact of replaying a fixed pool.
  Report it and do not deploy the policy.
* **H2 fails** (mean K CI upper ≥ 3.0): the agreement signal is weaker online
  than offline; the cost saving is the entire case for the policy, so without it
  there is no policy.
* **Both fail**: Track A's premise does not survive prospective test, and
  `reports/phase2_plan.md` §1 selects Track C (diversity and difficulty).

---

## 8. Task stratification

Reported per task, with **`rare_disease_diagnosis` shown as its own section and
never folded silently into an aggregate**. Per-task cells are 5 to 25 instances;
everything at task level is directional and is labelled directional. The
carried-forward Phase-1.5 caveat stands: this task's residual failure rate is
a known, task-scoped limitation, not evidence of uniform performance.

---

## 9. Compute budget

Measured throughput, not guessed:

| source | config | trajectories | wall | rate |
| --- | --- | ---: | ---: | ---: |
| `phase1` | unrepaired, 2 replicas, concurrency 8 | 208 | 10.20 h | 20.4 /h |
| `phase1_5` | **repaired (Arm 2)**, 1 replica | 42 | 1.92 h | 21.9 /h |

The repaired configuration achieved a *higher* rate on *half* the hardware,
because bounding the runaway generations stopped them monopolising slots. Mean
wall time per trajectory fell from 577 s to 324 s.

**Phase 2B: 600 trajectories.** The controller also serializes *within* an
instance (trajectory *j+1* cannot start until the decision on *j* is committed),
but not across instances, so with 150 instances and concurrency 8 the run stays
work-bound rather than latency-bound.

| scenario | assumption | estimate |
| --- | --- | ---: |
| conservative | Phase-1 packing efficiency (41%), 450 s/trajectory | **~23 h** |
| expected | Phase-1.5-like packing (70%), 400 s/trajectory | **~12 h** |

**Plan: 2 Slurm jobs of 12 h on one 4×H100 node** (≈**80–96 GPU-hours**), using
the existing tested resumption path — Phase 1 already exercised a mid-run
relaunch. If throughput matches Phase 1.5, one job may suffice.

Predicted split of the 600: ~422 consumed by the controller, ~178 shadows.

---

## 10. Smoke test (requires separate approval before it runs)

**Not part of the prospective sample.** Experiment ID `phase2b_smoke`, on
instances drawn from the 233 reserved, never from the 150.

| check | pass condition |
| --- | --- |
| Multi-task coverage | ≥ 6 instances spanning ≥ 4 task families, including `rare_disease_diagnosis` |
| Controller executes online | every instance has a decision at every step; no step lacks one |
| Hash chain intact | decision log verifies end to end |
| Shadow isolation | every shadow trajectory's start timestamp is **after** the commit of the final decision for its instance |
| Leakage | no ground truth, reward, or shadow field appears in any controller input record |
| Stopping | at least one instance stops at K=2 and at least one reaches K=4 |
| Failure override | if a failure occurs, the controller continues rather than accepting it |
| Cost accounting | consumed + shadow = 4 per instance, exactly |
| Aggregation | `aggregate` and the analysis pipeline run end to end and produce tables |

A smoke failure blocks the full launch. Smoke results are reported before the
full run is requested.

---

## 11. Stopping and failure-handling rules

**Trajectory-level.**

* *Infrastructure* failures (`model_server_failure`, `model_timeout`,
  `external_resource_failure`) are retried up to 2 attempts with the original
  preserved (D-14). They are not agent behaviour.
* *Agent-side* outcomes — budget termination, degeneration, context overflow,
  unparseable answer — are **never retried**. They are genuine observations and
  are exactly what the failure override exists to see. Retrying them would
  manufacture the recovery the experiment is measuring.

**Run-level halt conditions.** If any of these trips, halt, report, and do not
analyze as planned:

* `model_context_overflow` + degeneration exceeds **15%** of completed
  trajectories — the Phase-1.5 repair has regressed and the pool would be
  dominated by an artifact again (Phase-1.5 measured 8.0%).
* More than **10%** of instances fail to produce any trajectory at all.
* The decision-log hash chain fails to verify, or any shadow trajectory
  predates its instance's final decision commit. Either means the isolation
  guarantee is broken and the run is not prospective evidence.

**No mid-run tuning.** The controller config is frozen. If a change proves
unavoidable, the run stops, the change is logged as a deviation with its reason,
and the experiment restarts under a **new experiment ID**.

---

## 12. Deliverables

* `reports/phase2_report.md` — prospective results
* complete run provenance per trajectory (existing schema)
* the controller decision log with action, reason and hash chain
* paired reward–cost analysis, selective risk/coverage, failure recovery
* task-specific results with `rare_disease_diagnosis` separate
* every deviation from this protocol, logged as a deviation

## 13. Deviations from this protocol

*(none yet — this section is appended to during the run, never rewritten)*

---

## 14. Launch commands

Nothing below runs without explicit approval.

```bash
# 0. Already done: manifest frozen and hashed (§ header).
#    Verify before launching anything:
python - <<'PY'
import json, sys; sys.path.insert(0, "src")
from biomni_uncertainty.benchmark import ManifestEntry, manifest_hash
e = [ManifestEntry(**json.loads(l)) for l in open("manifests/phase2b.jsonl")]
assert manifest_hash(e) == "7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd"
print("manifest hash verified:", len(e), "instances")
PY

# 1. Smoke test  (REQUIRES APPROVAL)
scripts/run_phase2b.sh configs/cluster.yaml configs/phase2b_smoke.yaml

# 2. Full prospective run  (REQUIRES SEPARATE APPROVAL, after smoke review)
scripts/run_phase2b.sh configs/cluster.yaml configs/phase2b.yaml

# 3. Analysis (CPU only, after the run completes)
python -m biomni_uncertainty.cli aggregate --config configs/phase2b.yaml
python scripts/phase2b_analyze.py --config configs/phase2b.yaml
```

`scripts/run_phase2b.sh`, `configs/phase2b_smoke.yaml`, the online controller
driver and `scripts/phase2b_analyze.py` are **not yet written** — they are the
implementation step that follows approval of this protocol. Nothing in this
document depends on them.
