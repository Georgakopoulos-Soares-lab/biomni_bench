# AutoBA K=4 pilot v1 — preregistration (LAUNCHED, one task substitution)

## Amendment (2026-08-29, after launch, before any valid trajectory)

The campaign was launched from this preregistration, then **stopped after
~9.5 hours** when the first four tasks' results were inspected: every one of
the 16 trajectories run so far had `completed=false`, `official_reward=0.0`,
`failure_class=timeout`, with **zero attempted artifacts**. Root cause: this
preregistration's audit (`reports/autoba_tool_provisioning.md`) checked
whether each task's *grading* criteria required an unavailable tool, but
never checked whether each task's **data-generation step**
(`tests/<domain>/<test_id>/data/generate_data.py`) does — and none of the 12
frozen tasks except the already-admitted `assembly-001` had ever had their
`generate_data.py` run, so 11 of 12 task workspaces had no input data at all.
This was an engineering oversight in preparing the launch, not a scientific
result about AutoBA; the 16 affected trajectories carry no information about
AutoBA's reliability and are excluded from the campaign, archived (not
deleted) at
`/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829_INVALID_missing_data_20260829/`
for the record. The original manifest is left untouched (its SHA-256 above
still verifies); this correction is recorded in a separate amendment
manifest,
`/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829_amendment_01.json`
(SHA-256 `97b400c98c9ad8ebf31e53e5fb8b557950d1ac1fdd89adcb159dc1468d6a52cd`),
never by editing the frozen artifact in place.

Auditing all 34 tasks' `generate_data.py` scripts (not just the 12 selected)
found exactly one genuinely infeasible task in the frozen panel:
**`chip-seq/chipseq-001`**, whose generator requires `samtools`, `bedtools`,
and `HOMER` (none installed, no conda/mamba path — same gap already
documented in `reports/autoba_tool_provisioning.md` for the *grading* axis,
now also true for *data generation*) to build a multi-caller ENCODE-derived
ground truth. Internet access itself works from this node and `curl` is
present, so a task needing only a network download (`chip-seq/chipseq-003`,
GENCODE annotations, "Python only") is not blocked by this gap. No other
task among the 34 needs network access or an external binary at data-
generation time — confirmed by inspecting every `generate_data.py`'s
docstring/requirements and grepping for download/subprocess calls, not
inferred.

**Correction, applying the original selection rule mechanically to the
corrected eligible set** (`{assembly-001, chipseq-001}` excluded instead of
just `{assembly-001}`): chip-seq's first-pass pick (no basic-tier task
remains after excluding chipseq-001, same fallback already used for
genome-assembly) becomes `chipseq-002` (was previously the domain's
second-pass pick); chip-seq's second-pass pick becomes `chipseq-003` (next
alphabetically eligible non-basic task after `chipseq-002`). No other
domain's pick changes. The corrected panel is reflected in the task table
and manifest below; `scripts/run_autoba_k4_pilot_v1.sh` was updated to match
before relaunch. See `DECISIONS.md` D-56 for the full record, per this
project's standing rule that a post-freeze correction is documented as a
change, never edited away silently.

`generate_data.py` was then run once for all 12 corrected-panel tasks
(deterministic setup, not a source or scorer change — the same category of
action already taken for `assembly-001` during admission), verified against
each task's declared `context.data_files`, before relaunching.

---

Status: **`LAUNCHED_20260829_AMENDED`**. Explicit operator approval to launch
was given 2026-08-29 (referencing commit `8f0fc9b` and the manifest SHA-256
below). This document, plus the machine-readable manifest at
`/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829_preregistration_manifest.json`
(SHA-256 `6709a7762512820e3073cfe0002c0be9f56596acddd79b5f4eecf29caeb38579`),
froze every protocol parameter before any confirmatory-campaign execution,
per instruction. One task substitution was made post-launch, before any
valid trajectory ran — see the Amendment section immediately below.

## Why this pilot exists

`reports/autoba_admission.md` closed out AutoBA admission (K=1 score 1.000,
tiny K=4 smoke 4/4 correct/agreeing) as the project's third distinct
biomedical agent, but flagged three prerequisites for a scientific campaign:
a Reliability Suite v1 importer, token accounting, and early-completion
detection. `prompts/autoba_reliability.md` asked for those three, an
environment audit, and a frozen 12-task x K=4 preregistration before any
confirmatory trajectory runs — mirroring exactly how the GenoMAS K=4 pilot
was staged (`reports/genomas_k4_pilot_v1_preregistration.md`).

## Engineering prerequisites completed (this pass)

1. **Reliability Suite v1 schema mapping** — `src/biomni_uncertainty/adapters/autoba.py`
   (`autoba_row`, `answer_cluster_key`, `classify_autoba_failure`) plus the
   campaign runner `scripts/run_autoba_k4_reliability.py`, mirroring
   GenoMAS's runner-script pattern rather than a separate importer class.
   `answer_cluster_key` canonicalizes each trajectory from the native
   grader's own per-criterion `details` strings (no ground truth, no new
   free-text parsing) — see the module docstring for why this is safe and
   sufficient. `src/biomni_uncertainty/reliability.py`'s metric definitions
   are unchanged.
2. **Token accounting** — `scripts/autoba_biotaskbench_agent.py`'s
   `local_vllm_client` now wraps `chat.completions.create` to record
   `response.usage` on every call (never fabricating a count when usage is
   unavailable — `aggregate_token_usage`), flushed to
   `<workspace>/token_usage.json` both on normal completion and on
   SIGTERM (early termination), via a signal handler installed in `main()`.
3. **Early-completion detection** —
   `biomni_uncertainty.adapters.autoba.run_with_early_completion` +
   `workspace_fingerprint`, run from the campaign script (bioTaskBench's own
   `harness/runner.py::_run_agent_command` implements the same poll/
   terminate mechanism but never wires it up for its own `--agent-cmd` path
   — this is the "equivalently narrow harness-level mechanism" the prompt
   permits as an alternative). `workspace_fingerprint` snapshots
   `(path, size, mtime_ns)` for the task's declared output file(s) only
   (never `expected/`); a trajectory is judged done when that snapshot is
   non-empty and unchanged across consecutive polls for `done_stable_seconds`.

   **Two real bugs were found and fixed against a live trajectory before
   this preregistration was written** (not left as known gaps):
   - Bare file existence (bioTaskBench's own `grader.detect_attempted`) is
     not a safe completion signal: a live run terminated after 60s having
     only written a placeholder later meant to be overwritten. Fixed by
     requiring the fingerprint to be *unchanged*, not merely present.
   - A generic `file_check` criterion's loose glob (`*.tsv`) matched an
     incidental file while the actual scored deliverable (referenced by an
     exact `target_file` on a different criterion) had not been created —
     terminating early at score 0.1. Fixed by preferring exact
     `target_file` entries over pattern globs, and requiring *every*
     declared target file to exist (all-or-nothing), not just one.

   Both fixes are covered by regression tests
   (`tests/test_adapters_autoba.py`) reproducing the exact failure shapes
   with real subprocesses, not mocks.

## Verification smoke (not new scientific evidence)

A post-fix K=1 re-run of the already-admitted `assembly-001` task validated
the full pipeline end-to-end against the live vLLM endpoint:
`completed=true`, `official_reward=0.5`, `input_tokens=108756`,
`output_tokens=18475`, `n_model_calls=97`, `timed_out=true` (the agent kept
revising its output past the 1800s external timeout and never stabilized —
early-completion correctly did **not** fire on a non-converged trajectory,
falling back to the timeout exactly as the mechanism is supposed to).
`evaluate_reliability()` produced a well-formed report from the resulting
row. Evidence:
`/scratch/11034/atzanakak/genomas_admission/autoba_admission/verify_reliability_v1_smoke_20260828_221823_v7/`.
This reuses already-spent admission ground (`assembly-001`) and is engineering
validation, not a confirmatory-campaign result.

## Environment provisioning

`reports/autoba_tool_provisioning.md`. Summary: no `conda`/`mamba`/`R` on
this node; seven pip-only bioinformatics packages installed and verified
this session (pysam, scikit-allel, MACS3, QUAST, NanoStat, Scanpy, Squidpy)
into the execution venv (`/scratch/11034/atzanakak/genomas_admission/venv`).
No task is excluded from the candidate pool on infeasibility grounds — every
task's grading criteria score output-file structure/values, never tool
provenance (the same property already established for the admitted
`assembly-001` task), so an unavailable named tool (R, HOMER, MEME suite,
bedtools/samtools/VCFtools/PLINK as standalone binaries) means AutoBA would
need a Python-native substitute, not that the task is unexecutable. Panel
selection below prefers tasks that exercise a *confirmed-installed* tool for
the "real bioinformatics binary" diversity axis.

## Task selection

**Excluded:** `genome-assembly/assembly-001` (spent on admission).

**Selection rule** (mechanical, pre-outcome, never conditioned on any AutoBA
run — see the manifest's `task_selection_rule` for the exact wording):

1. Sort the 10 bioTaskBench domains alphabetically.
2. First pass: one task per domain, the alphabetically-first eligible task
   at `difficulty=basic` (genome-assembly has none left after excluding
   assembly-001, so its alphabetically-first eligible task at any difficulty
   is taken) — 10 tasks.
3. Second pass: continuing the same alphabetical domain cycle for 2 more
   slots (chip-seq, then crispr-screens), take the alphabetically-first
   remaining task at `difficulty != basic` in that domain, to add difficulty
   diversity without hand-picking a specific task.

## The 12 tasks

| # | Task ID | Difficulty | Diversity axis |
| - | --- | --- | --- |
| 1 | `chip-seq/chipseq-002`\* | intermediate | alignment/mapping; de novo motif discovery, distinct output structure |
| 2 | `crispr-screens/crispr-001` | basic | sequence processing |
| 3 | `genome-assembly/assembly-002` | intermediate | genome assembly |
| 4 | `long-read-sequencing/lrs-001` | basic | sequence processing; real tool (NanoStat) |
| 5 | `metabolomics/metab-001` | basic | tabular/statistical bioinformatics |
| 6 | `methylation-analysis/meth-001` | basic | tabular/statistical bioinformatics |
| 7 | `multi-omics-integration/moi-001` | basic | tabular/statistical bioinformatics |
| 8 | `population-genetics/popgen-001` | basic | variant/genomic analysis; real tool (scikit-allel) |
| 9 | `proteomics/prot-001` | basic | tabular/statistical bioinformatics |
| 10 | `spatial-transcriptomics/stx-001` | basic | real tool (Scanpy); distinct output structure |
| 11 | `chip-seq/chipseq-003`\* | intermediate | alignment/mapping; peak-to-gene annotation, distinct output structure |
| 12 | `crispr-screens/crispr-003` | intermediate | sequence processing |

\* Slots 1 and 11 were originally `chipseq-001`/`chipseq-002`; see the
Amendment above for why and how they changed. Every other slot is unchanged
from the original freeze.

## Frozen protocol

All of the following are locked in the machine-readable manifest
(`autoba_k4_pilot_v1_20260829_preregistration_manifest.json`,
`frozen_protocol` / other top-level keys):

- **K = 4** per task (48 trajectories total across 12 tasks).
- **AutoBA source commit:** `a9f8f1244faf8b33cf1154150d612acf5026a4d9` (unchanged, pinned).
- **bioTaskBench source commit:** `c9206d570098349143fec3d14d97699928a3bb13` (unchanged, pinned).
- **Model:** `Qwen3-Coder-30B-A3B-Instruct`, local vLLM OpenAI-compatible
  endpoint — same weights/serving procedure already used for admission
  (`reports/autoba_admission.md`); AutoBA's own OpenAI-path transport is
  repointed at it, native Ollama path unused.
- **Sampling:** native AutoBA defaults (no temperature/seed override added by
  the adapter); `requested_seed` = trajectory index, `seed_supported=false`
  (the admitted transport adapter never exposed seed control).
- **Timeout / early-completion parameters:** `timeout_seconds=1800`
  (external safety net, matching the value used throughout admission),
  `done_stable_seconds=60`, `poll_seconds=10` — the same values exercised in
  the verification smoke above.
- **Failure-accounting rules:** the existing 4-layer taxonomy
  (`agent_execution_success -> artifact_contract_valid -> native_scorer_success
  -> scored`) plus `failure_class` (`execution_failure`, `timeout`,
  `agent_control_failure`, `native_scorer_failure`).
- **Primary agreement definition:** plurality/consensus computed only over
  `completed=true` trajectories (reliability.py's existing completed-only
  fix); all-runs behavior preserved separately as `*_legacy_all_runs`.
- **Retry policy:** no retries for a scientific/execution/scorer reason. The
  single narrow exception — matching the precedent already exercised in the
  K=4 admission smoke, where a Slurm allocation expiry killed trajectory 4
  mid-run — permits re-running a trajectory interrupted purely by
  infrastructure external to AutoBA/the adapter (allocation expiry, vLLM
  crash, node failure) once, as a distinctly-logged fresh trajectory, with
  the interrupted attempt preserved on disk and excluded from the primary
  48-trajectory count.
- **Scorer:** unchanged, pinned `harness/grader.py::grade_task`, invoked
  directly by `scripts/run_autoba_k4_reliability.py`.
- **Metrics:** unchanged Reliability Suite v1 definitions
  (`reports/reliability_suite_v1.md`) — Pass@1, plurality accuracy,
  Oracle@K, agreement/plurality fraction, agreement-to-correctness
  AUROC/AUPRC, risk-coverage/AURC, selection-failure rate, all-wrong rate,
  the four stability/recoverability states, typed execution/artifact/scorer
  failures, token cost, runtime cost.
- **Bootstrap:** `n_bootstrap=2000`, `bootstrap_seed=20260825` (same as
  every other campaign in this project).
- **Resource configuration:** single GH200 GPU (TACC Vista, partition `gh`),
  sequential execution — one task campaign and one trajectory at a time
  (matching GenoMAS's pilot default; AutoBA's own generated code has not
  been observed to have GenoMAS's whole-process memory-growth issue, so no
  `RLIMIT_AS` cap is applied here, but this is an assumption to revisit if
  the campaign shows otherwise).

## Expected trajectories

12 tasks x K=4 = **48 trajectories**.

## Runtime / cost estimate

Using the verification smoke's single real data point on `assembly-001`
(1800s wall time when the agent does not converge, ~127K total tokens) and
the earlier admission K=4 smoke's cleaner-convergence anchor (~30 min
wall time, hitting the same external timeout even after finishing early) as
bounds: **roughly 24-36 GPU-hours sequential for the full 48-trajectory
panel**, consistent with the admission report's own planning estimate
(Sec 6, item 12). This is a planning-order-of-magnitude figure, not a
calibrated model — actual cost depends heavily on how often trajectories
converge before the external timeout, which is exactly what
early-completion is intended to reduce but cannot guarantee.

## Launch commands (executed via `scripts/run_autoba_k4_pilot_v1.sh`)

**1. Endpoint** — reuse the already-running vLLM server from admission
(`http://127.0.0.1:8000`, `Qwen3-Coder-30B-A3B-Instruct`) if the same Slurm
allocation is still live; otherwise relaunch fresh on a new allocation using
the exact procedure in `reports/autoba_admission.md` (same `CC=nvc++` +
`libcudart.so` shim this node's `nvidia/24.7` module requires).

**2. Data generation** — for each of the 12 (corrected) tasks, run its own
`tests/<domain>/<test_id>/data/generate_data.py` once (deterministic setup,
not a source/scorer change) before launching. See the Amendment above.

**3. One campaign per task** (12 invocations, sequenced by
`scripts/run_autoba_k4_pilot_v1.sh`; example shown for task #1 as amended —
substitute `--domain`/`--test-id` per the table above for a manual re-run of
a single task):

```bash
/scratch/11034/atzanakak/biomni_vista/envs/biotaskbench/bin/python3 \
  scripts/run_autoba_k4_reliability.py \
  --campaign-root /scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829/01_chipseq-002_k4 \
  --biotaskbench-root /work/11034/atzanakak/biomni_bench/external_agents/bioTaskBench \
  --domain chip-seq --test-id chipseq-002 \
  --endpoint http://127.0.0.1:8000 --model Qwen3-Coder-30B-A3B-Instruct \
  --k 4 --timeout-seconds 1800 --done-stable-seconds 60 --poll-seconds 10 \
  --source-commit a9f8f1244faf8b33cf1154150d612acf5026a4d9 \
  --benchmark-revision c9206d570098349143fec3d14d97699928a3bb13
```

Repeat for the remaining 11 tasks. Each invocation writes its own
`records.jsonl` and `reliability_report.json`; the 12 task-level
`records.jsonl` files are concatenated into one 48-row table for the
combined Step 5 report (not built by this script, which is intentionally
single-task like `run_genomas_k4_reliability.py`).

**Launched 2026-08-29 with explicit operator approval** (Step 4 of
`prompts/autoba_reliability.md`); the one task substitution above was made
before any valid trajectory ran.

## Provenance

- Preregistration manifest (machine-readable, this document's source of
  truth for frozen parameters):
  `/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829_preregistration_manifest.json`
  (SHA-256 `6709a7762512820e3073cfe0002c0be9f56596acddd79b5f4eecf29caeb38579`).
- Engineering: `src/biomni_uncertainty/adapters/autoba.py`,
  `scripts/run_autoba_k4_reliability.py`,
  `scripts/autoba_biotaskbench_agent.py`, `tests/test_adapters_autoba.py`.
- Tool audit: `reports/autoba_tool_provisioning.md`.
- Verification smoke evidence:
  `/scratch/11034/atzanakak/genomas_admission/autoba_admission/verify_reliability_v1_smoke_20260828_221823_v7/`.
- Invalid pre-amendment trajectories (16, all `failure_class=timeout` due to
  the missing-data-generation bug, excluded from the campaign): archived at
  `/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829_INVALID_missing_data_20260829/`.
- Orchestration: `scripts/run_autoba_k4_pilot_v1.sh` (sequences the 12
  amended-panel invocations), `scripts/aggregate_autoba_k4_pilot_v1.py`
  (Step 5 combined report).
- This preregistration does not modify, and was not informed by, any frozen
  admission or prior campaign artifact. The one post-launch amendment above
  was made before any valid trajectory ran, per DECISIONS.md D-56.
