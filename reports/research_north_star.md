# Research north star

The document to re-read when the work starts feeling like plumbing.

---

## The question

> **Can biomedical AI agents recognise when their scientific analyses are
> unreliable, and allocate verification effort accordingly?**

Not "can we make Biomni score higher on BiomniEval1". The intended contribution
is a **general reliability layer for scientific agents**: a component that
watches a trajectory, estimates whether its conclusion can be trusted, and
decides whether to accept it, verify it, repair it, sample again, or hand it to a
human.

Biomni + Biomni-R0-32B + BiomniEval1 is the **testbed**, not the subject.

## Why it matters

An agent that is wrong 40% of the time but *knows which 40%* is deployable. An
agent that is wrong 20% of the time with uniform 96% stated confidence is not.
Phase 1 measured a mean stated confidence of 0.96 against an actual accuracy of
0.59 — the second agent is the one we have.

## What is established (Phase 1, independently verified)

* Better candidates exist: Oracle@4 0.620 vs first-trajectory 0.420 — **20 pp** of
  headroom, 34.5% relative error reduction.
* They are findable without ground truth: plurality 0.580, **+0.16** over first,
  95% CI [+0.06, +0.26].
* Consensus is the strongest measured signal: `agreement_fraction` AUROC
  **0.874**, above verbalized confidence (0.789).
* Confidence *ranks* but does not *calibrate*: overconfidence gap **0.37**,
  ECE 0.370.
* Diminishing returns are steep: K=1→2 +12.2 pp, 2→3 +4.8, 3→4 +2.5. **K=2
  captures ~63% of the K=4 headroom at half the cost** — which is the entire
  economic case for an adaptive controller.

## What is not established

* Anything after **trajectory 1**, when no agreement signal exists. This is the
  hard half of the problem and Phase 1 does not solve it.
* Whether any of it transfers to another agent or model.
* Whether a correct answer was reached by a **valid workflow**. Phase 1 scores
  final answers only. A right answer from a broken analysis is a failure that
  this project currently cannot see.
* Whether the signals hold at full completion — 24% of the pilot was lost
  non-randomly (`reports/phase2_entry_assessment.md` §3).

## The target result

> **Approach fixed-K=4 reliability at roughly K=2 average compute, while
> recovering tool and context failures and abstaining safely when uncertainty
> stays unresolved.**

A complicated selector that adds 2 points of accuracy at K=4 cost is **not** the
result. Plain fixed-K plurality is the baseline that must stay visible in every
comparison, and a method that only wins by spending more has not won.

---

## The five questions

Ask before any substantial piece of work:

1. Does this resolve an important **scientific** uncertainty?
2. Is it required for a **valid evaluation**?
3. Is it likely to **generalise** beyond these 50 pilot instances?
4. Would it matter for **another biomedical agent**?
5. Is there a **simpler experiment** that answers the same question?

Two or more "no"s means stop and say so, rather than building it anyway.

### Worked example — the context-overflow repair

1. **Yes.** 24% non-random data loss makes every aggregate a biased estimate.
2. **Yes.** Intention-to-evaluate results are impossible without it.
3. **Yes.** "Serving a model beyond its trained context degrades it into
   repetition loops, and a bigger window makes that worse" is a property of
   long-context serving, not of Biomni.
4. **Yes.** Any agent looping a long-context model over tool output hits this.
5. **Partly.** The forensics itself was the simple experiment — it cost zero GPU
   hours and it is what ruled out the expensive repairs (bigger context, prompt
   rewriting). The rerun is the minimum remaining spend.

Contrast — **trimming Biomni's tool descriptions**: (1) no, (2) no — the median
post-retrieval prompt is 2,687 tokens, (3) no — Biomni-specific, (5) yes, the
measurement already answered it. **Not doing it**, despite it being first on the
brief's repair list. The measurement overruled the plan; that is what the
measurement was for.

---

## Standing constraints

* **50 instances.** One instance moves a rate by 2 pp. Per-task cells hold 5.
  No model with more than a handful of parameters. No neural selector.
  `GroupKFold` on the instance, always.
* **Ground truth is read by exactly one selector** (`oracle`), labelled an upper
  bound everywhere. It never selects instances, never resolves an ambiguous
  parse, and never reaches the agent or the controller.
* **The oracle is not a method** and never becomes a baseline.
* **Failed runs are evidence.** Never deleted, never retried into silence.
* **Offline replay is not prospective evidence** and must be labelled as such
  wherever it appears.
* **Confirmatory and exploratory analyses stay separately labelled.** Anything
  decided after seeing data says so.

---

## Architecture consequence

Keep the generic layer separable from the Biomni layer, so transfer is a
possibility rather than a rewrite — but do **not** build a second adapter until
there is a result worth transferring:

```
generic:  trajectory schema · risk-signal interface · controller/action schema · policy replay
biomni:   A1 adapter · instrumentation · canonicalization · BiomniEval1 evaluator
```

One agent, done properly, beats two done shallowly. The separation is insurance,
not a feature.

---

## Forest checks

At each milestone, append to `PROJECT_STATUS.md`:

1. What scientific uncertainty was resolved?
2. Did the main research claim change?
3. Is the next task necessary for the central contribution?
4. Are we overfitting to implementation details or to the original pilot?
5. What is the simplest decisive next experiment?

---

## The failure mode to watch

This project's characteristic risk is not sloppiness — it is **producing
excellent engineering for a question nobody asked**. The overflow repair is
necessary and its diagnosis was cheap. The moment it becomes an inference-serving
optimisation project rather than a two-day unblock, the north star has been lost.

The controller is the contribution. Everything before it is clearing the road.
