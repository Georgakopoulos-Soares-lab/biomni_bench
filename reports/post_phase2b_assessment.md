# Post-Phase-2B assessment — independent review before any redesign

**Written:** 2026-08-10, after Phase 2B was complete and reported, by a session
that read the repository rather than the project history. **Nothing frozen was
modified.** Every number below was recomputed from stored artifacts by an
independent script (`scripts/` untouched; the reproduction harness ran from a
scratch directory and wrote nothing into any experiment output tree).

**Purpose.** Decide, on the evidence, whether one redesigned-controller
prospective experiment is justified before the project moves to Track C — and
say what would count as success and what would end the line of work.

> **Evidence class of this document: MIXED and labelled inline.** §2 and §3 are
> confirmatory (pre-registered, prospective). §4 and §5 are **exploratory
> re-analysis of already-used prospective data** and can never be reported as
> validation of anything. §6–§8 are judgements.

---

## 0. Verification performed before writing

| check | result |
| --- | --- |
| `pytest -q` (agent env, Python 3.12) | **369 passed** |
| H1, H2, coverage, selective table, matched-compute, S4, sensitivity | **all reproduce exactly** from `p2b_pooled_trajectories.csv` + the on-disk decision logs, via an independent script that does not import `scripts/phase2b_analyze.py` |
| controller re-simulated offline vs. what the online controller committed | **0/150 mismatches**; all 150 hash chains verify |
| corrected halt gate, **failure path deliberately exercised** | `phase2b_verify.py` on `phase2b_smoke`: **BLOCKED, exit code 1**, 9/24 = 37.5%. On `phase2b`: **BLOCKED, exit code 1**, 93/600 = 15.5%. Every other gate passes in both. |
| manifest hash | `7cb5da3a…` matches the frozen value |

Two process findings that are **not** in the existing record:

* **The gate's negative path is now proven, including its exit code.** D-27
  records the fix and a unit-level regression test. It did not record an
  end-to-end exercise against real failing data. That has now been done: the
  script returns **1** and prints `VERDICT: BLOCKED`, which is what an
  unattended launcher consumes. Before Phase 2B this had never been run against
  data that should fail.
* **The code that produced the prospective result is not in git.** Every Phase-2B
  run's `metadata.json` records `project_git.commit = 2c0bfc1`, `dirty = true`.
  `src/biomni_uncertainty/controller.py`, `scripts/phase2b_run.py`,
  `scripts/phase2b_analyze.py`, `scripts/phase2b_verify.py`,
  `tests/test_controller.py`, `tests/test_phase2b_analyze.py` and
  `reports/phase2_report.md` are **untracked**; `DECISIONS.md`,
  `PROJECT_STATUS.md`, `CLAUDE.md` and `reports/phase2_protocol.md` are modified
  and uncommitted. The result itself is safe — it reproduces bit-exactly from
  on-disk artifacts — but *the exact controller that ran cannot currently be
  recovered from git history*. For a pre-registered prospective experiment that
  is a real provenance gap, and it must be closed before a second one is
  launched.

---

## 1. What exactly did Phase 2B falsify?

**Precisely this and no more:** the specific frozen policy

> mandatory K=2 → ACCEPT the instant two *usable* trajectories share a canonical
> answer → otherwise continue to K=4 → ACCEPT the K=4 plurality if any two agree
> → otherwise ABSTAIN

fails both co-primary endpoints on 150 held-out instances:

| | value | pre-registered rule | verdict |
| --- | --- | --- | --- |
| **H1** reward vs fixed K=4 | −0.033, 95% CI [−0.067, −0.007] | CI lower > −0.05 | **FAIL** |
| **H2** mean K | 2.893, 95% CI [2.760, **3.033**] | CI upper < 3.0 | **FAIL** |

That verdict is correct, is not softened here, and is not reinterpreted. Two
things make it robust rather than an unlucky draw: the ordering-averaged replay
of the same trajectories moves in the same direction (S5), and excluding the
oversampled high-risk task reproduces it almost exactly (−0.032, mean K 2.856).

**A sharper way to state the falsification, which the existing report does not
state.** The frozen controller is **dominated by fixed K=2 on both axes at
once**: fixed K=2 scores **0.580** at mean K exactly **2.00**, the controller
**0.573** at mean K **2.893**. The reward difference is not significant
(−0.007, 95% CI [−0.047, +0.033]), but there is no axis on which the adaptive
policy is ahead of the simplest non-adaptive alternative. It is also behind the
matched-compute random allocation (0.5919 vs 0.573). *An adaptive controller
that loses to blind allocation at equal compute, and to a fixed budget it
outspends by 45%, has not earned its complexity.* That is the falsification
stated at full strength.

**What was NOT falsified.** Four things people could wrongly read into this:

1. **Not** "consensus carries no signal." It carries a lot, prospectively —
   see §2.
2. **Not** "there is no headroom." Oracle@4 on the held-out pool is **0.700**
   against fixed K=1's 0.513 and fixed K=4's 0.607 (**9.3 pp** still on the
   table above the best deployable fixed policy).
3. **Not** "abstention is a bad idea." S2 passed: the abstained set really is
   harder. What failed is abstaining *and being charged 0 for it* under an
   accounting the protocol itself mandated.
4. **Not** "adaptive allocation is impossible in principle." It is a statement
   about one rule with one action set (`ACCEPT`/`CONTINUE`/`ABSTAIN`, where
   `CONTINUE` means only *resample*).

---

## 2. Which claims from Phases 1 / 1.5 / 2A still survive?

### Survive, and are now independently confirmed *prospectively*

| claim | origin | prospective status on the 150 held-out instances |
| --- | --- | --- |
| Agreement is the strongest cheap correctness signal | P1 (AUROC 0.874 → 0.815 pooled) | **Strongly confirmed.** Terminal K=4 state → accuracy: **4-of-4 97.8%** (n=46), **3-of-4 76.7%** (n=30), **2-of-4 42.2%** (n=45), **no two agree 13.8%** (n=29). A monotone, steep gradient on data no one had seen. |
| Oracle headroom is real | P1 (16–20 pp) | **Confirmed, smaller.** 0.700 vs 0.513 (K=1) = 18.7 pp; vs 0.607 (K=4) = 9.3 pp. |
| Sampling more helps, with diminishing returns | P1/P2A | **Confirmed.** 0.513 / 0.580 / 0.593 / 0.607 for K=1/2/3/4. |
| Failure recovery from a dead first trajectory is real and free | P2A (§8) | **Confirmed (S3).** 32/150 instances opened on a failure; the controller resolved 53.1% to a real answer, fixed K=1 resolves 0%. |
| Verbalized confidence ranks but does not calibrate | P1/P1.5 | **Confirmed and extended (S4):** `final_confidence == 1.00` → 89.8% correct (44/49) vs 65.1% (267/410). |
| The K=1 acceptance trigger is too weak to use | P2A §5 (negative result, 3/5 folds refused) | **Untouched.** Nothing in Phase 2B tests or contradicts it; it stands. |
| `rare_disease_diagnosis` is a genuine high-risk stratum | P1.5 | **Confirmed.** Residual failure 33.0% vs 12.0% for the other nine tasks pooled. |

### Do **not** survive

| claim | why it no longer holds |
| --- | --- |
| **"Mandatory K=2 reproduces fixed K=4 exactly at 68% of the trajectories"** (P2A headline; reward Δ 0.000 [0.000, 0.000], mean K 2.70) | Prospectively the reward difference is −0.033 [−0.067, −0.007] and mean K is 2.893, not 2.70. The degenerate offline CI was an artifact of replaying a pool in which the two policies happened to return identical answers on all 50 instances. **This is the single largest lesson: a zero-width bootstrap CI from offline replay is a warning sign, not a strong result.** |
| "The abstention rule writes itself: abstain when four trajectories give four different answers" (P2A §9) | The rule is not what it was described as. See §4.1 — in the prospective run it fires overwhelmingly on *failed* trajectories, not on four distinct answers. |
| P2A's selective gradient 0.709 / 0.562 / 0.556 for 2-of-2 / 2-of-3 / 2-of-4 | Directionally right, badly under-stated in magnitude. Prospectively: **0.877 / 0.611 / 0.350**. The offline pool flattened the very contrast the redesign now depends on. |

---

## 3. What new findings from Phase 2B are genuinely prospective?

Confirmatory — pre-registered in `reports/phase2_protocol.md` before any outcome
existed, and therefore usable as evidence:

1. **H1 fails, H2 fails** (§1).
2. **S1 — safety.** Controller confidently-wrong rate **0.0%** (0/150) vs fixed
   K=4 **5.3%** (8/150). Real, but read it with P2A's own caveat: the controller
   never *enters* the high-agreement band, because it stops at support 2. The
   honest statement is "makes no confident claims", not "its confident claims
   are better."
3. **S2 — abstention is well-targeted.** Answered 0.711 vs forced-answer 0.600.
4. **S3 — failure recovery.** 53.1% of failure-opened instances resolved.
5. **S4 — `final_confidence == 1.00`.** 89.8% (44/49) vs 65.1% (267/410).
   Registered as a secondary hypothesis in D-19 *before* the run, so it is a
   clean prospective pass and is **eligible** for a future controller.
6. **S5 — ordering robustness.** Same direction under ordering-averaged replay.
7. **The matched-compute comparison** (D-24, pre-registered): −0.019, 95% CI
   [−0.053, +0.015]. Not significant, but the wrong sign.
8. **Selective risk by stopping state** (a pre-registered *deliverable*):
   0.877 / 0.611 / 0.350 at k = 2 / 3 / 4.

A necessary distinction on item 8: the **table** is pre-registered; the
**rule you would write from it** is not. Producing the selective table was
planned; deciding to abstain at 2-of-4 *because* this table came out this way is
a post-hoc decision and inherits none of the table's confirmatory status.

**A caveat on S4 the report does not carry.** Confidence is parseable in only
**52.1%** of parseable answers (239/459). The "rest" group of 410 therefore
mixes 190 trajectories that stated a confidence below 1.00 with 218 that stated
none at all. Among trajectories that *did* state a value, the contrast is
0.898 (n=49) vs 0.500 (n=190) — larger, not smaller. But a controller keying on
this signal is blind roughly half the time and needs a defined fallback. That is
a design constraint, not a refutation.

---

## 4. Which findings are post-hoc mechanism analyses?

Everything in this section is **exploratory re-analysis of already-used
prospective data**. It may motivate a new experiment. It may never be cited as
evidence for a claim.

### 4.1 The frozen abstention rule is mostly a failure detector, not a disagreement detector

Decomposing the 29 abstentions by how many of the four trajectories were
*usable at all*:

| abstention cause | n | K=4-plurality reward there | Oracle@4 there |
| --- | ---: | ---: | ---: |
| **≤1 usable trajectory** (dead/unparseable — a failure, not a disagreement) | **15** | 0.200 | 0.200 |
| ≥2 usable, every answer distinct (genuine 4-way disagreement) | 14 | 0.071 | 0.357 |

Over half the abstentions happen because the instance produced fewer than two
opinions, not because it produced conflicting ones. This matters for two
reasons:

* It **qualifies §7 of `reports/phase2_report.md`.** That sensitivity analysis
  removes `rare_disease_diagnosis` and shows H1/H2 unchanged, which is correct —
  but it does not remove the failure confound, because the residual failure rate
  is still **12.0%** across the other nine tasks. The halt condition that the
  broken gate hid is therefore *entangled with the controller's headline
  behaviour*, not merely adjacent to it. The paired contrast remains valid
  (fixed K=4 is scored on the same damaged trajectories), so **the H1/H2
  verdicts stand**. What does not stand is the implication that data quality is
  irrelevant to the mechanism.
* It means "redesign the abstention rule" and "reduce the residual failure rate"
  are partly the same intervention.

### 4.2 Abstention accounts for 80% of the H1 gap — and removing it does not rescue the policy

Reward forgone by abstaining (the K=4 plurality would have scored 4 of those 29
instances correct) = 4/150 = **0.0267**, against an H1 gap of 0.0333.

So a no-abstention variant of the same controller would score ≈ **0.600** vs
fixed K=4's 0.607 — inside the δ = 0.05 margin, i.e. **H1 would have passed**.
But:

* **H2 still fails** (mean K unchanged at 2.893, CI upper 3.033);
* it would still sit at 0.600 against matched-compute's **0.592** — a margin of
  **+0.8 pp**, far inside the noise;
* and it would forfeit S1 and S2, the two genuine wins.

**This is the central, uncomfortable number in the whole assessment.** The best
case for any rule confined to *when to stop resampling* is roughly one point of
reward over blind allocation at the same cost.

### 4.3 Continuing past a k=2 disagreement buys almost nothing

Restricted to the 85 instances with no valid agreement at k=2 — exactly the
population any consensus-history rule operates on:

| what you do with those 85 | reward |
| --- | ---: |
| take the first trajectory (K=1) | 0.235 |
| answer at k=2 anyway (fixed K=2's tiebreak) | 0.353 |
| **continue to K=4 and take the plurality** | **0.400** |
| Oracle@4 on the same 85 | 0.529 |

Two more trajectories per instance buy **+4.7 pp** on this subset (+2.7 pp on
the full sample). The mechanism works — it is just very weak, and the deployable
ceiling above it (0.400 → 0.529) is only 12.9 pp even with a perfect selector.

### 4.4 Errors are strongly correlated, which is the Track-C premise measured directly

| distinct usable answers among 4 | instances | K=4 plurality | Oracle@4 |
| ---: | ---: | ---: | ---: |
| 0 (all failed) | 6 | 0.000 | 0.000 |
| 1 (unanimous) | 91 | 0.791 | 0.791 |
| 2 | 40 | 0.375 | **0.625** |
| 3 | 11 | 0.273 | **0.636** |
| 4 | 2 | 0.500 | 0.500 |

* **45 of 150 instances (30%) have no correct trajectory at all** — no selector,
  no controller and no amount of resampling can fix those.
* On the 91 unanimous instances, all four trajectories agree; **exactly one** is
  unanimously wrong. Unanimity is nearly safe.
* The action is in the 51 split instances: selection captures 0.375/0.273 where
  an oracle gets 0.625/0.636. **~25 pp of recoverable headroom sits in
  disagreement cases, and voting cannot reach it** — the right answer is present
  but in the minority.

That last row is the strongest empirical argument in this document *for* the
Track-C question as the prompt frames it: when trajectories disagree, the
information needed to adjudicate is not in the vote count.

### 4.5 `final_confidence == 1.00` adds little *on top of* consensus history

Within the controller's own stopping states, splitting by whether the winning
cluster contains a trajectory stating 1.00:

| stopped at | without conf=1.00 | with conf=1.00 |
| --- | ---: | ---: |
| k=2 (2-of-2) | 0.841 (n=44) | **0.952 (n=21)** |
| k=3 (2-of-3) | 0.613 (n=31) | 0.600 (n=5) |
| k=4 (2-of-4) | 0.316 (n=19) | 1.000 (n=1) |

The signal's incremental value is concentrated in the state that is *already*
87.7% accurate, where there is almost nothing to gain, and it vanishes in the
weak states where a controller would actually need it (n=5 and n=1 — too small
to read either way). **Per the prompt's own instruction, this is the test of
whether confidence adds decision value beyond consensus history, and on existing
data the answer is: not where it matters.** It should not enter a Controller-v2
primary rule. It remains worth carrying as a secondary prospective analysis.

---

## 5. Does the evidence justify one redesigned-controller experiment before Track C?

**My assessment: not on the evidence available today, and probably not at all —
but the question deserves the cheap offline test rather than a judgement call.**

The case *for* a redesign (as the prompt frames it) rests on the 0.877 / 0.611 /
0.350 gradient being actionable. The case *against* is arithmetic:

1. The entire achievable gain from any stop-rule redesign is bounded by §4.2's
   ~1 pp over matched compute and §4.3's +4.7 pp over answering at k=2.
2. Phase 2B was powered at 0.99 to detect a δ = 0.05 effect. An effect of
   ~0.01–0.02 would need a far larger sample; at n=150 a Controller-v2 run would
   be **underpowered for the effect it is now plausible to expect**, which means
   a likely-inconclusive prospective result at 80–96 GPU-hours.
3. The redesign's active ingredient — "treat 2-of-4 differently from 2-of-2" —
   would have to beat *fixed K=2*, which already gets 0.580 for 2.00
   trajectories and no logic at all.
4. Every prospective run consumes held-out instances. **233 remain** of 433.
   Spending 150 more on a ~1 pp question leaves ~83 for the question in §4.4,
   which is the larger one.

**Therefore: do not authorise a Controller-v2 prospective run on the strength of
this assessment.** Run the CPU-only offline redesign analysis first
(`reports/controller_v2_offline_assessment.md`), and recommend a prospective run
**only if** it clears a bar stated in advance, here, before the analysis is run:

> **Pre-stated bar for recommendation A.** Some rule that is (a) parameter-free
> or has at most one integer parameter, (b) beats matched-compute random
> allocation by **≥ 3 pp** point estimate, (c) beats **fixed K=2** on reward
> without spending more than **2.5** mean trajectories, and (d) does so on
> **both** the Phase-2A pool (n=50) and the Phase-2B pool (n=150) with the rule
> fixed on one and evaluated on the other — in both directions.

Requirement (d) is the important one. Any rule chosen by inspecting Phase-2B's
selective table and then evaluated on Phase-2B is circular; the two pools give
the only out-of-sample check available without new GPU time.

---

## 6. What is the smallest decisive experiment?

**It is not a GPU experiment.** The smallest decisive step is the CPU-only
offline replay described above: existing trajectories, ~minutes, no model calls,
no held-out instances consumed. It is decisive because the quantity in doubt —
does *any* consensus-history rule beat matched compute by enough to be worth
150 held-out instances — is fully determined by data already on disk.

If that analysis clears the §5 bar, the smallest decisive *prospective*
experiment is a new frozen run with:

* a new experiment ID and a new held-out manifest from the 233 reserved
  instances, with zero overlap asserted against `phase1` **and** `phase2b`;
* **primary comparison against matched-compute random allocation and fixed K=2**
  — not against Controller v1, which is the weakest possible comparator and
  would let a null result masquerade as progress;
* a power calculation done for the effect size the offline analysis actually
  produces, not for δ = 0.05 carried over from Phase 2B;
* the residual-failure halt condition checked by the **now-exercised** gate,
  with the negative path re-run against injected failing data before launch;
* all code committed, so `project_git.dirty` is `false` in every run record.

If it does not clear the bar, the smallest decisive next experiment is the
Track-C measurement in §4.4 — which is *also* CPU-only to begin with: on the
51 split instances plus Phase 1's, measure whether disagreement corresponds to
different plans and tool paths or merely to noisy final answers. That
determines whether "generate a genuinely independent verification" is a
mechanism with anything to work on, before a single GPU hour is spent on it.

---

## 7. What would count as a successful result?

For a Controller-v2 prospective run, stated before anything is built:

* **Primary.** Reward exceeds the matched-compute random allocation at its own
  realized cost, with a 95% paired instance-level bootstrap CI excluding 0.
  Nothing weaker counts — a controller that ties blind allocation has not
  demonstrated a reliability layer.
* **Co-primary.** Mean K CI upper bound below 2.5, *and* reward not below fixed
  K=2's. A rule that needs ~3 trajectories to beat a 2-trajectory baseline is
  not a cost-aware controller.
* **Secondary, non-gating.** Confidently-wrong rate no higher than fixed K=4's;
  selective accuracy at ≥85% coverage above full-coverage accuracy; failure
  recovery retained; `final_confidence == 1.00` re-tested as a signal the
  primary rule does not use.

Note what is deliberately **absent**: "beats Controller v1". Controller v1 loses
to fixed K=2 and to random allocation. Beating it is not evidence of anything.

---

## 8. What would cause us to stop pursuing adaptive verification?

Any one of these should end the line of work rather than prompt another
iteration:

1. **The offline analysis fails the §5 bar.** Then no stop-rule redesign has a
   demonstrable effect worth a prospective run, and the honest conclusion is
   that *resampling-and-voting is not where reliability lives in this system*.
2. **A Controller-v2 prospective run fails its primary comparison against
   matched compute.** Two pre-registered prospective failures of the same
   premise, with the mechanism understood, is a result — and it is publishable
   as one. It is not an invitation to a third rule.
3. **Rule complexity grows without matched gains.** If beating blind allocation
   requires fitted thresholds, a learned model, or per-task parameters on 150
   instances, the thing being measured is the fitting procedure. The standing
   50-instance constraint in `reports/research_north_star.md` applies.
4. **The recoverable headroom keeps shrinking under honest accounting.**
   Oracle@4 − fixed K=4 was 16 pp on the repaired Phase-1 pool and is 9.3 pp
   prospectively. If it shrinks again on the next pool, selection among
   correlated samples is exhausted regardless of the rule.
5. **The residual failure rate cannot be brought under the 15% halt threshold.**
   At 15.5% overall (12.0% excluding the high-risk task), roughly one trajectory
   in seven is dead. Below some quality floor a reliability controller is
   measuring infrastructure, not epistemics, and the correct project is the
   repair — not the controller.

**What would *not* be a reason to stop, and should be preserved either way:**
the S1/S3 safety-and-recovery findings, the failure-override design, the
leakage barrier, the hash-chained decision log, and the confirmatory/exploratory
discipline. Those are the parts of this project that transfer to another agent
regardless of whether the controller idea survives.

---

## 9. Bottom line

* Phase 2B is a real prospective falsification. Track C is the pre-registered
  selection and stays selected.
* The mechanism is understood, but understanding it makes a redesign look
  *less* attractive, not more: the ceiling for any stop-rule change is ~1 pp
  over blind allocation at equal cost, on a policy that is currently dominated
  by fixed K=2.
* The genuinely interesting finding for what comes next is §4.4: **the answer is
  present but in the minority on ~51 instances where voting cannot reach it, and
  absent entirely on 30%.** That is a statement about *evidence*, not about
  *voting rules*, and it points at the Track-C question the prompt describes.
* Next step, and the only thing that should happen before a decision:
  `reports/controller_v2_offline_assessment.md` — CPU only, no GPU, no new
  manifest, judged against the bar in §5 written before it was run.
