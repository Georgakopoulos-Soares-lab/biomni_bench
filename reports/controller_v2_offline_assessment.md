# Controller-v2 — offline redesign assessment

**Written:** 2026-08-10. **Experiment:** `controller_v2_offline` (analysis-only,
new ID). **CPU only, ~40 s, no model calls, no GPU, no new held-out instance
consumed.** Driver: `scripts/controller_v2_offline.py`. Tests:
`tests/test_controller_v2_rules.py` (13). Full suite: **382 passed**, lint clean.

> **EVIDENCE CLASS: OFFLINE REPLAY, EXPLORATORY.** Every number below is a
> replay of trajectories that already exist, on two pools that have both already
> been used — `phase1_pooled` (the pool Controller v1 was *designed* on) and
> `phase2b` (the pool Controller v1 was *falsified* on). **Nothing here is
> prospective evidence and nothing here validates any policy.** Its only job is
> to decide whether a new prospective experiment is justified.

> **RECOMMENDATION: B — MOVE DIRECTLY TO TRACK C.** The pre-stated bar in
> `reports/post_phase2b_assessment.md` §5 is not met, and it is not met by a
> narrow margin. More importantly, the analysis produced a *structural* reason
> why no rule of this shape can meet it (§4), which is a stronger result than
> the failure of any particular candidate.

---

## 1. What was replayed

18 policies, **none with a fitted parameter**, each expressible in one sentence.

| policy | rule |
| --- | --- |
| `fixed_k1` … `fixed_k4` | spend exactly K, answer by plurality |
| **`v1_frozen`** | Controller v1 exactly as frozen: mandatory K=2, ACCEPT on any 2-agreement, ABSTAIN at K=4 if no two agree |
| `v1_no_abstain` | as above, but accept the K=4 plurality instead of abstaining |
| **`v2_majority`** | **the prompt's candidate**: accept only on a strict majority of trajectories seen — 2-of-2 ✓, 2-of-3 ✓, 3-of-4 ✓, **2-of-4 ✗** — abstain otherwise |
| `v2_majority_no_abstain` | strict majority, accept the K=4 plurality rather than abstain |
| `v2_usable_majority` | strict majority among *usable* trajectories; dead runs get no vote |
| `v2_usable_majority_no_abstain` | as above without abstention |
| `v2_unanimous` | every usable trajectory agrees |
| `v2_abstain_on_failure_only` | escalate **only** when no usable trajectory exists; accept weak-but-real answers |
| `v2_no_abstain_k3` | mandatory K=2, stop on agreement, accept the K=3 plurality (cheapest continuing rule) |
| `v2_k3_cap`, `v2_majority_k3`, `v2_abstain_on_failure_only_k3`, `v2_k2_or_abstain` | cheaper caps of the above |
| `v2_majority_or_conf1` | strict majority **or** a bare plurality whose winning cluster states `final_confidence == 1.00` |

Three replay views, all reported, never mixed:

* **`phase2b_realized`** — the single arrival order the prospective run actually
  drew. This is the honest analogue of what a new prospective run would return.
* **`phase2b_all_orderings`** — all 24 orderings, exhaustive.
* **`phase1_pooled_all_orderings`** — the Phase-2A pool, all 24 orderings.

`v1_frozen` is asserted byte-for-byte equal to `controller.build_controller`'s
output across every state and ordering
(`test_v1_frozen_reproduces_the_frozen_phase2b_controller`), so the incumbent
cannot silently drift.

**Oracle@4 (UPPER BOUND, not deployable):** 0.700 on `phase2b`, 0.640 on
`phase1_pooled`.

---

## 2. Headline table

Reward charges abstention 0, exactly as the Phase-2B protocol mandates.
`vs matched-compute` is D-24's runnable equal-cost blind allocation at *each
policy's own realized cost*. Bootstrap: 10,000 paired instance-level replicates,
seed 20260810 (a new stream, not Phase 2B's).

### phase2b, realized order (n=150) — the honest single-draw view

| policy | reward | mean K | coverage | vs matched-compute [95% CI] | vs fixed K=2 [95% CI] |
| --- | ---: | ---: | ---: | --- | --- |
| fixed K=4 | 0.607 | 4.00 | 1.00 | — | +0.027 [−0.007, +0.067] |
| `v1_no_abstain` ≡ `v2_majority_no_abstain` ≡ `v2_usable_majority_no_abstain` | 0.600 | 2.89 | 1.00 | +0.008 [−0.021, +0.038] | +0.020 [−0.020, +0.060] |
| fixed K=3 | 0.593 | 3.00 | 1.00 | — | +0.013 [−0.013, +0.040] |
| **`v2_abstain_on_failure_only`** | **0.593** | **2.13** | 0.96 | **+0.012 [−0.003, +0.032]** | **+0.013 [ 0.000, +0.033]** |
| `v2_no_abstain_k3` | 0.593 | 2.57 | 1.00 | +0.006 [−0.006, +0.017] | +0.013 [−0.013, +0.040] |
| **fixed K=2** | **0.580** | **2.00** | 1.00 | — | — |
| **`v1_frozen`** (the falsified incumbent) | 0.573 | 2.89 | 0.81 | −0.019 [−0.053, +0.015] | −0.007 [−0.053, +0.033] |
| `v2_usable_majority` | 0.560 | 2.89 | 0.77 | −0.032 [−0.064, −0.006] | −0.020 [−0.060, +0.020] |
| `v2_majority_or_conf1` | 0.533 | 2.89 | 0.68 | −0.059 [−0.099, −0.025] | −0.047 [−0.093, −0.007] |
| **`v2_majority`** ← *the prompt's candidate* | **0.527** | 2.89 | 0.67 | **−0.065 [−0.107, −0.027]** | **−0.053 [−0.100, −0.013]** |
| fixed K=1 | 0.513 | 1.00 | 1.00 | — | −0.067 |
| `v2_unanimous` | 0.500 | 2.99 | 0.63 | −0.093 [−0.132, −0.058] | −0.080 |
| `v2_k2_or_abstain` | 0.380 | 2.00 | 0.43 | −0.200 | −0.200 |

### The same ranking holds on both other views

| policy | phase2b, 24 orderings | phase1_pooled, 24 orderings |
| --- | ---: | ---: |
| `v1_no_abstain` (≡ both majority twins) | 0.613 @ K 2.87 | 0.577 @ K 2.70 |
| fixed K=4 | 0.613 @ K 4.00 | 0.577 @ K 4.00 |
| `v2_no_abstain_k3` | 0.608 @ K 2.54 | 0.555 @ K 2.47 |
| `v2_abstain_on_failure_only` | 0.603 @ K 2.15 | 0.527 @ K 2.04 |
| fixed K=2 | 0.581 @ K 2.00 | 0.525 @ K 2.00 |
| `v1_frozen` | 0.577 @ K 2.87 | 0.560 @ K 2.70 |
| **`v2_majority`** | **0.520** @ K 2.87 | **0.510** @ K 2.70 |

---

## 3. The redesign hypothesis is falsified offline, before any GPU time

The prompt's Controller-v2 candidate — *"a 2-of-4 outcome should not be treated
as equivalent to 2-of-2; complete disagreement should remain an
abstention/escalation state"* — is `v2_majority`. It is **the worst
consensus-history rule tested**, and it is worse than the incumbent it was meant
to fix:

| | phase2b realized | phase2b 24-ord | phase1_pooled |
| --- | ---: | ---: | ---: |
| `v1_frozen` | 0.573 | 0.577 | 0.560 |
| `v2_majority` | 0.527 | 0.520 | 0.510 |
| **difference** | **−4.7 pp** | **−5.7 pp** | **−5.0 pp** |

Consistent in sign and magnitude on both pools and both replay conventions.

**Why, in one line.** The 2-of-4 state is **35–42% accurate**, not 0% accurate.
Refusing it converts a 0.40-expected-reward answer into a certain 0. The
selective table that motivated the redesign (0.877 / 0.611 / 0.350) shows that
2-of-4 is *relatively* bad; the redesign then treats "relatively bad" as
"worthless", and the arithmetic of `reward_abstain_zero` punishes that
immediately. Escalating a 35%-accurate answer is only a gain if abstention is
*worth* something — which is a different accounting than the one the protocol
mandated, and adopting it after seeing this result would be exactly the kind of
metric substitution D-26 refused.

The confidence-augmented variant does not rescue it: `v2_majority_or_conf1`
recovers +0.7 pp (phase2b) / +1.0 pp (phase1_pooled) over `v2_majority` and
remains far below both `v1_frozen` and plain fixed K=2. **Answering the prompt's
explicit question — does `final_confidence == 1.00` add decision value beyond
consensus history, tested on existing data only — the answer is no.** It should
not enter a primary controller.

---

## 4. The structural finding: consensus history has nowhere to act

This is the most important result in the document, and it is a fact about the
action set rather than about any candidate.

**`v1_no_abstain`, `v2_majority_no_abstain` and `v2_usable_majority_no_abstain`
are the identical policy.** Same reward, same mean K, same coverage, same
per-instance decisions, on all three views — and asserted in
`test_without_abstention_consensus_history_cannot_change_any_decision`.

The reason is mechanical. Within the frozen action set
{`ACCEPT`, `CONTINUE`, `ABSTAIN`} where `CONTINUE` means only *resample*,
knowing that support is 2-of-4 rather than 2-of-2 can change exactly two things:

1. **spend more** — but 2-of-4 is only reachable at K=4, where the budget is
   already exhausted and there is nothing left to spend; or
2. **abstain** — which §3 shows is net-negative under the mandated accounting.

There is no third option. **The distinction the redesign is built on is
therefore unactionable in this action space, by construction.** A Controller-v2
prospective run would not be testing a weak hypothesis; it would be testing a
hypothesis that cannot express itself.

To act on "how consensus formed", the controller needs an action it does not
have: `VERIFY` (seek independent evidence) or `REPAIR` (fix the workflow rather
than resample around it). Both are listed as unimplemented in
`reports/phase2_protocol.md` §2.1 and `reports/phase2_report.md` §10.5. **That
observation routes directly to Track C**, and it arrives from the controller
side rather than by assumption.

---

## 5. What *does* survive: failure-driven continuation, and only that

Two candidates beat both fixed K=2 and matched compute on point estimate:

| | reward | mean K | vs matched-compute | vs fixed K=2 | failure recovery |
| --- | ---: | ---: | ---: | ---: | ---: |
| `v2_abstain_on_failure_only` (phase2b realized) | 0.593 | **2.13** | +0.012 [−0.003, +0.032] | +0.013 [0.000, +0.033] | 0.080 |
| fixed K=2 | 0.580 | 2.00 | — | — | 0.067 |

Its entire edge is **recovery from dead trajectories**, not from disagreement:
it behaves like fixed K=2 except that it keeps sampling when an instance has
produced no usable answer. That reproduces Phase 2A §8's "failure recovery is
free and attributable" as the *only* component of adaptivity that pays for
itself, and it is consistent with the post-hoc finding that 15 of Controller
v1's 29 abstentions had ≤1 usable trajectory.

**But it does not clear the bar, and the per-task table says why:**

| task | n | fixed K=2 | `v2_abstain_on_failure_only` | Δ |
| --- | ---: | ---: | ---: | ---: |
| `gwas_causal_gene_gwas_catalog` | 15 | 0.467 | 0.533 | **+0.067** |
| `rare_disease_diagnosis` | 25 | 0.480 | 0.520 | **+0.040** |
| the other **eight** tasks | 110 | — | — | **0.000** |

The whole effect is **two instances out of 150**, both in tasks with elevated
failure rates. On `phase1_pooled` the same policy's margin over fixed K=2 is
**+0.0017** — one-eighth of an instance. That is not a controller; that is
noise with a good story attached.

---

## 6. Adjudication against the pre-stated bar

`reports/post_phase2b_assessment.md` §5, written before this analysis ran:

| criterion | best achieved | verdict |
| --- | --- | --- |
| (a) parameter-free or ≤1 integer parameter | all 18 candidates qualify | **MET** |
| (b) beats matched-compute by **≥ 3 pp** | best is **+1.8 pp** (`v2_abstain_on_failure_only`, phase2b 24-ord); **+1.2 pp** realized; **+0.05 pp** on phase1_pooled | **NOT MET** |
| (c) beats fixed K=2 at ≤ **2.5** mean K | `v2_abstain_on_failure_only`: K 2.13, +1.3 pp (phase2b) but **+0.17 pp** (phase1_pooled) | **marginally met on one pool, not the other** |
| (d) holds with the rule fixed on one pool and evaluated on the other, **both directions** | the two leading candidates disagree about which is better across pools, and both effects collapse on `phase1_pooled` | **NOT MET** |

**Two of four criteria fail, including the two that matter.** Recommendation A
is not available on this evidence.

### Three further reasons not to spend a prospective run

1. **Power.** Phase 2B was powered 0.99 for δ = 0.05. The largest plausible
   effect here is ~0.01–0.02. A repeat at n=150 would be **underpowered for the
   effect it is now reasonable to expect**, i.e. ~80–96 GPU-hours bought an
   almost-certainly inconclusive answer.
2. **Ordering variance swamps the effect.** Across the 24 orderings, reward
   spread is 0.033 (phase2b) to 0.080–0.100 (phase1_pooled) for the leading
   candidates — **two to eight times the effect being chased**. Note also that
   `v1_frozen` has the *smallest* spread (0.007) purely because abstention
   flattens outcomes; low variance is not a virtue here.
3. **Held-out instances are the scarce resource.** 233 of 433 remain. Spending
   150 on a ~1 pp question leaves ~83 for the question in §7, which is larger.

### The methodological lesson, recorded because it recurs

Phase 2A's fatal error was reading a degenerate offline CI (0.000 [0.000,
0.000]) as a strong result. The same trap is visible here in a milder form:
`v2_no_abstain_k3`'s advantage over matched compute has a CI excluding 0 under
**24-ordering averaging** (+0.013 [+0.006, +0.020]) and a CI **spanning 0** at
the single realized order (+0.006 [−0.006, +0.017]). Ordering-averaged CIs are
narrower than any prospective run can deliver, because a prospective run gets
one draw. **The realized-order column is the one to read when deciding whether
to spend GPU hours.**

---

## 7. Where the remaining headroom actually is

From the same replay, stated because it is what should be attacked next
(exploratory, `phase2b`, n=150):

| distinct usable answers among 4 | instances | K=4 plurality | Oracle@4 | recoverable by *voting* |
| ---: | ---: | ---: | ---: | --- |
| 0 (all trajectories failed) | 6 | 0.000 | 0.000 | nothing exists |
| 1 (unanimous) | 91 | 0.791 | 0.791 | already taken |
| 2 | 40 | 0.375 | **0.625** | **no — 25 pp, minority-held** |
| 3 | 11 | 0.273 | **0.636** | **no — 36 pp, minority-held** |
| 4 | 2 | 0.500 | 0.500 | — |

* **30% of instances (45/150) have no correct trajectory at all.** No stop rule,
  no selector and no amount of resampling touches them.
* On the 51 split instances, the correct answer is **present but in the
  minority**. Voting is definitionally unable to reach it; ~25–36 pp of
  headroom sits there, unreachable by any consensus rule.
* Unanimity is nearly safe: of 91 unanimous instances, exactly **one** is
  unanimously wrong.

**That is the Track-C question, arrived at empirically:** when trajectories
disagree, the information needed to adjudicate is not in the vote count, so the
next intervention has to *produce new evidence*, not re-weight existing votes.

---

## 8. Recommendation

> ## **B — MOVE DIRECTLY TO TRACK C.**

Consistent with `reports/phase2_plan.md` §1's pre-registered selection, which
Phase 2B already triggered. This analysis was the check on whether that
selection should be deferred for one redesign experiment. **It should not.**

Specifically:

1. **Do not build or run Controller v2.** The redesign hypothesis is falsified
   offline (§3) and is structurally unactionable within the current action set
   (§4). Record it as a hypothesis tested and rejected at zero GPU cost — which
   is what this analysis was for.
2. **Do not treat `v2_abstain_on_failure_only` as a finding.** Carry it as an
   observation: the only self-funding adaptive component is continuation on
   failure, worth ~1 pp and concentrated in two instances.
3. **Do not use `final_confidence == 1.00` in a controller.** It survived its
   prospective test as a *signal* (S4) and that stands; it adds nothing on top
   of consensus history where a controller would need it (§3, and
   `post_phase2b_assessment.md` §4.5). Keep it as a secondary prospective
   analysis in whatever runs next.
4. **The first Track-C step is CPU-only, not GPU.** Before any diversity
   mechanism is built, measure on existing traces — Phase 1, Phase 1.5 and
   Phase 2B all preserve full trajectories — whether the 51 split instances
   disagree because of *different plans and tool paths* or merely *noisy final
   answers*. If disagreement is noise, independent verification has nothing to
   work on and Track C should be reframed too. This is the §7 question and it
   costs no GPU time.
5. **Before any future prospective run**, close the two process gaps recorded in
   `post_phase2b_assessment.md` §0: commit the code (Phase 2B's runs record
   `project_git.dirty = true`, and the controller that produced the result is
   untracked), and re-exercise the corrected halt gate's *failure* path —
   already done once here, and it now returns exit code 1 and `VERDICT: BLOCKED`
   on both the smoke and the full run.

**What would reopen the controller question.** A single condition: a `VERIFY` or
`REPAIR` action that generates genuinely independent evidence. With such an
action, "how consensus formed" becomes actionable (§4) and the 25–36 pp of
minority-held headroom in §7 becomes addressable. Until then, further stop-rule
work is measuring the same ~1 pp with more machinery.

---

## 9. Reproduction

```bash
python scripts/controller_v2_offline.py \
    --phase2b-table <output_root>/phase2b/results/tables/p2b_pooled_trajectories.csv \
    --phase1-table  <output_root>/phase1_pooled/results/tables/trajectories.csv \
    --out           <output_root>/controller_v2_offline/results
```

CPU only, ~40 s, deterministic (bootstrap seed 20260810). Reads frozen tables
read-only; writes only under `controller_v2_offline/`. 12 tables:
`summary__*`, `by_task__*`, `selective_v1__*`, `selective_majority__*`, plus
`controller_v2_offline.json`.

**No frozen Phase-0/1/1.5/2A/2B artifact was modified by this work.**
