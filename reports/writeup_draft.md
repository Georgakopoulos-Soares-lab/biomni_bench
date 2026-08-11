# Reliability control for biomedical AI agents: where the failures actually are

**Status: DRAFT.** Structure and claims revised 2026-08-11 (Stage 0) after
D-39 retracted the "upper bound" inference in D-38. Organised around *what can
go wrong* rather than the order the experiments happened to run in. Slots
marked **[Stage A]** await the existing-data decomposition in
`reports/stage_a_decomposition.md`; every number already present is frozen and
cited.

---

## Abstract

Can a biomedical AI agent recognise when its own conclusions are reliable
enough to accept, and defer when they are not? We built a reliability layer
around Biomni (Biomni-R0-32B) on BiomniEval1 and tested the most natural
instantiation of that idea — sample multiple trajectories, stop early when
they agree, escalate when they don't — as a pre-registered prospective
experiment on 150 held-out instances never seen during design. **Both
co-primary hypotheses failed**, and not marginally: a blind, same-cost random
allocation of the identical trajectory budget scored *higher* than the
adaptive controller. We then show why the obvious repair cannot work, as a
structural result with its scope stated precisely: under exchangeable
resampling from a single policy with a fixed budget ceiling and no terminal
action beyond accept-or-abstain, the tested consensus rules collapse to one
policy, because at the ceiling — exactly where the distinction matters —
consensus history can only trigger abstention. Two further mechanisms were
tested and did not recover the gap: resampling for diversity (trajectories
that disagree have statistically indistinguishable *plans* from trajectories
that agree, Jaccard 0.546 vs 0.538 against a 0.301 control), and handing a
tool-enabled agent the disagreeing candidates to adjudicate between (Δ =
−0.077 against the voting floor, 95% CI [−0.192, 0.038]). The adjudication
null is reported with its confound named rather than generalised: the same
run shows 46.2% of instances emitting an answer outside the candidate list it
was told to choose from and 96.2% showing runaway generation, which is an
unstable elicitation regime, not a demonstrated inability to verify. The
contribution is a decomposition — separating *candidate generation* from
*candidate selection* from *execution reliability* from *selective deferral* —
and the finding that on this benchmark the binding constraint is selection,
not generation: the correct answer is frequently present among four samples
and not chosen.

---

## 1. The question

> Can biomedical AI agents recognise when their scientific conclusions are
> reliable enough to accept, when they require independent verification, when
> their workflow should be repaired, and when they should defer to a human?

Biomni + Biomni-R0-32B + BiomniEval1 is the testbed, not the subject. The
intended contribution is a general reliability layer for scientific agents,
not a benchmark-score optimisation for one agent.

**Why this matters, concretely.** An agent that is wrong 40% of the time but
*knows which 40%* is deployable. An agent that is wrong 20% of the time with
uniform 96% stated confidence is not — and the latter is closer to what was
measured: mean stated confidence 0.96 against actual accuracy 0.59.

## 2. Four things that can go wrong, and why separating them is the contribution

Most of the confusion in this literature comes from treating "the agent got it
wrong" as one failure. It is at least four, with different fixes and different
ceilings:

| axis | question | fix if this binds |
| --- | --- | --- |
| **generation** | does the agent ever produce the correct answer? | better model, better tools, more samples |
| **selection** | given it produced it, is it chosen? | better aggregation, verification, reranking |
| **execution reliability** | does the machinery return a usable answer at all? | engineering: context, parsing, tool health |
| **selective deferral** | does it know when not to answer? | calibration, abstention policy |

The measurements below are organised on these axes. The headline finding is
that on this benchmark **selection binds hardest**, and that the mechanisms
most obviously suited to fixing selection did not fix it.

## 3. Generation — the correct answer is present more often than it is chosen

* **Repeated sampling finds better candidates.** Oracle@4 0.620–0.640 vs.
  first-trajectory 0.420–0.480 depending on realisation: 16–20 points of
  headroom, 30–35% relative error reduction. (Phase 1, n=50, independently
  re-verified at n=230 after a repair.)
* **Returns diminish steeply.** K=1→2 gains 12.2 points; K=2→3 gains 4.8;
  K=3→4 gains 2.5. K=2 captures roughly two-thirds of K=4's headroom at half
  the cost — the entire economic argument for adaptivity.
* **A substantial floor of instances is not solved by any of four samples.**
  Of 150 held-out instances, **45 (30%) have no correct trajectory among four
  independent samples.**

**That 30% is not yet established as a generation limitation, and this draft
does not claim it is.** Three non-generation explanations are live and
individually checkable, and conflating them with model capability would erase
the distinction this paper is built on: the answer may have been scored wrong
by an evaluator/canonicalisation mismatch (this project has been burned there
before — a symbol-first parser bug moved every Phase-1 headline number); the
answer may appear in the trajectory's reasoning without being committed in the
final block; or the prompt may not determine the answer uniquely without
external knowledge it never supplies. **[Stage A.5]** triages exactly these
three, and reports the no-correct fraction under official scoring and under
audit-corrected scoring side by side. Until then, "30% unreachable" is an
upper bound on the generation problem, not a measurement of it.

**A separate population, and the one this paper finds most interesting.** On
**53 of 150** instances the samples disagree substantively and *the correct
answer is demonstrably present among them* — the model generated it and the
aggregation did not return it. That is a **selection** failure, and it must
not be pooled with the 45. On those instances the best deployable selector
recovers 37.5% and 27.3% of two- and three-way splits against an oracle
ceiling of 62.5% and 63.6%.

## 4. Selection — where the constraint actually binds

### 4.1 What voting already buys, and the ceiling it defines

Plurality voting beats the first trajectory by **+0.14 to +0.16** (95% CI
excluding zero in both pools), and agreement is the strongest cheap signal
measured (AUROC 0.815–0.874, stronger than verbalised confidence at
0.749–0.789).

The remaining selection headroom over plurality is **0.093 [0.047, 0.140]**
across all 150 instances, concentrated entirely in the 53 disagreement
instances (0.264 [0.151, 0.377] there). **This number is a ceiling on
candidate *selection* over a fixed pool of four samples drawn from one
policy — nothing more.** It is not a ceiling on any family of methods: a
different generator, more samples, a repair action that changes the
trajectory, or a different terminal resolver each move it, and none of those
are bounded by it. Reading 0.093 as "the most any reliability method could
add" is a misreading this draft explicitly disclaims.

### 4.2 The prospective test: both co-primary hypotheses fail

**Design, frozen before any outcome existed.** 150 instances never used in any
prior phase. Two co-primary hypotheses, both required: non-inferiority in
reward against fixed K=4 (margin 5 points) and mean cost below 3.0
trajectories per instance. A hash-chained append-only decision log made "the
controller never saw a trajectory it didn't ask for" checkable from artifacts
rather than asserted — every shadow trajectory's start time is required to
post-date its instance's committed terminal decision.

| | reward vs. fixed K=4 | mean cost |
| --- | --- | --- |
| margin | −0.05 | < 3.0 |
| **observed** | **−0.033, 95% CI [−0.067, −0.007]** | **2.893, 95% CI upper 3.033** |
| **verdict** | **FAIL** | **FAIL, narrowly** |

Neither failure is attributable to one bad task or one unlucky draw: excluding
the highest-variance task reproduces both (−0.032, mean K 2.856), and an
exhaustive ordering-averaged replay of the same 600 trajectories shows the
same direction.

**The sharpest single comparison:** a same-cost, uniformly-random,
non-adaptive allocation of the identical trajectory budget scored **higher**
than the adaptive controller (0.592–0.593 vs. 0.573). An adaptive method that
loses to blind allocation at equal spend has not demonstrated that its
adaptivity does anything.

**Mechanism, from pre-registered deliverables rather than a post-hoc story.**
The controller is accurate when it answers (71.1% on the 80.7% it accepts) but
abstains on 19.3%, each scored zero by the pre-registered accounting. Every
acceptance carries identical nominal support — "two trajectories agreed" —
whether that happened on the second trajectory or the fourth, erasing the
difference between a confident early stop (87.7% accurate) and a reluctant
four-trajectory plurality (35.0% accurate, *below* the 51.3% a single blind
trajectory achieves).

**A methodological note worth more than the result.** The offline replay that
motivated this run returned a *degenerate* paired-difference interval,
[0.000, 0.000] — the policy appeared to reproduce fixed-K=4's answers exactly
at 68% of the cost. That was an artifact of replaying one fixed pool, not a
property of the policy. A zero-width bootstrap CI is a warning to check for a
replay artifact, not evidence of a strong result.

### 4.3 The obvious repair cannot work — a structural result, with its scope stated

The mechanism analysis points at one fix: stop collapsing "two-of-two" and
"two-of-four" into the same accept. Eighteen parameter-free variants were
replayed offline against both pools with the adjudication bar written down
first. Every variant that escalates rather than accepts a two-of-four
plurality is **worse** than the policy it was meant to fix, by 4.7 to 5.7
points — because a two-of-four plurality is 35–42% accurate, not 0%, and
refusing it converts an expected win into a certain loss under the
pre-registered accounting.

The structural result, **stated with the conditions it actually requires**:

> Under exchangeable resampling from a single policy, a fixed maximum K, the
> same terminal plurality resolver, and no terminal action beyond accept or
> abstain, the tested no-abstention consensus rules collapse to one policy;
> and at the budget ceiling, consensus history can only trigger abstention.

Verified by direct comparison across every replay ordering: `v1_no_abstain`,
`v2_majority_no_abstain` and `v2_usable_majority_no_abstain` make the
identical decision on every instance under every ordering.

**What this does not say.** It is *not* the claim that any policy over
{accept, resample, abstain} is equivalent. Consensus history can act on
*continuation* before the ceiling is reached, and a different terminal
selector could behave differently. The collapse is a consequence of the four
stated conditions, and dropping any of them — a non-exchangeable resampler, a
repair action, a reranking terminal resolver — escapes it. The scope is
asserted by test (`tests/test_structural_scope.py`) so that a future edit
cannot silently widen it.

One quantity survives as a genuine finding: **the only self-funding piece of
adaptivity in the whole family is continuing past a trajectory that failed
outright** — escalating only on zero usable answers beats a fixed
two-trajectory baseline by roughly one point.

### 4.4 Diversity by resampling does not manufacture independence

Trajectories that reach different conclusions have statistically
indistinguishable *opening plans* from trajectories that agree: Jaccard
**0.546 vs. 0.538**, 95% CI [−0.040, +0.058], measured against a
same-task-different-question control of **0.301** — the control is what makes
the null readable rather than merely a small number. Workflow independence
does not predict whether a more independent trajectory corrects an error
(non-monotone across distance quartiles; CI for the high-minus-low contrast
spans zero against a 10-point pre-registered bar).

### 4.5 Adjudication among existing candidates — a null, with its confound named

If the correct answer is present but minority-held, the natural mechanism is
not more sampling but *selection by an adjudicator*. This was tested directly:
hand the real, tool-enabled agent the disagreeing candidates for all 78
disagreement instances across both pools (53 + 25), ask it to choose among
them, majority-resolve over 3 samples, score against the same frozen plurality
floor.

**Result: Δ = −0.077, 95% CI [−0.192, 0.038]**, against a pre-registered bar
requiring recovery of at least a third of the 0.192 available gap. The point
estimate is negative — the adjudicator scores worse than doing nothing but
voting on the trajectories already in hand — and the direction replicates
independently on one of the two source pools (Δ = −0.16, CI entirely below
zero). A no-tools, one-shot arm is worse still (Δ = −0.218, CI [−0.333,
−0.103]).

**The mechanism is not "confidently wrong" but "frequently no answer."** On
the same run: **47.4%** of instances produced no 2-of-3 majority at all,
**46.2%** had at least one sample answering *outside the candidate list it was
explicitly instructed to choose from*, **96.2%** showed at least one runaway
generation event, and **17.9%** of trajectories were terminated by
degeneration.

**What this licenses, and what it does not.** An earlier version of this
analysis argued that because the adjudicator saw *strictly more* information
than a constrained verifier would, its failure upper-bounds verification
generally. **That inference is withdrawn (D-39).** Monotonicity of
value-of-information holds for an optimal decision-maker that can ignore
irrelevant input; a fixed LLM under a fixed prompt is not one, and the data
contains a direct counterexample — the off-menu failure mode is *created by*
the extra information, since a verifier never shown a candidate list cannot
produce an off-menu answer at all. The surviving claim is exactly:
**free-form, same-model, tool-enabled candidate adjudication failed under a
maximally-informed but operationally unstable regime.** Every qualifier is
load-bearing. Whether a *different* verifier under a *stable* interface can
select better is open, and is the one remaining experiment
(`reports/stage_c_stop_rule.md`, stop rule committed before any of the
decomposition below existed).

**[Stage A.1–A.2]** decompose this null into capture (voting wrong,
adjudicator right) versus harm (voting right, adjudicator wrong or
unresolved), and separate *interface* harm from *judgment* harm — the
quantitative content of the retraction above.

## 5. Execution reliability — a first-class axis, not a footnote

Three findings that belong to the machinery rather than the reasoning, and
that repeatedly turned out to be the binding constraint on interpreting
everything else:

* **A hard degeneration boundary at ~32,768 input tokens.** Above it the model
  collapses into unterminated repetition: runaway rate **3.1% below the
  boundary, 94.1% above**. The served context had been raised to 65,536 on a
  prompt-size estimate that measurement later refuted — the median
  post-retrieval prompt is 2,687 tokens, not the 17k–41k projected — so the
  extra window added capacity exclusively *above* the point where the model
  stops working, converting a hard rejection into silent behavioural collapse.
  The repair was a trajectory budget, not a bigger window.
* **Residual trajectory failure never came under control.** 15.5% at the
  prospective run; re-measured later at **28.1%, 95% CI [15.6%, 45.4%]** on a
  fresh unscreened sample, against a pre-registered 15% halt threshold.
  Failure concentrates in specific pathological instances rather than spreading
  evenly — one instance accounted for 44% of the failures in that sample.
* **The evidence channel was substantially broken**, precisely where a
  verification mechanism would live: 30.0% of 1,395 tool calls errored, with
  `query_pubmed` at 68.9%, `advanced_web_search_claude` 77.0%, `query_scholar`
  80.0%, while structured databases worked (6–7%). Two were repaired to 8/8;
  three were excluded on evidence, including one — `search_google` — that the
  error-rate metric had scored *healthy* at 3.4% because it silently returns an
  empty result rather than raising.

A related result that reframes the benchmark: **35.7% of trajectories make
zero tool calls, and they are *more* accurate (0.724) than tool-using ones
(0.652).** Correct answers here come substantially from parametric memory
rather than retrieved evidence — which bounds how much any evidence-based
verification mechanism could contribute on this benchmark, independent of
whether it works.

## 6. Selective deferral — one real signal, and one claim corrected

* **A single verbalised-confidence threshold discriminates, prospectively,
  out of sample.** Trajectories stating `confidence == 1.00` were correct
  **89.8%** (44/49) against **65.1%** (267/410) otherwise — registered as a
  hypothesis *before* the prospective run on a post-hoc offline pattern
  (26 of 27) and confirmed on data it was never fit to. Later offline work
  found its incremental value sits almost entirely inside the state that is
  already 87.7% accurate and vanishes where a controller would need it, so it
  does not resolve §4.3; the discrimination itself is real.
* **Confidence ranks but does not calibrate.** Overconfidence gap 0.37–0.43,
  and it got *worse* after the pool was repaired to include harder
  previously-lost instances — a genuine finding, since the rescued instances
  were disproportionately hard-and-wrong.

**A claim from an earlier draft, corrected.** That draft reported "zero
high-confidence wrong claims" for the controller against 5.3% for fixed K=4,
as a safety property. The correct statement is that **the controller made zero
online claims meeting the high-confidence definition at all** — 0 of 150. The
rate is not 0%; it is undefined. All **121** of its acceptances carried
support exactly 2, and the maximum support observed at any acceptance was 2.
The ≥3-agreement band is **unreachable by construction** for this policy:
reaching three agreeing trajectories requires two of the first three to have
agreed, which would have terminated the trajectory earlier. "Zero
confidently-wrong claims" is therefore a theorem about the stopping rule, not
an empirical safety finding, and it is not evidence that the controller's
confident claims are trustworthy.

The comparison that *is* defined: fixed K=4 made 76 high-confidence calls of
150 and was wrong on 8 — **10.5% of its confident calls, 95% Wilson CI
[5.4%, 19.4%]**.

**[Stage A.3]** replaces this with the analysis the deferral question actually
needs: risk–coverage curves at matched coverage, and an explicit attribution
of any selectivity to the agreement signal versus the controller wrapped
around it.

## 7. What this adds up to

The binding constraint on this system is **selection, not generation**. Across
150 held-out instances the correct answer is present among four samples far
more often than it is returned, and every mechanism tried for closing that gap
failed under prospective or pre-registered offline test: an adaptive
consensus controller (dominated by blind allocation at equal cost), the
consensus-history repair it pointed to (structurally unable to act, under
stated conditions), resampling for diversity (plans do not diverge), and
tool-enabled adjudication among the existing candidates (negative point
estimate, under an elicitation regime unstable enough that the null does not
generalise on its own).

The negative results are not symmetric, and the paper's value is in
distinguishing them. Three are structural or well-identified: the controller's
domination by blind allocation, the collapse of consensus rules at the budget
ceiling, and the absence of plan divergence are all measured against
controls or proved from stated conditions. The fourth — adjudication — is a
null whose instrument was demonstrably unstable, and it is reported as such
rather than promoted to a general claim about verification.

What follows is a methodological point rather than a benchmark result. A
reliability layer for scientific agents is usually proposed as a *policy*
question: when to stop, when to escalate, when to abstain. On this evidence
the policy vocabulary is the wrong level of description. Within an action set
whose only non-terminal move is to draw another correlated sample, and whose
terminal moves are accept-or-abstain, there is nothing for a richer stopping
rule to spend information on — the gains claimed for adaptivity in that
setting are recoverable by allocation that inspects nothing. Progress requires
either an action that changes the trajectory rather than repeating it, or a
terminal resolver that ranks candidates rather than counting them. Both lie
outside the vocabulary this literature has mostly been searching.

## 8. Reproducibility and deviations

The frozen artifacts, decision logs, per-trajectory source hashes, and the
scripts reproducing every table are described in the underlying reports; the
protocol deviations below are recorded because they bear on how much weight
individual numbers carry, not because they alter the conclusions above.

**A monitoring gate reported a false PASS.** The gate meant to block launch
when residual degeneration exceeded 15% tested `failure_class` for exact
equality against a string the runner never emitted, and so reported 0.0% in
every run it checked — including a smoke test whose true rate was 37.5% and a
full run at 15.5%, both above the halt threshold. Under the corrected gate the
smoke test would have blocked the launch it in fact authorised. Fixed with a
regression test keyed to the exact string it missed, and the corrected gate's
*failure* path has since been exercised end-to-end against live data. The
generalisable point: a gate whose failure path has never executed is not a
gate, and a suite that exercises only the pass path leaves precisely the
mode that matters unverified.

**The prospective run executed from an uncommitted tree.** All 600 runs
recorded a dirty working-tree flag and the controller file under test was
never committed, so no commit can honestly be cited as the execution commit.
An artifact-level audit recovered what the evidence supports and labelled the
rest unrecoverable: the config and manifest are cryptographically attested by
stored hashes, and the controller is attested *behaviourally* — all 434
committed decision records reproduce exactly against the current source, with
150/150 hash chains verifying — which establishes behavioural identity on the
domain the run visited, not byte identity. Every headline number recomputes
from stored artifacts, with 0/150 mismatches against the online decision log.
The gap is in source auditability, not in the numbers. Launch entrypoints now
refuse a dirty tree and every trajectory records a hash of the source that
produced it.

**One inference was retracted after publication of its decision record**
(D-39): the argument that the adjudication arm upper-bounds verification
because it saw strictly more information. See §4.5. The empirical result it
over-claimed on is unchanged; only its scope is.

---

*Numbers in this draft trace to `reports/phase1_report.md`,
`phase1_repaired_report.md`, `phase2_offline_replay.md`, `phase2_report.md`,
`controller_v2_offline_assessment.md`, `track_c_diversity_diagnostic.md`,
`context_overflow_forensics.md`, `evidence_channel_repair.md`,
`residual_failure_remeasurement.md`, `track_c_preflight.md`,
`track_c_step2.md`, and `DECISIONS.md` D-01–D-39.*
