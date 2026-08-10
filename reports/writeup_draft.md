# Reliability control for biomedical AI agents: what a pre-registered prospective test found

**Status: DRAFT.** Written 2026-08-10, Step 3 of the live-GPU-window plan,
started in parallel with Step 2 (the candidate-adjudication pilot) and
updated the same day once Step 2 completed (D-38, NO-GO). Every number below
is frozen and cited to a specific report.

---

## Abstract

Can a biomedical AI agent recognize when its own conclusions are reliable
enough to accept, when they need independent verification, and when it
should defer? We built a reliability layer around Biomni (Biomni-R0-32B) on
BiomniEval1 and tested the most natural instantiation of that idea — sample
multiple trajectories, stop early when they agree, escalate when they don't
— as a pre-registered, prospective experiment on 150 held-out instances,
never seen during design. **Both co-primary hypotheses failed.** The
controller was not merely underpowered; it was *dominated*: a blind,
same-cost random allocation beat it outright, and the controller's own
no-abstention variant is provably identical, under three different
consensus-weighting rules, to the frozen policy it was meant to improve on —
not because the improvement was small, but because the action set (accept,
resample, abstain) cannot express the distinction those rules were built to
capture. A companion structural diagnostic on the same trajectories found
why: trajectories that disagree have statistically indistinguishable
*plans* from trajectories that agree (Jaccard 0.546 vs 0.538, against a
same-task-different-question control of 0.301) — free resampling does not
manufacture the independence a verification mechanism would need. Two
narrower claims survive prospectively and are carried forward: the
controller made zero high-confidence wrong claims where a fixed policy made
several, and a single verbalized-confidence threshold (`== 1.00`)
discriminates correctness cleanly out of sample. A pre-registered process
failure — a monitoring gate that silently reported 0% instead of 15.5%
residual model degeneration — is reported with the same prominence as the
substantive result, because catching it late is itself a finding about how
this kind of research fails quietly.

---

## 1. The question

> Can biomedical AI agents recognize when their scientific conclusions are
> reliable enough to accept, when they require independent verification,
> when their workflow should be repaired, and when they should defer to a
> human?

Biomni + Biomni-R0-32B + BiomniEval1 is the testbed, not the subject. The
intended contribution is a general reliability layer for scientific agents —
a component that watches a trajectory, estimates whether its conclusion can
be trusted, and decides whether to accept it, verify it, or escalate it —
not a benchmark-score optimization for one agent.

**Why this matters, concretely.** An agent that is wrong 40% of the time but
*knows which 40%* is deployable. An agent that is wrong 20% of the time with
uniform 96% stated confidence is not — and the latter is closer to what was
measured. Phase 1 found a mean stated confidence of 0.96 against actual
accuracy of 0.59.

## 2. What is established before any controller is built (Phase 1, n=50, independently re-verified at n=230 after a repair)

* **Better candidates exist among repeated samples.** Oracle@4 0.620–0.640
  vs. first-trajectory 0.420–0.480, depending on realization — 16–20
  percentage points of headroom, 30–35% relative error reduction.
* **They are findable without ground truth.** Plurality voting beats the
  first trajectory by +0.14 to +0.16 (95% CI excluding zero in both the
  original and repaired pools).
* **Agreement is the strongest cheap signal measured**, AUROC 0.815–0.874,
  stronger than verbalized confidence (0.749–0.789).
* **Confidence ranks but does not calibrate.** Overconfidence gap 0.37–0.43;
  the miscalibration got *worse*, not better, after the pool was repaired to
  include the harder, previously-lost instances — a genuine finding, not
  noise, since the rescued instances were disproportionately hard-and-wrong.
* **Diminishing returns are steep.** K=1→2 gains 12.2 points; K=2→3 gains
  4.8; K=3→4 gains 2.5. K=2 captures roughly two-thirds of K=4's headroom at
  half the cost — the entire economic argument for adaptivity.

**What Phase 1 could not establish**, stated as clearly as what it did:
anything about trajectory 2 onward (the sequential-decision problem);
whether a correct final answer came from a valid workflow (only final
answers are scored); whether any of this transfers past one agent and one
model family.

## 3. The offline replay that motivated a prospective test (Phase 2A, analysis-only, exhaustive over all 24 arrival orderings)

A sequential policy — **mandatory second opinion, stop the instant two
trajectories agree, continue to a ceiling of four otherwise** — replayed
against the same trajectory pool returned the *same answer on every
instance and every task* as fixed-K=4 voting, at 68% of the cost (mean K
2.70 of 4.00). The offline paired-difference confidence interval was
degenerate: **[0.000, 0.000]**. This is, in hindsight, the single most
important number in the whole project, and not for the reason it originally
looked like one — see §4.

A companion negative result, equally important and equally honest: nested,
leakage-free cross-validation found that accepting after a *single*
trajectory could not be justified — three of five folds chose never to
accept early. That result was not carried into the prospective design.

## 4. The prospective test (Phase 2B): both co-primary hypotheses fail

**Design, frozen before any outcome existed.** 150 instances never used in
any prior phase. Two co-primary, both required: non-inferiority in reward
against fixed K=4 (margin 5 percentage points, one-sided 95% CI), and mean
cost below 3.0 trajectories per instance. A hash-chained, append-only
decision log made "the controller never saw a trajectory it didn't ask for"
checkable from artifacts rather than merely asserted — every shadow
trajectory's start time is required to post-date its instance's committed
terminal decision, verified after the fact, not trusted in advance.

**Result.**

| | reward vs. fixed K=4 | mean cost |
| --- | --- | --- |
| non-inferiority margin | −0.05 | < 3.0 |
| **observed** | **−0.033, 95% CI [−0.067, −0.007]** | **2.893, 95% CI upper 3.033** |
| **verdict** | **FAIL** | **FAIL, narrowly** |

Neither result is attributable to one bad task or one unlucky draw: excluding
the single highest-variance task reproduces both failures almost unchanged
(−0.032, mean K 2.856), and an exhaustive ordering-averaged replay of the
same 600 trajectories shows the same direction. **The offline degenerate
interval in §3 was an artifact of replaying one fixed pool, not a property of
the policy** — the clean lesson for offline-replay methodology generally: a
zero-width bootstrap CI is a warning sign to check for a replay artifact, not
evidence of a strong result.

**Mechanism, from pre-registered deliverables, not a post-hoc story.** The
controller is accurate when it answers (71.1% among the 80.7% of instances it
accepted) but abstains on 19.3%, each scored zero by the pre-registered
accounting. Every acceptance carries identical nominal support — "two
trajectories agreed" — regardless of whether that happened on the second
trajectory or the fourth, which erases the difference between a confident
early stop (87.7% accurate) and a reluctant four-trajectory plurality (35.0%
accurate, *below* the 51.3% a single blind trajectory gets by chance). The
sharpest single comparison: **a same-cost, uniformly-random, non-adaptive
allocation of the identical number of trajectories scored higher than the
adaptive controller** (0.592–0.593 vs. 0.573). An adaptive method that loses
to blind allocation at equal spend has not demonstrated that its adaptivity
does anything.

## 5. Why the natural redesign doesn't work — a structural result, not a tuning failure

The report on the prospective failure named an apparently reasonable fix:
stop collapsing "two-of-two" and "two-of-four" into the same accept
decision — the exact split the mechanism analysis pointed at. Before
spending any further prospective budget on it, eighteen parameter-free
variants of the consensus rule were replayed offline against both available
pools (the original 50-instance pool and the 150-instance prospective
pool), with the adjudication bar written down before the replay ran.

**Every variant that distinguishes "two-of-two" from "two-of-four" and
therefore escalates rather than accepts the latter is *worse* than the
policy it was meant to fix** — by 4.7 to 5.7 percentage points, because a
two-of-four plurality is 35–42% accurate, not 0%, and refusing it converts
an expected win into a certain loss under the pre-registered accounting.

The more important result is structural, and it holds regardless of how the
rule weights consensus history: **stripped of its abstention step, every
rule tested — naive two-agreement, strict majority, majority-among-usable-
only — reduces to the *identical* policy**, provably, checked by direct
comparison across every replay ordering. Inside an action set of {accept,
resample, abstain} where the only non-terminal move is *resample*,
information about *how* consensus formed can only be spent two ways: buy
another trajectory (impossible once the budget ceiling is reached, which is
exactly when the distinction matters) or abstain (already shown net-negative
above). **There is no third channel.** A further prospective run testing
this family of redesign would not be testing a weak hypothesis; it would be
testing one that cannot express itself in the policy's own vocabulary. The
project moved directly to the diversification question this points toward,
rather than iterating on stop-rule variants.

One quantity carried forward as a genuine finding rather than folded into a
new policy: **the only self-funding piece of adaptivity in the whole family
is continuing past a trajectory that failed outright** — escalating only on
zero usable answers beats a fixed two-trajectory baseline by roughly one
point, the empirical floor for what any variant of this mechanism can
deliver.

## 6. Two results that survive prospectively, and belong to a different question than "does the controller work"

* **Zero high-confidence wrong claims.** Among instances where the
  controller answered with three-or-more-way agreement, it was never wrong;
  a fixed four-trajectory policy was wrong on 5.3% of its own
  high-agreement claims. Read correctly, not as "the controller's confident
  claims are more trustworthy" — it never reaches the confidence band where
  the comparison is even defined, because it stops the instant two agree —
  but as "it made zero unsafe high-confidence claims," which is a real,
  narrower safety property.
* **A single verbalized-confidence threshold discriminates cleanly,
  prospectively, out of sample.** Trajectories that stated `confidence ==
  1.00` were correct 89.8% of the time (44 of 49) against 65.1% (267 of 410)
  for everything else — a hypothesis registered *before* the prospective run
  based on a post-hoc pattern in the offline pool (26 of 27), and confirmed
  on data the pattern was never fit to. This is now eligible to inform a
  future controller as a secondary signal — later offline work found its
  incremental value sits almost entirely inside the state that is already
  87.7% accurate and vanishes exactly where a controller would need it, so
  it does not by itself resolve the mechanism-level problem in §5, but the
  discrimination itself is real and prospectively validated.

## 7. Track C — is disagreement addressable at all?

Two CPU-only diagnostics, both on the same held-out prospective pool,
established the shape of the remaining question before any further GPU time
was spent.

**Is more sampling diversity the answer?** No. Trajectories that reach
different conclusions have statistically indistinguishable *opening plans*
from trajectories that agree (Jaccard 0.546 vs. 0.538, 95% CI [−0.040,
+0.058]) — measured against a same-task-different-question control of 0.301,
which is what makes the null readable rather than merely a small number.
Divergence, when it happens, happens downstream of the plan, and workflow
independence — however it is measured — does not predict whether a more
independent trajectory corrects an error (non-monotone across
distance quartiles, 95% CI for the high-minus-low contrast spanning zero
against a 10-point pre-registered bar). Generating more diverse samples by
resampling is not, on this evidence, a productive direction.

**Where does the remaining headroom actually live, and is it reachable at
all?** Of the 150 held-out instances, 30% have no correct trajectory among
any of four independent samples — unreachable by any selection mechanism,
however good. On the instances where trajectories genuinely disagree, the
correct answer is disproportionately *minority-held* — the best available
selector recovers 37.5% and 27.3% of two- and three-way splits respectively,
against an oracle ceiling of 62.5% and 63.6% on the same instances. A
follow-up check found that only 7.1% of this addressable headroom sits on
tasks where the answer is a deterministic quantity computable from the
prompt itself, rather than one requiring external evidence or domain
judgment — the tasks with re-derivable structure are already the tasks that
work well; the tasks with headroom are not.

**Can active adjudication recover it, where passive resampling cannot? No —
and decisively.** A two-arm pilot tested this directly: hand the real,
tool-enabled agent the existing disagreeing candidates for the 78 stratum-B
instances across both pools (53 + 25) and ask it to adjudicate between
them, majority-resolved over 3 samples. This arm was deliberately
constructed to have *strictly more* information than a real VERIFY
trajectory ever could — the full candidate set, an explicit adjudication
framing, and unrestricted tool access, against a real VERIFY's task prompt
plus a single candidate — making it an upper bound on what any
evidence-based verification mechanism could achieve, not merely one
implementation of it. The result: Δ (adjudicated majority reward minus the
plurality floor already achieved by voting) = **−0.077, 95% CI [−0.192,
0.038]**, entirely below the pre-registered bar for even partial recovery
(a third of the 0.192 available gap). The point estimate is *negative*:
tool-enabled adjudication scores worse on average than doing nothing but
voting on the trajectories already in hand. This replicates as an
independent, standalone negative result on one of the two source pools
(phase1-derived instances alone: Δ = −0.16, 95% CI entirely below zero) and
is not reversed by any pre-registered secondary cut.

The mechanism is not "confidently wrong" but "frequently no answer at all":
47% of instances produce no majority-resolved answer under adjudication (no
2-of-3 sample agreement, or every sample failing outright), and 46% of
instances have at least one sample that ignores the explicit instruction to
answer from the given candidate list. A companion, near-universal signal —
96% of instances show at least one over-length "runaway" generation event,
though only 18% of trajectories are terminated by it — indicates this
prompt shape (a full original task plus a candidate-adjudication framing)
pushes this reasoning model into long-generation territory almost routinely,
not just in rare failure cases. Because the tested arm strictly upper-bounds
any real verification mechanism's available information, this null result
generalizes: a more-constrained implementation has no plausible path to
succeeding where this idealized version did not, on the same population,
model, and tooling. Independent verification via tool-mediated adjudication,
on this evidence, is not the right next mechanism either — the candidate
answer may sit latent in the disagreement, but neither passive resampling
nor active, maximally-informed adjudication reliably surfaces it.

## 8. Process findings, reported with equal prominence

**A pre-registered halt condition tripped and was not caught.** The
monitoring gate that was supposed to block launch if residual model
degeneration exceeded 15% checked for an exact string that the runner never
actually produced — an exact-match bug against a fuller failure-class
string. It silently reported 0.0% in every run it ever checked, including a
smoke test whose *true* rate was 37.5% and a full run whose true rate was
15.5%, both above the pre-registered threshold. The bug was fixed, a
regression test was written keyed to the exact string it missed, and — not
enough on its own — the corrected gate's *failure* path was subsequently
exercised end-to-end against live data for the first time, returning the
correct blocked verdict with the correct exit code. The general lesson,
stated as a rule rather than a war story: a monitoring gate that has never
been proven to fail is not a gate, and a test suite that only exercises the
pass path leaves exactly the failure mode that matters unverified.

**A prospective experiment ran from an uncommitted working tree.** Every
run of the prospective controller recorded a dirty working-tree flag, and
the file implementing the controller under test was never committed —
meaning no commit in the repository could honestly be cited as the one that
produced the result. Recovery was possible only because the *outcome*
reproduced exactly from stored artifacts (every headline number, and every
committed online decision, matched an independent offline recomputation on
0 of 150 mismatches) — the gap was in source auditability, not in the
result's validity, and that distinction is exactly why it is safe to
report the result at all. Going forward, every launch entrypoint now
refuses to start from an uncommitted tree, and every trajectory carries a
hash of the exact source that produced it.

## 9. What this adds up to

A pre-registered adaptive-verification controller was prospectively
falsified, not marginally but dominated by a policy that looks at nothing.
The mechanism is understood well enough to show that the natural repair
fails for a structural reason, not a tuning one, and that result
generalizes past this specific rule: any policy confined to an action set of
{accept, resample, abstain} cannot use information about *how* trajectories
came to agree, only *whether* they did. A follow-up, deliberately
upper-bound test of the remaining alternative — active, tool-mediated
adjudication among already-disagreeing candidates, rather than more passive
resampling — closes off that direction too: it does not merely fail to
recover headroom, its point estimate is negative, and the failure
replicates independently on one of its two source pools. Two narrower,
genuinely useful results survive from the original controller — a safety
property and a calibration signal — and neither depends on the controller
working. What began as an open question — is disagreement a resolvable
epistemic state at all? — now has a specific, evidenced answer for the two
most natural mechanisms tried: neither generating more samples nor handing
the existing ones to a tool-enabled adjudicator reliably surfaces the
correct answer when trajectories disagree, even though that answer is
often present, just minority-held. Building a real VERIFY implementation on
top of either mechanism is not supported by this evidence; that remains the
user's decision to make, not one this project makes on its own.

---

## Reproduction and provenance

Every number above traces to a specific commit, table, and (where
prospective) a hash-chained decision log verified end-to-end; nothing here
is asserted without a cited artifact in the underlying reports. §7's Step-2
result is documented in full in `reports/track_c_step2.md` and `DECISIONS.md`
D-38.
