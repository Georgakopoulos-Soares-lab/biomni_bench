# Track C — first diagnostic: is disagreement between trajectories substantive?

**Written:** 2026-08-10. **Experiment:** `track_c_diversity` (analysis-only, new
ID). **CPU only, ~4 min, read-only, no GPU, no model calls.** Nothing about
prompts, temperature, tools, models or trajectory generation was changed.
Driver: `scripts/track_c_diversity.py`. Reusable primitives:
`src/biomni_uncertainty/diversity.py`. Tests: `tests/test_diversity.py` (19).
Full suite: **409 passed**, lint clean. Tables and one figure:
`<output_root>/track_c/results/`.

> **EVIDENCE CLASS: OFFLINE, EXPLORATORY.** This re-reads the Phase-2B traces —
> data that has already been used. It is a *feasibility diagnostic for a future
> experiment*, not a test of any hypothesis. The interpretation rule in §2 was
> written into the script's docstring **before any outcome association was
> computed**, so the label could not be chosen to fit the result.

> ## GO/NO-GO: **Outcome B, with a strong secondary component of Outcome C.**
> **NO-GO for "generate more diverse trajectories" as a Track-C intervention.**
> Trajectories that reach different conclusions have **the same plans** as
> trajectories that agree (plan Jaccard 0.546 vs 0.538, difference +0.008, 95%
> CI [−0.040, +0.058]), against a "different question" null of 0.301. Where
> workflow *does* diverge, the divergence **does not predict correction**
> (+0.056, 95% CI [−0.074, +0.180], non-monotone across quartiles), and a
> correct minority is **not** more isolated from the wrong plurality than that
> plurality is from itself (−0.037, 95% CI [−0.131, +0.046]).
>
> A useful `VERIFY` action therefore cannot be "sample again, differently." §8
> states what it would have to do instead.

---

## 1. Dataset and inclusion

| item | value |
| --- | --- |
| source | Phase-2B preserved traces: 600 trajectories over 150 held-out instances (434 consumed + 166 shadow) |
| unit of analysis | the **instance** for every statistic; pairs are nested inside it (D-13) |
| within-instance pairs | 900 (6 per instance); **566** have both sides usable |
| bootstrap | 10,000 replicates, **resampling instances, not pairs**, seed 20260811 (a new stream) |
| control | 3,290 pairs drawn from **different instances of the same task** — see §3 |

**Usable** uses the controller's own definition (D-11/D-18): the run completed
*and* produced a parseable, clusterable answer. Failed runs stay in the sample
and are analysed separately, never deleted.

---

## 2. The interpretation rule, fixed in advance

Copied verbatim from `scripts/track_c_diversity.py`'s docstring, written before
any association was computed:

* **Outcome A — useful independence exists.** P(correct | high workflow distance
  from a wrong trajectory) exceeds P(correct | low distance) by **≥ 10 pp** with
  a 95% instance-clustered CI excluding 0, **and** correct-minority trajectories
  are further from the wrong plurality than the plurality's members are from each
  other. ⇒ Track C should deliberately generate independent verification.
* **Outcome B — correlated upstream, noisy downstream.** Disagreeing pairs are
  no more distant than agreeing pairs (difference < 0.05, or CI covering 0).
  ⇒ resampling is not producing independent verification; Track C must
  explicitly decorrelate.
* **Outcome C — already diverse, still wrong together.** Disagreeing pairs *are*
  substantially more distant (≥ 0.05) but distance does not predict correction.
  ⇒ more diversity is not the answer; reframe toward external verification.

Mixed outcomes are permitted and reported as mixed.

---

## 3. How "different" is measured

Four levels, all structural set/sequence comparisons over what the agent
actually did. **No embedding model and no LLM judge is used** — the stored
structure was sufficient, so the escape hatch was not needed.

| level | metric | why this and not something else |
| --- | --- | --- |
| **answer** | canonical cluster key | already computed upstream by the frozen canonicalizer |
| **plan** | Jaccard over content words of the **first `<think>` block** | it is emitted *before any tool runs*, so it is the trajectory's own opening analysis conditioned only on the prompt. Later reasoning is contaminated by observations, which are themselves a function of earlier tool choices — comparing whole transcripts would measure how much the *environment* diverged, not the *plan*. |
| **tool path** | Jaccard on the tool set; `SequenceMatcher` ratio on the ordered tool sequence | order-free and order-sensitive views of the same path |
| **evidence** | Jaccard on content words of tool-call **arguments** (the literal queries issued); Jaccard on exact **code-block hashes** | the arguments are what evidence was actually sought; identical code hashes detect literal workflow duplication |

`workflow_distance` = 1 − mean of the four available similarity components. Each
component is also reported on its own; the composite exists so one number can be
plotted, never so a component can hide inside it.

**Two measurement decisions that matter, both load-bearing and both tested.**

1. **An empty side yields `None`, not 0.0.** A trajectory that made no tool call
   is *not comparable* on tool path; scoring it 0.0 would label every degenerate
   run "maximally independent" and manufacture a positive Track-C result.
   `tests/test_diversity.py` asserts this for every metric.
2. **Missing components drop out of the composite** rather than being imputed.

**What could not be measured, stated plainly.**

* `system_prompt.txt` takes exactly **two** distinct values across all 600
  trajectories (one per condition) — it is a static base prompt and carries no
  per-trajectory retrieval signal. It is not used.
* The `retrieval_end` event records only **counts** of selected tools, never
  their names. Retrieval *overlap* is therefore unmeasurable; the counts are
  carried descriptively and nothing is inferred from them about *which* evidence
  was retrieved. **This is a real gap and the single most valuable thing to
  instrument before any Track-C run.**

### The control, without which none of the numbers mean anything

A within-instance plan Jaccard of 0.54 is uninterpretable on its own. The
control pairs trajectories from **different instances of the same task** — two
trajectories answering *different questions*, which cannot be convergent on
anything except style and task boilerplate:

| metric | within-instance (both usable) | control: different question | verdict |
| --- | ---: | ---: | --- |
| plan Jaccard | **0.540** | **0.301** | plans are strongly question-specific — the metric works |
| query Jaccard | 0.347 / 0.277 | **0.158** | queries are question-specific |
| tool-set Jaccard | 0.442 | **0.396** | **tool choice is barely question-specific at all** |
| tool-sequence similarity | 0.437 | **0.367** | likewise |
| code-hash Jaccard | 0.019 | 0.000 | code is essentially never literally reused |

The third row is a finding in its own right: **which tools a trajectory reaches
for is nearly independent of the question being asked.** Two trajectories on
*different* questions in the same task share 40% of their tools; two on the
*same* question share 44%. The tool repertoire is a task-level habit, not a
methodological choice — so "different tool path" is mostly which generic
literature-search function happened to be called, not a different analysis.

---

## 4. Failure is not disagreement (the §4 requirement)

The two must never both be called "uncertainty". Of 150 instances:

| state | n | definition |
| --- | ---: | --- |
| unanimous | 82 | ≥2 usable, all agree |
| **B — substantive disagreement** | **53** | ≥2 usable trajectories reaching genuinely different conclusions |
| **A — insufficient evidence** | **15** | fewer than two usable trajectories: the instance produced fewer than two opinions |

Outcome structure:

| evidence state | outcome | n |
| --- | --- | ---: |
| unanimous | unanimous correct | 69 |
| unanimous | all wrong (unanimously) | 13 |
| **B** | correct plurality | 19 |
| **B** | **all wrong** | **20** |
| **B** | wrong plurality, correct minority | 10 |
| **B** | tied, correct minority | 4 |
| **A** | all wrong | 12 |
| **A** | unanimous correct | 3 |

**Stratum A is an agent/infrastructure reliability problem, reported separately
and not analysed as uncertainty.** Its 15 instances are the same phenomenon as
the unresolved 15.5% residual trajectory failure rate; 12 of the 15 are simply
wrong, with an Oracle@4 of 0.20 — there is usually no correct answer among the
four to find. Nothing in §§5–7 is computed on stratum A.

**The Track-C question is about the 53 B instances**, and within those the
action is the 34 where the answer is not already carried by a correct plurality.

---

## 5. Do disagreeing trajectories differ upstream? — **No, not in the plan**

566 both-usable pairs; instance-clustered 95% CIs.

| metric | pairs that DISAGREE | pairs that AGREE | difference | 95% CI | n |
| --- | ---: | ---: | ---: | --- | ---: |
| **workflow distance** | 0.530 | 0.511 | **+0.020** | [−0.034, +0.074] | 151 / 415 |
| **plan Jaccard** | 0.546 | 0.538 | **+0.008** | [−0.040, +0.058] | 151 / 415 |
| tool-set Jaccard | 0.366 | 0.470 | −0.104 | [−0.229, +0.021] | 68 / 190 |
| **tool-sequence similarity** | 0.332 | 0.437 | **−0.105** | **[−0.207, −0.005]** | 68 / 190 |
| query Jaccard | 0.277 | 0.347 | −0.070 | [−0.148, +0.002] | 68 / 190 |
| code-hash Jaccard | 0.002 | 0.019 | −0.017 | [−0.051, +0.003] | 151 / 415 |

Read carefully, this is two findings, not one:

1. **The plan is identical whether or not the conclusions agree.** 0.546 vs
   0.538 — a difference of eight thousandths against a null of 0.301. Two
   trajectories that will end up contradicting each other open with the *same
   analysis*. **The divergence happens downstream of the plan, not in it.** This
   is the single most important number in the report and it is what selects
   Outcome B.
2. **The tool path does diverge somewhat** — tool-sequence similarity is 0.105
   lower for disagreeing pairs, CI excluding 0. But §3's control shows the tool
   repertoire is nearly question-independent (0.396 on unrelated questions), so
   this is variation *within a generic habit*, not a methodological choice. And
   §6 shows it buys nothing.

**Only 68 of 151 disagreeing pairs can be compared on tools at all**, because at
least one side made no tool call. That is §7's finding, and it caps how much any
tool-based diversity intervention can even apply.

---

## 6. The conditional analysis — does independence correct errors?

This is the question the brief insists on, and the one that separates a real
mechanism from a correlation.

**Anchor a wrong trajectory; ask whether the other trajectory in the pair holds
the correct answer, as a function of how far apart their workflows are.** Both
directions of each pair are used where both qualify, because arrival order is an
artifact (D-21). 311 ordered pairs across 64 instances.

| workflow-distance quartile | n pairs | mean distance | **P(other is correct)** |
| --- | ---: | ---: | ---: |
| Q1 most similar | 78 | 0.279 | 0.308 |
| Q2 | 79 | 0.467 | **0.190** |
| Q3 | 76 | 0.585 | 0.263 |
| Q4 most independent | 78 | 0.747 | 0.359 |

**Non-monotone.** The most similar quartile beats two of the three more
independent ones. High-minus-low distance: **+0.056, 95% CI [−0.074, +0.180]** —
below the pre-registered 10 pp bar and with a CI covering 0.

### Is the correct minority more independent from the wrong plurality?

The sharpest form of the question, paired within instance so difficulty cancels.
10 instances have a wrong plurality and a correct minority:

**Isolation (correct-to-plurality distance minus within-plurality distance):
−0.037, 95% CI [−0.131, +0.046].** Directionally the *wrong* sign. Per instance
it splits 6 positive / 4 negative, with the negatives large (−0.245, −0.250,
−0.238): in those, the correct trajectory was the one that looked **most like**
the wrong plurality.

Both Outcome-A conditions fail. Outcome A is rejected.

### Are wrong pluralities built from more correlated workflows?

Among pairs that agree with each other:

| the instance's outcome | n pairs | workflow distance | plan Jaccard |
| --- | ---: | ---: | ---: |
| wrong plurality (correct minority exists) | 15 | 0.485 | 0.527 |
| all wrong | 40 | 0.497 | 0.548 |
| correct plurality | 38 | 0.506 | 0.556 |
| unanimous correct | 322 | 0.514 | 0.535 |

Wrong pluralities are marginally more tightly clustered (0.485 vs 0.506), in the
predicted direction, but the spread across all four strata is **0.03** — inside
noise at n=15. **No usable signal.** A controller cannot tell a wrong plurality
from a right one by how similar its members' workflows are.

### Early vs late consensus

First-pair workflow distance: **0.481** when the first two agreed immediately
(n=65) vs **0.546** when they did not (n=26); difference −0.065, 95% CI
[−0.148, +0.021]. Directionally, early agreement *is* associated with more
duplicated reasoning — the "convergent independent evidence vs duplicated
reasoning" question resolves toward duplication — but the CI covers 0.

---

## 7. What the agent is actually doing — and it is not evidence-based analysis

Three measurements that reframe the whole track.

### 7.1 A third of trajectories consult no evidence at all

**214 of 600 trajectories (35.7%) make zero tool calls.** Among usable
trajectories, 163 of 459 (35.5%). Their accuracy:

| group | n | accuracy |
| --- | ---: | ---: |
| **zero tool calls** | 163 | **0.724** |
| ≥1 tool call | 296 | 0.652 |
| ≥1 *successful* tool call | 268 | 0.657 |

Answering from parametric memory alone is **more** accurate than using tools.
Median tool usage among the rest is 1–2 unique tools. Whatever produces correct
answers on this benchmark, it is largely not external evidence retrieval.

### 7.2 The evidence channel is substantially broken

1,395 tool calls, **418 errors — a 30.0% overall error rate**, and it is
concentrated precisely in the literature/web tools that a `VERIFY` action would
depend on:

| tool | calls | errors | error rate |
| --- | ---: | ---: | ---: |
| **query_pubmed** | 286 | 197 | **68.9%** |
| **advanced_web_search_claude** | 139 | 107 | **77.0%** |
| **query_scholar** | 20 | 16 | **80.0%** |
| query_gwas_catalog | 177 | 13 | 7.3% |
| query_monarch | 172 | 18 | 10.5% |
| query_ensembl | 122 | 8 | 6.6% |
| query_opentarget | 112 | 12 | 10.7% |
| query_clinvar | 78 | 5 | 6.4% |
| search_google | 59 | 2 | 3.4% |

Commonest causes: `No module named 'pymed'` (225), `No module named 'anthropic'`
(84), `cannot import name 'advanced_web_search_claude'` (57).

**This is a known, deliberate limitation, not a new bug** — the full Biomni E1
environment was skipped in Phase 0 (`reports/phase0_environment.md` §157,
`reports/phase1_report.md` §7). What is new is its *shape*: structured
biomedical databases work (3–11% error); the **literature channel fails 69–80%
of the time**. `reports/phase2_plan.md` §2.3 anticipated exactly this — "requires
the E1 environment so that failures are genuine tool failures rather than
missing imports" — and this measurement is the first time the cost has been
quantified against the mechanism it blocks.

### 7.3 Failed trajectories are not "thinking too hard"

| | n | tool calls | failed tool calls | `<think>` blocks | has a plan |
| --- | ---: | ---: | ---: | ---: | ---: |
| usable | 459 | 2.01 | 0.65 | 14.4 | 100% |
| **not usable** | 141 | 3.34 | 0.84 | **4.5** | **34%** |

Unusable trajectories make *more* tool calls and produce *fewer* reasoning
blocks, and two thirds never emit a plan at all. Their failure mode is losing
the thread early, not over-deliberating.

---

## 8. Case studies

### 8.1 `lab_bench_seqqa` / i0027 — identical plan, four different answers

The clearest instance in the sample of Outcome B.

| trajectory | answer | reward | stated confidence |
| --- | --- | ---: | ---: |
| t0 | C | 0 | **1.00** |
| t1 | C | 0 | 0.95 |
| **t2** | **A** | **1** | — |
| t3 | E | 0 | — |

Pairwise plan Jaccard: t0–t2 **0.931**, t2–t3 **0.931**, t0–t3 0.871, t0–t1
0.657. Every plan is a near-verbatim restatement of the same four steps:

> "I need to find the longest ORF … then determine what amino acid is encoded at
> position 44. 1. find all ORFs 2. identify the longest 3. translate it
> 4. find the amino acid at position 44."

**The correct trajectory (t2) is the one *most similar* to a wrong one (t0):
0.931.** Four trajectories executed the same deterministic computation and got
four different answers. There is nothing here for a diversity intervention to
diversify — the plan is right and shared, and the arithmetic is what varies. It
also shows S4's limit: t0 stated confidence **1.00** and was wrong.

### 8.2 `gwas_causal_gene_opentargets` / i0690 — the counter-example

| trajectory | answer | reward |
| --- | --- | ---: |
| t0, t1, t2 | CYP2E1 | 0 |
| **t3** | **PAOX** | **1** |

Here the correct trajectory *is* the most distant: plan Jaccard t0–t3 **0.433**
against t1–t2 0.720. Isolation +0.067. This is what Outcome A would look like if
it were real — and it happens in **6 of 10** such instances while the other 4 go
the other way, which is exactly why the pooled estimate is −0.037 with a CI
covering 0. One instance is a story; ten instances split 6–4 is noise.

### 8.3 Stratum A — `crispr_delivery` / i0007

Four trajectories; the first tool call in each is `advanced_web_search_claude`,
which returns `No module named 'anthropic'` in every one. Retrieval selected
26 / 4 / 3 / 0 tools across the four — the retrieval step is itself highly
variable — but that variability changed nothing downstream, because the evidence
channel it selected was unavailable.

---

## 9. Per-task view

Directional only; cells are 21–79 pairs and are not used for any conclusion.

| task | pairs | workflow distance | plan Jaccard | tool Jaccard |
| --- | ---: | ---: | ---: | ---: |
| rare_disease_diagnosis | 76 | 0.599 | 0.525 | 0.234 |
| patient_gene_detection | 60 | 0.594 | 0.495 | 0.208 |
| screen_gene_retrieval | 26 | 0.565 | 0.456 | 0.366 |
| gwas_causal_gene_opentargets | 78 | 0.556 | 0.498 | 0.405 |
| gwas_causal_gene_gwas_catalog | 47 | 0.552 | 0.551 | 0.311 |
| gwas_causal_gene_pharmaprojects | 78 | 0.532 | 0.517 | 0.520 |
| crispr_delivery | 21 | 0.475 | 0.636 | 0.472 |
| lab_bench_dbqa | 69 | 0.464 | 0.538 | 0.600 |
| gwas_variant_prioritization | 32 | 0.444 | 0.588 | 0.798 |
| lab_bench_seqqa | 79 | 0.369 | 0.632 | 0.735 |

The ordering is intelligible: open-ended diagnostic tasks produce the most
varied workflows, closed computational ones (`lab_bench_seqqa`) the least. It is
the reverse of what would be useful — the task with the most workflow diversity
(`rare_disease_diagnosis`) is the one with the worst accuracy and the highest
failure rate.

---

## 10. Limitations

1. **Exploratory, on already-used data.** No hypothesis is tested here.
2. **Retrieval content is unmeasurable.** Only counts were logged, never the
   names of retrieved tools or data-lake items. The evidence-diversity claim
   rests on tool calls and query arguments, not on what was retrieved.
3. **"Plan" is the first `<think>` block.** Defensible (§3) but one operational
   choice; a trajectory whose plan is implicit in its code is under-served, and
   34% of unusable trajectories have no plan at all.
4. **Lexical similarity is not semantic similarity.** Two plans could use the
   same words for different intents. The control (§3) shows the metric has real
   discriminative power (0.540 vs 0.301), which is the evidence that it is not
   measuring only style — but it is not a semantic judgement, deliberately.
5. **Small cells where it matters most.** The decisive minority-isolation
   analysis has **n=10 instances**. It is reported with its CI and not
   over-read; a strong effect would have shown at n=10, and none did.
6. **The environment limits generality.** With a 69–80% failure rate on the
   literature channel, this measures Biomni-with-a-broken-evidence-channel. A
   repaired environment could change §7 substantially — though not §5, which is
   about plans and is upstream of any tool.
7. **One agent, one model, one benchmark.**

---

## 11. Conclusion and what a `VERIFY` action would have to do

### GO/NO-GO: **NO-GO for diversity-by-resampling. Outcome B primary, C secondary.**

* **Outcome B is selected** on its pre-registered criterion: disagreeing pairs
  are no more distant than agreeing pairs (+0.020, CI [−0.034, +0.074]), and at
  the plan level they are indistinguishable (+0.008 against a 0.301 null).
* **Outcome C is present as a secondary component**: on the tool axis there
  *is* real divergence (−0.105, CI excluding 0), and it fails to predict
  correction (+0.056, CI [−0.074, +0.180]) — diversity that exists but does not
  rescue errors.
* **Outcome A is rejected** on both of its conditions.

The two components point the same way: **the diversity that exists is not
useful, and the diversity that would be useful — a different analysis — does not
occur.** Resampling Biomni at temperature 0.7 re-runs the same plan.

### What a useful `VERIFY` action must do differently from `RESAMPLE`

Answering the forest question directly, from the evidence above:

1. **Change the plan, not the sample.** Plan Jaccard is 0.54 within an instance
   against a 0.30 floor for entirely different questions. A verification
   trajectory must be *constructed* to plan differently — an explicitly
   different method, or a critique of the leading answer — because free
   resampling will not do it. This is the load-bearing requirement.
2. **Check the computation, not the conclusion.** §8.1 is a shared, correct plan
   executed four ways with four results. For that failure mode the useful action
   is re-deriving or independently validating a specific computational step, not
   asking a fresh trajectory for its opinion.
3. **Repair the evidence channel first, or do not claim to be verifying.** A
   `VERIFY` action that consults the literature would today fail 69–80% of the
   time. Structured databases (GWAS Catalog, Monarch, Ensembl, OpenTargets,
   ClinVar — all 3–11% error) work and are the only currently usable
   independent-evidence route.
4. **Make evidence retrieval mandatory and logged by name.** 35.7% of
   trajectories consult nothing, and retrieval content was never recorded, so
   "independent evidence" is currently neither enforced nor auditable. Both are
   cheap to fix and both are prerequisites for measuring whether verification
   works.
5. **Do not spend a verification trajectory on stratum A.** 15 instances failed
   to produce two opinions at all. That is an infrastructure repair, not an
   epistemic action, and conflating them is what made Controller v1's abstention
   rule look like an uncertainty rule when it was mostly a failure detector.

### Recommended next step

**Do not build a diversity mechanism.** The cheapest decisive follow-up is
**not** another sampling study; it is a *constructed-verification* pilot on a
small number of instances, in which the verification trajectory is given a
different method by construction and the evidence channel it needs is known to
work. That is a new prospective design and it needs its own pre-registration —
and, per D-29, a committed tree and a residual failure rate under threshold
before it launches.

---

## 12. Reproduction

```bash
BIOMNI_UNC_OUTPUT_ROOT=<output_root> \
python scripts/track_c_diversity.py --config configs/phase2b.yaml \
    --out <output_root>/track_c/results
```

CPU only, ~4 min, deterministic (seed 20260811). Reads frozen run artifacts
read-only; writes only under `track_c/`. 17 tables (`tc_*.csv`),
`track_c_diversity.json`, one figure
(`tc_01_independence_and_correction.png`).

**No frozen Phase-0/1/1.5/2A/2B artifact was modified.**
