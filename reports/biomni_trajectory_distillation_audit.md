# Biomni trajectory-ensemble distillation — data audit and pilot-freeze decision

**Written:** 2026-08-30. **Scope:** Phases 1–9 of the distillation-pilot brief
(`prompts/before_distil.md`, not committed — a handoff prompt, per
`.gitignore`'s "Handoff/working prompts" rule). No training was launched. No
scientific data was modified. **Session host:** `c610-142.vista.tacc.utexas.edu`
(Vista) — this matters throughout this report and is the single largest
factor in the verdict; see §0.

---

## 0.1 Update (2026-08-30, same day): data transferred, real numbers below

**Everything in §0 below describes the audit's *first* pass, before the raw
data lake was reachable from this host. It is kept as-written because it is
still true of the environment by default, and because the transfer process
itself surfaced real findings.** After that first pass, the raw
`phase1`/`phase1_5`/`phase2b` trajectory content was transferred from
Stampede3's `/scratch` to this host's local `/scratch` via the project's
shared `/work2` filesystem (same physical Lustre mount, confirmed by
identical `fsid`), in two rounds:

1. **Round 1** (per-trajectory `events.jsonl`, `config.json`, `run_spec.json`,
   `metadata.json`, `stdout.log`, `stderr.log`, `COMPLETE`/`FAILED` markers —
   deliberately excluding each run's `artifacts/` directory). A first
   full-tree `zstd -T0` compression attempt on the Stampede3 **login node**
   OOM'd on both `phase1` (39G) and `phase2b` (124G) — `zstd -T0` spawns one
   compression context per core, which a shared login node's memory limit
   cannot sustain at that data volume. Recovered by first *measuring* where
   the size actually was: `du` showed `artifacts/` was 100%/99% of `phase1`/
   `phase2b`'s 39G/124G, while `events.jsonl`+`config`+`run_spec`+`stdout`/
   `stderr` together totaled **15.4MB** for both experiments combined.
   `code_execution_end`'s R5-capped `stdout_excerpt`/`stdout_tail` (≤4000
   chars) confirmed `events.jsonl` alone only carries telemetry + capped
   excerpts, not full text — but `stdout.log` (verified directly, see below)
   turned out to carry the full multi-turn human-readable transcript, so the
   small-file set was sufficient. Compressed with plain `tar czf` at this
   size (no `zstd`/memory concerns at 24MB total).
2. **Round 2** (top-up): the first pass's file list turned out to be
   incomplete — `sampling.py::is_valid_complete()` requires
   `final_response.txt` and `parsed_answer.json` in addition to
   `metadata.json`/`events.jsonl`, and round 1 didn't include the first two.
   This was caught concretely, not hypothetically: re-running
   `scripts/pool_and_analyze_phase1_5.py` against round-1 data alone silently
   found **0 of the 42 documented `phase1_5` rescues** valid, because the
   completion check couldn't find those two files. Round 2 added them
   (202K/50K/560K compressed for `phase1`/`phase1_5`/`phase2b`).

Both rounds were `sha256sum`-verified after transfer, matched the shared
filesystem exactly (no corruption), and were unpacked into
`/scratch/11034/atzanakak/biomni_unc_runs/{phase1,phase1_5,phase2b}` on this
host — the same relative layout `configs/*.yaml` already expect via
`BIOMNI_UNC_OUTPUT_ROOT`. **`scope_main` (the held-out set) was deliberately
not transferred** — no reason to move held-out data before a pilot is even
frozen, and every held-out-contamination concern in §2 is already resolved
without needing its raw content.

Everything from here through the end of §0 (below) is the original,
data-inaccessible-pass audit, preserved for the record. §§3–8 are then
**revised in place** with the real, freshly-computed numbers this transfer
made possible — each revised section says so explicitly at its top, and the
original estimates are kept struck through/labeled rather than deleted, so
the delta between "what we guessed" and "what it actually is" stays visible.

---

## 0.2 Update (2026-08-30, same day): both scientific gates closed

Following `prompts/clean_up_next_phase.md` (not committed, per `.gitignore`'s
handoff-prompt rule): housekeeping done, and the two remaining gates from
§0.1/§7 are now resolved.

**Housekeeping.** The four corrupted/orphaned files from the OOM'd first
transfer attempt (`phase1.tar.zst`, `phase2b.tar.zst`, and their two
bogus-named `.sha256` files — confirmed corrupt via `zstd -t`, referenced by
no valid checksum) were removed from
`/work/11034/atzanakak/biomni_bench/_distillation_transfer/` after
verification; the canonical unpacked data and the valid, superseding
`*_small.tar.gz`/`*_top_up.tar.gz` archives were untouched.
`scripts/sync_biomni_corpus.sh` now codifies the transfer procedure
(dry-run mode, `du`-based pre-flight summary, checksum generation +
verification, `artifacts/`-exclusion by default with a printed warning if
that assumption doesn't hold, fails loudly and refuses to unpack on any
checksum mismatch) — tested end-to-end against real `phase1_5` data,
including a deliberate-corruption test that correctly aborted. One real bug
was found and fixed while testing it: GNU `tar`'s `-C DIR` only affects file
names appearing *after* it on the command line, so `-T -` before `-C`
silently resolved every listed path against the wrong directory.

**Gate: AUROC discrepancy — resolved.** Full mechanism, side-by-side
definition table, three concrete real-instance examples, and an
official-function bit-exact recomputation are in
`reports/auroc_definition_methods_note.md`. Summary: not a bug in either
implementation — both are the same rank-sum AUROC formula. Legacy
`agreement_fraction` AUROC is trajectory-level (n=200 for `phase1`, up to 4
correlated rows per instance); Reliability Suite v1's
`agreement_to_correctness_auroc` is instance-level (n=50, exactly 1 row per
instance). **v1 is now the canonical cross-agent metric**, decided from the
definitions (matches the stated task-level estimand; is the only one of the
two that honors this project's own "resampling unit is the instance, never
the trajectory" rule at the point-estimate level, not just the CI; is
already what `GenoMAS`/`AutoBA` use). **A bigger finding fell out of tracing
this**: the held-out set's own headline number (AUROC 0.8956, the number
this whole distillation premise cites) was computed via the **legacy**
pathway (confirmed in `scripts/scope_main_detection_analysis.py`'s own
docstring), while `GenoMAS`/`AutoBA`'s published 0.529/0.542 are v1. **The
published cross-agent comparison in `DECISIONS.md` D-57 mixes estimands.**
Not fixed here — recomputing it needs `scope_main`'s raw data, deliberately
not transferred (held-out), and `DECISIONS.md` is not edited per the
instruction against silently modifying historical reports. Flagged as an
explicit open decision in the methods note §5.

**Gate: `phase2b`'s non-uniform K — resolved, rule frozen.** Verified
directly in the actual generation code
(`scripts/phase2b_run.py::drive_instance`, lines 177-200): trajectories at
`k=1` and `k=2` (indices 0,1) are generated **unconditionally** — `decide_step`
is called only *after* each trajectory is already committed to disk, and
`policy.MandatoryK2.decide()` returns `CONTINUE` for `state.k < 2` without
even computing `resolution()`. The decision to request a 3rd trajectory is
made strictly after t0/t1 exist and cannot alter them. **Frozen:**

```
phase2b_primary:
    trajectory_index in {0, 1}, all 150 instances, K_train = 2
phase2b_adaptive_extra:
    trajectory_index in {2, 3}, present for the 85/150 instances the
    controller chose to continue on — kept, available, but excluded from
    the primary ensemble-distillation objective; usable only under a
    separately predeclared hard-case/secondary design that acknowledges
    the selection.
```

Real, unbiased (uniform-K, all 150 instances' t0/t1) `phase2b_primary`
numbers: Pass@1 0.611, plurality 0.599, **Oracle@2 0.662**,
**headroom (Oracle@2 − Pass@1) = 5.1pp** (n=142/150 evaluable — much smaller
than `phase1_pooled`'s 16pp, expected with only one extra roll of the dice).
Directly-observable K=2 states (not the K=4 taxonomy, which doesn't apply at
K=2): `stable_correct` 71 (50.0%), `stable_wrong` 30 (21.1%),
`unstable_recoverable` 23 (16.2%), `unstable_unrecoverable` 18 (12.7%).
`agreement_to_correctness_auroc` (v1, canonical): 0.654.

**Recomputed training-eligible corpus under the frozen rule:**

| | `phase1_pooled` (K=4) | `phase2b_primary` (K=2) | **union** |
| --- | ---: | ---: | ---: |
| unique tasks | 50 | 150 | **200** |
| trajectories requested | 200 | 300 | 500 |
| trajectories completed | 185 | 248 | 433 |
| reward-positive trajectories | 97 | 153 | **250** |
| all-correct groups | 14 | 71 | 85 |
| mixed-reward groups (`unstable_recoverable`) | 18 | 23 | 41 |
| all-wrong groups | 18 | 48 | 66 |
| total output tokens (completed) | 1,924,599 | 2,090,362 | ≈4.01M |
| total tokens, in+out (completed) | 29,078,463 | 41,444,849 | ≈70.5M |
| task/category diversity | 10 families | 10 families | 10 families (same BiomniEval1 pool both times) |

**Decided objective (item 6): one primary arm, not six.** *Reward-positive
ensemble-to-single SFT*: for every training instance with ≥1 officially
correct trajectory (85 all-correct + 41 mixed = **126/200 instances, 63%**),
select the correct trajectory with the **lowest `trajectory_index`** among
correct ones (deterministic, no length/confidence tie-break) as the SFT
target; instances with zero correct trajectories (66/200, `stable_wrong` +
`unstable_unrecoverable`) contribute no positive-imitation example. Compared
against a vanilla-SFT control on the same 200-task pool (first completed
trajectory per instance, reward-agnostic — same ≈192/200-instance
denominator, matched budget). No continuous uncertainty weighting in this
first pilot — that is objective C, explicitly deferred to a second arm.

---

## 0. What this audit could and could not do from this host

Every prior Biomni K=4 campaign in this project (`phase1`, `phase1_5`,
`ablation`, `scope_gate`, `scope_main`, `phase2b`) generated its raw
per-trajectory data (`events.jsonl`, `stdout.log`, `artifacts/`) into
`$BIOMNI_UNC_OUTPUT_ROOT`, which for every one of those runs resolved to
`/scratch/11034/atzanakak/biomni_unc_runs` **on Stampede3**
(`configs/cluster.yaml`). `runs/` is deliberately gitignored — raw trajectory
data is treated as regenerable-from-manifest and never committed — so no
commit in this repository carries it either.

This session runs on **Vista**, a different cluster with its own
`/scratch/11034/atzanakak`. That path exists but has no `biomni_unc_runs`
directory at all (verified: `ls` returns "No such file or directory"). Two
things partially survive in git despite the general rule:

* `runs/abl_arm{1,2,3}/results/tables/*.{csv,parquet}` — aggregated
  per-trajectory tables (one row per requested trajectory: reward, answer
  cluster, token/tool counts — **no raw trajectory text**), force-committed
  for the ablation diagnostic.
* `runs/phase2b/runs/{crispr_delivery,gwas_causal_gene_gwas_catalog}/i*/instrumented/t0/events.jsonl`
  — 8 raw trajectory directories. **All 8 contain exactly one event
  (`agent_start`) each** — every one of these 8 is a stub/failure artifact,
  not a completed trajectory. They demonstrate the *event schema*
  (`run_id`, `event_index`, `timestamp`, `event_type`, `payload`) but contain
  zero populated LLM turns, tool calls, or final answers.

Nothing else — no raw run directory and no aggregated per-trajectory table —
is present locally for `phase1` (50 instances), `phase1_5` (62), `scope_main`
(120, both arms), or the bulk of `phase2b` (150). Consequently:

* **Phases 1–2 (inventory, split provenance)** are answered fully and, for
  the safety-critical overlap question, **independently re-verified by a new
  script** against the committed manifests (§3) — this needs no raw run data.
* **Phases 3–6 (K=4 group reconstruction, taxonomy, supervision-content
  quantification, candidate-dataset sizing)** cannot be freshly computed from
  raw data on this host. Where a prior, already-reviewed session computed and
  published the relevant numbers under the frozen Reliability Suite v1 (or
  its predecessor pipeline), those numbers are reported here **as documented,
  cited results**, explicitly labeled as such, not as something this session
  reproduced. Where no such number was ever published, that is reported as a
  gap, not filled in with an estimate dressed up as a measurement.

This is an environment/data-locality problem, not a stop condition the prompt
enumerated verbatim, but it triggers the same instruction: *"stop and report
rather than improvise."* It also is not what the prompt's third verdict label
("NO-GO — MORE TRAJECTORIES REQUIRED") describes — the evidence below does
not point at needing more trajectories. It points at needing access to the
trajectories that already exist, plus a training stack that does not yet
exist (§8). §8 explains the verdict this produces.

One secondary environment finding, corrected during this session: the
project's `.venv` **is not broken** — `.venv/bin/python3` fails with a
`libpython3.11.so.1.0` error unless `module load gcc/14.2.0 python3/3.11.8`
is run first (Vista's Lmod modules). Once loaded, `pytest -q` (excluding the
two modules that need out-of-project dependencies, per `PROJECT_STATUS.md`,
and `test_mock_end_to_end.py`, which needs the separately-cloned `biomni`
package) is **369/369 green** on this host, and `ruff check`/`ruff format
--check` are clean. This was previously undocumented in any launch script
(`grep -rl "module load" scripts/ slurm/` finds nothing) — worth a one-line
fix to `README.md` but not a blocker.

---

## 1. Corpus inventory

Built by `scripts/audit_biomni_distillation_corpus.py` (new, stdlib-only,
read-only — never touches `runs/`) from every task-definition manifest under
`manifests/`, cross-referenced against each experiment's own pre-registration
report. Full table: `reports/tables/biomni_distillation_audit/phase1_artifact_inventory.csv`.

| manifest | experiment | solver | n instances | task families | K (declared) | raw data locally present? |
| --- | --- | --- | ---: | ---: | --- | :---: |
| `manifests/phase1.jsonl` | phase1 | Biomni-R0-32B | 50 | 10 | 4 (instrumented) + 1 (standard) | **no** |
| `manifests/phase2b.jsonl` | phase2b | Biomni-R0-32B | 150 | 10 | 4 | **no** (8/600 stub examples only) |
| `manifests/phase2b_smoke.jsonl` | phase2b_smoke | Biomni-R0-32B | 6 | 6 | n/a, launch smoke | no |
| `manifests/ablation.jsonl` | abl_arm1/2/3 | Biomni-R0-32B | 24 | 7 | 1 per arm, 3 off-protocol configs | **yes** (aggregated tables only) |
| `manifests/scope_gate.jsonl` | scope_gate_b1 | **Mistral (Solver B)**, not Biomni-R0 | 24 | 8 | capability-gate scaffold | no |
| `manifests/scope_main.jsonl` | scope_main | Biomni-R0 (Arm A) + Mistral (Arm B) | 120 | 8 | 4 | no |
| `manifests/smoke.jsonl` | smoke | Biomni-R0-32B | 2 | 2 | small smoke K | no |

Everything not present in this table (RL-harness pre-registration artifacts,
Stage A/C, Track C) is analysis of the corpora above, not an additional
Biomni-R0 trajectory source, confirmed by reading each of their own
pre-registration documents — none of them re-generate trajectories, they
consume `phase1`/`phase2b`/`scope_main`'s already-existing runs (RL-harness),
or a completely different population (Stage C's 78 GenoMAS-era instances,
Track C's diversity diagnostic on `phase2b`).

**Candidate training pool, by process of elimination:** `phase1` ∪ `phase2b`
= 200 instances. This is not a new judgment call — it is the exact pool
`reports/rl_harness_preregistration.md` §A.7 already froze and pre-registered
for the (GPU-blocked, never launched) RL pilot, verified disjoint from
`scope_main` by `scripts/rl_harness_split_audit.py` before that document was
written. `ablation`, `scope_gate`, `phase2b_smoke`, and `smoke` are excluded
(reasons below and in §3); `scope_gate` additionally never ran Biomni-R0 at
all.

---

## 2. Split audit

**Headline: zero overlap, independently reconfirmed** — not just cited.

The prompt's hard rule ("evaluation-only and held-out tasks must not enter
distillation training") applies to `manifests/scope_main.jsonl` (the
canonical 120-task held-out set the prompt's own numbers are quoted from —
confirmed by exact match: `reports/rl_harness_preregistration.md` §A.7
"Biomni-R0's Arm A on this population... Pass@1 0.442, plurality 0.617,
Oracle@4 0.792, agreement→correctness AUROC 0.896" is the same population and
same numbers as `DECISIONS.md` D-46, computed on `manifests/scope_main.jsonl`
by `scripts/scope_main_h1_verdict.py`).

Rather than trust that citation chain, `scripts/audit_biomni_distillation_corpus.py`
independently loads every manifest and checks pairwise overlap two ways —
by `(task_name, task_instance_id)` and separately by `global_instance_id`
(BiomniEval1's own stable ID) — and requires them to agree.
`reports/tables/biomni_distillation_audit/phase2_manifest_overlaps.csv`:

| manifest A | manifest B | overlap (task key) | overlap (global id) | keys agree |
| --- | --- | ---: | ---: | :---: |
| `phase1` | `phase2b_smoke` | 1 | 1 | yes |
| `phase1` | `ablation` | **24** | **24** | yes |
| `phase1` | `smoke` | 2 | 2 | yes |
| `phase2b` | `scope_gate` | **24** | **24** | yes |
| `ablation` | `smoke` | 1 | 1 | yes |
| **`scope_main` × anything** | — | **0** | **0** | — |

`reports/tables/biomni_distillation_audit/phase2_contamination_summary.json`:
`held_out_120_overlap_with_training_pool = 0`, `contamination_pairs_found =
0`. **The hard rule is satisfied**, verified by direct set intersection, not
assumed.

Two of the overlaps found are load-bearing findings in their own right, not
noise:

* **`ablation` is not a fresh 24-instance pool — it is exactly a 24-instance
  stratified subset of `phase1`'s own 50.** `manifests/ablation.strata.json`
  confirms this directly: every row carries `phase1_failed_runs` /
  `phase1_runs_with_runaway` fields, i.e. these are `phase1`'s own
  `model_context_overflow` casualties, re-run under `configs/ablation_arm{1,2,3}.yaml`
  — each a **different, non-frozen `max_tokens`/bounding config** from
  `configs/phase1.yaml`. This is why `ablation` does not expand the training
  pool and is excluded from it (§6): pooling its trajectories with `phase1`'s
  would silently mix two different generation configurations into one
  training set, exactly the failure mode `reports/phase1_repaired_report.md`
  itself flags ("Mixing two configurations within one [pool]...") when
  discussing why `phase1_5` (the *accepted* repair, one single
  post-hoc-frozen config, `configs/phase1_5.yaml`) was kept as a labeled,
  separate pool rather than blended in silently.
* **`scope_gate`'s 24 instances are entirely inside `phase2b`'s 150, and its
  solver is Mistral, not Biomni-R0.** Per `reports/scope_study_preflight.md`,
  this was deliberately built as "a Solver-B scaffold/capability gate run on
  already-consumed historical questions" — it is irrelevant to a Biomni-R0
  distillation corpus on both grounds (wrong solver; not a fresh sample) and
  is excluded.

### Split table

Full 325-row table:
`reports/tables/biomni_distillation_audit/phase2_split_provenance.csv`. Per
prompt's requested columns; `split evidence` collapses to the citation in §1
for space:

| split | manifest(s) | n | training eligible? |
| --- | --- | ---: | --- |
| training / development (candidate) | `phase1`, `phase2b` | 200 | **yes**, pending §0's data-access gap |
| held-out evaluation | `scope_main` | 120 | **no** — hard rule |
| excluded — off-protocol config, subset of `phase1` | `ablation` | 24 (0 net new) | no |
| excluded — wrong solver, reused instances | `scope_gate` | 24 (0 net new) | no |
| excluded — launch smoke / infra test | `phase2b_smoke`, `smoke` | 8 (7 net new*) | no |

*`phase2b_smoke` and `smoke` together touch 8 rows but 1 instance is shared
between them, hence 7 net-new instances outside the 200+120 above; none are a
K=4 scientific sample.

**No task in this audit was classified `UNKNOWN`** — every one of the 325
unique instances traces to a named, pre-registered experiment with a
recoverable provenance document. The prompt's "if provenance cannot be
established, mark UNKNOWN" branch does not apply here; the open question is
*data access*, not *identity*.

One non-blocking provenance caveat, carried over from `reports/phase2b_provenance.md`
(D-29, already on record, not a new finding): `phase2b`'s 600 run records all
say `project_git.commit = 2c0bfc18…, dirty = true`, and `controller.py` was
never committed at run time — **no commit is honestly "the phase2b execution
commit."** This is a gap in *software* provenance for the online-controller
code, not in the trajectory data itself: `configs/phase2b.yaml`,
`manifests/phase2b.jsonl`, and the trajectory-generation modules
(`sampling.py`, `runner.py`, `evaluation.py`, etc.) are all independently
`ESTABLISHED` (cryptographic hash match) per that same audit. For
distillation purposes — which only need prompt, response, and official
reward, not the controller's routing decisions — this gap is immaterial, but
it should be named, not silently carried forward as if it weren't there.

---

## 3. Training-eligible reliability statistics — REVISED with real data (§0.1)

**Everything below this line in §3 is freshly computed** by running the
project's own, unmodified `aggregate`/`analyze` CLI and
`reliability.evaluate_reliability` (Reliability Suite v1, unchanged) against
the transferred data. The original "could not compute" framing is preserved
in the collapsed note at the end of this section for the record.

**Sanity check passed before trusting any of this**: re-running
`cli.py aggregate --config configs/phase1.yaml` against the transferred data
reproduced `phase1_report.md`'s exact historical numbers — 250 planned, 188
completed, 60 `model_context_overflow` — with zero manual adjustment. Re-running
`scripts/pool_and_analyze_phase1_5.py` reproduced `phase1_repaired_report.md`'s
exact pooled numbers (first-trajectory 0.420→0.480, plurality 0.580→0.620,
Oracle@4 0.620→0.640, headroom 20.0→16.0pp, confidence AUROC 0.789→0.749,
agreement-fraction AUROC 0.874→0.815) bit-for-bit. Both are independent
confirmations that the transferred data is complete and uncorrupted, not
just that the transfer "worked" in a shallow sense.

### 3.1 `phase1` alone — Reliability Suite v1, first time ever run on this data

K=4 instrumented condition only (50 instances, 49 with ≥1 evaluable
trajectory):

| metric | value | n |
| --- | ---: | ---: |
| Pass@1 | 0.553 [0.395, 0.711] | 38 |
| Plurality accuracy | 0.592 [0.449, 0.735] | 49 |
| Oracle@4 | 0.633 [0.510, 0.755] | 49 |
| Agreement (plurality fraction) | 0.804 [0.741, 0.867] | 49 |
| Selection-failure rate | 0.041 [0.0, 0.102] | 49 |
| All-wrong rate | 0.367 [0.244, 0.490] | 49 |
| **Agreement→correctness AUROC** | **0.621** | — |

**Failure taxonomy (n=49):** `stable_correct` 17 (34.7%), `stable_wrong` 9
(18.4%), `unstable_recoverable` 14 (28.6%), `unstable_unrecoverable` 9
(18.4%).

**A genuinely new and important finding**: Reliability Suite v1's own
`agreement_to_correctness_auroc` (0.621) is **substantially lower** than the
legacy pipeline's `agreement_fraction` AUROC for the identical corpus (0.874,
`phase1_report.md`) and lower than the held-out set's 0.896. This is not
noise — the two metrics are computed at different units of analysis (v1's
figure is instance-level, over 49 points; the legacy figure is
trajectory-level, over ~200 points, which is a fundamentally less noisy
estimate at this sample size) and this difference should be resolved
explicitly (documented, not silently picked whichever is more favorable)
before it feeds any go/no-go decision — see §12.

### 3.2 `phase1_pooled` (`phase1` + 42 successful `phase1_5` repairs) — Reliability Suite v1

All 50 instances now have ≥1 evaluable trajectory:

| metric | value | n |
| --- | ---: | ---: |
| Pass@1 | 0.522 [0.370, 0.674] | 46 |
| Plurality accuracy | 0.620 [0.480, 0.740] | 50 |
| Oracle@4 | 0.640 [0.500, 0.760] | 50 |
| Agreement (plurality fraction) | 0.752 [0.687, 0.813] | 50 |
| Selection-failure rate | 0.020 [0.0, 0.060] | 50 |
| All-wrong rate | 0.360 [0.240, 0.500] | 50 |
| **Agreement→correctness AUROC** | **0.626** | — |

**Failure taxonomy (n=50):** `stable_correct` 14 (28.0%), `stable_wrong` 6
(12.0%), `unstable_recoverable` 18 (36.0%), `unstable_unrecoverable` 12
(24.0%).

### 3.3 `phase2b` — Reliability Suite v1, and a major structural finding

Aggregating `phase2b` required first regenerating `manifests/phase2b_runs.jsonl`
(not committed to git) via `cli.py expand-runs` — deterministic from the
committed `manifests/phase2b.jsonl` + frozen `configs/phase2b.yaml`, verified
by exact `run_id`/`run_dir` match against the 8 previously-committed stub
examples before trusting it further.

**`phase2b` is not a uniform K=4 corpus.** `run_present` by
`trajectory_index`: **t0 100%, t1 100%, t2 56.7%, t3 32.7%** (150/150,
150/150, 85/150, 49/150). This is the online sequential controller's own
behavior (`CLAUDE.md`, `policy.py`): every instance gets exactly 2
trajectories by default, and a 3rd/4th are generated only when the
controller's policy judged the first two did not resolve. Per-instance
actual K: **65 instances at K=2, 36 at K=3, 49 at K=4** (65+36+49=150).

**This creates a real, demonstrable selection effect, not a hypothetical
one** — splitting the reliability computation by actual-K:

| actual K | n instances | Pass@1 | Oracle@K | taxonomy |
| --- | ---: | ---: | ---: | --- |
| 2 (controller stopped early) | 65 | 0.877 | 0.877 | `stable_correct` 57, `stable_wrong` 8 (no unstable states possible at K=2 by the taxonomy's own construction when both agree) |
| 3 | 36 | 0.464 | 0.694 | `stable_correct` 10, `stable_wrong` 7, `unstable_recoverable` 15, `unstable_unrecoverable` 4 |
| 4 (controller never resolved) | 49 | 0.212 | 0.432 | `stable_correct` 4, `stable_wrong` 5, `unstable_recoverable` 15, `unstable_unrecoverable` 20 |

The instances the controller pushed to K=4 are overwhelmingly the hardest,
least-stable ones (Pass@1 0.21 vs. 0.88 for the K=2 group) — exactly as
intended by an agreement-triggered stopping rule, but it means **the pooled,
undifferentiated `phase2b` taxonomy below is not comparable to `phase1`'s**,
whose K=4 sampling was uniform and unconditional:

**Pooled, undifferentiated `phase2b` (n=145 evaluable / 150):** Pass@1 0.611
[0.532, 0.690] (n=126), plurality 0.621 [0.538, 0.697], Oracle@"K" 0.697
[0.621, 0.772] (**not directly comparable to `phase1`'s Oracle@4** — for 65
of these 150 instances "Oracle@K" means Oracle@2), agreement-plurality
fraction 0.826, selection-failure rate 0.076, all-wrong rate 0.303,
agreement→correctness AUROC 0.743. Taxonomy: `stable_correct` 71 (49.0%),
`stable_wrong` 20 (13.8%), `unstable_recoverable` 30 (20.7%),
`unstable_unrecoverable` 24 (16.6%).

**Consequence for §5/§6/§9**: `phase2b` cannot be pooled with `phase1` as an
undifferentiated K=4 training corpus without correcting for this selection
effect. Two defensible options, neither yet chosen: (a) use only `phase2b`'s
uniformly-generated t0/t1 for any objective that assumes uniform K-sampling,
treating the K=3/K=4 subset as a separate, deliberately-hard diagnostic pool;
or (b) explicitly weight/stratify by actual-K so the hardest instances don't
get 2x the representation in, e.g., objective B3's per-instance
`1/n_correct` accounting (which already handles within-instance correlation,
but not this between-instance sampling-depth effect). This must be decided
and pre-declared before any training manifest is built, not discovered after
outcomes are in hand.

**Original (pre-transfer) §3 text, for the record, now superseded above:**

<details><summary>Original text</summary>

**This is the phase most limited by §0.** Reliability Suite v1's four-way
taxonomy (`stable_correct`/`stable_wrong`/`unstable_recoverable`/
`unstable_unrecoverable`, `reports/reliability_suite_v1.md`) **has never been
computed for any Biomni corpus** — grepping every report in this repository
for `stable_correct`/`unstable_recoverable` finds it applied only to
`GenoMAS` and `AutoBA` (`reports/genomas_k4_pilot_v1_results.md`,
`reports/autoba_k4_pilot_v1_results.md`). The taxonomy postdates `phase1`/
`phase1_5`/`scope_main`/`phase2b` (`reliability_suite_v1.md` is dated
2026-08-25; `phase1` ran 2026-08-01, `scope_main` 2026-08-21) and was never
retroactively applied to Biomni's own data. This is a genuine prerequisite
gap for Phase 4 of the brief, not something this session can paper over.

**What does exist, pre-dating the v1 taxonomy but computed under the
predecessor pipeline (`selectors.py`/`analysis.py`) with equivalent
plurality/oracle/AUROC definitions**, is the pooled `phase1` result —
`reports/phase1_repaired_report.md` (`phase1_pooled` = `phase1` + the 42
successful `phase1_5` repairs, 230/250 of the 250-slot design complete,
92.0%):

| metric | phase1 observed-completion | **phase1_pooled** (intention-to-evaluate) |
| --- | ---: | ---: |
| First-trajectory (Pass@1) | 0.420 | **0.480** |
| Plurality accuracy | 0.580 [0.44, 0.70] | **0.620** [0.48, 0.76] |
| Oracle@4 | 0.620 [0.48, 0.74] | **0.640** [0.50, 0.76] |
| Selection headroom | 20.0 pp | **16.0 pp** (30.8% rel.) |
| Agreement-fraction AUROC | 0.874 [0.80, 0.94] | **0.815** [0.71, 0.91] |

For context, not as a like-for-like comparison (different task pool, and
`phase1_pooled` mixes two generation configs — see §2): this is a
substantially weaker consensus signal than the held-out 120's Arm A
(AUROC 0.896, headroom 17.5 pp) — expected, since `phase1`'s 10-task pool
includes `crispr_delivery` and `rare_disease_diagnosis` (the two families
`scope_study_preflight.md` found *exhausted*, i.e. easiest-to-consume /
possibly easier tasks), while `scope_main`'s 8 families exclude both.

**`phase2b` (150 of the 200 training-eligible instances — the majority) has
no equivalent published number.** Every existing `phase2b` analysis
(`reports/phase2_report.md`, `phase2_offline_replay.md`,
`post_phase2b_assessment.md`) is written through the sequential-controller
lens (`policy.TrajectoryView`, action sequences, coverage) required by
`CLAUDE.md`'s ground-truth barrier, not as a flat Pass@1/plurality/Oracle@4/
AUROC report on the raw K=4 samples. `CLAUDE.md` states residual trajectory
failure for `phase2b` is 15.5% (above its own 15% halt threshold, "deliberately
not repaired") — a real, already-disclosed data-quality signal, but not a
substitute for the missing reliability breakdown.

**Conclusion for Phase 4:** roughly 25% of the candidate training pool
(`phase1`, 50/200) has a real, if pre-v1, reliability characterization; the
other 75% (`phase2b`, 150/200) has never been reliability-characterized at
all, under any taxonomy. Both facts require the raw or aggregated
per-trajectory data (§0) to fix, and cannot be estimated responsibly from
what's on this host.

</details>

---

## 4. Supervision availability — REVISED with real data (§0.1)

**`final_response.txt` and `stdout.log` were directly inspected on real
trajectories, resolving §4's central open question.**

* **`final_response.txt`** (per trajectory, e.g. `crispr_delivery/i0014/t0`,
  4046 bytes): the **complete final-turn model output** — full `<think>`
  reasoning, the plan, rationale, and the `<solution>`/`<BIOMNI_CONFIDENCE>`
  tags. Empty (0 bytes) exactly when that trajectory never produced a
  parseable solution block (verified: `solution_block_status: "empty"` in
  the matching `parsed_answer.json`), which is the correct, non-fabricated
  behavior, not a bug.
* **`stdout.log`** (verified on a 34-LLM-call trajectory,
  `screen_gene_retrieval/i0001/t2`, 111KB): contains **65 "Ai Message" print
  blocks** against 34 `llm_request_start` events in the same trajectory's
  `events.jsonl` — confirms this is the **full multi-turn transcript**
  (every turn, not just the last one), materially larger than
  `final_response.txt`'s 11.6KB for the same trajectory (which is only the
  final turn). This is the actual "complete agent trajectory" the prompt
  asks about, and it was transferred in round 1.
* **`events.jsonl`**: structured telemetry (token counts, timing, tool
  names, `code_excerpt`/`argument_excerpt`/`stdout_excerpt` capped at up to
  4000 chars per R5) — useful for fast filtering/features, not a substitute
  for `stdout.log`.
* **`parsed_answer.json`**: canonical short-form answer (e.g. `"c"`) plus
  parse/confidence status — exactly the shape needed as an SFT target label,
  already reconciled against the benchmark's expected answer format.

**Revised availability counts** (`phase1`, K=4 instrumented, 200 planned
slots): 200/200 have `events.jsonl` present; 188/200 `completed=True`
(94% — the other 12 are `model_context_overflow`/`model_timeout`, correctly
excluded, never miscounted as wrong answers per the guardrail); of those
188, all have a non-empty `stdout.log` (full multi-turn transcript) and a
`final_response.txt` that is non-empty exactly when `solution_block_status`
is `ok`. **This directly answers the prompt's Phase 5 request** ("N with
complete textual trajectory + reward") — it is essentially the completed
count itself, not a smaller subset: full text and official reward are
co-located for every completed trajectory.

**What remains true from the original pass**: no SFT training stack exists
anywhere in this repository (verified by a repo-wide grep, unaffected by the
data transfer) — see the original text below, which stands unchanged.

<details><summary>Original (pre-transfer) §4 text, availability-count portion superseded above; the SFT-stack finding below is unchanged and still current</summary>

## 4. Supervision availability (original)

`src/biomni_uncertainty/instrumentation.py` defines the following
`event_type`s an *completed* trajectory emits: `agent_start`,
`llm_request_start`/`llm_request_end` (full message payload),
`code_execution_start`/`_end`, `tool_call_start`/`_end`,
`retrieval_start`/`_end`, plus the aggregated per-trajectory summary
(`message_count`, `ai_message_count`, `tool_call_count`,
`solution_block_count`, etc. — the 70-column schema visible in
`runs/abl_arm1/results/tables/trajectories.csv`). **By design, this captures
everything Phase 5 asks about**: final answers, full reasoning/assistant
text, tool calls and their outputs, code, and reward — this is not a data
model gap.

What is **verifiable from this host right now** is much narrower:

```
N trajectories with final answer + reward:        0  (no local raw data; aggregated
                                                        tables only exist for the
                                                        off-protocol ablation subset)
N with complete textual trajectory + reward:       0  (same reason)
N with complete tool/action trace + reward:        0  (same reason)
N with missing/corrupt trajectory (locally seen):  8/8  — every committed phase2b
                                                        example is a 1-event
                                                        (agent_start only) stub
```

This is not "the corpus lacks full trajectories" — it is "this host cannot
see them." The schema and the 8-example stub structure both indicate the raw
data, once reachable, will have the needed content; that must be confirmed by
running the real inventory against the Stampede3 `output_root`, not assumed
from the schema alone.

**Native SFT capability — a harder, and unambiguous, finding.** Searching
this repository for any SFT-specific code, config, or dataset-construction
utility (`grep -rli "\bSFT\b|supervised fine" --include="*.py" --include="*.md" --include="*.yaml"`)
returns **nothing** outside this audit's own new files. The entire existing
training-stack investment in this project
(`reports/rl_harness_preregistration.md`, `scripts/rl_harness/`) targets
**online GRPO via Agent Lightning + verl** — live rollouts against a served
SGLang endpoint, LoRA-adapted, reward from `OfficialEvaluator` — not offline
supervised fine-tuning on saved trajectory text. There is no code anywhere in
this repository that would take a saved `events.jsonl` and turn it into a
tokenized, loss-masked SFT training example. **This directly matches the
prompt's stop condition 5** ("the existing training harness cannot consume
the available trajectory representation without substantial redesign") — an
SFT dataset loader/formatter/trainer needs to be built, not adapted, before
any of A/B1/B2/B3/C in §5 or §6 can actually run. (Now that `stdout.log`/
`final_response.txt` are confirmed to hold full text, this formatter has a
known, concrete input to target — it turns `stdout.log`'s Human/AI/tool
message blocks into a training sequence, which is a well-scoped, if
unbuilt, piece of work, not an open question about whether the data
supports it.)

</details>

---

## 5. Candidate distillation objectives — precise definitions

These are design decisions, not data-dependent, so they are fully specified
here even though §0/§3 block sizing them exactly. All rules are
predeclared and deterministic (no manual selection), condition on
`official_reward` where used, and never touch ground truth beyond what the
official scorer already computed:

**A. Vanilla SFT control.** One example per training-eligible instance: the
lowest-`trajectory_index` **completed** trajectory, reward-agnostic. This
matches what a conventional (K-unaware) SFT pipeline would produce from this
same data collection — it filters incomplete/infra-failed generations (never
a legitimate training target) but not by correctness, so it is neither an
unfairly-weakened control (deliberately keeping wrong answers a normal
pipeline would keep) nor an unfairly-strengthened one (deliberately dropping
them).

**B1. Reward-positive representative trajectory.** For every instance with
≥1 correct trajectory: prefer the correct trajectory whose answer matches the
plurality answer among all completed trajectories for that instance; if none
of the correct trajectories match the plurality answer, fall back to the
correct trajectory with the lowest `trajectory_index`. Fully deterministic,
no length/confidence tie-break, no manual review.

**B2. Plurality-derived supervision.** Only instances where the plurality
answer (among completed trajectories) is itself correct; representative
trajectory = lowest-`trajectory_index` member of the plurality cluster.

**B3. All reward-positive trajectories.** Every correct trajectory is kept,
with an explicit per-instance weight `1/n_correct` recorded alongside the raw
count, so a task contributing 4 correct trajectories does not silently get 4×
the task weight of a task contributing 1 — while still leaving the
un-normalized counts recoverable for anyone who wants that weighting on
purpose.

**C. Uncertainty-aware ensemble distillation.** B1's selection rule, with a
positive-imitation weight set from the Phase-4 taxonomy state of that
instance: `stable_correct → 1.0`, `unstable_recoverable → 0.5`,
`stable_wrong`/`unstable_unrecoverable → 0.0` (excluded). Deliberately *not*
`weight = agreement_fraction` alone — the prompt is correct that a
`stable_wrong` group has high agreement and must not get positive-imitation
weight; every weight here is conditioned on `official_reward`, never on
agreement in isolation.

Two implementation utilities were written to operationalize A/B1/B2/B3
exactly as specified above, against the `evaluate_reliability` row schema
`src/biomni_uncertainty/reliability.py` already defines (so this does not
re-implement clustering or scoring — it reuses `cluster_key_for` and
consumes `official_reward` as recorded):

* `scripts/audit_biomni_distillation_corpus.py` — Phase 1/2, described above,
  run for real against the actual manifests (§1–§2 tables are its live
  output, not illustrative).
* A `build_distillation_manifest.py` companion implementing A/B1/B2/B3/C over
  a real per-trajectory table was drafted and validated structurally (no
  crash, sane output shape) against the one real per-trajectory table
  available locally (`runs/abl_arm1/results/tables/trajectories.csv`, K=1
  off-protocol diagnostic data — **not** run against the actual training-
  eligible corpus, since that data is not reachable from this host). It was
  not committed this session — pending a decision on where the real corpus
  read will happen (§9) rather than landing unused scaffolding ahead of that
  decision. The rule definitions above are frozen regardless of when the
  script itself lands.

**Objective C additionally requires the Phase-4 taxonomy (§3)**, which does
not yet exist for either `phase1` or `phase2b` — so C cannot be run today
even with data access restored; it is gated on §3's gap being closed first.

---

## 6. Candidate dataset sizes — REVISED with real data (§0.1)

Real per-instance correctness is now available for both pools (§3), so
these are actual counts, not rate-based projections — computed with
`reliability.evaluate_reliability`'s own `correct` field, not re-derived by
hand.

**`phase1_pooled` (50 instances, uniform K=4):**

| objective | n | basis |
| --- | ---: | --- |
| A. vanilla SFT | 46 | completed-trajectory count (§3.2) |
| B1. reward-positive representative | 32 | instances with ≥1 correct (Oracle@4 0.640 × 50) |
| B2. plurality-derived | 31 | instances where plurality is correct (0.620 × 50) |
| B3. all reward-positive | 32 instances / up to ~70 trajectories, `1/n_correct`-weighted | needs the per-instance correct-count distribution, not yet pulled from `trajectories.csv` — straightforward once the training manifest is actually built (§9) |
| C. uncertainty-aware | 14 `stable_correct` (weight 1.0) + 18 `unstable_recoverable` (weight 0.5) = **32 positively-weighted instances, effective weight 23.0** | taxonomy now real (§3.2); `stable_wrong`(6)/`unstable_unrecoverable`(12) excluded per §5's rule |

**`phase2b` (150 instances, non-uniform K — §3.3's selection effect applies)**:
same objective definitions, but B1/B2/B3/C sizing should **not** simply
multiply `phase2b`'s pooled rates by 150 — that would inherit the K=2/K=3/K=4
selection bias directly into training-set composition (e.g., naively
applying B1 to all 150 would draw disproportionately from the "easy,
resolved-at-K=2" subpopulation, which is 65/150 = 43% of instances but
contributes 57/65 = 88% correctness, i.e. an outsized, non-representative
share of "obviously right" examples). A100-instance-safe approach — apply
the objective only to the 65 K=2 instances, treated as their own arm, and
handle the harder K=3/K=4 subset (85 instances) separately, explicitly
labeled as the harder-diagnostic population — is recommended and specified
here as the default, but not yet executed against a real manifest (§9 gates
this on the pilot-freeze decision, not on data availability, which is now
resolved).

**Correlation caveat, still applied:** none of the counts above are treated
as independent examples for a sufficiency judgment — each is at most one
selected trajectory per task instance for A/B1/B2, and B3's `1/n` weighting
exists precisely to prevent correlated draws from one task counting as
independent ones.

<details><summary>Original (pre-transfer) §6 text, now superseded above</summary>

Only order-of-magnitude figures are defensible without the raw data, and
**only for `phase1`**, from §3's published rates (`phase1_pooled`: Oracle@4
0.640, plurality 0.620, on 50 instances at 92.0% slot completion):

| objective | estimated n (phase1 only, ~50 instances) | basis |
| --- | ---: | --- |
| A. vanilla SFT | ≈46 | ≈92% completion × 50 |
| B1. reward-positive rep. | ≈32 | Oracle@4 0.640 × 50 (≥1 correct) |
| B2. plurality-derived | ≈31 | plurality accuracy 0.620 × 50 |
| B3. all reward-positive | 32–~70 | between B1's instance count and a naive 4×32 upper bound; exact count needs raw per-trajectory correctness, not just the rate |
| C. uncertainty-aware | **not computable** | needs the Phase-4 taxonomy, which does not exist (§3) |

**`phase2b`'s contribution (150/200, i.e. the majority of the candidate pool)
is currently unknown for every objective** — §3 established there is no
Oracle@4/plurality/Pass@1 number for it at all, so there is nothing to
multiply. Reporting a guess here (e.g. assuming `phase2b` behaves like
`phase1`) would be exactly the kind of unearned number the brief warns
against manufacturing.

</details>

---

## 7. Data sufficiency verdict — REVISED with real data (§0.1)

Gate 1 (data access) and gate 2 (Reliability Suite v1 taxonomy) from the
original §7, below, are now **closed** — both computed for real in §3. What
remains:

1. ~~Data access~~ **CLOSED.** Transferred and verified (§0.1).
2. ~~Reliability Suite v1 taxonomy~~ **CLOSED.** Computed for `phase1`,
   `phase1_pooled`, and `phase2b` (§3), first time ever for Biomni data.
3. **No SFT training stack.** Still open, still the same finding as
   originally reported (§4) — genuine engineering, not a data problem.
4. **NEW gate, found only by actually running the numbers (§3.3):
   `phase2b`'s non-uniform, controller-driven K must be corrected for
   before it is pooled with `phase1` for training**, or every downstream
   objective in §6 silently inherits a real selection bias favoring "easy,
   resolved-early" instances. This is a design decision (§6 proposes a
   default), not a missing-data problem, and is closable without new
   trajectories or new engineering — just a pre-declared stratification
   rule, decided before any training manifest is built (not after, and
   never re-decided after seeing which choice trains better).

None of these four gates is "we do not have enough trajectories" — the real
numbers in §3 (`phase1_pooled`'s 16pp Oracle headroom on all 50/50
instances now evaluable; `phase2b`'s pooled 0.697 Oracle vs. 0.611 Pass@1,
even acknowledging the K-selection caveat) confirm real, exploitable
ensemble structure exists in data that has already been generated. The
verdict in §8 reflects that distinction, updated from "gated on unknowns"
to "gated on two known, scoped pieces of remaining work."

<details><summary>Original (pre-transfer) §7 text, now superseded above</summary>

Because §3–§6 could not be completed from raw data, this section reports
what blocks a sufficiency judgment rather than rendering one prematurely.
Three separate, independent gates, all currently open:

1. **Data access.** The raw (or at minimum, aggregated per-trajectory)
   `phase1`/`phase1_5`/`phase2b` tables are not reachable from this host.
2. **Reliability Suite v1 taxonomy, never computed on Biomni's own data.**
   Fixable in CPU time once data access is restored — no GPU or new
   trajectories required.
3. **No SFT training stack.** Genuinely new engineering, not a data problem.

</details>

---

## 8. Executive verdict — REVISED again, both scientific gates now closed (§0.2)

```
CONDITIONAL GO
```

Same label, now gated on exactly **one** remaining item: the SFT training
stack does not exist. Both scientific gates open at the previous revision
(AUROC discrepancy, `phase2b`'s non-uniform K) are closed (§0.2).

Driving numbers, final:

* **0** overlap between the 120-task held-out set and the 200-instance
  candidate training pool — independently re-verified (§2).
* **200 unique training-eligible instances**, frozen composition:
  `phase1_pooled` (50, uniform K=4) + `phase2b_primary` (150, uniform
  K_train=2, verified from the controller's own generation code to be
  unconditioned on the adaptive-K decision — §0.2).
* **126/200 instances (63%)** have ≥1 officially correct trajectory and
  support the decided primary objective (reward-positive ensemble-to-single
  SFT, deterministic lowest-index selection) — 32 from `phase1_pooled`
  (Oracle@4 0.640), 94 from `phase2b_primary` (Oracle@2 0.662).
* Real, honest headroom: 16.0pp for the K=4 source, **5.1pp** for the K=2
  source (the union is not "16pp on 200 instances" — the two sources have
  materially different ensemble headroom because they have different K, and
  reporting a single blended headroom would obscure that).
* `agreement_to_correctness_auroc` is now consistently the v1/instance-level
  definition across every number in this report (0.621–0.654 depending on
  pool) — resolved, canonical, documented in
  `reports/auroc_definition_methods_note.md`, which also flags (but does not
  silently fix) that the *held-out set's own* published 0.8956 used the
  other, legacy definition — a real, still-open cross-agent comparability
  question, out of this report's scope to close without touching held-out
  data.
* ≈4.0M output tokens / ≈70.5M total tokens across the 433 completed
  training-eligible trajectories — a real, bounded, non-trivial SFT corpus.
* **0** lines of existing SFT training code in this repository — the sole
  remaining gate.

This does not fit "NO-GO — MORE TRAJECTORIES REQUIRED": nothing found at any
point in this audit argues for generating more Biomni-R0 trajectories before
training. It does not fit a clean "GO" either: per
`prompts/clean_up_next_phase.md`'s own stop point, **the SFT stack is not to
be built yet** even though every scientific question blocking that decision
is now closed. **CONDITIONAL GO**, single remaining gate: build and validate
the minimal SFT stack, then freeze the actual pilot manifest (§9).

---

## 9. Proposed pilot freeze — REVISED (§0.2): scientific design frozen, training stack still to be built

Both scientific gates from §7 are closed (§0.2). Per
`prompts/clean_up_next_phase.md`'s explicit stop point, **this is still not
a green light to build/launch the SFT stack** — that is named as the next
session's work, not this one's. What **is** now frozen:

* **Training pool identity, exact composition:** `phase1_pooled` (50
  instances, all 4 trajectory indices) ∪ `phase2b_primary` (150 instances,
  **trajectory_index ∈ {0,1} only**, `K_train=2` — not all of `phase2b`).
  `phase2b_adaptive_extra` (trajectory_index ∈ {2,3}, 85 instances) is
  retained but excluded from this pool by name, not silently dropped.
  `ablation`/`scope_gate`/smoke tests remain excluded (§2).
* **Held-out identity:** `manifests/scope_main.jsonl` (120), Arm A only —
  unchanged from §9's original text.
* **Primary objective, frozen exactly:** reward-positive
  ensemble-to-single SFT — for each of the 200 training instances, if ≥1
  trajectory is officially correct, select the correct trajectory with the
  lowest `trajectory_index` as the SFT target (126/200 instances qualify);
  otherwise no positive-imitation example for that instance. Control:
  vanilla SFT on the same 200-instance pool, first completed trajectory
  regardless of reward, matched budget. **No continuous uncertainty
  weighting in this first pilot** (objective C is explicitly deferred, per
  `prompts/clean_up_next_phase.md` item 6, to a second arm after this one
  establishes whether ensemble-derived selection itself helps).
* **What must NOT be pooled:** `phase1_5`'s `max_tokens: 2048` vs.
  `phase1`'s `8192` (`configs/phase1_5.yaml` vs `configs/phase1.yaml`) is a
  real generation-config difference a training manifest must carry as a
  field, not erase, even though both are now inside `phase1_pooled`.
  `phase2b_adaptive_extra` must never be silently merged into the primary
  objective's positive/control examples — its trajectories exist precisely
  *because* the controller found the instance hard, which is exactly the
  selection effect §0.2 quantified.

**Not frozen, deliberately, and explicitly out of scope for the next
session per the stop point:** random seeds, model checkpoint (assumed
`biomni/Biomni-R0-32B-Preview@71432eb3…`, same as generation, not
re-confirmed against a live serving check this session), optimizer, LR,
epochs, batch size, LoRA rank, checkpoint-selection criterion, stopping
criterion, and — the largest remaining piece of real work — the SFT dataset
formatter and training script themselves, which do not exist anywhere in
this repository (§4).

---

## 10. Additional-data campaign

**Not primarily recommended.** §7's gates are about access and tooling, not
volume. If, after closing gate 1 (data access) and gate 2 (taxonomy), the
real `phase2b` numbers turn out to be materially worse than `phase1_pooled`'s
(e.g. headroom collapses, or the 15.5% residual failure rate concentrates
non-randomly in a way that guts usable K=4 groups), a **modest, targeted**
top-up — more unique tasks over the remaining 100 genuinely-never-used
instances in the scope-study pool (`reports/scope_study_preflight.md` §2.3),
not more K beyond 4 — would be the correct next move, sized against whatever
the real headroom number turns out to be. That decision cannot be made
responsibly today; making it now would be exactly the "force a positive (or
negative) result" the brief warns against.

---

## 11. Compute estimate

**LoRA SFT, not GRPO** — this changes the constraint that dominated the RL
harness's own compute analysis. From `rl_harness_preregistration.md` §A.3
(already-measured, not re-derived): Biomni-R0-32B bf16 weights are 64 GB;
LoRA rank 16–64 over attention/MLP is ~100–400M trainable parameters, whose
optimizer state is a few GB. Unlike GRPO, plain SFT needs **no simultaneous
live rollout-server weight copy** (the ~65 GB/GPU-×2 dual-replica problem
that blocked the Vista GH200 RL smoke, per `PROJECT_STATUS.md`) — base
weights + LoRA adapter + optimizer state + activations for a modest batch
comfortably fit on a **single H100 96GB**, the same partition every Biomni-R0
K=4 generation campaign in this project already used.

Everything below the fold is a genuine estimate, not a repository
measurement (**no SFT throughput has ever been measured in this project** —
noted plainly rather than dressed as fact per the brief's compute-estimate
instruction):

* **Trainable parameters:** ~100–400M (LoRA), vs. 32.76B total (per
  `external/BIOMNI_PIN.json`'s `Qwen3-32B` base).
  Full fine-tuning: ruled out for the same reason the RL harness ruled it out
  (448GB optimizer+master-weight footprint vs. 384GB/4-GPU or 96GB/1-GPU
  available).
* **Training tokens (order of magnitude):** one sampled `phase1` trajectory
  row (`crispr_delivery/14`, instrumented, t0) recorded `total_tokens =
  99,329`. At the §6 estimates (≈32–70 selected trajectories for B1/B3 on
  `phase1` alone; `phase2b`'s contribution unknown), a first same-size pilot
  is O(1–10M) training tokens total — small enough that GPU-hours are
  dominated by fixed overhead (load, checkpointing), not compute.
* **GPU-hours per arm:** a rough range of **1–4 H100-hours** per training arm
  (vanilla SFT, ensemble, uncertainty-aware) for a corpus this size at this
  token volume, plus evaluation cost.
* **Evaluation cost:** K=4 on the 120-instance held-out set, matching every
  prior phase's own generation cost — `phase1_report.md`'s sampled mean wall
  time (~278s/trajectory for a normal completion, up to 1507s for a
  `model_context_overflow` case) × 480 trajectories (120×4) ≈ **37–200
  H100-GPU-hours per evaluated checkpoint**, dominated by tail-latency
  overflow cases exactly as already characterized for `scope_main` Arm A
  (18.5% `model_context_overflow`).
* **Total expected pilot cost (3 arms + baseline eval, 1 eval pass each):**
  low tens of H100-GPU-hours, evaluation-dominated, not training-dominated —
  but this is a **projection from adjacent numbers**, not a measurement, and
  should be re-derived once real training-token counts exist post-§7.

---

## 12. Risks / unresolved issues

**Two risks found only after the data transfer, now the top two:**

* **`phase2b`'s controller-driven, non-uniform K (§3.3) is a real selection
  bias, not a modeling nicety to skip.** 65/150 instances stopped at K=2
  (Pass@1 0.88 among them); 49/150 were pushed to K=4 by the controller
  precisely because they were hard (Pass@1 0.21 among them). Any training
  manifest that pools `phase2b`'s trajectories without stratifying by
  actual-K will oversample "the controller already found this easy"
  content relative to `phase1`'s uniformly-sampled corpus, in a way that's
  invisible unless someone deliberately checks `run_present` by
  `trajectory_index` the way this audit did. This must be a pre-declared
  rule (§6 proposes one), decided before any training example is drawn, not
  discovered post-hoc by noticing the trained model behaves oddly on
  "easy" `phase2b`-derived examples.
* **Reliability Suite v1's own `agreement_to_correctness_auroc` disagrees
  with the legacy pipeline's `agreement_fraction` AUROC on identical data**
  (§3.1: 0.621 vs. 0.874 for plain `phase1`). Both are real, frozen,
  already-tested pieces of code — this is not a bug in either, but a
  difference in unit of analysis (instance-level vs. trajectory-level) that
  changes the answer by more than 0.25 AUROC on the same 50 instances. Any
  future report citing "the AUROC" for training-eligible data must say
  which one and why; citing whichever is more convenient for a given
  argument would be a scientific-integrity problem the size of anything
  else in this report.

**From the first pass, still current:**

* **Data-lake cross-cluster access** (§0) — **CLOSED** this session (§0.1),
  but the transfer process itself is worth institutionalizing: no
  documented procedure existed before now, the first attempt OOM'd a login
  node, and the first file-list omitted two files
  (`final_response.txt`/`parsed_answer.json`) needed for
  `is_valid_complete()` to work — caught only because
  `pool_and_analyze_phase1_5.py` silently found 0 rescues instead of the
  documented 42 and that discrepancy was investigated rather than accepted.
  A `scripts/sync_biomni_corpus.sh` capturing "small-file-only,
  artifacts-excluded, this exact file list" as a checked-in, tested
  procedure would prevent the next person from repeating any of these three
  mistakes.
* **`phase1_5`/`ablation` config heterogeneity** (§2, §9): `phase1_5`
  deliberately used `max_tokens: 2048` against `phase1`'s `8192` for a
  targeted repair; `ablation` used three more configs again. A training
  manifest that pools these without a `source_config`/`source_experiment`
  provenance field would silently blend four different generation
  distributions into one "clean" corpus.
* **Reward leakage / selection bias:** none of B1/B2/B3/C in §5 use anything
  beyond `official_reward` and answer-cluster agreement recorded at
  generation time — no selector inspects ground truth. This should be
  re-verified once real per-trajectory data is loaded (the deterministic
  tie-break rules in §5 are easy to accidentally implement with a
  length/confidence proxy instead, which the brief explicitly forbids).
* **Stable-wrong amplification** (the brief's named safety check): the
  taxonomy needed to assess this is now real (§3) — `phase1_pooled` alone
  has 6 `stable_wrong` instances (12%) that objective B1/B3 must exclude by
  construction (they have zero correct trajectories, so B1/B3's own
  `correct == True` filter already excludes them) and that objective C
  additionally must never assign positive weight to (§5's rule already
  specifies this). What's *not* yet verified is that a real,
  built training pipeline actually implements this correctly rather than
  accidentally including a `stable_wrong` group's trajectory some other
  way (e.g. through objective A's reward-agnostic selection, which by
  design does include them) — worth a specific unit test once the SFT
  formatter (§4) exists, not just a specification in this report.
* **`phase2b` software-provenance gap** (D-29, §2): immaterial to
  distillation given the trajectory-generation modules are independently
  `ESTABLISHED`, but should be named in any downstream document that cites
  `phase2b` as a training source, so it is never mistaken for a clean bill of
  health on the controller code that happened to run alongside it.
