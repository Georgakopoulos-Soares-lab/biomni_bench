# Track-C CPU preflight — Step 1 of the live-GPU-window plan

**Written:** 2026-08-10. **CPU-only, ~15 s, no GPU, no model calls, no held-out
instance touched.** Driver: `scripts/track_c_preflight.py`. Tests:
`tests/test_track_c_preflight.py` (11). Tables:
`<output_root>/track_c_preflight/results/`.

> **Headline: Step 1b returns a decisive result that reshapes Step 2.** Only
> **7.1%** of the recoverable headroom on the split (`B_substantive_disagreement`)
> stratum is mode-A-eligible — below the pre-registered 15% floor. **The
> computational-verification route is not where the headroom is.** Step 2's
> pilot is therefore, in substance, a test of *evidence-based/inferential*
> adjudication, not computational re-derivation, and its task-family
> stratification is revised accordingly (§4).
>
> Step 1c replicates cleanly on both pools: degeneration concentrates in the
> **no-correct-trajectory** bucket, not the split stratum, on `phase2b`
> (68.9% vs 27.3%) and `phase1_pooled` (33.3% vs 21.4%) alike. The bias
> objection against pre-screening is substantially, though not completely,
> dissolved.

---

## 1a. Stratum reconciliation

Two partitions of the same 150 `phase2b` instances have been quoted in prior
reports without stating that they are **different, non-nested
classifications**. Recomputed directly from `p2b_pooled_trajectories.csv`:

| scheme | basis | counts |
| --- | --- | --- |
| **`evidence_state`** (D-30's Track-C partition) | how many *usable* trajectories exist and whether they agree | unanimous 82 / `B_substantive_disagreement` 53 / `A_insufficient_evidence` 15 |
| **`distinct_usable`** count (the "91 unanimous" framing) | how many distinct answers appear among usable trajectories, with no floor on how many trajectories that is | 0→6, **1→91**, 2→40, 3→11, 4→2 |
| **`no_correct_trajectory`** (the "45" framing) | whether *any* usable trajectory holds the correct answer | 45 true / 105 false — **orthogonal to both of the above** |

### The reconciliation, exactly

```
CROSS-TAB evidence_state x distinct_usable
distinct_usable              0   1   2   3  4
evidence_state
A_insufficient_evidence      6   9   0   0  0
B_substantive_disagreement   0   0  40  11  2
unanimous                    0  82   0   0  0
```

**The "91 unanimous" figure is not the same population as `evidence_state`'s
82 "unanimous."** It is 82 genuine unanimous instances (≥2 usable trajectories,
all agreeing) **plus 9 instances with exactly one usable trajectory** — a
single opinion trivially has "1 distinct answer," which is not unanimity in
any meaningful sense. Those 9 belong to stratum A
(`A_insufficient_evidence`), and are counted there, not among the 82.

**The "51 split" figure** is the 2-or-3-distinct-answer slice of stratum B
(40+11); stratum B's full 53 also includes the 2 four-way-disagreement
instances Track-C already treats as an abstention/escalation state.

**The "45 no-correct-trajectory" figure is a different axis entirely** —
outcome-based (did anyone get it right), not evidence-based (how much
independent opinion exists). It cuts across all three `evidence_state`
strata: 12 of stratum A's 15, 20 of stratum B's 53 ("all_wrong" within
substantive disagreement), and **13 of the 82 true-unanimous instances**
(the model agreed unanimously and was wrong). None of these three
sub-populations is visible in either single-axis framing alone.

### The canonical table (cite this, not either framing in isolation)

| `evidence_state` | `outcome` | n | mean oracle | mean plurality |
| --- | --- | ---: | ---: | ---: |
| A_insufficient_evidence | all_wrong | 12 | 0.000 | 0.000 |
| A_insufficient_evidence | single_usable_correct | 3 | 1.000 | 1.000 |
| B_substantive_disagreement | all_wrong | 20 | 0.000 | 0.000 |
| B_substantive_disagreement | correct_plurality | 19 | 1.000 | 1.000 |
| B_substantive_disagreement | wrong_plurality_or_tied_correct_minority | 14 | 1.000 | 0.000 |
| unanimous | all_wrong | 13 | 0.000 | 0.000 |
| unanimous | unanimous_correct | 69 | 1.000 | 1.000 |

### Headroom, both ways, as instructed

| | mean headroom (oracle − plurality) | 95% CI | n |
| --- | ---: | --- | ---: |
| stratum B only | 0.264 | [0.151, 0.377] | 53 |
| **overall (all 150)** | **0.093** | **[0.047, 0.140]** | 150 |

**Exactly 100% of all recoverable headroom sits in stratum B**, by
construction: strata A and unanimous have `oracle == plurality` on every row
(asserted by test — `test_headroom_is_zero_whenever_oracle_equals_plurality`),
since a single opinion or a unanimous one cannot produce a plurality that
diverges from the best available answer. This is the arithmetic fact
underlying every later step: **the entire addressable target for any
verification mechanism is these 53 instances**, worth 9.3 pp of overall
reward at the ceiling.

Replicated on `phase1_pooled` (50 instances): stratum B headroom 0.040
[0.000, 0.120] (n=25), overall 0.020 [0.000, 0.060] — the same structure, a
smaller pool.

---

## 1b. Verifiability × headroom crossing — the decisive check

**Premise under test:** VERIFY assumes checking is cheaper than solving —
plausible for deterministic computation, implausible for tasks requiring
external knowledge, where checking is about as hard as answering.

### Mode-A eligibility, fixed before classification

One representative prompt was read per task (all 10; BiomniEval1's prompts
are template-generated per task, so one template determines eligibility for
every instance of that task). Criterion: **eligible if and only if the asked
quantity is computable from raw data given verbatim in the prompt, with no
external database, literature, or domain-knowledge lookup required.**

| task | eligible? | why |
| --- | --- | --- |
| **`lab_bench_seqqa`** | **YES** | the raw DNA/protein sequence is given verbatim; the answer (an ORF translation, a position) is a pure computation over it |
| `crispr_delivery` | no | selecting a delivery method requires cell-type domain knowledge |
| `gwas_causal_gene_gwas_catalog` | no | causal-gene likelihood requires external GWAS-database evidence |
| `gwas_causal_gene_opentargets` | no | same |
| `gwas_causal_gene_pharmaprojects` | no | same |
| `gwas_variant_prioritization` | no | requires external fine-mapping/eQTL evidence |
| `lab_bench_dbqa` | no | explicitly phrased as a lookup against a *named external database* ("according to miRDB v6.0") |
| `patient_gene_detection` | no | requires external phenotype-gene association knowledge |
| `rare_disease_diagnosis` | no | requires clinical diagnostic knowledge |
| `screen_gene_retrieval` | no — **the one case checked against the full prompt, not the task name** | sounds data-driven ("strongest perturbation effect") but the full prompt supplies **no perturbation data** — only a research description and a candidate-gene list. Resolved as not-eligible, the same as every other non-`seqqa` task. |

No task was ambiguous after reading its full prompt; `screen_gene_retrieval`
is the one that could plausibly have gone the other way from its name alone,
and is reported as resolved, not as a judgment call left open.

### The number

| | value |
| --- | ---: |
| total stratum-B headroom | 14.0 (sum of oracle−plurality gaps, unnormalized) |
| stratum-B headroom on `lab_bench_seqqa` (the only mode-A task) | **1.0** |
| **fraction of headroom that is mode-A-eligible** | **7.1%** |

| task | n (stratum B) | headroom sum | mode-A? |
| --- | ---: | ---: | --- |
| patient_gene_detection | 13 | 4.0 | no |
| gwas_causal_gene_pharmaprojects | 5 | 2.0 | no |
| screen_gene_retrieval | 4 | 2.0 | no |
| lab_bench_dbqa | 6 | 2.0 | no |
| rare_disease_diagnosis | 7 | 2.0 | no |
| gwas_causal_gene_opentargets | 4 | 1.0 | no |
| **lab_bench_seqqa** | **1** | **1.0** | **yes** |
| crispr_delivery | 1 | 0.0 | no |
| gwas_causal_gene_gwas_catalog | 7 | 0.0 | no |
| gwas_variant_prioritization | 5 | 0.0 | no |

**Only one `lab_bench_seqqa` instance falls in stratum B at all** — the task
is already 86.7% accurate (D-30 §9), so almost nothing is left to disagree
about. This is exactly the reservation raised before any of this was
measured: *the tasks with re-derivable structure are the tasks that already
work; the tasks with headroom are not the tasks with structure.* It is now a
measured fact, not a hunch.

### Decision, per the rule fixed before this number existed

> **7.1% < 15% → "the computational-verification route is not where the
> headroom is." Stated plainly, as the rule required.**

Secondary check (all headroom, not just stratum B, since 13 "unanimous but
wrong" instances also carry zero addressable headroom by construction and do
not change the picture): mode-A share of *all* headroom is also **7.1%**
(1.0 of 14.0) — identical, because stratum B is where all headroom lives
(§1a).

---

## 1c. Degeneration × stratum

**Question.** Are `consecutive_runaway`-prone instances concentrated in the
no-correct-trajectory bucket (screening loses little) or the split stratum
(screening would destroy the target population)?

| bucket | phase2b: n / degenerate / rate [95% CI] | phase1_pooled: n / degenerate / rate [95% CI] |
| --- | --- | --- |
| **no_correct_trajectory** | 45 / 31 / **68.9%** [55.6%, 82.2%] | 18 / 6 / **33.3%** [11.1%, 55.6%] |
| split_B | 33 / 9 / 27.3% [12.1%, 42.4%] | 14 / 3 / 21.4% [0.0%, 42.9%] |
| other_has_correct | 72 / 17 / 23.6% [13.9%, 33.3%] | 18 / 1 / 5.6% [0.0%, 16.7%] |

**Same direction on both pools.** Degeneration is 2.5–2.6× more common in the
no-correct-trajectory bucket than in the split stratum on `phase2b`
(68.9% vs 27.3%), and 1.6× on `phase1_pooled` (33.3% vs 21.4%) — smaller
gap, wide CIs (n=14–18 per bucket), but the same direction, not a reversal.

**Reading: CONCENTRATED IN NO-CORRECT-TRAJECTORY.** Pre-screening out
`consecutive_runaway`-prone instances would disproportionately remove
instances that have nothing to learn anyway (69% of them already degenerate
on `phase2b`), while touching the split stratum meaningfully less (27%). The
bias objection against D-34's proposed pre-screening mitigation is
**substantially, though not completely, dissolved** — split-stratum
instances are not immune (27%/21% is not negligible), so screening would
still trim some of the target population, just disproportionately less of it
than the population with nothing to find.

---

## What this changes for Step 2

1b is a hard constraint, not a soft preference. Concretely:

* **Step 2's two-arm design (one-shot vs. tool-enabled adjudication) is
  unaffected in mechanics** — it was never mode-A-specific; Arm 2's tool
  access covers evidence retrieval (mode-B-style) as much as computation.
* **The originally proposed "computational vs. inferential" task-family
  stratification is no longer a meaningful two-group split** — stratum B
  contains exactly one mode-A instance. Restated as the axis that actually
  separates the 53 target instances: **evidence-retrievable via a working
  tool** (structured-database tasks — `gwas_*`, `lab_bench_dbqa`, drawing on
  the D-33-repaired/already-healthy database tools) versus
  **domain-judgment tasks with no reliable retrieval route**
  (`patient_gene_detection`, `rare_disease_diagnosis`, `crispr_delivery`,
  `screen_gene_retrieval` — evidence needs D-33 already found unmet, e.g.
  general web search).
* **Expectations are recalibrated, not the design.** Step 2 is now
  understood, before it runs, as principally a test of whether
  evidence-based/inferential adjudication can recover minority-held answers
  — which is the scientifically live question per 1b — rather than a mixed
  computational-and-inferential test as originally framed.
* **1c licenses stating the pre-screening idea from D-34 with more
  confidence, not less** — it would not be evidence-blind in the way the
  original objection worried, though it is not free of cost on the split
  stratum either. Both facts are carried into any future protocol that adopts
  it.

---

## Reproduction

```bash
python scripts/track_c_preflight.py --out <output_root>/track_c_preflight/results
```

CPU only, ~15 s, deterministic (bootstrap seed 20260811001). Reads frozen
tables read-only; writes only under `track_c_preflight/`. 10 tables plus
`track_c_preflight.json`.

**No frozen artifact was modified.**
