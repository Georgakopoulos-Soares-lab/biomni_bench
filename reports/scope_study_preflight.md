# Scope-and-boundary study — preflight and frozen design

**Written:** 2026-08-12. **Status: FROZEN** for every section below.
**CPU-only at the time of writing.** No Solver-B trajectory existed when this
file was committed; the commit that contains it is the freeze point, and the
capability-gate results are appended afterwards under a dated heading rather
than folded back into the sections they would have changed.

---

## 0. Boundary — what this study may not touch

The previous experimental program ended at **D-43 / Stage C**. That verdict is
**CLOSED**: C2 NO-GO (Δ = −0.0641, CI [−0.1667, 0.0384]), C1 INCONCLUSIVE
(Δ ≈ −0.0000, CI [−0.1154, 0.1025]), both independently triggering
`reports/stage_c_stop_rule.md` §6.

**Nothing in this study alters, recomputes, rescues, overturns or reinterprets
D-43.** Concretely, and checkable against the diff of the freeze commit: no
Stage-C cell is added or re-run, no Stage-C bar moves, no Stage-C artifact under
`reports/tables/stage_c/` is rewritten, and no analysis here takes Stage C's 78
frozen instances as its population. D-43's reversal condition already says the
right thing about this file — *"a future separately pre-registered study on a
different population or with different verifiers is not a reversal of this
entry; it would be new work, subject to its own north-star check."* This is that
new work, on a different population, and it is subject to that check.

**The new primary question:**

> Does the separation between reliability detection and successful error
> correction replicate when the same biomedical-agent tasks are solved by an
> independent solver family?

**The pre-registered secondary question:**

> Does verifier headroom recovery vary with the criterion verifiability of the
> task?

The secondary is **secondary** and is not promoted to a co-primary endpoint by
anything this file or any later result says.

**Tonight is not the main experiment.** Tonight is (a) the CPU preflight and the
freezing of every design component that can be fixed before data exists, and
(b) a Solver-B scaffold/capability gate run on **already-consumed** historical
questions. **Zero fresh scope-study instances are consumed**, and the fresh
manifest is deliberately not built — it waits on operator approval.

---

## 1. Repository state at freeze

| item | value |
| --- | --- |
| parent commit | `53b80b7` — *D-43: Stage C verdict — NO-GO (C2) and INCONCLUSIVE (C1)* |
| working tree at session start | clean |
| test suite at session start | **548 passed** |
| GPU allocation | job `3396219`, node `c563-001`, h100 partition, 4×H100 96 GB |
| live SGLang servers found already running | `Biomni-R0-32B-Preview` :30000 (tp2, GPU 0–1); `gemma-4-31B-it` :30010 (tp2, GPU 2–3) |

---

## 2. Verified remaining BiomniEval1 pool

Driver: `scripts/scope_pool_audit.py`. Artifacts:
`reports/tables/scope_study/pool_audit.{json,csv}`.

**Prose was not trusted.** The audit reconstructs consumption from three
independent artifact sources — the benchmark parquet (the denominator), every
`manifests/*.jsonl`, and every `<output_root>/*/runs/<task>/i####/` directory on
disk. The third source is the one that matters: a run directory exists if and
only if a trajectory was generated against that instance, whether or not any
manifest records it.

### 2.1 The table

| task | total | consumed by phase1 ∪ phase2b | consumed by other runs | consumed total | **never used** | eligible |
| --- | ---: | ---: | ---: | ---: | ---: | :---: |
| `crispr_delivery` | 10 | 10 | 0 | 10 | **0** | no |
| `gwas_causal_gene_gwas_catalog` | 50 | 20 | 2 | 22 | **28** | yes |
| `gwas_causal_gene_opentargets` | 50 | 20 | 1 | 21 | **29** | yes |
| `gwas_causal_gene_pharmaprojects` | 50 | 20 | 0 | 20 | **30** | yes |
| `gwas_variant_prioritization` | 43 | 20 | 0 | 20 | **23** | yes |
| `lab_bench_dbqa` | 50 | 20 | 3 | 23 | **27** | yes |
| `lab_bench_seqqa` | 50 | 20 | 1 | 21 | **29** | yes |
| `patient_gene_detection` | 50 | 20 | 3 | 23 | **27** | yes |
| `rare_disease_diagnosis` | 30 | 30 | 0 | 30 | **0** | no |
| `screen_gene_retrieval` | 50 | 20 | 3 | 23 | **27** | yes |
| **total** | **433** | **200** | **13** | **213** | **220** | 8 tasks |

### 2.2 Two findings, one of them a correction to the record

**Confirmed:** `crispr_delivery` and `rare_disease_diagnosis` are exhausted —
0 never-used instances each, exactly as D-22 declared in advance it would spend
them. **Eight task families remain available.**

**Corrected:** the reserved pool is **220, not 233.** D-22 and
`reports/phase2_protocol.md` §3.1 both record 233 reserved (433 − 50 − 150).
Thirteen further instances were consumed after those documents were written, by
two runs that never wrote a manifest into `manifests/`:

| consumer | n | instances |
| --- | ---: | --- |
| `verify_prereq_diag3` (D-34 residual-failure re-measurement, a deliberately *fresh unscreened* sample) | 8 | `gwas_causal_gene_gwas_catalog/{4,623}`, `lab_bench_dbqa/{217,505}`, `patient_gene_detection/{273,387}`, `screen_gene_retrieval/{236,334}` |
| `phase2b_smoke` (launch smoke test) | 5 | `gwas_causal_gene_opentargets/230`, `lab_bench_dbqa/303`, `lab_bench_seqqa/256`, `patient_gene_detection/212`, `screen_gene_retrieval/302` |

This is not a scientific error in either run — D-34 needed an unscreened sample
by construction, and a smoke test needs instances. It is a **bookkeeping** gap:
the reserved count in the prose was never decremented, and any future document
citing 233 is citing a stale number. The scope study's pool is **220**, and its
exclusion set is the full 213-instance consumed set, not the 200 named by the
two confirmatory manifests.

### 2.3 Is 15 × 8 = 120 feasible with zero overlap?

**Yes, with margin.** The binding task is `gwas_variant_prioritization` at 23
never-used; every other eligible task has 27–30. A design of 15 per task across
the 8 eligible families needs 120 of the 220, leaving **100 unspent**. Zero
overlap with phase1, phase2b, the ablation arms, phase1_5, the smoke runs, the
Track-C adjudication pilot, the VERIFY-prerequisite diagnostics or Stage C is
guaranteed by construction, because the never-used set is defined as the
complement of all of them.

**No fresh manifest is built tonight.** Per Part F this file records only that
the design is *possible*; selecting the 120 is tomorrow's operator decision.

---

## 3. Criterion-verifiability rubric — FROZEN

### 3.1 What the rubric is allowed to look at

Assignments below were made from exactly three inputs:

1. the benchmark task definition;
2. the **official** correctness criterion, read from
   `biomni/eval/biomni_eval1.py::_compute_reward` (the same function
   `OfficialEvaluator` wraps — this project never re-implements it);
3. the operation that would independently establish that a given answer is
   correct, judged from the task's own prompt template.

**Deliberately excluded, as instructed:** historical Biomni accuracy, Stage-C
verifier performance, oracle headroom, any task-specific outcome, any new model
result.

**A disclosure about ordering, because it matters more than the assignments.**
The tiers below were fixed from (1)–(3) before any per-task accuracy number was
computed in this session. Per-task Solver-A accuracies were computed afterwards,
to set the capability-gate bars in §6 — and they turn out to be *suggestive* of
the secondary hypothesis (Tier 1 `lab_bench_seqqa` at 0.867 first-trajectory
accuracy, Tier 3 `screen_gene_retrieval` at 0.067). **That is precisely why the
rubric is frozen here and is not revised in light of them.** A tier assignment
adjusted after seeing which tasks the solver finds hard is not a verifiability
rubric; it is a relabelling of difficulty.

### 3.2 The three tiers

**Tier 1 — mechanically verifiable.** Correctness is decidable *without
consulting any external, curated, time-varying resource*: everything needed is
supplied by the prompt, or lives in a fixed formal system. Verification is a
computation whose result cannot drift.

**Tier 2 — evidence-grounded.** Correctness is decidable by consulting named,
objective, structured biomedical resources. The answer is a record, or a small
set operation over records, in those resources. Verification is a lookup: it can
drift with database version, but it is not a judgement call.

**Tier 3 — integrative / domain judgment.** No mechanical operation and no
database lookup settles it. The ground truth derives from a specific empirical
result or curated prioritisation that a verifier cannot re-derive from public
structured evidence, so establishing correctness requires weighing several
plausible alternatives.

### 3.3 Assignments and rationale, all eight families

| task | official criterion (`_compute_reward`) | independent-establishment operation | **tier** |
| --- | --- | --- | :---: |
| `lab_bench_seqqa` | exact letter match, case-insensitive | The sequence, plasmid, enzyme and candidate primers are given **in full in the prompt**. Correctness follows from deterministic sequence operations — restriction-site location, ORF/reading-frame computation, primer-overlap and homology-arm checking. No external resource is consulted. | **1** |
| `lab_bench_dbqa` | exact letter match, case-insensitive | Items name their authoritative resource explicitly ("According to ClinVar…", "according to DisGeNet but not according to OMIM", MSigDB gene-set membership). Verification is a lookup, sometimes a two-source set difference. Not Tier 1: nothing in the prompt determines the answer. | **2** |
| `gwas_causal_gene_gwas_catalog` | exact gene-symbol match, case-insensitive | Query the GWAS Catalog for the phenotype/locus and read the mapped/reported gene. The source database is named by the task itself. | **2** |
| `gwas_causal_gene_opentargets` | exact gene-symbol match, case-insensitive | Query Open Targets Genetics for the locus-to-gene assignment for that phenotype. Source named by the task. | **2** |
| `gwas_causal_gene_pharmaprojects` | exact gene-symbol match, case-insensitive | The gold standard is drug-target evidence for the indication. The originating source (Pharmaprojects) is **commercial and not openly queryable**; an independent check must use an open proxy (Open Targets drug data / ChEMBL / DrugBank). Still a lookup, not a judgement — but the check is against a proxy resource, and that is recorded as this family's specific weakness. | **2** |
| `gwas_variant_prioritization` | exact rsID match (case-sensitive) | Retrieve reported association statistics for each candidate variant against the phenotype (GWAS Catalog / Open Targets) and take the strongest. Objective ordering over retrieved records. | **2** |
| `patient_gene_detection` | JSON `causal_gene` list intersects the ground-truth gene set | Retrieve HPO/OMIM/Monarch phenotype–gene annotations for the ~18 supplied HPO terms and intersect with the candidate ENSG list. Objective sources, but requires aggregation across annotations rather than one unique record — the defining shape of Tier 2. | **2** |
| `screen_gene_retrieval` | exact gene-symbol match, case-insensitive | The answer is the **empirical top hit of one specific perturbation screen** (cell line × perturbagen × dose × duration). Unless the agent locates that exact screen dataset, no lookup settles it, and biological plausibility does not recover it — ground truths include entities such as an antisense RNA (`ZNF561-AS1`) chosen over canonical protein-coding candidates. Requires choosing among plausible alternatives. | **3** |

### 3.4 Structural adequacy check — and a confound flagged at both ends

| tier | task families | n families | never-used instances | under a 15-per-task design |
| :---: | --- | ---: | ---: | ---: |
| **1** | `lab_bench_seqqa` | **1** | 29 | 15 |
| **2** | `lab_bench_dbqa`, `gwas_causal_gene_gwas_catalog`, `gwas_causal_gene_opentargets`, `gwas_causal_gene_pharmaprojects`, `gwas_variant_prioritization`, `patient_gene_detection` | 6 | 164 | 90 |
| **3** | `screen_gene_retrieval` | **1** | 27 | 15 |
| | | **8** | **220** | **120** |

**Tiers are not forced into balance, and they did not come out balanced.**

> **FLAGGED, and binding on every later report of the secondary analysis:
> task identity and tier are fully confounded at BOTH extremes.** Tier 1 is
> `lab_bench_seqqa` and nothing else; Tier 3 is `screen_gene_retrieval` and
> nothing else. Any Tier-1-vs-Tier-3 contrast is therefore *numerically
> identical* to a `lab_bench_seqqa`-vs-`screen_gene_retrieval` contrast, and
> every property distinguishing those two families — answer space, prompt
> length, evidence requirement, whatever else — is a live alternative
> explanation. This is not a limitation to be recalled in a discussion section;
> it is a statement about what the design can identify, and it means the
> secondary analysis can never support a claim of the form "verifiability
> causes recovery". At most it supports "recovery differs across strata that
> also differ in verifiability", with the single-family confound named in the
> same sentence.

Only the six-family Tier 2 supports a within-tier variance estimate; the two
singleton tiers do not, and no per-tier confidence interval computed over one
task family will be presented as if it did.

### 3.5 MedAgentBench stays an external anchor

MedAgentBench (`reports/stage_c_preregistration.md` ADDENDUM 1, A1.1 — the
family-neutral verification-capability anchor, C1 93.1% / C2 23.6% headroom
recovered) is a **mechanically-checkable** corpus and would sit at Tier 1 under
this rubric.

**It is not an observation in any within-Biomni regression or monotonic trend
fit.** It is reported separately, as an external positive control, exactly as
instructed. Adding it as a fourth point would create a between-benchmark
comparison wearing the clothes of a within-benchmark trend, on a corpus whose
traces were generated by a different model (Claude Opus 4.8) under a different
scaffold, and where the verifier's relationship to the generator is different
again. A1.1 already records the stability assumption this would silently rely
on, and records it as attackable.

### 3.6 No monotonic law is pre-registered

The secondary analysis is **directional and descriptive**. This file
pre-registers no ordering hypothesis, no trend test, and no threshold. With one
family at each end, a monotonic fit over three tiers has one degree of freedom
and two confounded endpoints; reporting a slope from it would be a stronger
claim than the design can carry.

---

## 4. Solver B — B1 and B2, FROZEN

### 4.1 What was available, checked rather than assumed

The local HF cache holds exactly two general instruct LLMs:
`biomni--Biomni-R0-32B-Preview` (Solver A) and `google--gemma-4-31B-it` (the
frozen Stage-C C1 verifier). Both are served and healthy on `c563-001` right
now. Everything else in the cache is a genomics or protein encoder, unusable as
an agent.

### 4.2 The problem with the obvious choice, and the operator decision

`gemma-4-31B-it` is the obvious B1: already deployed, scale-matched, ungated,
proven on this exact serving stack, and `stage_c_preregistration.md` A1.3
already pre-registers the open question of whether it can operate the Biomni
scaffold at all. **Verifier capability is not evidence of agent capability**,
and that is what the gate exists to test.

But the planned matched study fixes the verifier at the frozen C1
`gemma-4-31B-it`. If Solver B were also `gemma-4-31B-it`, then for **Solver A**
the verifier is cross-family (D-43's C1 condition) while for **Solver B** it is
same-model (D-43's C2 condition) — so the cross-solver error-correction contrast
would confound *solver family* with *solver–verifier relatedness*, on exactly
the axis D-43 measured as large: candidate-ranking AUROC 0.6345 (C1) vs 0.5218
(C2), intransitivity 5.3% vs 52.6%.

This was put to the operator with the alternative of accepting the confound and
labelling it. **The operator chose the three-family design**: Solver A, Solver B
and the verifier each from a distinct lineage. Recorded here as an operator
decision, not as a routine selection.

### 4.3 The two candidates, pinned

| cell | role | model | revision | lineage |
| --- | --- | --- | --- | --- |
| **B1** | primary Solver B | `mistralai/Mistral-Small-3.1-24B-Instruct-2503` | `68faf511d618ef198fef186659617cfd2eb8e33a` | Mistral |
| **B2** | the single predeclared fallback | `google/gemma-4-31B-it` | `842da3794eaa0b77d5f08bae87a17459d91ff475` | Gemma |

**There is no B3.** If neither is suitable the conclusion is that the matched
second-solver study is not currently feasible with the predeclared candidates.

### 4.4 B1 selection reasoning — on the permitted criteria only

* **Family independence from Biomni-R0.** Biomni-R0-32B-Preview was tuned from
  `Qwen/Qwen3-32B`; Mistral is an independent lineage. This is the criterion the
  study actually requires.
* **Independent of the verifier as well**, which is what buys the three-family
  separation in §4.2.
* **Availability.** Ungated on the Hub, no credential required, so the choice is
  reproducible by a third party — the same test Amendment 2 applied to C1.
* **Serves on the pinned stack unchanged.** `Mistral3ForConditionalGeneration`
  is in SGLang 0.5.16's model registry, so no serving-stack change is introduced
  alongside the model change.
* **Context feasibility.** Native `max_position_embeddings` 131072, served at
  **65536** to match Solver A's served context exactly, removing context length
  as a variable.
* **Resource feasibility.** Dense 24B, bf16 ≈ 47 GB, fits tp2 on two H100 96 GB
  with the layout already in use.
* **Scale.** 24B against Solver A's 32B. Not matched, and stated as such: this
  is a real asymmetry and it is *why* §6's gate measures capability rather than
  assuming it. Dense, so the parameter count is not discounted by a small active
  fraction as it would be for a same-nominal-size MoE.

**A point release was substituted for serving compatibility, before freezing.**
The newer `mistralai/Mistral-Small-3.2-24B-Instruct-2506` was downloaded first
and rejected on inspection: it ships a Mistral-format tokenizer (`tekken.json`)
and **no HF tokenizer**, and SGLang 0.5.16 exposes only
`--tokenizer-mode {auto,slow}` — it has no `mistral` mode, so serving it would
require a serving-stack change, which is the one thing §4.4's own criterion
forbids. `Mistral-Small-3.1-24B-Instruct-2503` is the same official upstream
publisher, the same architecture and size, ungated, and ships
`tokenizer.json` / `tokenizer_config.json` / `chat_template.json`. The
substitution was made on serving compatibility alone, before any Solver-B
trajectory existed, and a third-party HF-format mirror of 3.2 was declined in
favour of an official repository for reproducibility.

**Not a selection criterion, and not consulted:** preliminary BiomniEval1
accuracy for either candidate. No such number existed for either model at the
time of this freeze.

### 4.5 What the Biomni scaffold actually demands of Solver B

Checked in the pinned Biomni source rather than assumed, because it bounds what
the gate can attribute to the model:

* the runner drives `biomni.agent.A1` with `source="Custom"` and
  `base_url=<local SGLang endpoint>` — an OpenAI-compatible chat API, so the
  interface is model-agnostic;
* the agent protocol is **prompt-instructed XML tags** (`<execute>…</execute>`,
  `<solution>…</solution>`) with `stop_sequences=["</execute>", "</solution>"]`
  (`biomni/agent/a1.py:199`), not a trained-in tool-call format;
* `a1.py` already contains generic repair paths — it appends a missing closing
  tag and re-prompts a response that carried no tag at all.

So a general instruct model can drive this scaffold **in principle**. Whether a
specific one does it reliably is an empirical question, and §6 is the answer.

---

## 5. Capability-gate sample — FROZEN, historical instances only

Driver: `scripts/prepare_scope_gate_manifest.py`. Artifacts:
`manifests/scope_gate.jsonl`, `manifests/scope_gate.groundtruth.jsonl`,
`manifests/scope_gate.report.json`.

| item | value |
| --- | --- |
| size | **24 instances**, 3 per task × 8 eligible families |
| source pool | `manifests/phase2b.jsonl` — **already consumed**, and carrying four frozen Solver-A trajectories each under the same scaffold and config |
| selection rule | `benchmark._rng_order(task, 20260812, phase2b_consumed_ids)[:3]` — the project's existing deterministic keyed-hash permutation, new seed |
| manifest hash | `dd084f0e81243be40e2cd2f24ffedf76b4eaf608cad3d5f01e3b6eb56286a6d2` |
| never-used instances consumed | **0**, asserted by a fatal guard in the builder |

| task | instances |
| --- | --- |
| `gwas_causal_gene_gwas_catalog` | 128, 138, 541 |
| `gwas_causal_gene_opentargets` | 460, 546, 745 |
| `gwas_causal_gene_pharmaprojects` | 821, 1158, 1250 |
| `gwas_variant_prioritization` | 50, 121, 130 |
| `lab_bench_dbqa` | 105, 273, 401 |
| `lab_bench_seqqa` | 27, 171, 378 |
| `patient_gene_detection` | 49, 88, 339 |
| `screen_gene_retrieval` | 160, 189, 339 |

**Selection is label-free.** Nothing about Solver A's reward, failure class,
agreement or difficulty enters the ordering. Selecting historical cases by
whether Biomni got them right would make the gate's own accuracy diagnostic
uninterpretable before it was ever run. Two guards in the builder abort the
build: every selected instance must be present in the Phase-2B manifest, and the
selected set must be disjoint from the never-used pool reported by
`scripts/scope_pool_audit.py`.

**Ground truth reaches the evaluator only.** It is written to a separate file,
as every manifest in this project is, and is applied **after** inference as a
capability diagnostic. It never reaches the solver.

---

## 6. PASS / FAIL / CAPABILITY-CONFOUNDED — FROZEN before inference

Driver: `scripts/scope_gate_analyze.py`, whose constants are pinned against this
section by `tests/test_scope_gate.py`.

**The question the gate answers, and the only one:**

> Can Solver B operate the Biomni scaffold well enough that a future matched
> solver-family comparison would be interpretable?

**It is not a contest.** The highest-accuracy candidate does not win. B2 is
reached only through the FAIL branch, so "run B2 because B1's accuracy
disappointed" is impossible without editing a committed file.

### 6.1 Solver-A reference, computed before the bars were set

Biomni-R0-32B-Preview, experiment `phase2b`, **first trajectory only** (K=1, the
gate's own budget), restricted to the eight eligible task families. Source:
`<output_root>/phase2b/results/tables/p2b_pooled_trajectories.csv`.

| metric | n=120 (8 families) | n=24 (the exact gate instances) |
| --- | ---: | ---: |
| completion rate | **0.8917** | 0.9167 |
| usable-answer rate | **0.8250** | 0.8333 |
| accuracy | **0.5417** | 0.5833 |
| degeneration-termination rate | **0.1083** | 0.0833 |
| Oracle@4 | — | 0.7083 |
| mean wall time / trajectory | — | 309.7 s |
| erroring code-block fraction (all K) | 0.2604 | 0.2808 |

The **n=120** column sets the bars; n=24 is too small to set a bar from and is
reported descriptively. All 57 non-completions across the 8 families carry
failure class `budget_terminated_consecutive_runaway` — Solver A's own residual
failure mode, and the reason a degeneration bar exists at all.

### 6.2 Measured metrics

Run completion; usable-answer rate (completed **and** `answer_parse_status ==
ok`); scaffold answer-protocol compliance (`solution_block_status == ok` among
completed); degeneration rate (`budget_terminated_consecutive_runaway`,
`model_context_overflow`); infrastructure-failure rate
(`model_server_failure`, `model_timeout`, `dependency_failure`); erroring
code-block fraction; mean tool calls, zero-tool fraction, LLM calls; trajectory
cost (output tokens, wall seconds); and **first-trajectory accuracy as a
capability diagnostic**.

### 6.3 The bars

Evaluated **strictly in this order**.

**FAIL** — clear interface/scaffold incompatibility or catastrophic agent
behaviour. Any one suffices:

| condition | bar | against Solver A |
| --- | --- | --- |
| completion rate | **< 0.50** | 0.8917 |
| usable-answer rate | **< 0.40** | 0.8250 |
| `solution_block_ok` rate among completed | **< 0.50** | the scaffold's own answer protocol is not being followed on most runs |
| degeneration rate | **≥ 0.40** | 0.1083 (≈4×) |
| infrastructure-failure rate | **≥ 0.25** | a serving/integration defect, not agent behaviour |

**CAPABILITY-CONFOUNDED** — not FAIL, but too weak for a later family contrast
to be read as solver-family generalisation. Any one suffices:

| condition | bar | rationale |
| --- | --- | --- |
| usable-answer rate | **< 0.65** | materially below Solver A's 0.8250 |
| accuracy | **< 0.2708** | exactly **0.50 × Solver A's matched 0.5417**. Pooled random-guess accuracy across the eight families is ≈0.115, so this sits at ≈2.4× chance — low enough not to demand parity, high enough to exclude a floor-effect solver |
| degeneration rate | **≥ 0.25** | more than double Solver A's 0.1083 |

**PASS** — none of the above. The model is frozen as Solver B.

**Solver B is not required to equal Solver A's accuracy.** Requiring parity
would defeat the purpose of testing a different family. What is required is that
it not be a floor-effect solver, because a floor-effect solver later described
as "an independent replication" is the single most misleading outcome this gate
exists to prevent.

### 6.4 The interpretation rule, frozen now and binding on the future study

> **If Solver B is materially capability-confounded, normalized headroom
> recovery does not cure the confound. The main cross-family claim must be
> labelled capability-confounded.**

Stated now because it is exactly the move that becomes tempting later:
normalising by each solver's own available headroom makes a weak solver's
recovery look comparable to a strong one's, while the two are answering
different questions. Normalisation controls for *how much headroom exists*; it
does not control for *whether the solver is operating in a regime where
agreement, plurality and oracle structure mean the same thing*.

---

## 7. Normalized-headroom denominator guard — FROZEN

The future primary analysis reports both **absolute verifier gain** and
**normalized oracle-headroom recovery**:

```
normalized recovery = (verifier performance − baseline performance)
                      ────────────────────────────────────────────
                            (Oracle@4 − baseline performance)
```

with `baseline` = plurality over the K=4 trajectories (the project's standing
floor, the same one Stage C used) and `Oracle@4` = best-of-4 over the same
trajectories.

### 7.1 The guard

For any solver × stratum cell, normalized recovery is **defined and reported
only if both** conditions hold:

| condition | bar |
| --- | --- |
| **absolute headroom** | `Oracle@4 − baseline` ≥ **0.10** |
| **headroom count** | at least **5** instances in that cell where Oracle@4 is correct and the baseline is wrong |

If either fails, normalized recovery is reported as **`undefined`** — not as a
number with a caveat, not as `n/a` in a table whose other cells carry
percentages — together with the observed denominator and headroom count, and
the **absolute gain with its CI is reported in its place**.

### 7.2 Why both conditions, and why these numbers

A ratio with a small denominator is unstable in the obvious way, and the two
conditions fail in different regimes. The absolute condition catches a stratum
where the solver has nearly saturated Oracle@4 relative to plurality — there is
nothing to recover, so any recovery percentage is noise amplified by division.
The count condition catches the case the absolute condition misses: a *small*
stratum where 15 instances and 2 recoverable ones produce a denominator of 0.133
that clears the absolute bar while a single instance moves the ratio by 50
percentage points.

Under the planned design the count condition will usually bind. A per-task cell
holds 15 instances and a per-tier cell holds 15 (Tier 1), 90 (Tier 2), 15
(Tier 3); on a 15-instance stratum, requiring 5 recoverable instances means
requiring a denominator of at least 0.333. That is deliberately strict, and it is
the honest reading: **with 15 instances one cannot estimate this ratio stably,
and the guard says so rather than printing a number that looks like it can.**

### 7.3 Three further rules, fixed now

* The ratio is computed **per stratum from that stratum's own numerator and
  denominator**. Averaging per-instance or per-task ratios is not the same
  quantity and is not substituted for it.
* A normalized recovery outside **[−100%, +100%]** is never reported without its
  denominator printed beside it in the same table.
* The guard is a **reporting** rule, not a filtering rule. A stratum failing the
  guard stays in every absolute-gain analysis at full weight; only its ratio is
  withheld.

---

## 8. Provenance and launch requirements for tonight

* This document, the pool audit, the rubric, the B1/B2 freeze, the gate manifest
  and every decision constant are committed **before** the first Solver-B
  trajectory (Part D.8).
* Launch goes through `cli.py dispatch`, which calls
  `provenance.assert_clean_tree` and exits non-zero on an uncommitted tree
  (D-36). **`--allow-dirty` is not used.** The guard's failure path is exercised
  deliberately before the real launch, per D-27's standing lesson that a gate
  whose failure path has never executed is not a gate.
* Every trajectory records model id, revision, endpoint, project commit, Biomni
  commit, dirty flag, config hash and the D-36 `source_hashes` map.
* New experiment IDs: `scope_gate_b1`, and `scope_gate_b2` only if the frozen
  FAIL branch is reached.

**Guard exercised, 2026-08-12, before the freeze commit.** `cli.py dispatch` was
invoked against `configs/scope_gate_b1.yaml` and
`manifests/scope_gate_b1_runs.jsonl` while the tree still held all twelve
untracked scope-study files. It printed
`REFUSING TO LAUNCH: DIRTY TREE at launch: ... (commit 53b80b7...)` and exited
**2**, before loading the config, reading the run manifest or contacting an
endpoint. The failure path ran on the real entrypoint, not in a test.

| artifact | hash |
| --- | --- |
| `manifests/scope_gate.jsonl` | `dd084f0e81243be40e2cd2f24ffedf76b4eaf608cad3d5f01e3b6eb56286a6d2` |
| run manifest `manifests/scope_gate_b1_runs.jsonl` | `19006eb711987d668f3baa8208faaab556d0079deb9f09d1cdd03c393d06bc43` |

### 8.1 The single bounded interface repair, predeclared

One repair is permitted, and only if B1 **cannot technically communicate with
the scaffold** because of a clear integration incompatibility. It must: not
depend on any correctness outcome; be documented here; be committed before the
restart; be verified on the same 24-instance gate set; and not change the
biomedical problem. A second failure ends B1's gate — it is not an invitation to
keep engineering until B1 looks competent. Tuning prompts, temperature, context
limits, tool lists or answer parsing **in response to observed accuracy** is
forbidden outright and is not what this clause permits.

---

## 9. Explicitly not done tonight

No trajectory against any never-used instance. No fresh scope-study manifest. No
Stage-C re-run, amendment or new cell. No modification to D-43. No search over
Solver-B models beyond B1 and the single predeclared B2. No accuracy-driven
tuning. No second verifier. No new controller. No HealthAgentBench. No new
benchmark. No K>4. No GPU time spent on additional Biomni-R0 trajectories.
