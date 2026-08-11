# Stage A — existing-data decomposition (A.1–A.5)

**Written:** 2026-08-11. **CPU only, no GPU, no model calls, no new instances.**
Drivers: `scripts/stage_a_decomposition.py` (A.1–A.4),
`scripts/stage_a_label_triage.py` (A.5). Tests: `tests/test_stage_a.py` (15).
Tables: `reports/tables/stage_a/`. Interpretation rules for every analysis were
written into each script's docstring **before** the corresponding numbers were
computed.

**Nothing here gates Stage C.** `reports/stage_c_stop_rule.md` was frozen and
committed (`63c179b`) before this file's first number existed — deliberately,
because once alternative aggregations of the Arm-2 data exist a Stage C NO-GO
becomes negotiable.

> **Headline.** Three results change how the project's central numbers should be
> read. (1) The adjudication null is **not** an aggregation artifact — no
> alternative aggregation of Arm 2's own samples beats the voting floor, and
> even a perfect selector over them reaches only 0.513. (2) But **69% of Arm 2's
> harm is interface harm**, not judgment harm, which is the quantitative content
> of D-39's retraction. (3) The "30% of instances are unreachable" figure is an
> **upper bound on a generation limitation, and a loose one**: on 18 of the 35
> assessable no-correct instances the model *singled out* the correct answer —
> discussed it more than the average wrong candidate — and committed something
> else, and 3 more generated it and lost it to answer parsing.

---

## A.1 — the adjudication null is not an aggregation artifact

The question: did Arm 2 lack verification ability, or did its 2-of-3 majority
rule destroy a real signal?

| aggregation over Arm 2's 234 samples | value | vs. floor 0.4103 |
| --- | ---: | --- |
| random single sample | 0.329 [0.231, 0.436] | below |
| per-sample, all 234 | 0.329 [0.248, 0.410] | below |
| per-sample, usable only (n=169) | 0.456 [0.353, 0.557] | CI covers floor |
| per-sample, in-menu only | 0.497 [0.388, 0.601] | CI covers floor |
| plurality among *available* samples (no 2-of-3 requirement) | 0.423 | **Δ +0.013 [−0.090, +0.115]** |
| **Oracle@3 over Arm 2's own answers** | **0.513** | **Δ +0.103 [0.000, +0.218]** |

**Per the rule fixed in advance: no alternative aggregation is materially above
the floor** — neither CI excludes zero (Oracle@3's lower bound is exactly 0.000).
Dropping the 2-of-3 requirement entirely buys **+0.013**, i.e. nothing. The
majority rule did not destroy a recoverable signal.

The Oracle@3 figure is the sharper bound: **even a perfect selector over Arm 2's
three answers reaches only 0.513**, against the original candidate pool's oracle
ceiling of 0.6026. Arm 2's answer set is *worse* than the candidate set it was
asked to adjudicate. No aggregation rule could have rescued this arm.

The in-menu-conditional figure (0.497) is the one number that looks favourable,
and it is **conditioned on partial success** — restricting to samples that
respected the answer format is a selection effect, not a clean estimate. It is
reported because it motivates Stage C's interface fix, not as evidence of
recovery.

**Terminal categories** (mutually exclusive, partitioning all 78; asserted by
`assert` in the driver):

| category | n |
| --- | ---: |
| unresolved aggregation (no 2-of-3, samples usable and in-menu) | 28 |
| usable and correct | 26 |
| usable but wrong | 15 |
| off-menu | 5 |
| all samples failed | 4 |

**Off-menu answers are not always violations.** Of 24 off-menu trajectories,
**5 scored correct** — the true answer was absent from the candidate set, so the
agent corrected the menu rather than disobeying it. Any future adjudication
design that hard-constrains output to the candidate list would forfeit these.

**Trace correlates** (descriptive): trajectories using tools were *less* accurate
(0.286 vs 0.394 for zero-tool trajectories), and trajectories with a runaway
generation event were markedly worse (0.258 vs 0.480). The second is the
clearest single sign that degeneration, not judgment, dominates this arm.

## A.2 — capture vs. harm: the quantitative content of D-39

`Δ = (capture − harm)/n` reconciles **exactly** for every selector (binary
rewards; asserted by test, 200 randomised cases).

| selector | base | n | capture | harm | Δ | interface share of harm |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Arm 2 | plurality | 78 | 7 | 13 | −0.0769 | **69.2%** (9/13) |
| Arm 1 | plurality | 78 | 4 | 21 | −0.2179 | 61.9% (13/21) |
| controller v1 | fixed K=4 | 150 | **0** | 5 | −0.0333 | 80.0% (4/5) |
| controller v1 | fixed K=2 | 150 | 5 | 6 | −0.0067 | 50.0% (3/6) |
| plurality (identity control) | plurality | 78 | 0 | 0 | 0.0000 | — |

**Arm 2's harm is 69% interface harm** — above the 50% bar fixed in advance, so
**the pre-registered reading is that D-39's retraction has real quantitative
content**: the null is substantially an elicitation failure rather than a
demonstrated inability to judge between candidates. Of the 13 harmed instances,
only **4** are `wrong_in_menu` (the adjudicator looked at the candidates and
chose a worse one); 7 are `no_majority`, 1 off-menu, 1 outright trajectory
failure.

**The tempting counterfactual, and why it is not claimed here.** Arm 2 captured
7 and lost only 4 to judgment, so a hypothetical interface-perfect adjudicator
looks net positive (+3 instances, ≈ +0.038). **That is a counterfactual, not a
measurement** — it assumes fixing the interface converts each interface-harmed
instance to its plurality outcome, which is untested and not entailed. It is
stated as the motivation for Stage C, and Stage C's frozen stop rule is what
decides it.

**A separate finding, clean and independent of all of the above: the controller
captured nothing.** Against fixed K=4 it has **capture = 0** — across 150
prospective instances it never once turned a fixed-K=4 error into a correct
answer. Its entire difference from fixed K=4 is harm. This is a stronger
statement of the Phase-2B failure than the headline Δ: the controller is not
"slightly worse on net", it is *strictly dominated* on this pairing.

## A.3 — the selectivity belongs to the agreement signal, not the controller

| | coverage | accepted-case accuracy |
| --- | ---: | ---: |
| controller, `k_used ≤ 2` | 0.433 | 0.877 |
| controller, `k_used ≤ 3` | 0.673 | 0.782 |
| controller, `k_used ≤ 4` | 0.807 | 0.711 |
| fixed K=4, `support ≥ 4` | 0.307 | 0.978 |
| fixed K=4, `support ≥ 3` | 0.507 | 0.895 |
| fixed K=4, `support ≥ 2` | 0.807 | 0.719 |
| fixed K=4, `support ≥ 1` | 1.000 | 0.607 |

At matched coverage, agreement-thresholded fixed K=4 **matches or beats the
controller everywhere it is comparable**: 0.895 at coverage 0.507 vs the
controller's 0.877 at 0.433, and 0.719 vs 0.711 at the identical coverage of
0.807. **Verdict, per the rule fixed in advance: the selectivity is attributable
to the agreement signal, not to the controller wrapped around it.** This is a
selective-prediction result and must not be reported as a controller result.

Restricted to the overlapping coverage domain [0.433, 0.807], AURC is **0.058
for agreement-thresholded fixed K=4 vs 0.075 for the controller** — again
favouring the simpler method. *(Full-domain AURCs are not comparable: the
controller's reachable coverage is a strict subset of fixed K=4's, and comparing
integrals over different domains would spuriously favour whichever curve covers
less of the hard tail. The raw comparison inverts this conclusion, which is why
it is not reported.)*

**Deployment-relevant, and the sharpest form of the result:** at a 5% or 10%
error budget the controller reaches **zero** coverage — its best operating point
is 12.3% error — while agreement-thresholded fixed K=4 reaches **30.7%** coverage
at 2.2% error. A practitioner wanting a low-error operating point cannot get one
from the controller at all, and can from plain agreement counting.

## A.4 — cheap trace features do not separate the correct minority

Trajectory-level AUROC for holding the correct answer, on the 53 `phase2b`
disagreement instances, instance-clustered bootstrap:

| feature | AUROC | 95% CI |
| --- | ---: | --- |
| final_confidence | 0.588 | [0.498, 0.680] |
| unique_tool_count | 0.476 | [0.385, 0.570] |
| tool_call_count | 0.462 | [0.376, 0.554] |
| failed_tool_call_fraction | 0.452 | [0.364, 0.539] |
| code_execution_count | 0.452 | [0.373, 0.529] |
| llm_call_count | 0.446 | [0.370, 0.522] |
| total_output_tokens | 0.398 | [0.300, **0.4998**] |

**The pre-registered rule is technically triggered** by `total_output_tokens`,
whose CI excludes 0.5 — but by **0.0002**, and it does not survive Bonferroni
adjustment for the seven features swept (**post hoc** check, added after seeing
the nominal result and labelled as such). Its direction is negative: longer
trajectories are *less* likely correct, which is a degeneration proxy rather
than verification-relevant content.

The mechanical verdict string is reported unchanged rather than restated to fit
the adjustment — the bar is not moved after the fact. **The substantive reading
is that no usable separating signal was found in these traces.** For Stage C
this means a null there would be substantially attributable to the traces
carrying little separating signal, not solely to the verifier — which is why
§8 of the stop rule fixes in advance that this interprets a Stage C null and
never reverses it.

## A.5 — mechanical label triage of the 45 no-correct instances

**No LLM was used to adjudicate any label.** Using a model to validate labels
the model failed on is the circularity this audit exists to avoid.

### A.5a — evaluator / canonicalisation mismatch: none found

**0 of 45** instances are scoring artifacts under deterministic normalisation
(case, whitespace, quotes, trailing punctuation, integer-vs-string identity,
rsID prefix case). The normaliser applies these repeatedly rather than in one
pass — a single pass leaves `'BRCA1'.` as `BRCA1'` and would have let a real
artifact through; this was caught by a test, and the zero result is reported
only after the stronger normaliser.

**Gene-symbol synonymy: NOT DONE.** No offline alias table is available, and a
guessed alias list would manufacture exactly the corrections it is meant to
detect. This is the one place where the "scoring artifact" count could still be
an undercount.

### A.5b — the correct answer is often present and not committed

**The enumeration problem dominates this analysis and is why three separate
measures are reported.** On 9 of 10 tasks the prompt supplies a candidate list
that literally contains the correct answer (35 of the 45 instances), so "the
trajectory mentions the right answer" is near-vacuous — a model echoing the
list mentions it without ever considering it.

| measure | n | of |
| --- | ---: | --- |
| `never_mentioned` in the model's own text | **7** | 45 |
| `mentioned` somewhere in model text | 38 | 45 |
| **`singled_out`** — mentioned more than the average wrong candidate | **18** | 35 assessable |
| genuine extraction failure — answer *dominates* an unparseable trajectory's own solution block | **3** | 45 |
| (looser: answer merely *appears* in an unparseable solution block) | 14 | 45 |

Model text is AIMessage content with `<observation>` blocks stripped, so tool
and code output cannot be mistaken for the model's own reasoning.

**Reading, per the rule fixed in advance.** `singled_out` is the
enumeration-robust measure and it is **18 of 35 — 51%**. On half the assessable
no-correct instances the model discussed the correct answer preferentially over
the wrong candidates and still committed something else. **"30% unreachable" is
therefore an upper bound on a generation limitation, and a loose one**: a
substantial part of that 30% is a commitment failure, not an inability to
produce the answer.

Two concrete sub-findings:

* **3 instances are outright extraction failures** — a trajectory produced no
  parseable answer while its own solution block committed the correct one. The
  clearest, verified by reading the text: `gwas_causal_gene_gwas_catalog/492`,
  where a solution block states *"Most likely causal gene: LONP1"* — the correct
  answer — and parsed to `NaN`, scoring 0.
* The looser count (14) is **not** claimed as extraction failure: solution
  blocks here are long prose reports that routinely discuss several candidates
  while committing one, so mere appearance is discussion, not a lost answer.
  The strict count applies the same enumeration-robust dominance test inside the
  block.

### A.5c — prompt underdetermination

A structural read of each task's prompt **template** (one read fixes every
instance of that task — D-37's procedure), judging only whether the prompt
supplies what is needed to determine the answer, never domain correctness:

**44 of the 45 instances are on tasks that `require_external_knowledge`; 1 is on
the single `determinate` task** (`lab_bench_seqqa`, where the sequence is given
in full and the answer is computable from it). This independently reproduces
D-37's mode-A finding from a different direction, and the two are pinned to each
other by test — if either drifts, both must be re-read.

### Corrected scoring, side by side

A.5a found no normalisation artifacts, so official and audit-corrected scoring
differ **only** by the 3 extraction failures. `singled_out` is deliberately
**not** used to re-score anything: considering an answer is not producing it.

| | official | audit-corrected |
| --- | ---: | ---: |
| no-correct instances | 45 | **42** |
| no-correct rate | 30.0% | **28.0%** |
| Oracle@4 | 0.700 | **0.720** |
| plurality | 0.607 | 0.607 |
| selection headroom | 0.093 | **0.113** |

The corrected instances are one each in `gwas_causal_gene_gwas_catalog`,
`gwas_variant_prioritization`, `screen_gene_retrieval`.

### Explicitly not done, and why

Stale-label checks, incorrect-label adjudication, and multiple-defensible-answer
judgments require domain reviewers, who are not available. They are **not
approximated and not delegated to an LLM**. This is a real limitation on the
interpretation of the remaining 42: some unknown share may be label problems
rather than model failures, and this audit cannot distinguish them.

---

## What Stage A changes in the manuscript

1. **The adjudication null stands as a null** (A.1) — it is not an aggregation
   artifact, and no re-slicing rescues it.
2. **But its scope is genuinely narrow** (A.2): 69% interface harm means the
   result is about an elicitation regime, exactly as D-39 argued on logical
   grounds and now with numbers behind it.
3. **The controller result is stronger than reported**: capture = 0 against
   fixed K=4 (A.2), and its apparent selectivity belongs to the agreement signal
   (A.3). Any selective-prediction claim must be attributed to agreement
   counting, not to the controller.
4. **The generation/selection split moves toward selection** (A.5b): at least
   half the "unreachable" instances had the correct answer singled out in
   reasoning and not committed.

## Reproduction

```
python scripts/stage_a_decomposition.py  --out reports/tables/stage_a
python scripts/stage_a_label_triage.py   --out reports/tables/stage_a
```

CPU only, a few minutes. Full suite: **474 passed.**

---

# Addenda — A.6, A.7, A.8, and a sensitivity on A.5b (2026-08-11)

Added after the sections above, before Stage C opens. A.6 and A.7 were the two
items that had to complete before Stage C could start, because both feed
decisions Stage C freezes at its start and cannot revisit.

## A.6 — semantic discriminability probe: **NULL**

Decision rule frozen and committed (`2051a7f`) **before any AUROC or feature
value existed** — `reports/a6_decision_rule.md` fixes the feature family, the
primary feature, and the Bonferroni correction in advance, precisely because
A.4's nominal hit died under a correction applied afterwards.

**The leakage barrier is the load-bearing part.** A.5b's `singled_out` takes
ground truth as an *input* — it measures discussion of *the correct answer*.
That is legitimate for an audit and invalid for a feature a Stage C capsule
would compute at inference time. Reformulated label-free: how preferentially
does a trajectory discuss **its own committed answer** relative to the other
candidates? Enforced structurally — `extract_features()` takes exactly
`(model_text, own_answer, candidates)`, forbidden columns are dropped before
extraction, and the decisive test asserts feature values are **invariant under
permuting the labels**.

Population: 263 usable trajectories (176 `phase2b` + 87 `phase1_pooled`) across
the 78, of which 96 correct / 167 incorrect.

| feature | AUROC | 95% CI | corrected (98.75%) CI |
| --- | ---: | --- | --- |
| **`own_answer_share`** (primary) | **0.504** | [0.352, 0.641] | [0.313, 0.670] |
| `closing_concentration` | 0.528 | [0.416, 0.644] | [0.388, 0.676] |
| `n_competing_candidates_discussed` | 0.439 | [0.366, 0.515] | [0.341, 0.533] |
| `hedging_near_answer` | 0.414 | [0.333, **0.491**] | [0.314, 0.514] |

**Verdict: NULL.** The primary feature sits on chance. `hedging_near_answer`
clears the *nominal* bar in the inverse direction (more hedging → less likely
correct) and **does not survive the pre-declared correction**, so per the frozen
rule it is reported as multiplicity noise — the identical pattern to A.4, except
that this time the correction was fixed in advance and there is nothing to
argue about.

**The sharp reading, and the reason this probe was worth running.**
`singled_out` carried A.5b *only because it was handed the correct answer*. Its
label-free analogue — the same measure computed against the trajectory's own
committed answer — carries **nothing** (AUROC 0.504). A model that discusses its
own answer preferentially is no more likely to be right than one that does not.
**A Stage C capsule cannot expose this signal, because at inference time the
signal does not exist.** A.4's null therefore strengthens materially: a Stage C
NO-GO becomes attributable to the traces on positive evidence, across both the
structural and the semantic feature classes, rather than by elimination.

## A.7 — 31 of the 78 are unreachable by construction

A verifier scoring the **committed candidates** cannot reach an instance where
none of them is correct. Defined without heuristics as *oracle over committed
candidates == 0*:

| | n | floor | ceiling | gap | gap/3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| all 78 (primary, unchanged) | 78 | 0.4103 | 0.6026 | 0.1923 | **0.0641** |
| reachable subset (secondary) | **47** | 0.6809 | 1.0000 | 0.3191 | **0.1064** |

**31 of 78 (39.7%) are unreachable** — 20 `phase2b`, 11 `phase1_pooled`. Both
bars are now written into `reports/stage_c_stop_rule.md` as **Amendment 1**,
before Stage C runs. The primary is unchanged and still decides the verdict; the
secondary decides nothing and exists only so that a null on the full 78 can be
read correctly.

**A correction to the framing this was requested under:** the A.5b-flagged
instances number **18, not 21** — the 3 extraction failures are a strict
*subset* of the 18 singled-out, not disjoint from them. 6 of the 18 fall inside
the frozen 78, and all 6 are unreachable.

## A.8 — matched-K oracle: the arm was re-solving, not adjudicating

A.1 compared Arm 2's Oracle@3 against the pool's Oracle@**4**, which is not
like-for-like. Recomputed at matched K *and* on a matched population (the 67
instances with ≥3 usable trajectories, since Oracle@3 is undefined below that):

| | n | oracle |
| --- | ---: | ---: |
| pool, Oracle@3, exact over all 3-subsets | 67 | **0.6455** [0.534, 0.757] |
| Arm 2, oracle over its own samples, same 67 | 67 | **0.5522** [0.433, 0.672] |
| **difference** | | **−0.0933** |

The gap survives matching at essentially its original magnitude, and it licenses
a stronger claim than the monotonicity argument in D-39:

> **Selection from a set cannot produce something worse than the set's best
> element.** Arm 2's best obtainable answer is 9.3 points *below* the best answer
> already sitting in the candidate set it was handed. It was therefore
> **re-solving the task, not adjudicating between the candidates** — whatever
> the prompt asked it to do.

This is a cleaner basis for D-39's retraction than information monotonicity: it
is a structural fact about the outputs, not an argument about decision-makers.

## Sensitivity on A.5b's 51% — **post hoc**, and it matters

*Computed after seeing the A.5b result and therefore labelled post hoc.* The
`singled_out` threshold is "mentioned more than the average wrong candidate",
i.e. a ratio strictly above 1.0. That boundary turns out to carry real weight:

| ratio of GT mentions to mean wrong-candidate mentions | instances |
| --- | ---: |
| > 1.0 (the reported threshold) | 18 |
| ≥ 1.1 | 13 |
| ≥ 1.25 | 11 |
| ≥ 1.5 | 8 |
| ≥ 2.0 | 7 |

**Five of the 18 sit within 10% of parity** — for example
`screen_gene_retrieval/160` at 62 vs 60.5, and `crispr_delivery/7` at 15 vs
14.6, whose excerpts are visibly option-by-option enumeration ("Let me consider
each option: a… b… c…"). At that margin the measure cannot distinguish
preferential discussion from enumeration, which is the very artifact it was
designed to exclude.

**Consequence for the claim.** The headline should be stated as a band, not a
point: **between 20% (7/35, ratio ≥ 2) and 51% (18/35, ratio > 1)** of the
assessable no-correct instances show the correct answer discussed preferentially
and not committed. The qualitative conclusion — that a substantial part of the
"30% unreachable" figure is a commitment failure rather than a generation
ceiling — survives at every threshold in that band. The precise fraction does
not, and is not claimed. `reports/a5b_review_sheet.md` puts the 18 in front of
the operator for a reading-comprehension check that would settle it.
