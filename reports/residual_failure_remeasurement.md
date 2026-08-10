# Residual trajectory failure — re-measured post evidence-channel repair

**Written:** 2026-08-10. **VERIFY prerequisite item 3**
(`reports/verify_prerequisites.md`), performed only after items 1 and 2
(D-33) were complete, as instructed. Per explicit instruction, **the old
15.5% number was not assumed to still apply, and no repair was begun before
measuring.**

> **VERDICT: prerequisite 3 is NOT met.** Residual failure is
> **9/32 = 28.1%, 95% Wilson CI [15.6%, 45.4%]** on a fresh, stratified,
> live-generated sample — the lower CI bound barely clears 15%, not
> "comfortably below" it. **The mechanism is identical to the one already
> diagnosed in Phase 1.5** (input tokens crossing the model's ~32,768-token
> trained-context boundary, triggering repeated degenerate generation until
> the Arm-2 circuit breaker fires) and **is confirmed not caused by the
> evidence-channel repair** — see §4. No broad Arm-1/2/3-style search is
> proposed, per instruction, because the evidence does not point to anything
> new: this is the same, already-understood residual limitation Phase 1.5
> already characterized and decided not to chase further before Phase 2B.

---

## 1. What was run, and why it is not a prospective manifest

**Live GPU inference**, the first of this engagement — approved separately
before launch given the live cost involved. Job `3388121` (the same Slurm job
that served Phase 2B) was still running with a live, responsive SGLang
endpoint; no new allocation was requested.

* **8 fresh instances**, 2 each from `patient_gene_detection`,
  `lab_bench_dbqa`, `screen_gene_retrieval`, `gwas_causal_gene_gwas_catalog` —
  the four highest-historical-failure-rate tasks (D-30) that still have
  **unused reserved pool**. `crispr_delivery` and `rare_disease_diagnosis`
  were excluded because D-22 already exhausted their entire remaining pools;
  reusing an already-spent instance for a discarded diagnostic was judged not
  worth the ambiguity it would introduce.
* **Zero overlap** with `manifests/phase1.jsonl` and `manifests/phase2b.jsonl`,
  asserted in code before the run (200 prior instances excluded from the
  selection pool).
* **Config byte-identical to `configs/phase2b.yaml`** — same model revision,
  same Arm-2 budget guards, same controller — except the experiment name and
  the 8 hand-picked instances, so this measures the environment, not a changed
  protocol.
* **Manifest hash `bf08938d…`, 8 instances** — recorded here for the record,
  **not frozen, not written to `manifests/`, not cited in any future protocol
  as a held-out sample.** Both the manifest and config live in the session
  scratchpad, never in a git-tracked path.
* Output isolated under `<output_root>/verify_prereq_diag3/`, its own
  directory, never merged with any tracked experiment.
* **32 trajectories generated, 8.5 GPU-minutes-equivalent × concurrency ≈
  62 minutes wall clock, 0 chain failures, 0 errored instances.**

---

## 2. Headline number

| | value |
| --- | --- |
| trajectories | 32 (8 instances × 4) |
| residual failure (`model_context_overflow` / `budget_terminated*`) | **9/32 = 28.1%** |
| 95% Wilson CI | **[15.6%, 45.4%]** |
| pre-registered halt threshold | 15% |

The point estimate is **above**, not below, the historical 15.5%. The CI's
lower bound (15.6%) sits essentially at the threshold itself — this sample
cannot support "comfortably below 15%" under any reasonable reading.

---

## 3. Task-matched comparison against Phase 2B

The right comparison is task-matched, not against the old *pooled* 15.5%
(computed over all ten tasks at different weights) — this sample only touches
four of them.

| task | before (Phase 2B, n=60) | after (this run, n=8) |
| --- | --- | --- |
| `gwas_causal_gene_gwas_catalog` | 16.7% [9.3%, 28.0%] | 25.0% [7.1%, 59.1%] |
| `lab_bench_dbqa` | 18.3% [10.6%, 29.9%] | **0.0%** [0.0%, 32.4%] |
| `patient_gene_detection` | 20.0% [11.8%, 31.8%] | **62.5%** [30.6%, 86.3%] |
| `screen_gene_retrieval` | 18.3% [10.6%, 29.9%] | 25.0% [7.1%, 59.1%] |
| **pooled over these 4 tasks** | **18.3%** (44/240) | **28.1%** (9/32) |

Every "after" CI overlaps its "before" CI — **at n=8 per task nothing here is
statistically distinguishable from the historical rate**, in either
direction. The `patient_gene_detection` point estimate (62.5%) looks alarming
in isolation and is explained entirely by concentration, not a new problem —
see §4.

---

## 4. Mechanism, confirmed identical to Phase 1.5's diagnosis — and confirmed unrelated to the evidence-channel repair

Every one of the 9 failures carries `terminated_reason: "consecutive_runaway"`
and `peak_input_tokens` in **32,936–40,637** — the exact boundary Phase 1.5
identified (`context_overflow_forensics.md`: the model is trained at 32,768
tokens; the serving override lifts the position ceiling but not the usable
context, and generations past that boundary degenerate into repetition). This
is the **Arm-2 guard doing exactly what it was designed to do**: bound the
cost of a trajectory that keeps re-degenerating, not prevent the degeneration
itself. Nothing about this mechanism is new.

**Is the evidence-channel repair (D-33) responsible?** No, on two independent
pieces of evidence from this same run:

1. **query_pubmed/query_arxiv were not the common factor.** Of the 9 failed
   trajectories, only 5 called `query_pubmed` at all (and none called
   `query_arxiv`); the other 4 failed using only already-healthy structured
   database tools (`query_ensembl`, `query_monarch`, `query_clinvar`,
   `query_gwas_catalog`).
2. **The single most-failed instance fails identically regardless of which
   tools it used.** `patient_gene_detection/i0273` failed on **all 4** of its
   independent trajectories — accounting for 4 of the 9 failures (44%) in
   this entire sample. Two of those four (`t0`, `t2`) never called
   `query_pubmed` or `query_arxiv` at all, using only `query_ensembl` and
   `query_monarch`. The same degenerate pattern occurred whether or not the
   repaired tools were used, which is only possible if the repair is not the
   cause.

**This is a single pathological instance, not a systematic regression.**
Excluding `i0273` alone: **5/28 = 17.9%, 95% CI [7.9%, 35.6%]** — closer to,
though still not comfortably under, the historical rate. This is exactly the
concentration pattern already documented for `rare_disease_diagnosis` in
Phase 1.5 (`reports/phase1_repaired_report.md` §8: "10 of its 13 failures
persist even with the repair… a residual limitation, not a repair bug") —
specific instances push the model into repeated degeneration "no matter how
it's nudged," independent of task identity.

---

## 5. The gate exercise

Run live against this fresh run's data — not a replay of historical
artifacts, as D-29's provenance audit was; this is the first time the
corrected gate has judged data it had never seen before.

```
[FAIL] residual failure rate    9/32 = 28.1% overflow/degeneration (halt above 15%)
VERDICT: BLOCKED - 1 fatal gate(s) failed.
```

**Exit code 1, `VERDICT: BLOCKED`.** Every other gate **passes**: 8/8
instances terminated, all 8 hash chains verify, shadow isolation holds for
all 8 shadows, no forbidden field appears anywhere, no failure was ever
accepted by the failure override, and `consumed + shadow == K` for every
instance. **The controller, the instrumentation and the gate all function
correctly on data generated after the D-32/D-33 changes** — nothing about
those changes broke anything upstream of the residual-failure question
itself.

---

## 6. Localization and recommendation

**Localization.** Failure is not spread evenly across trajectories — it
concentrates in specific pathological instances (one instance, `i0273`,
contributed 44% of all failures in this sample), consistent with the existing
`rare_disease_diagnosis` precedent. The mechanism is fully diagnosed
(Phase 1.5) and the Arm-2 repair is already doing what it can: bounding cost,
not eliminating the underlying degeneration.

**Per instruction, no broad Arm-1/2/3-style search is proposed.** The
evidence does not call for one: this run added no new information about the
mechanism, confirmed the existing Arm-2 guard behaves as designed, and
confirmed the evidence-channel change (D-33) is not implicated. Re-running the
72-trajectory ablation would spend real GPU time re-measuring something
already measured.

**Smallest targeted intervention — proposed, not implemented.** Since the
failure is concentrated in specific instances rather than being uniform, and
Phase 1.5 already tried and **explicitly rejected** raising the context
ceiling (shown to make things worse), the intervention that fits the evidence
is at the **selection** layer, not the **serving** layer: **screen candidate
instances for a future held-out sample with one cheap trajectory before
committing K=4 to them, and exclude ones that hit `consecutive_runaway` on
that screen.** This does not reduce the underlying degeneration rate; it
prevents a prospective run's compute and statistical power from being spent
on instances already known to be pathological before the run starts. This is
a proposal for a future protocol to adopt, not something implemented here.

**What this means for a future prospective run.** Two honest options, stated
for whoever designs the next protocol:
1. **Accept the current residual rate** and design the statistical plan
   (sample size, halt threshold) around it explicitly, rather than assuming
   improvement; or
2. **Adopt instance-level pre-screening** (above) and re-measure on the
   screened pool before trusting the number for a real experiment.

Either way: **do not launch a real prospective run assuming this number has
improved.** It has not, on the evidence available.

---

## 7. Limitations

1. **n=32 is small.** The Wilson CI is wide (±15 pp either side of the point
   estimate); this is a screening measurement, not a precise estimate.
2. **Stratified, not representative.** Only 4 of 10 tasks are covered, chosen
   for their historically elevated rate; the true pooled rate across all 10
   tasks is not directly estimated here.
3. **One instance drives much of the signal.** `i0273`'s 4/4 failure is a
   large share of a small sample; a different draw of 8 instances could easily
   show a materially different number by chance alone.
4. **`crispr_delivery` and `rare_disease_diagnosis` are not covered** — their
   pools are exhausted, and `rare_disease_diagnosis` was the single largest
   contributor to Phase 2B's excess failure rate. Whatever this sample shows
   says nothing new about that task specifically.
5. **Single draw, single ordering.** No repeated draws or orderings were run,
   consistent with the "smallest fresh diagnostic sample" scope, not a
   confirmatory measurement.

---

## 8. Reproduction

Not reproducible byte-for-byte in the frozen-protocol sense — this is a
throwaway diagnostic and its manifest/config are deliberately outside version
control. The method is fully described in §1 and is reproducible in kind
(same task quotas, same exclusion logic, a new seed) using
`scripts/prepare_phase2b_manifest.py`'s pattern as a template, and analyzed
with the existing `scripts/phase2b_verify.py` unchanged. Raw run data:
`<output_root>/verify_prereq_diag3/` (not committed, not cited by any frozen
report).

**No frozen artifact was touched. No file was written to `manifests/` or
`configs/`. No experiment ID was registered in `PROJECT_STATUS.md`'s Active
Experiment IDs table** — this run is explicitly not one.
