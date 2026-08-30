# Methods note: two agreement→correctness AUROC estimands, and which is canonical

**Addendum, 2026-08-30 (later same day): `scope_main` Arm A recomputed for real.**
§5 below originally left this an open, unresolved question — held-out data
was deliberately not on hand. It has since been transferred (small-file-only,
`scripts/sync_biomni_corpus.sh`, read-only, `sha256`-verified) and
recomputed. **Original §5 text is preserved unedited below** ("Do not modify
historical reports silently" applies to this note's own prior text too, not
only to `DECISIONS.md`); this addendum states the result on top of it,
dated, without erasing what came before.

**Legacy AUROC reproduced bit-exactly**, confirming this is the same
population D-46 measured, not a different sample: `0.8955597248280175`,
CI `[0.8552910774430531, 0.9298434530954218]` — matches D-46's published
`0.8956 [0.8552, 0.9302]` to 4 decimal places, computed via
`analysis.signal_auroc_table` on `configs/scope_main_a.yaml`'s own
`build_tables()` output (480 planned, 391 completed, 89
`model_context_overflow` — also an exact match to D-46's completion counts).

**Canonical v1 instance-level AUROC: `0.8508`** (n=116/120 evaluable
instances; AUPRC `0.894`; AURC `0.143`), computed via
`reliability.evaluate_reliability`, identical method to every other number
in `reports/biomni_trajectory_distillation_audit.md` §3.

```
legacy trajectory-level estimand:   0.8956  [0.8552, 0.9302]  (n=480 trajectories)
canonical v1 instance-level estimand: 0.8508  (n=116 instances)
```

**A real, interesting secondary finding**: the legacy/v1 gap here (−0.045)
is far smaller than `phase1`'s gap (−0.253, §1–§2). This is not a
coincidence — it's explained by §1's own mechanism. The gap is driven by
`stable_wrong` instances (agreeing majority, wrong answer — legacy dilutes
their difficulty across several correlated rows; v1 concentrates it into one
full point). `scope_main` Arm A's taxonomy has only **3/116 (2.6%)**
`stable_wrong` instances (taxonomy: `unstable_recoverable` 48,
`stable_correct` 47, `unstable_unrecoverable` 18, `stable_wrong` 3) — far
fewer than `phase1`'s share — so there is much less "confidently wrong"
mass for the two estimands to disagree about. **The size of the legacy/v1
gap is population-dependent, not a fixed correction factor** — a caution
worth keeping for any future population this metric is applied to.

**Cross-agent table, harmonized, at last:**

| agent | v1 instance-level AUROC | population |
| --- | ---: | --- |
| **Biomni-R0** (Arm A) | **0.8508** | `scope_main`, 116/120 evaluable, K=4 |
| GenoMAS | 0.529 | 12-task K=4 pilot |
| AutoBA | 0.542 | 10-task K=4 pilot (12 frozen, 2 excluded for non-evaluability) |

**Answering the four questions this addendum was written to resolve:**

1. **Does Biomni still show clearly stronger agreement→correctness
   discrimination?** Yes — 0.851 vs. 0.529/0.542 is still a very large,
   unambiguous gap under the harmonized metric.
2. **Is the difference large, modest, or essentially absent?** **Large.**
   The gap shrank only slightly from the legacy comparison (0.896→0.851 for
   Biomni; GenoMAS/AutoBA's own numbers were already v1 and don't move).
3. **How much of the old apparent Biomni advantage was caused by mixing
   estimands?** A small amount, quantifiable exactly: the legacy-vs-v1
   correction moves Biomni's own number down by 0.045 (0.896 → 0.851) — not
   nothing, but nowhere near enough to close a ~0.31-point gap against
   GenoMAS/AutoBA. The original three-agent story was not an artifact of
   metric-mixing; it was mostly measuring something real, with a modest,
   now-quantified overstatement.
4. **What claims are now stale?** `DECISIONS.md` D-57's cross-agent table
   should be read with **0.8508 substituted for 0.896** for Biomni whenever
   it is cited as a v1-comparable number — the qualitative conclusion in
   D-57 ("this project now has two independently-built agents... showing a
   near-chance self-consistency signal against one showing a strong one")
   **survives unchanged**. No claim in `PROJECT_STATUS.md` or `DECISIONS.md`
   needs retraction; the one correction is a decimal, not a conclusion.

**Decision Gate A classification: `A. STRONG`** — Biomni remains clearly
separated from GenoMAS/AutoBA using the canonical v1 metric. The distillation
project's primary objective (reward-positive ensemble supervision, not
agreement-weighting) was already scientifically meaningful independent of
this classification per `reports/close_out.md`'s own framing, and remains so
now that the classification came back STRONG rather than needing that
fallback framing at all.

**`DECISIONS.md` is not edited by this addendum** — this note is the
correction record; D-46/D-57 remain as originally written, historically
accurate to what was computed at the time.

---

**Written:** 2026-08-30. **Status:** resolves the discrepancy flagged in
`reports/biomni_trajectory_distillation_audit.md` §3.1/§12 between the
legacy `agreement_fraction` AUROC (`analysis.signal_auroc_table`, ~0.874 on
`phase1`) and Reliability Suite v1's `agreement_to_correctness_auroc`
(`reliability.evaluate_reliability`, ~0.621 on the identical `phase1` data).

**Headline: not a bug in either implementation.** Both compute a standard
rank-sum (Mann–Whitney U) AUROC with average-rank tie handling — verified by
reading both formulas (`analysis.py::auroc`, `reliability.py::_auc`), which
are numerically the same statistic. The discrepancy is entirely a
**difference in unit of observation and target variable**, demonstrated
below with real data, not asserted.

---

## 1. Side-by-side definition

| | legacy (`agreement_fraction` AUROC) | Reliability Suite v1 (`agreement_to_correctness_auroc`) |
| --- | --- | --- |
| **Unit of observation** | one row per **trajectory** | one row per **task instance** |
| **Agreement/score variable** | `agreement_fraction = agree_count / (K_completed - 1)` — a **leave-one-out** measure: how many *other* trajectories in the group share this trajectory's answer, as a fraction of the other trajectories (`features.py:177`). Can differ *within* one instance's group (majority members score higher than minority members). | `plurality_fraction = size_of_largest_cluster / K_completed` (`features.py::consensus`, matches the prompt's own stated formula). **Identical for every trajectory in the same instance** — it is a property of the instance, not of any one trajectory. |
| **Correctness target** | that **same trajectory's own** `correct` (0/1) | whether the **deterministically tie-broken plurality winner** is correct — one label per instance, independent of which physical trajectory instantiates the winning answer |
| **Handling of K** | contributes up to `K_completed` rows per instance (2–4 in this project) | contributes exactly **1** row per instance, regardless of K |
| **Handling of ties** | winner selection for the *label* doesn't apply (label is per-trajectory); cluster membership itself has no ties to break | shared with the legacy pipeline's own plurality logic — `features.py::consensus()`'s deterministic rule: among clusters tied for largest, the winner is the one containing the lowest `trajectory_index` (`is_tie` is recorded, never hidden) |
| **Handling of incomplete groups** | trajectories with no `correct` value are dropped from the AUROC input; groups with `K_completed < 2` contribute `agreement_fraction = None` (undefined LOO agreement, correctly excluded) | an instance contributes no row if it has zero completed trajectories (`con is None`); otherwise `plurality_fraction`'s denominator is `K_completed`, not a fixed 4 — an instance with only 2 completed trajectories is scored on its actual 2, not padded to 4 |
| **Sample count entering AUROC** (`phase1`, instrumented K=4) | **n = 200** trajectory-rows, 50 instances | **n = 50** instance-rows |
| **Exact statistical call** | `analysis.py::auroc()` — manual rank-sum AUROC, average ranks for ties | `reliability.py::_auc()` — `pandas.Series.rank(method="average")` then the same rank-sum formula. Verified numerically identical to the legacy formula on the same inputs (both reduce to `(sum_of_positive_ranks - n1(n1+1)/2) / (n1 n0)`, the Mann–Whitney U statistic in AUROC form). |
| **Bootstrap CI** | `grouped_bootstrap`, resampling whole **instances** (`group_col="instance_uid"`) — the CI already respects the instance as the resampling unit, but the **point estimate** does not | `_ci()` resamples the (already instance-level) array directly — point estimate *and* CI both respect the instance as the unit |

**The load-bearing asymmetry**: legacy's bootstrap *CI* already follows this
project's own stated rule (`CLAUDE.md`: "Resampling unit is the task
instance, never the individual trajectory") — but its **point estimate**
does not, because up to 4 correlated trajectory-rows from the same instance
are pooled into the rank-sum as if independent. Reliability Suite v1 applies
that rule to the point estimate too.

---

## 2. Three concrete real instances, same raw data, different contributions

From `phase1`'s actual K=4 groups (`configs/phase1.yaml`, `manifests/phase1.jsonl`):

| instance | cluster shape | trajectories (index: answer, correct) | legacy rows contributed | v1 row contributed |
| --- | --- | --- | --- | --- |
| `gwas_causal_gene_gwas_catalog/159` | 4–0 unanimous, correct | t0–t3 all `RNF213`, all correct | **4 rows**: `(agreement=1.0, correct=1)` × 4 | **1 row**: `(plurality_fraction=1.0, plurality_correct=1)` |
| `gwas_causal_gene_opentargets/32` | 3–1, majority correct | t0 unparseable (wrong); t1–t3 `PAX4` (correct) | **4 rows**: `(0, 0)`, `(0.667, 1)` × 3 | **1 row**: `(0.75, 1)` |
| `gwas_causal_gene_gwas_catalog/520` | 3–1, **majority wrong** | t0,t1,t3 `GAS7` (wrong); t2 `CFAP52` (wrong — both are wrong, ground truth is neither) | **4 rows**: `(0.667, 0)` × 3, `(0, 0)` | **1 row**: `(0.75, 0)` |

The mechanism, visible directly in these three instances: legacy's 12
trajectory-rows from just these 3 instances include **3 rows at score 0.667
labeled correct** (instance 32's majority) sitting right next to **3 rows at
the *same* score 0.667 labeled wrong** (instance 520's majority) — a
same-score, opposite-label pair that *should* be a maximally confusing,
AUROC-neutral tie, but because instance 520 (the genuinely hard, "confident
and wrong" case) is diluted across 3 nearly-identical correlated rows while
contributing only as much total rank-sum weight as one contested instance,
its difficulty is under-weighted relative to how much it matters at the
instance level. In v1, this same instance is exactly one full,
undiluted `(0.75, wrong)` point — a `stable_wrong`-adjacent case that pulls
the instance-level AUROC down by its full weight. This is the general
mechanism behind the ~0.25 point gap, not an artifact of these three
examples specifically.

---

## 3. Independent recomputation (verification, not re-derivation)

Both official functions (`analysis.signal_auroc_table`,
`reliability.evaluate_reliability`) were called on the **identical**
`tables["instrumented"]` DataFrame that `cli.py analyze` itself builds for
`phase1` (not a hand-reloaded CSV, to rule out any silent preprocessing
difference):

```
LEGACY agreement_fraction AUROC:  0.8743734015345268   n_rows=200  n_instances=50
V1 agreement_to_correctness_auroc: 0.6206896551724138   n_instances=50
```

Both reproduce their previously-published/reported values exactly
(`phase1_report.md`'s 0.874; this audit's §3.1 0.621) from the same input,
confirming the discrepancy is fully explained by §1's definitional
differences and is not an artifact of which file the number came from.

A from-scratch, independently-written reimplementation (not calling either
production function, built only from the raw `trajectories.csv` columns and
manual rank-sum AUROC) reproduced the same **qualitative** result — trajectory-level
AUROC (0.772 on a differently-filtered subset) exceeding instance-level AUROC
(0.698 on the same subset) — confirming the direction and mechanism
independently of both codebases, even though the exact values differ from
the official ones due to this note's simplified filtering (a `≥2`-completed
cutoff instead of the pipeline's own condition/consistency handling). The
official-function comparison above is the one to cite; the from-scratch
version exists only to confirm the mechanism isn't an artifact of either
production implementation.

---

## 4. Which is canonical, decided from the definitions

**Reliability Suite v1's `agreement_to_correctness_auroc` (instance-level) is
the canonical cross-agent metric**, for three independent reasons — none of
them "because the number is lower":

1. **It matches the stated scientific question.** The estimand this project
   asks for is *"given the observable self-consistency of repeated runs for
   a task, how well can we rank task-level predictions by their probability
   of being correct?"* — a task-level question. Legacy's `agreement_fraction`
   AUROC answers a genuinely different, also-valid question: *"does an
   individual trajectory's own local agreement with its siblings predict
   that trajectory's own correctness?"* — useful for trajectory-level
   filtering/selection, not for characterizing a task's ensemble value.
2. **It's the only one of the two that fully honors this project's own
   scientific-integrity rule** ("resampling unit is the task instance, never
   the individual trajectory") — legacy applies this to the confidence
   interval but not the point estimate; v1 applies it to both.
3. **It's already the metric used for `GenoMAS` and `AutoBA`.**
   `scripts/run_genomas_k4_reliability.py` and
   `scripts/run_autoba_k4_reliability.py` both call
   `reliability.evaluate_reliability` directly — their published AUROCs
   (GenoMAS 0.529, AutoBA 0.542, `reports/autoba_k4_pilot_v1_results.md`)
   are already instance-level. Using legacy's trajectory-level number for
   Biomni while these two use v1 is comparing different estimands under one
   table, not a fair cross-agent comparison — see §5.

**The legacy `agreement_fraction` AUROC is retained** as a distinct,
explicitly-labeled secondary/historical estimand — it remains a legitimate
trajectory-level filtering signal (e.g., `phase1_report.md`'s own
selector-comparison work, which is about *choosing among a group's
trajectories*, a trajectory-level question by nature) — but must never again
be cited as "the" agreement→correctness AUROC without that qualifier.

---

## 5. Open finding: the published cross-agent comparison mixes estimands

**`scripts/scope_main_detection_analysis.py`'s own docstring confirms** the
120-task held-out set's headline number —
`agreement→correctness AUROC 0.8956` (`DECISIONS.md` D-46, quoted throughout
`prompts/before_distil.md` and `reports/rl_harness_preregistration.md`) — was
computed via **the same legacy `signal_auroc_table`/`agreement_fraction`
pathway** as `phase1`'s 0.874 ("the same instance-clustered-bootstrap AUROC
used for Phase 1's `agreement_fraction` result"), **not** Reliability Suite
v1. The published cross-agent table in `DECISIONS.md` D-57 — Biomni-R0 0.896
vs. GenoMAS 0.529 vs. AutoBA 0.542 — therefore compares a **legacy**
trajectory-level number against two **v1** instance-level numbers. Per §1–§2
above, the trajectory-level formula tends to read higher for the same
underlying data. **Some fraction of Biomni's apparent reliability-signal
advantage over GenoMAS/AutoBA in that table may be a metric-definition
artifact, not (or not entirely) a genuine difference in self-consistency
structure.** This does not mean the qualitative finding is wrong — Biomni's
raw trajectory-level number (0.896) is itself far above GenoMAS/AutoBA's
instance-level numbers (0.529/0.542), which is suggestive either way — but
the *magnitude* of the gap has not been measured on a like-for-like basis.

**This is not fixed in this note.** Recomputing `scope_main` Arm A's v1
instance-level AUROC needs its raw or aggregated per-trajectory data
(`manifests/scope_main.jsonl`'s 120 instances), which was **deliberately not
transferred** to this host — it is the held-out evaluation set, and pulling
it wasn't part of what today's session was asked to do. `DECISIONS.md`
D-46/D-57 are **not edited** here, per the instruction not to modify
historical reports silently; this note exists precisely so the mismatch is
visible rather than quietly carried forward. **Recommended next step, held
for an explicit decision rather than done unprompted:** transfer
`scope_main`'s small-file data (same procedure as
`scripts/sync_biomni_corpus.sh`, read-only, no different in kind from what
was already done for `phase1`/`phase2b`) and recompute its v1
`agreement_to_correctness_auroc` for Arm A (and, for completeness, Arm B),
then add — never overwrite — a dated addendum to the relevant reports
stating both numbers side by side.

---

## 6. Consistency action taken in this session

Every Biomni number newly computed in this session
(`reports/biomni_trajectory_distillation_audit.md` §3) uses
`reliability.evaluate_reliability` exclusively — `phase1`, `phase1_pooled`,
and `phase2b`'s `agreement_to_correctness_auroc` values (0.621, 0.626, 0.743)
are already v1/instance-level and already comparable to GenoMAS/AutoBA on
that basis. The only remaining inconsistency is the **historical**
`scope_main` number named in §5, which requires the additional data-access
decision above to close.
