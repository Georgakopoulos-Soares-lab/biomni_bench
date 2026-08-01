# PROJECT_STATUS

**Last updated:** 2026-08-01 06:40 CDT
**Phase:** **PHASE 1 COMPLETE.** Pilot ran, was fixed and re-analyzed, report is final.

---

## Headline result

**GO.** Oracle headroom 20.0 pp (relative error reduction 34.5%). Plurality
beats first-trajectory by +0.16 with a 95% CI `[+0.06, +0.26]` that excludes
zero. Agreement-fraction is the strongest uncertainty signal measured (AUROC
0.874), stronger than verbalized confidence (0.789), which is itself
discriminative but severely miscalibrated (mean stated 0.96 vs actual accuracy
0.59). Full detail: `reports/phase1_report.md`.

The largest data-quality issue is a **24% context-overflow rate** — the
top engineering priority before Phase 2.

---

## Completed

### Phase 0 (steps 1–10) — see prior entries below, all done.

### Phase 1 pilot — run to completion

* Launched 2026-07-31 19:25 CDT, detached (`setsid`, PPID 1). Relaunched
  19:33 at dispatcher concurrency 8 (measured throughput at concurrency 4
  would not finish inside the allocation; 8 gave 379 tok/s vs 190, KV usage
  well under capacity).
* **Finished 2026-08-01 05:38 CDT.** 248/250 runs present, 188/250 (75.2%)
  completed. All 250 runs accounted for (2 truly missing run directories).
* Full pipeline ran automatically: dispatch → aggregate → analyze → 13
  figures + tables, via `scripts/run_detached.sh`.

### Post-pilot bug fixes (found by reading real pilot data, not the smoke test)

1. **Canonicalization gap** — Biomni states gene-symbol answers symbol-first
   ("**PDGFRB** is identified as the most likely causal gene...") far more
   often than label-first ("answer: PDGFRB"); the old parser only matched
   label-first and marked 32 trajectories `ambiguous` (all in the three
   `gwas_causal_gene_*` tasks, 44–52% of those tasks). Fixed with a new
   symbol-first-conclusion regex; **reparsed every stored raw response with
   `scripts/reparse_pilot.py`** (no model calls — data was already on disk):
   31/32 resolved cleanly. This meaningfully moved every headline number
   (first 0.36→0.42, plurality 0.50→0.58, headroom 24pp→20pp). The report
   reflects the **corrected** numbers; the fix and its effect are documented
   in `reports/phase1_report.md` §3 for full transparency.
2. **Context-overflow misclassification** — a second 400-error phrasing
   ("the input (N tokens) is longer than the model's context length") wasn't
   recognised by the classifier; 2 runs were mislabelled `unknown_failure`.
   Fixed and relabelled from the already-recorded error text.
3. **Confidence parse-rate denominator** — the missingness plot divided by
   all planned runs instead of runs that actually requested confidence,
   understating the rate (found on smoke data, fixed before the pilot ran).
4. **`system_prompt.txt` truncation** — the audit copy was cut to 20k of
   ~190k chars by the event-log redactor, hiding the confidence instruction
   from the record (verified functional behavior was unaffected; fixed for
   auditability, mid-pilot).
5. **Resumption append bug** — `events.jsonl` is append-only, so a resumed
   run would have interleaved two attempts. Fixed by archiving a prior
   attempt to `attempt<N>/` before re-running (this mattered in practice: the
   concurrency-4→8 relaunch exercised this path for real).

All five are regression-tested. Full list of earlier (pre-pilot) fixes is
preserved below.

### Reports

* `reports/phase0_environment.md` — complete.
* `reports/phase1_protocol.md` — frozen before the pilot; deviations logged
  (concurrency change, one-replica layout, failure-class addition) rather than
  edited away.
* `reports/phase1_report.md` — **complete, all real numbers**, no
  placeholders remain. Go/No-Go: **GO**.
* `reports/phase2_plan.md` — decision rule; this pilot's outcome selects
  **Track A (adaptive controller)**, with context-overflow fix and
  confidence recalibration flagged as prerequisites.

---

## Current blockers

None. Phase 1 is complete.

---

## Tests run

| check | result |
| --- | --- |
| `pytest -q` | **247 passed** |
| `ruff check src tests` | clean |
| `ruff format --check src tests` | clean |
| Import check inside the Biomni environment | OK |
| Manifest dry run | OK — 50 instances, 5 per task, stable hash |
| Mock end-to-end | 20 passed, 13 figures |
| GPU smoke test | passed — 6 runs, aggregation, analysis, 13 figures |
| **GPU pilot (250 runs)** | **complete** — 188/250 completed, full analysis, report written |

All bugs found and fixed (pre-pilot + post-pilot) are listed with detail in
`reports/phase0_environment.md` §8 and `reports/phase1_report.md` §3.

---

## Active experiment IDs

| id | config | state |
| --- | --- | --- |
| `smoke` | `configs/smoke.yaml` | complete, not pooled with pilot results |
| `phase1` | `configs/phase1.yaml` | **COMPLETE.** Results at `<output_root>/phase1/results/`. Report: `reports/phase1_report.md` |

---

## Known failures (final)

* `model_context_overflow`: 60/250 (24.0%) — dominant failure mode, concentrated
  in `rare_disease_diagnosis` (52%), `patient_gene_detection` (44%),
  `crispr_delivery`/`lab_bench_seqqa` (36% each); zero in two GWAS tasks.
  Flagged as the top Phase-2 engineering priority.
* `confidence_parse_failure`: 17 — model answered but confidence block was
  missing/malformed.
* `agent_parse_failure`: 8 (6 genuinely ambiguous, 2 unparseable) — down from
  40 before the canonicalization fix.
* `missing_run`: 2 — no run directory ever created; preserved as a finding,
  not silently dropped (see `status_summary.json`).

---

## Next actions

Phase 1 is done. Candidates for follow-up, not started:

1. Decide whether to act on the Phase-2 recommendation
   (`reports/phase2_plan.md`, Track A) — requires user direction.
2. If continuing: fix context overflow first (§16 of the report) before any
   Phase-2 controller is trained or evaluated on this pilot's distribution.
3. Optional: expand the pilot (more instances) now that the canonicalization
   bug is fixed, if a tighter CI is wanted before committing to Phase 2.
