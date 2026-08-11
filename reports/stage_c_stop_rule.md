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

---

# AMENDMENT 1 — 2026-08-11 — reachability denominator pre-registered

**Labelled amendment, appended per §10, not a silent edit.** Written before
Stage C runs and before any Stage C number exists. It adds a secondary analysis
and its bar; it does **not** alter the primary analysis, the primary bar, the
stop semantics, or any forbidden move in §7.

## A.7 finding: 31 of the 78 are unreachable by construction

A verifier that scores the **committed candidates** cannot reach an instance
where none of those candidates is correct — the right answer is not in the set
it is choosing from. Every such instance scores zero for every verifier, while
still occupying a slot in the denominator of any mean over the 78.

Measured on the frozen population (`scripts/stage_a7_overlap.py`), where
unreachable is defined without heuristics as **oracle over committed candidates
== 0**:

| | n | plurality floor | oracle ceiling | gap | gap/3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| **all 78** (primary, unchanged) | 78 | 0.4103 | 0.6026 | 0.1923 | **0.0641** |
| **reachable subset** (secondary) | **47** | 0.6809 | 1.0000 | 0.3191 | **0.1064** |

**31 of 78 (39.7%) are unreachable** — 20 from `phase2b`, 11 from
`phase1_pooled`. The reachable subset's oracle ceiling is exactly 1.0, which is
a consequence of the definition and serves as a check on it.

**Correction to the framing this amendment was requested under.** The A.5b
instances flagged as "the answer was in play" number **18, not 21**: the 3
extraction failures are a strict *subset* of the 18 singled-out instances, not
disjoint from them (verified directly — all 3 are also `singled_out`, which is
unsurprising, since a trajectory that generated the correct answer and lost it
to parsing would also have discussed it preferentially). **6 of those 18 fall
inside the frozen 78, and all 6 are unreachable**, consistent with the general
definition above.

## Pre-registered analyses, both bars fixed now

* **PRIMARY — unchanged.** Δ on all **78** against the existing **0.0641** bar,
  with §6's stop semantics applying to it exactly as written. This remains the
  analysis that decides GO / NO-GO / INCONCLUSIVE, and it is unchanged
  specifically so Stage C stays directly comparable to D-38.
* **SECONDARY — new.** Δ on the **47** reachable instances against a bar of
  **0.1064**, recomputed from that subset's own floor and ceiling.

**The secondary does not decide anything.** It cannot produce a GO, cannot
overturn a NO-GO, and cannot convert either into INCONCLUSIVE. It exists so
that a null on the full 78 can be read correctly: a verifier scoring zero on 31
instances it could not possibly get right is a different fact about the world
than a verifier failing on instances it could have got right, and the primary
alone cannot distinguish them.

**Why this is declared now.** Chosen after seeing Stage C's numbers, a
restricted denominator reads as a denominator picked to fit. Fixed before the
run, it is a stated limitation of the primary and a sharper reading of the
secondary. Both bars are frozen by this amendment and neither may move.

**Unchanged by this amendment:** §3's two cells, §4's interface-validity
precondition and its single bounded repair, §6's stop semantics (NO-GO **and**
INCONCLUSIVE both end the programme), and every forbidden move in §7 — in
particular, the secondary analysis introduced here is **not** licence for
re-aggregation shopping, and no third denominator may be added later.

---

# AMENDMENT 2 — 2026-08-11 — cell identities pinned; C2's role substituted

**Labelled amendment, appended per §10, not a silent edit.** Written before any
Stage C number exists and before any BiomniEval1 capsule has been scored. It
pins the two cells' identities (the amendment §3 explicitly anticipates),
substitutes C2's *role* (which goes beyond identity, and is therefore recorded
below as an operator decision rather than as a routine substitution), and fixes
the method departures and the interface-health mapping. It changes **no** bar,
**no** denominator, and **no** stop semantic.

## A three-cell design was proposed and declined

The Stage C brief pre-registered **three** verifier cells: a same-model control,
a cross-family primary, and a larger "capability ceiling" cell. §3 of this file
permits an amendment to *substitute* a model "of the same role" but states that
it "may **not** raise the cell count above two", and §7.1 forbids "no verifier
model beyond the two pre-registered cells".

**The cell count remains two.** The brief's third cell — the larger capability
ceiling — is **not run**. This is recorded here rather than left implicit,
because a ceiling cell is exactly the kind of addition §7.1 exists to block:
it is descriptive, it cannot change the verdict, and its availability after a
disappointing primary is what makes "we also tried" tempting.

## The two cells, pinned

| cell | role | model | revision |
| --- | --- | --- | --- |
| **C1** | *different lineage* — the **cross-family primary** | `google/gemma-4-31B-it` | `842da3794eaa0b77d5f08bae87a17459d91ff475` |
| **C2** | *same model* — **interface control** (role substituted, see below) | `biomni/Biomni-R0-32B-Preview` | `71432eb3d5e583bee757e0f9437a17e711e8e3d1` |

**C1 selection reasoning**, recorded as §3 and the brief both require. Chosen
for general verifier strength rather than biomedical specialization: a dense
~31B instruct model (`num_experts: null`, 60 layers, 62.5 GB bf16), so its
capability is not discounted by a small active-parameter fraction as it would be
for a same-nominal-size MoE; Gemma lineage, independent of the Qwen3 lineage
Biomni-R0-32B was tuned from; scale-matched to the 32B generator, so a C1-vs-C2
difference is not trivially a size difference; **ungated** on the Hub, so no
credential is needed and the choice is reproducible by a third party; and
natively supported by the SGLang version this project already serves with
(`Gemma4ForConditionalGeneration`, `sglang/srt/models/gemma4_mm.py`, 0.5.16),
so no serving-stack change is introduced alongside the model change.

## C2's role is substituted — an operator decision, labelled

§3 originally assigned C2 the role *same lineage, no agent RL*, proposing
`Qwen/Qwen3-32B` to isolate whether Biomni-R0's agent-task RL fine-tuning cost
it verification ability. C2 is instead `Biomni-R0-32B-Preview` itself, in the
role *same-model / interface control*.

This is a change of **role**, not merely of identity, so it is not the
substitution §3 pre-authorised. It was put to the operator as such, with the
alternative of honouring §3 exactly, and the substitution was chosen.

* **What it buys.** It tests D-39's actual hypothesis directly. D-39 retracted
  D-38 on the grounds that the failure was confounded by *same-model* and
  *unstable interface* together. With C2 holding the model fixed at the very
  checkpoint that failed D-38 and changing **only** the interface, a C2 result
  separates those two confounds by construction; C1 then varies the model at
  matched scale. The two cells become a clean 2-point contrast on the axis the
  retraction named.
* **What it costs, stated as a limitation and not deferred.** No cell now
  addresses whether agent-task RL degraded verification ability. That question
  is **not** answered by Stage C and does **not** become a candidate third cell
  later — §7.1 continues to bind.

## Method departures from the published configuration, frozen now

Both are deliberate, both are reported in the write-up, and neither is tuned
against any Stage C outcome:

1. **Full round-robin, not the Probabilistic Pivot Tournament.** PPT exists to
   avoid O(N²) comparisons at large N; the reference paper demonstrates up to
   N=20. Here N ≤ 4 unique candidate answers and usually 2 — measured on the
   frozen population: **59 instances with 2, 17 with 3, 2 with 4**. Full
   pairwise comparison in both directions is therefore **244 directed pairs
   across all 78 instances**, which is cheap, removes pivot-selection
   randomness, and makes the result independent of the ring seed. PPT is
   reported as a faithful secondary on the same cached scores.
2. **Biomedical criteria decomposition** replacing the published per-benchmark
   criteria, frozen in `reports/stage_c_preregistration.md` before any
   BiomniEval1 capsule is scored, at the published cardinality of three.

**Intransitivity, and an honest bound on it.** Round-robin buys a validity
diagnostic — a verifier with cyclic preferences over three candidates is
guessing — and it is reported. But a cycle requires N ≥ 3, so the diagnostic is
**defined on only 19 of the 78 instances (24.4%)**. It is reported with that
denominator visible and is not generalised to the other 59.

## §4's interface-health bars, mapped onto a scoring interface

§4's bars were written for a free-form arm that emitted a chosen answer and was
resolved by 2-of-3 majority. The scoring interface has no such step, so the
three bars are mapped now, before the smoke run, rather than being quietly
dropped:

| §4 bar | mapping under the scoring interface | bar |
| --- | --- | --- |
| off-menu ≤ 10% | **structurally impossible**: the score position is constrained by decoding to the 20 scale tokens, so a response outside the answer space cannot be emitted | 0% by construction |
| no-majority ≤ 20% | **unresolved round-robin** — no strict argmax of w_i/c_i, i.e. an exact tie at the top | ≤ 20% |
| hard degeneration-failure ≤ 10% | **comparison failure rate** — the fraction of directed comparisons that raise and are scored 0.5/0.5 by the runner's own error policy | ≤ 10% |

The brief's additional **structured-output validity ≥ 95%** condition is
adopted as a GO requirement and is measured as the complement of the comparison
failure rate. Note it is *stricter* than this file's original GO condition; a
stricter GO bar is recorded here because tightening the condition for a positive
result cannot rescue a null, which is the direction §7.5 protects against.

**A cost of the constrained interface, pre-registered.** Constraining the
verifier to score the committed candidates forfeits the case A.1 found where an
off-menu answer was *correct* because the true answer was absent from the
candidate set (5 of 24 off-menu Arm-2 trajectories). This is the same fact A.7
measures as **31 of 78 instances unreachable**, and it is why Amendment 1's
reachable-47 secondary exists. The constrained scorer cannot exceed the
reachable subset's ceiling, and the primary's denominator is unchanged anyway.

## The cross-family direction is declared OPEN

Neither direction is predicted. The literature is contested on exactly this
axis: cross-family verification is reported to strengthen as solver–verifier
similarity falls, while the General AgentBench study (arXiv 2602.18998)
hypothesises that models judge their **own** execution traces better, because
external verifiers struggle with unfamiliar traces — and a trace capsule is an
execution trace. C1 > C2 and C2 > C1 are both live outcomes under this
amendment, and neither is a surprise to be explained away after the fact.

**Unchanged by this amendment:** the primary Δ on all 78 against **0.0641**;
Amendment 1's reachable-47 secondary against **0.1064**; §5's per-cell
evaluation with no pooling and no best-cell reporting; §6's stop semantics
(NO-GO **and** INCONCLUSIVE both end the programme); and every forbidden move
in §7.
