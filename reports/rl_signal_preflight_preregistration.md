# RL-signal preflight — pre-registration

**Written:** 2026-08-21. **Status: FROZEN.** Committed **before `mixed_reward`,
`reward_variance`, `selection_failure`, or any AUROC/enrichment number in this
study has been computed.** The commit containing this file is the freeze point;
everything below is checked, never adjusted, against the results that follow.

**Subordinate to nothing scientific it did not already inherit.** The scope
study (`reports/scope_study_preregistration.md`, D-44/D-45/D-46) is treated
here as a **frozen input**: its 120-instance, K=4, two-solver-family trajectory
set is reused wholesale, its agreement/self-consistency features and its
official-reward computation are reused unchanged, and none of its numbers
(Pass@1, plurality, Oracle@4, AUROC, verifier gain, the H1 verdict) are
recomputed, revised, or reinterpreted here.

**Boundary, restated because it must survive the whole document.** This is an
**offline analysis of already-consumed frozen trajectories.** No new inference,
no new instance, no RL training. D-43/Stage C, Track-C diversity-by-resampling
(D-30), candidate adjudication (D-38/D-39), and adaptive-K inference (Phase 2B,
D-25/D-26) are **closed and are not reopened** by anything here — this document
answers a different, new question about the same frozen data, not a re-run of
any of them.

---

## 0. The question, stated precisely

The scope study established that **agreement-based uncertainty detects
unreliable answers**, across two independent solver families, and that
**post-hoc correction via one specific verifier method does not** (D-46). This
document asks a **third, distinct** question those two do not answer:

> Does the same agreement-based uncertainty signal identify prompts whose K=4
> rollouts contain **useful within-prompt reward variation** — the raw
> material a GRPO-style RL update needs to compute a non-degenerate advantage?

This is **not** "uncertain prompts deserve more inference-time samples" (that
hypothesis already failed prospectively — Phase 2B, D-26). It is a question
about which prompts are informative for **training**, evaluated entirely from
data that already exists.

---

## 1. Primary hypothesis (H-RL1)

> Higher trajectory uncertainty, measured by the already-frozen per-instance
> agreement signal, is associated with a higher probability that a prompt's
> K=4 rollouts produce a **mixed-reward** group.

Agreement and mixed reward are explicitly **not** the same thing, and this
document exists to measure the gap between them, not assume it away: four
trajectories converging on the same *wrong* answer (`AAAA`, reward `0000`) is
maximal agreement and zero reward variation; four trajectories split `AABB`
with `A` correct and `B` wrong (reward `1100`) is disagreement *and* reward
variation. H-RL1 is a claim about which of these patterns dominates when
agreement is low, not a restatement of the scope study's detection result.

## 2. Primary predictor — reused, not invented

**No new learned uncertainty score is created.** The predictor is the
project's existing per-instance self-consistency quantity, already computed by
`biomni_uncertainty.features.compute_consistency` and already written to
`results/tables/instances.csv` for both scope-study arms by `cli aggregate`:

> **`plurality_fraction`** — the size of the largest agreement cluster among
> the instance's 4 trajectories, divided by 4. This is the direct per-instance
> analogue of the trajectory-level `agreement_fraction` signal that carried
> Phase 1's headline detection result (AUROC 0.874) and the scope study's own
> detection result (D-46: AUROC 0.896 / 0.814) — the same self-consistency
> construct, at the grain this new outcome actually lives at (the prompt, not
> the trajectory).

**Primary predictor, frozen:**

```
agreement = plurality_fraction              (already computed, ground-truth-free)
U = 1 - agreement                           (monotonic re-expression only)
```

For K=4, `plurality_fraction ∈ {0.25, 0.50, 0.75, 1.00}` by construction (the
largest cluster can hold 1, 2, 3, or 4 of the 4 trajectories) — a genuinely
coarse, 4-valued signal. This is stated now, before any AUROC is computed,
because a 4-valued predictor produces a step-function ROC curve with many
tied ranks; the AUROC is still well-defined and rank-based (ties get average
rank, exactly as `biomni_uncertainty.analysis.auroc` already implements), but
the coarseness is a property of the signal, not an artifact to be discovered
and explained away later.

**Secondary predictor (robustness only, decides nothing):** `pairwise_agreement`
— fraction of the 6 unordered trajectory pairs that share a cluster, also
already computed in the same table, at finer granularity (7 possible values for
K=4). Reported alongside the primary AUROC as a check that the finding is not
an artifact of `plurality_fraction`'s specific binning; it **never** enters the
GO rule.

**Not used, and why:** trajectory-level `agreement_fraction` (wrong grain — one
value per trajectory, not per prompt); verbalized confidence (not computed for
either scope-study arm); any embedding- or LLM-judged similarity (would be a
new learned signal, excluded by instruction).

## 3. Primary outcome, and the representation of terminal failures — verified before freezing

```
r = [r1, r2, r3, r4],  ri in {0, 1}      (official binary reward, trajectory_index order)

all_correct   := sum(r) == 4
all_wrong     := sum(r) == 0
mixed_reward  := 0 < sum(r) < 4            <- PRIMARY OUTCOME (binary: 1 if mixed_reward else 0)
reward_variance := p * (1 - p),  p = mean(r)
oracle_positive  := max(r) == 1            (Oracle@4 == 1; upper bound, never a selector)
```

**Verified directly against the aggregated tables before writing this
section** (not assumed): every one of the 120 instances in **both** arms has
**exactly 4 trajectory rows** in `results/tables/instrumented.csv`, including
every terminal `model_context_overflow` failure. A terminal failure is
represented as `completed=False`, `answer_parse_status="empty"`,
`answer_canonical=NaN`, and — because the official evaluator scores a
non-answer as wrong — **`reward=0.0`**, exactly the "non-answer never wins"
convention (D-18) already used everywhere else in this project. It also
receives its own singleton cluster key
(`__UNPARSEABLE__<run_id>`, from `features.cluster_key_for`), so it
participates in `plurality_fraction`/`pairwise_agreement` the same way an
unresolved disagreement does.

**Consequence, stated as a frozen representation choice, not discovered
after computing anything:**

* **`r` is always a full length-4 vector for every instance in both arms.**
  There is no instance with fewer than 4 "slots" to reason about — a terminal
  failure simply forces its slot to 0. The reward-vector / mixed-reward /
  reward-variance definitions above therefore apply **uniformly to all 120
  instances per arm, with no exclusion and no special case.**
* **This makes the existing metric definitions valid for every group without
  modification.** There is no group for which agreement, the reward vector,
  mixed-reward status, or the selector outcome is undefined. This was checked,
  not assumed, and is why no additional handling rule is introduced here.
* A caveat carried forward, not resolved: a `model_context_overflow` failure
  and a completed-but-wrong trajectory both score `reward=0`, and this
  document does not distinguish them anywhere below. A future, separate study
  could ask whether infrastructure failure and generation failure predict
  `mixed_reward` differently; that is out of scope here.

**Selection failure**, computed with the project's existing, unmodified
selector (`biomni_uncertainty.selectors.select_plurality`, the same function
behind every prior official plurality number in this project — **not
redefined here**):

```
selection_failure := oracle_positive AND (plurality-selected trajectory's reward == 0)
```

## 4. Primary analysis, frozen

**Unit of resampling: the instance**, exactly the convention every prior
bootstrap in this project uses (D-13 and every scope-study CI). **10,000
replicates, seed `20260821`** (a fresh seed for a new pre-registration, per
this project's standing practice of never reusing a frozen seed across
unrelated studies).

```
AUROC(U, mixed_reward)   via biomni_uncertainty.analysis.auroc (rank-based, existing code)
95% CI via a plain instance-resampling bootstrap (10,000 reps, seed 20260821)
```

Computed **independently per arm** (Biomni-R0, Mistral). **No pooling. No
best-arm reporting.** A cross-solver comparison is explicitly secondary (§7).

## 5. The GO rule — frozen now, compound, not a bare point estimate

Per the brief's explicit instruction, a point-estimate `AUROC > 0.5` is **not**
sufficient. **GO requires all three of the following, evaluated independently
per arm:**

**(a) Discrimination, CI-supported.** `AUROC(U, mixed_reward)` 95% CI lower
bound `> 0.5`. Not the point estimate — the interval must clear chance.

**(b) Practically meaningful enrichment, in a pre-specified stratum.** Rather
than an arbitrary quantile cut (which would require a boundary decision on
data with only 4 distinct predictor values — see §2), the **lowest-agreement
natural stratum** (`plurality_fraction == 0.25`, i.e. `U == 0.75`, all four
trajectories in distinct clusters) is fixed **now**, before computing
anything, as the "high-uncertainty" stratum. Required:

```
enrichment_ratio = P(mixed_reward | U == 0.75) / P(mixed_reward | overall)  >= 1.5
```

**and** the 95% instance-bootstrap CI on `P(mixed_reward | U == 0.75)` must
have its **lower bound exceed** the overall base rate `P(mixed_reward)` — i.e.
the enrichment must be distinguishable from noise, not just a point estimate
above 1.5×.

**(c) Budget-verified capture, in the offline simulation (§6).** At a
**25% sampling budget** (fixed now, before simulating anything — chosen as a
realistic RL data-curation fraction, not tuned against a result), the number
of `mixed_reward` instances captured by uncertainty-ranked sampling must have
its 95% bootstrap CI **lower bound exceed** the uniform-random baseline's
**expected** capture at the same budget (`0.25 x N_mixed`).

**Denominator guard, carried in spirit from D-44/D-45/D-46's normalized-
recovery guard:** if an arm has **fewer than 10 `mixed_reward` instances**
total, every ratio and stratum computation above is unstable at that n, and
the arm's verdict is reported as **INCONCLUSIVE regardless of the point
estimates**, with the observed count stated plainly.

**Verdict per arm:**

* **GO** — (a) and (b) and (c) all hold, and the denominator guard is clear.
* **NO-GO** — the denominator guard is clear, and **either** (a)'s CI upper
  bound is `<= 0.5` (no detectable signal at all) **or** (b)'s enrichment
  ratio is `<= 1.0` (uncertainty picks up mixed-reward prompts **no more
  often than chance**, i.e. actively uninformative for this purpose).
* **INCONCLUSIVE** — the denominator guard fires, **or** the three conditions
  disagree (e.g. (a) holds but (b) or (c) does not), **or** the observed
  values sit between the GO and NO-GO bounds above.

**None of these thresholds are revisited after computing a result.** A
combination that produces an uncomfortable verdict is reported as that
verdict.

## 6. Offline prioritization simulation — frozen procedure

Three curves, computed **per arm**, over a fixed budget grid
`{5%, 10%, 15%, ..., 100%}` of the 120 instances:

1. **Uniform baseline.** 10,000 simulated draws (without replacement) of each
   budget's instance count; report the empirical distribution's mean and
   95% band of `mixed_reward` instances captured. This is the actual
   resampled baseline, not the trivial linear expectation, though the two
   must and will agree in mean.
2. **Uncertainty-ranked.** Instances sorted by `U` descending (ties — and
   there will be many, per §2 — broken by lowest `task_instance_id`, a fixed,
   arbitrary, pre-declared rule with **no access to reward**). Deterministic
   given the frozen ranking; no bootstrap band applies to this curve itself.
3. **Oracle (upper bound, never a deployable policy).** Instances sorted by
   the **true** `mixed_reward` label (ties again broken by lowest
   `task_instance_id`). Labelled as an upper bound everywhere it appears,
   exactly as `oracle` is labelled everywhere else in this project.

**The uncertainty ranking never sees reward or correctness at any point.**
This is enforced structurally: the ranking script reads only
`plurality_fraction` and instance identifiers, never `reward` or `correct`.

Reported: capture-vs-budget curves; enrichment ratio (uncertainty capture /
uniform-mean capture) at each budget; "mixed-reward groups per 100 sampled
prompts" at each budget. Given K=4 is fixed for every instance in both arms,
"per 100 trajectories" is a constant 4x rescaling of "per 100 prompts" and is
noted as such rather than computed as an independent curve.

## 7. Secondary analyses — decide nothing

* **Reward-variance relationship.** Spearman rank correlation between `U` and
  `p(1-p)`, with the same instance bootstrap, reported with its CI. Predeclared
  as a rank correlation because `p(1-p)` is a deterministic, non-linear
  (inverted-U) function of `sum(r)`, for which a linear correlation would be a
  poor and misleading summary.
* **Selection-failure analysis.** `P(selection_failure)` overall, and
  `AUROC(U, selection_failure)` with the same bootstrap. Reported in full
  because it bears directly on the scope study's own finding (D-46 §4) that
  part of the observed correction signal was a plurality-baseline artifact —
  but it is **not** part of the GO rule, which concerns `mixed_reward` only.
* **Cross-solver comparison.** Whether the per-arm verdicts (§5) agree,
  computed only after both arms' primary analyses are final. Interpretation
  table, fixed now:

| observed | reading |
| --- | --- |
| GO, GO | uncertainty identifies RL-informative prompts **and** generalises across solver family — licenses a cross-solver uncertainty-guided-RL hypothesis |
| GO, one arm only | the detection-generalises / correction-does-not pattern (D-46) may extend to this third question too; RL may proceed **only** for the passing solver, with a correspondingly narrow claim |
| NO-GO or INCONCLUSIVE, both | agreement predicts correctness (established, D-46) but does **not** identify prompts with useful within-group reward variation; the current uncertainty-guided curriculum hypothesis is **not** supported and should not proceed |

This table is the only interpretation rule for the cross-solver question;
nothing else is added after seeing the per-arm verdicts.

## 8. What this document does not decide

* Whether RL training should launch — a GO here authorises **drafting** a
  protocol (already scoped: an epoch-1-identical, prompt-prioritization-only
  design), never launching one. Training requires separate, explicit operator
  approval, stated again at the end of this document's companion report.
* Any claim about `Biomni-R0` vs `Mistral` as the eventual RL model beyond
  what this preflight's own numbers say — the model recommendation weighs this
  preflight's result alongside context-overflow rate, rollout speed and
  compute footprint, all already measured elsewhere (D-44, D-46) and not
  recomputed here.
* Any redefinition of agreement, the selector, or the reward — all three are
  reused exactly as frozen upstream.

## 9. Explicitly not to be done

No RL training. No new inference. No new instance. No reopening Stage C,
candidate adjudication, diversity-by-resampling, or adaptive-K inference. No
new learned uncertainty score. No quantile-boundary tuning after seeing the
distribution. No bar movement on §5's thresholds after computing a result. No
promotion of §7's secondaries to primary.

---

*No `mixed_reward`, `reward_variance`, `selection_failure`, AUROC, enrichment
ratio, or simulation number exists at the time of writing. This file is a
precommitment, and is the authority against which any later claim from this
preflight is checked.*
