# Stage C — stop rule, frozen before any Stage A number exists

**Written:** 2026-08-11T14:08Z. **Status: FROZEN.** Committed before Stage A
(`reports/stage_a_decomposition.md`) computed a single number, and before any
alternative aggregation of the Arm-2 data existed.

**Why the ordering matters, stated plainly.** Once alternative aggregations of
Arm 2 exist (Stage A.1 will produce several), a Stage C NO-GO becomes
negotiable — there will always be some re-slicing under which the verifier
looks better than under the frozen rule. The only thing that stops this
program from reading as a fifth successive attempt to rescue the same
hypothesis is that the stop was committed while the numbers were still
unknown. That is this document's entire purpose. It is not a plan; it is a
precommitment.

---

## 1. What Stage C is

A **published-verifier pilot**: the same candidate-adjudication task as Step 2's
Arm 2 (D-38), on the same 78 `B_substantive_disagreement` instances, but with
the two properties D-39 identifies as confounded in Arm 2 changed *by
construction*:

* **a different, published verifier model** — not the Biomni-R0-32B-Preview
  checkpoint that generated the candidates, so the verifier's errors are not
  drawn from the same policy as the generator's;
* **a stable elicitation interface** — structured, constrained answer
  extraction rather than free-form generation, so that "the model could not be
  made to emit a parseable in-menu choice" and "the model could not tell the
  candidates apart" are separable outcomes rather than one confounded one.

Stage C runs in a **separate session**. Nothing in Stage 0 or Stage A touches
it beyond this file.

## 2. What Stage C is testing, and what it is not

D-39 retracts D-38's claim that Arm 2 upper-bounds verification performance.
What survives is narrower: *free-form, same-model, tool-enabled candidate
adjudication failed under a maximally-informed but operationally unstable
regime.* Stage C tests whether the failure survives removing the two
candidate explanations for that instability.

Stage C is **not** a test of whether a larger or better model scores higher on
BiomniEval1. It is a test of whether **candidate selection among an existing
disagreeing set** is recoverable at all by an independent verifier. The floor
is what plurality voting already achieves on those same instances; the ceiling
is the best answer already present among the candidates. A verifier that
answers well but does not *select* better than voting has not moved this
question.

## 3. Pre-registered cells — fixed count, substitution permitted, expansion forbidden

**Two verifier cells. Not three. Not "and also try".**

| cell | role | proposed identity |
| --- | --- | --- |
| **C1** | *different lineage* — tests whether an independently-trained verifier of comparable or larger scale separates the candidates | a published general instruct model, distinct family from Qwen3, ≥32B |
| **C2** | *same lineage, no agent RL* — holds family and scale fixed and removes only Biomni-R0's agent-task RL fine-tuning, isolating whether that tuning cost verification ability | `Qwen/Qwen3-32B` (the base Biomni-R0-32B-Preview was tuned from) |

**Availability is a precondition, not an excuse.** As of writing, the only
general LLM present in the local HF cache is `biomni--Biomni-R0-32B-Preview`;
both cells require acquiring weights. If a cell's weights cannot be obtained
or served, that cell is reported as **not run, with the reason**, and Stage C
proceeds on the remaining cell. A missing cell is a stated limitation; it is
never grounds for substituting an extra prompt variant, an extra aggregation,
or a third model in its place.

**Amendment permitted only for identity, never for count.** Before launch, the
exact model ids and revision hashes must be pinned in a dated amendment to
this file (this project pins revisions everywhere — D-03, D-04). That
amendment may *substitute* a specific model for another of the same role when
availability requires it. It may **not** raise the cell count above two, and
it may not be written after any Stage C number exists.

## 4. Interface-validity precondition — bounded, one repair, checked before the verdict run

A Stage C null computed under an interface as unstable as Arm 2's would
reproduce Arm 2's ambiguity exactly, and would be worthless. So interface
health is checked **first**, on a smoke sample, and is **not** part of the
verdict run:

* **Smoke sample:** ≤10 of the 78 instances, ≤3 samples each, per cell.
* **Health bars** (all three required): off-menu rate ≤10%; no-majority rate
  ≤20%; hard degeneration-failure rate ≤10%. These are set against Arm 2's
  observed 46.2% / 47.4% / 17.9% — an interface is "stable" here only if it is
  decisively better than the one D-39 calls unstable, not marginally so.
* **Exactly one bounded repair is permitted** if a bar is missed: constrained
  decoding, answer-schema enforcement, context trimming, or an explicit
  enumerated-choice format. The repair is logged with its rationale before the
  re-check. **A second failure ends Stage C before the verdict run**, and is
  reported as "the elicitation interface could not be stabilised" — which is
  itself a publishable, bounded negative result about this class of verifier
  deployment, and is *not* an invitation to keep trying.
* Smoke instances are **not excluded** from the verdict run — the smoke check
  measures the interface, not the verifier's accuracy, and its answers are
  discarded.

**This precondition is not a retry loophole.** It runs once, permits one
repair, and cannot be invoked after the verdict run has started. Poor
interface health *observed in the verdict run itself* is reported as a
finding and does **not** license a re-run.

## 5. The frozen decision rule

Deliberately **identical** to D-38's, so Stage C is directly comparable to
Arm 2 and no bar-shopping is possible:

* **Population:** all 78 `B_substantive_disagreement` instances (53 `phase2b` +
  25 `phase1_pooled`). No new instances. No held-out pool consumed.
* **Floor / ceiling** (frozen, from D-37's canonical table): plurality floor
  **0.4103**, oracle ceiling **0.6026**, gap **0.1923**.
* **Δ** = (Stage C majority-resolved reward) − (plurality floor), per instance,
  paired instance-clustered bootstrap, 10,000 replicates, seed 20260811001.
* **GO** if Δ's 95% CI lower bound > 0.
* **NO-GO** if Δ's 95% CI upper bound < gap/3 = **0.0641**.
* **INCONCLUSIVE** otherwise.
* Each cell is evaluated separately. There is **no pooling across cells** and
  no "best cell" reporting — reporting the better of two cells as the result
  is a two-shot test dressed as one.

## 6. Stop semantics — the actual stop rule

**Stage C runs once.**

| outcome | consequence |
| --- | --- |
| **NO-GO** (either cell, or both) | **The experimental program ends.** The manuscript ships with Stage C as a bounded negative result. |
| **INCONCLUSIVE** | **The experimental program ends**, reported as inconclusive at this n — explicitly *not* read as a soft GO, and not grounds for a larger replication. |
| **GO** (any cell) | Authorises **exactly one** pre-specified confirmatory design, on held-out instances, which itself requires separate explicit approval before it is built. A GO is not authorisation for open-ended follow-up work. |

"Runs once" means: one manifest, one launch, per cell. Resuming a crashed
dispatch is infrastructure recovery, not a re-run. Adding samples, adding
instances, or re-launching after seeing a partial result is a re-run and is
forbidden.

## 7. Forbidden — the specific rescue moves this rule exists to block

None of the following may be performed after Stage C's numbers exist, and none
may be introduced as "additional analysis" to soften a NO-GO:

1. **No verifier model beyond the two pre-registered cells.** No "we also
   tried".
2. **No prompt search.** The verifier prompt is fixed by §4's process before
   the verdict run and is not tuned against outcome. Prompt variation is
   permitted *only* inside §4's single bounded interface repair, which is
   judged on interface-health metrics and is blind to reward.
3. **No debate, persona, ensemble, or multi-agent variants.**
4. **No re-aggregation shopping.** The verdict uses majority resolution as
   specified. Alternative aggregations may be reported as **mechanism
   analysis** (the same status Stage A.1 gives them), and may never be
   substituted into the decision rule.
5. **No bar movement.** The 0.0641 NO-GO bar and the CI-excludes-zero GO bar
   are fixed. Re-reading a CI as "close enough" is bar movement.
6. **No temperature/sampling-diversity variants** — D-30 already returned a
   NO-GO on diversity-by-resampling.
7. **No expansion to a different benchmark** to find a population where it
   works.

## 8. Relationship to Stage A — A.4 interprets, it never gates

Stage A.4 (trace-discriminability probe) bounds what Stage C *could* show: if
cheap trace features fail to separate the correct minority from the wrong
plurality (AUROC ≈ 0.5), a Stage C null is attributable to the traces carrying
no separating signal rather than to the verifier failing to use one.

That attribution is written into the **manuscript's interpretation** of the
result. It has **no** effect on whether the program continues. A.4 landing at
0.5 does not convert a Stage C NO-GO into "doesn't count"; it makes the NO-GO
*more* interpretable, not less binding. This clause exists because "the
measurement was uninformative, so let's measure again differently" is the
single most available rescue from here, and it is closed.

## 9. Provenance requirements

* Clean tree at launch (D-36 guard, never bypassed).
* Throwaway experiment tree; not written to `manifests/` or `configs/`; no
  experiment ID registered as active unless Stage C is promoted past a GO.
* Exclusion list re-checked: Stage C consumes zero held-out instances, and its
  78 instances are already on Step 2's exclusion list.
* Model ids **and revision hashes** recorded per cell, per trajectory.
* The verdict is computed by a script whose decision-rule constants are pinned
  against this file by test, exactly as
  `tests/test_track_c_adjudication_analyze.py` pins D-38's `gap/3`.

## 10. Amendment rule

This file is not edited after Stage C produces a number. Before that, the only
permitted amendment is §3's model-identity pinning. Any other revision must be
a dated, labelled amendment appended below, never a silent edit — the standing
rule for every frozen protocol in this project (D-32).

---

*No Stage C work has been performed. This file is a precommitment written
while the outcome is unknown, and is the authority against which any later
Stage C claim is checked.*
