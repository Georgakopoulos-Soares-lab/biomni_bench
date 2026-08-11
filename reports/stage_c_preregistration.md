# Stage C — pre-registration: capsule, criteria, scoring, budget

**Written:** 2026-08-11T16:30Z. **Status: FROZEN.** Written before any
BiomniEval1 trace capsule has been serialized and before any BiomniEval1
candidate has been scored by any verifier.

**This file is subordinate to `reports/stage_c_stop_rule.md`.** That file holds
the stop semantics, the cell count, the bars and the forbidden moves, and
nothing here modifies any of them. This file freezes the four things gate 4 of
the Stage C brief requires and the stop rule does not already fix: the **cell
list** (pinned in that file's Amendment 2 and restated here for reference), the
**criteria**, the **serialization format**, and the **compute budget** — plus
the reporting and interpretation commitments, written now so that neither can be
chosen after seeing a number.

The method is **LLM-as-a-Verifier** (arXiv 2607.05391), training-free, scoring
candidates by the expectation over the verifier's distribution across an ordered
set of score tokens rather than by a discrete judge verdict.

---

## 1. Population — frozen, nothing new generated

The **78** `B_substantive_disagreement` instances (53 `phase2b`, 25
`phase1_pooled`), already on Step 2's `exclusion_list.json`.

* **No new solver trajectories are generated for the verdict.** Every candidate
  comes from already-completed, frozen trajectories.
* **Zero held-out pool consumed.**
* Frozen floor/ceiling, unchanged: plurality **0.4103**, oracle **0.6026**,
  gap **0.1923**, bar **0.0641**. Reachable-47 secondary: floor **0.6809**,
  ceiling **1.0000**, bar **0.1064** (Amendment 1).

**Unique-candidate structure, measured on the frozen population:** 59 instances
with 2 unique candidate answers, 17 with 3, 2 with 4. This is what makes full
round-robin cheap and what limits the intransitivity diagnostic to 19 instances.

## 2. Cells — two, pinned in Amendment 2

| cell | role | model | revision |
| --- | --- | --- | --- |
| **C1** | different lineage — **cross-family primary** | `google/gemma-4-31B-it` | `842da3794eaa0b77d5f08bae87a17459d91ff475` |
| **C2** | same model — **interface control** | `biomni/Biomni-R0-32B-Preview` | `71432eb3d5e583bee757e0f9437a17e711e8e3d1` |

Each cell is evaluated separately. No pooling, no best-cell reporting. The
cross-family direction is declared **open** — see Amendment 2.

## 3. The trace capsule — allowlist, not denylist

One deterministic capsule per **unique candidate answer**. Built by allowlist,
mirroring `policy.TrajectoryView`: a fixed field list, with everything not named
structurally absent rather than filtered out by convention.

### 3.1 Included

| field | source |
| --- | --- |
| `task_name`, `task_prompt` | the prompt as given to the solver, verbatim |
| `committed_answer` | canonical parsed answer (`parsed_answer.json`) |
| `answer_parse_status` | `final_answer.payload.parse_status` |
| `tools_invoked` | ordered `(tool_name, status)` from `tool_call_start` / `tool_call_end` |
| `retrieval_selection` | **counts only** (`retrieval_end.payload.selected`) |
| `code_executions` | ordered `(language, code_excerpt, status, error)` |
| `evidence_returns` | `stdout_excerpt` per execution, with a truncation marker where `observation_truncated` fired |
| `failures` | failed tool calls, non-`ok` statuses, errors, truncation events, empty returns |
| `provenance` | `argument_hash`, `code_hash` per step (D-33) |

**Availability is confirmed, not assumed** (brief gate 2). Every field above was
read out of live `phase2b` and `phase1_pooled` event logs before this file was
written; both pools carry the same instrumentation and the same artifact set
(`events.jsonl`, `transcript.json`, `parsed_answer.json`). Excerpt caps observed
in the existing traces: `code_excerpt` ≤ 3276 chars, `stdout_excerpt` ≤ 4000
chars, `argument_excerpt` ≤ 83 chars.

**One instrumentation gap, declared.** D-30's finding stands: the retriever logs
only *counts* of selected tools, never their identities. Tools actually
**invoked** are named (`tool_call_start.payload.tool_name`), so the capsule
carries real tool identity; what it cannot carry is which tools the retriever
*offered*. Evidence-overlap between trajectories therefore remains unmeasurable,
exactly as D-30 recorded.

### 3.2 Excluded — `FORBIDDEN_CAPSULE_FIELDS`

Strictly extends `policy.FORBIDDEN_VIEW_FIELDS` and follows D-32's
`FORBIDDEN_VERIFY_FIELDS` specification. Enforced by test, not by convention.

| excluded | why |
| --- | --- |
| `reward`, `strict_reward`, `correct`, `evaluation_status`, `evaluation_error` | ground truth never reaches a selector but `oracle` |
| vote count, support, `agreement_fraction` | the verifier must not be able to reconstruct the plurality baseline it is being compared against |
| `trajectory_index`, `run_id`, `position` | which sample produced the candidate |
| `final_confidence`, `confidence_parse_status` | D-32's anti-anchoring rule — an "independent" judgement must not be partly re-derived from the original's stated confidence |
| the other candidates | structural: each capsule is built independently, from one trace |
| model text / transcript / `AIMessage` content | free-form hidden reasoning |

### 3.3 Determinism, and the leak the format is designed against

* **Representative trace.** When several trajectories share a canonical answer,
  the capsule is built from the one with the lexicographically smallest
  `run_id`. Deterministic, independent of arrival order, and independent of how
  many trajectories agreed.
* **Capsule size must not encode support.** This is the non-obvious leak: if a
  capsule merged every trace holding an answer, a 3-vote candidate would produce
  a visibly longer capsule than a 1-vote candidate, and the verifier could
  recover plurality from length alone — reproducing the baseline instead of
  testing against it. Using exactly one representative trace closes it.
* **Fixed-key rendering.** Every section is emitted in a fixed order with a
  fixed header, and empty sections are rendered explicitly as `(none)` rather
  than omitted, so that absence is legible and does not signal through length.
* Excerpt caps are fixed constants applied identically to every capsule.

## 4. Criteria — frozen, biomedical, C = 3

Replacing the published per-benchmark criteria at the published cardinality.
Label-free: no criterion refers to the correct answer, and each is computable
from the capsule alone.

**Ground-truth note** (prepended to every comparison):

> You are scoring a biomedical analysis trajectory. Do NOT trust the agent's
> self-assessment; its stated confidence is deliberately withheld from you and
> would not be reliable. The only reliable evidence is what the tools and code
> actually returned. A correct answer may be a specific entity, a set, or an
> explicit statement that the evidence does not determine one. Do not favour
> specific-looking answers over cautious ones, or the reverse. Judge only
> whether the trajectory's own evidence logically supports what it committed.

**`#evidence` — Evidence adequacy and identifier fidelity.** Consider only what
the trajectory actually queried and retrieved. Did the tools and databases
invoked address the entity the task names? Are the identifiers used — gene
symbols, ENSG IDs, rsIDs, variant coordinates, OMIM codes, drug names, cell
lines — the ones the task specifies? Check them character by character. Were the
queries capable of returning evidence bearing on the question asked? A
trajectory that ran no query has no retrieved evidence; score it on that basis,
but do not reward querying for its own sake. Ignore the fluency of the write-up.

**`#alignment` — Answer–evidence alignment.** Look at what the tool and code
output actually returned. Where returns were empty, errored, or truncated, the
only answers they support are ones that acknowledge it; asserting a specific
biomedical entity from an empty or failed return is fabrication. Where
substantive evidence was returned, the committed answer should follow from it,
and ignoring returned evidence is equally wrong. Where the answer is computed —
a count, a rank, a set — check the computation against the returned records.

**`#commitment` — Commitment validity.** The trajectory must commit exactly one
answer in the form the task requires. Is exactly one answer committed, rather
than several left in play? Is it of the required type and cardinality — a single
gene symbol versus a list, an identifier versus a name, a set where a set is
asked for? Is it drawn from the answer space the task defines, where one is
defined? Discussion of an alternative that is never committed is not an answer.

## 5. Scoring configuration — published defaults, one departure

| parameter | value | source |
| --- | --- | --- |
| score granularity G | 20 (letters A–T) | published |
| repeated evaluation K | 8 | published default |
| criteria C | 3 | published cardinality, biomedical content |
| ranking | **full round-robin, both directions** | departure, Amendment 2 |
| aggregation | Bradley–Terry soft wins, argmax of `w_i / c_i` | published |
| constrained decoding | SGLang `regex` over the 20 scale tokens | port fix, §7 |

**PPT is reported as a faithful secondary at zero extra compute.** A PPT run's
directed pairs are a strict subset of the full round-robin's, so the secondary
is a re-aggregation of scores already cached — not new sampling, and not a
second shot at the endpoint.

## 6. Decision rule — inherited verbatim, nothing new

Unchanged from `stage_c_stop_rule.md` §5 and Amendment 1. Restated only so this
file is self-contained; if the two ever disagree, the stop rule governs.

* **Primary.** Δ = (Stage C selected-candidate reward) − (plurality floor) on
  all **78**, paired instance-clustered bootstrap, 10,000 replicates, seed
  `20260811001`.
* **GO** if Δ's 95% CI lower bound > 0, **and** structured-output validity
  ≥ 95%, **and** no task family shows a large negative reversal.
* **NO-GO** if Δ's 95% CI upper bound < **0.0641**, or validity < 95%.
* **INCONCLUSIVE** otherwise.
* **Secondary** (decides nothing): Δ on the reachable **47** against **0.1064**.
* Each cell separately. No pooling. No best-cell reporting.
* On NO-GO **or** INCONCLUSIVE the experimental programme ends.

The decision-rule constants are pinned against this file by test, exactly as
`tests/test_track_c_adjudication_analyze.py` pins D-38's `gap/3`.

## 7. The port, and why gate 1 is not a formality

The reference implementation supports SGLang on paper and **fails silently
against it in practice**. Its prefill step constrains the score position with
vLLM's `structured_outputs`; SGLang's `ChatCompletionRequest` declares no
`model_config`, so pydantic's default `extra="ignore"` drops the field without
error. Measured against this project's own served endpoint, with the full scale
description in the prompt:

| constraint sent | on-scale probability mass |
| --- | ---: |
| none | 0.5995769754515692 |
| `structured_outputs` (vLLM shape) | 0.5995769754515692 — **bit-identical** |
| `regex` (SGLang shape) | **0.9884** |

The reference code would then renormalize the expectation over a fragment of the
distribution, and on failure fall back to a flat 0.5 — a tie indistinguishable
from a verifier that genuinely cannot separate two candidates. `scripts/
stage_c_verifier_port.py` replaces the constraint mechanism and **raises**
instead of silently tying. The reference runner's own `on_error="tie"` policy is
left in place so the reproduction number stays comparable, but every failed
comparison is logged and the failure rate is reported alongside the score.

**A second, smaller port change, with its cost measured.** The reference offers
each scale letter in two spellings, bare and space-prefixed, so that models
which prefer a leading space are not penalised. That makes the constrained
support 40 tokens while `top_logprobs` is capped at 20, so the returned
distribution is truncated — measured coverage on real MedAgentBench comparisons
ranged from **0.762 to 0.9999** — and `extract_score` folds two spellings of one
value with `max` rather than a sum. The port constrains to the **20 bare
letters**, making the support exactly equal to the cap (measured coverage
**1.0000**) and token-to-value a bijection. Cost of the restriction, measured on
12 real comparisons across 4 tasks and all 3 criteria before this file was
frozen: **mean |ΔR| = 0.0005, max |ΔR| = 0.0015**. The constraint is applied
identically to slot A and slot B of every comparison, so it cannot bias a
pairwise preference.

Gate 1 runs the published implementation on the reference repo's own shipped
MedAgentBench trajectories. **The reproduction anchor is skipped**: the
published MedAgentBench figure (73.3%) uses Gemini 2.5 Flash via Vertex, and no
Vertex credentials exist on this allocation. Per brief §3 the port's absolute
number is reported against the published one and labelled explicitly **not a
controlled comparison**. This does not amend the project's standing rule against
proprietary-model dependencies; that rule binds on a comparator inside the
candidate pool, and every cell touching BiomniEval1 is open-weight.

**A confirmation that the shipped data is intact:** the loader yields 300 tasks,
187 all-pass, 38 swing, 75 all-fail, so Oracle = (187+38)/300 = **75.0%**,
exactly the published Oracle. The port is being validated against data that
reproduces the paper's own denominator.

## 8. Capability covariate — measure the confound, do not caveat it

Each verifier model is additionally run **as a solver at K=1 on the same 78
instances** (78 trajectories per model, 156 total). Parameter count does not
guarantee matched capability, and without this anchor a C1-vs-C2 difference
cannot be separated from a difference in raw ability. Verification gain is
reported conditional on solve accuracy. This incidentally measures whether the
biomedical finetune buys anything on these instances.

These are **new trajectories on the frozen 78**, which consume no held-out
instance and do not enter the verdict. They are covariate measurements, never a
candidate pool: no capability-covariate answer is ever added to the candidate
set a verifier chooses from.

## 9. Reporting — fixed now, for every cell

Capture / harm / net gain under Stage A's A.2 decomposition (capture = plurality
wrong and selector correct; harm = plurality correct and selector wrong or
unresolved; harm subdivided into wrong in-menu, unresolved tie, comparison
failure); fraction of the oracle gap recovered; candidate-ranking AUROC;
**intransitivity rate, with its n = 19 denominator stated**; accuracy
conditional on verifier score margin; risk–coverage using the margin as the
selection signal; same-model vs cross-family difference **conditional on solve
capability** (§8); task heterogeneity; and **total cost with verifier compute
counted** — tokens and GPU-seconds, not trajectory counts, because a verifier
that generates no new Biomni trajectory is not thereby free.

Official and A.5b audit-corrected headroom figures are reported **side by side**
wherever headroom is quoted, per brief gate 2's instruction: A.5b moved the
`phase2b` denominators (no-correct 45 → 42, Oracle@4 0.700 → 0.720, selection
headroom 0.093 → 0.113), and A.5b's own 51% is reported as the band **20%–51%**
per D-42. The frozen 78's floor and ceiling are unaffected.

## 10. Interpretation — bounded, written before the numbers exist

| observed | supported reading |
| --- | --- |
| C1 (cross-family) beats C2 (same-model) | a heterogeneity effect — though not clean causal isolation; read the margin against A1.1's 69.5 pp family-neutral anchor before attributing it to lineage rather than capability |
| both cells fail | see the two rows below; no capability-ceiling cell exists to distinguish scale, and none is added |
| both cells succeed | the D-38 arm's **interface** was the problem, as D-39 argued |
| **C2 fails** | **ambiguous** (A1.2) — between "the interface was not D-38's problem" and "this checkpoint is a weak verifier generally", which gate 1's 23.6% cannot separate. Does **not** license concluding that D-39's retraction was wrong. |
| **C2 succeeds** | **unambiguous** (A1.2) — strong evidence *for* D-39's retraction: same checkpoint, same candidates, same population as Arm 2, interface the only change |
| all cells fail, and A.4/A.6 found trace features at AUROC ≈ 0.5 | a broader trajectory-verification gap: the traces, not the verifier |
| scores discriminate but policy gain is absent | a calibration/aggregation limitation |

**A.4 and A.6 interpret; they never gate** (stop rule §8). Both landed null —
A.4's `total_output_tokens` cleared the nominal bar by 0.0002 and died under a
post-hoc Bonferroni correction; A.6's primary `own_answer_share` sat at 0.504
under a correction fixed in advance. A Stage C null is therefore attributable to
the traces on positive evidence across both the structural and semantic feature
classes. That makes a NO-GO **more** interpretable, not less binding.

**The scale question is closed, not deferred.** With no third cell, "both ~30B
cells failed but a larger verifier might not" is a statement Stage C cannot
address, and it does not become a follow-up.

## 11. Compute budget — frozen

| item | comparisons / trajectories | note |
| --- | ---: | --- |
| gate 1 port validation, per model | 10,944 | 38 swing × 12 directed pairs × 3 criteria × 8 reps |
| interface smoke, per cell | ≤ 600 | ≤ 10 instances, stop rule §4 |
| Stage C verdict, per cell | 5,856 | 244 directed pairs × 3 × 8 |
| capability covariate, per model | 78 | Biomni agent trajectories, K=1 |

**Ceiling: 40,000 verifier comparisons and 200 Biomni trajectories in total.**
Exceeding the ceiling halts Stage C rather than requesting more; a budget that
moves under pressure is not a budget. Caching is per directed
`(criterion, task, a, b, rep)` key, so an interrupted dispatch resumes without
rescoring — infrastructure recovery, not a re-run (§6 of the stop rule).

## 12. Provenance

* Clean tree at launch, D-36 guard active, never bypassed.
* Throwaway experiment tree under `$output_root/stage_c_*`; nothing written to
  `manifests/` or `configs/`; no experiment ID registered as active unless
  Stage C is promoted past a GO.
* Model ids **and revision hashes** recorded per cell, per trajectory.
* The reference implementation is a **pinned external checkout, never edited** —
  the same discipline Biomni gets under D-01. The port is an adapter
  (`scripts/stage_c_verifier_port.py`) that patches at import time; the
  reference commit is recorded in every run's metadata.
* Serving stack unchanged: SGLang 0.5.16, bfloat16, context 65536, the same
  launcher every earlier phase used.

## 13. Explicitly not to be done

Carried from brief §6 and stop rule §7, restated so this file is self-contained:
a second full solver run; the `VerifyView` mode-A implementation; fine-tuning
any verifier before zero-shot signal exists; **any verifier model beyond the two
pre-registered cells**; prompt or criteria search after seeing a result;
consuming any held-out instance outside the frozen 78; another benchmark;
re-aggregation shopping; bar movement.

---

# ADDENDUM 1 — 2026-08-11 — three interpretation pre-registrations enabled by gate 1

**Written after gate 1 completed and before any BiomniEval1 capsule was
serialized or scored.** These are **pre-registrations, not protocol changes**.
No threshold, sample, prompt, verifier configuration, task allocation or
decision rule moves. §6's rule is untouched, both bars are untouched, and
nothing here can produce, overturn or soften a verdict. They are recorded now
because gate 1's result made them formulable and the verdict does not yet exist.

## A1.1 — Gate 1 is a family-neutral verification-capability anchor

The MedAgentBench trajectories were generated by **Claude Opus 4.8**. Neither C1
nor C2 is the generating model there, so **family is held constant across the
two cells** — both are external verifiers of a third party's traces. That is
exactly what makes the gate-1 gap a clean measurement of *verification
capability*, uncontaminated by lineage.

**Reference point, frozen (full 300-task MedAgentBench, published
configuration, 0 comparison errors):**

| | C1 `gemma-4-31B-it` | C2 `Biomni-R0-32B` | margin C1 − C2 |
| --- | ---: | ---: | ---: |
| oracle headroom recovered | 93.1% | 23.6% | **69.5 pp** |
| rate | 74.7% | 71.3% | 3.4 pp |
| swing tasks selected correctly | 37/38 | 27/38 | 10 tasks |

**On BiomniEval1 the family symmetry breaks**, and in a known direction: C2 **is**
the model that generated the candidates, C1 is not. So the same margin measured
there carries an extra term that was absent on MedAgentBench. Pre-registered
reading of C1's margin over C2 on the frozen 78:

* **comparable to the 69.5 pp anchor** → attributable to **capability**; the
  cross-family difference adds nothing beyond what the family-neutral corpus
  already showed.
* **materially larger than the anchor** → **heterogeneity on top of capability**;
  the increment is what same-model verification costs, since C2 is same-model
  here and was not there.
* **materially smaller than the anchor** → *added here as the logical complement,
  because a two-branch rule that omits the direction favouring C2 would be
  one-sided.* This is the direction the General AgentBench hypothesis
  (arXiv 2602.18998) predicts — a model judging its **own** execution traces
  better — and Amendment 2 declares the direction open, so it must be readable.

**No numeric threshold is attached to "comparable" or "materially larger".**
Fixing one would create a second decision rule through the back door. This
comparison is **interpretation only**: it decides nothing, and §6's stop
semantics run entirely off the primary Δ.

**The assumption this rests on, stated so it can be attacked.** It assumes
**verifier capability ranking is stable between mechanically-checkable and
judgment tasks**. MedAgentBench correctness is largely decidable by checking
FHIR query parameters and returned JSON against the question; BiomniEval1
disagreement instances turn on biomedical judgment. If that ranking is not
stable — if, say, a model strong at structured checking is not correspondingly
strong at domain inference — the 69.5 pp anchor is not the right reference point
and this whole comparison is void. It is reported with that caveat attached, not
as an established calibration.

## A1.2 — A C2 null is ambiguous; a C2 success is not

C2 recovered only **23.6%** of available headroom on a clean,
mechanically-checkable corpus, as a bounded scorer with no agent loop, under a
constrained interface that produced **zero** comparison errors. Every condition
D-39 blamed for D-38's instability was already removed, and C2 still performed
weakly. That asymmetry must be recorded before the verdict, because it is
exactly the kind of thing that becomes convenient after it:

* **A C2 failure on BiomniEval1 is ambiguous** between *"the interface was not
  D-38's problem"* and *"this checkpoint is a weak verifier generally."* Gate 1
  cannot separate these, because 23.6% is already low on a corpus where the
  interface was demonstrably healthy. A C2 null therefore **does not** license
  the conclusion that D-39's retraction was wrong.
* **A C2 success on BiomniEval1 is unambiguous**, and is strong evidence *for*
  D-39's retraction: same checkpoint, same candidates, same population as
  D-38's Arm 2, with the elicitation interface as the one thing changed.

This asymmetry is added to §10's interpretation table and binds the write-up.

## A1.3 — The capability covariate: report UNAVAILABLE rather than a floor

§8's covariate runs each verifier model **as a solver** on the frozen 78. C1 is
not the model Biomni's scaffold was built around: Biomni-R0-32B was tuned for
its tag conventions, its `<execute>` / `<solution>` blocks and its
`</execute>` / `</solution>` stop sequences.

**Pre-registered now:** if `gemma-4-31B-it` cannot operate the Biomni scaffold —
failing to emit usable tagged blocks, or terminating degenerately rather than
solving — the covariate is reported as **UNAVAILABLE for C1, with the failure
mode stated**. It is **never** reported as a capability estimate. A scaffold
floor effect presented as a measurement would understate C1's ability and, worse,
would make C1's verification gain look artificially large *relative to its
apparent solve accuracy* — which is precisely the quantity §8 exists to
condition on. **A missing number is better than a wrong one**, and §8's purpose
is defeated by a number that measures scaffold compatibility instead of
capability.

The covariate is **deferred**, and the deferral is **scheduling, not a finding**:
the h100 allocation expired with the verdict run unstarted, and 156 agent
trajectories do not fit alongside the two verdict cells. It is not part of
primary adjudication, and the verdict does not wait on it. Where a Stage C
result is reported before the covariate exists, the conditioning in §9 is
reported as **pending**, not as satisfied.

---

*No BiomniEval1 capsule has been scored at the time of writing. This file is a
precommitment, and is the authority — together with `stage_c_stop_rule.md` —
against which any later Stage C claim is checked.*
