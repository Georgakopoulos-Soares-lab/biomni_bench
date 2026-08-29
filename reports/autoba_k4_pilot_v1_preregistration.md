# AutoBA K=4 pilot v1 — preregistration (NOT LAUNCHED)

Status: **`PREREGISTERED_NOT_LAUNCHED`**. No confirmatory K=4 trajectory has
been started. This document, plus the machine-readable manifest at
`/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829_preregistration_manifest.json`
(SHA-256 `6709a7762512820e3073cfe0002c0be9f56596acddd79b5f4eecf29caeb38579`),
freezes every protocol parameter before any confirmatory-campaign execution,
per instruction. Do not launch from this preregistration without explicit
operator approval.

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
| 1 | `chip-seq/chipseq-001` | basic | alignment/mapping; real tool (MACS3) |
| 2 | `crispr-screens/crispr-001` | basic | sequence processing |
| 3 | `genome-assembly/assembly-002` | intermediate | genome assembly |
| 4 | `long-read-sequencing/lrs-001` | basic | sequence processing; real tool (NanoStat) |
| 5 | `metabolomics/metab-001` | basic | tabular/statistical bioinformatics |
| 6 | `methylation-analysis/meth-001` | basic | tabular/statistical bioinformatics |
| 7 | `multi-omics-integration/moi-001` | basic | tabular/statistical bioinformatics |
| 8 | `population-genetics/popgen-001` | basic | variant/genomic analysis; real tool (scikit-allel) |
| 9 | `proteomics/prot-001` | basic | tabular/statistical bioinformatics |
| 10 | `spatial-transcriptomics/stx-001` | basic | real tool (Scanpy); distinct output structure |
| 11 | `chip-seq/chipseq-002` | intermediate | alignment/mapping; de novo motif discovery, distinct output structure |
| 12 | `crispr-screens/crispr-003` | intermediate | sequence processing |

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

## Exact launch commands (NOT EXECUTED)

**1. Endpoint** — reuse the already-running vLLM server from admission
(`http://127.0.0.1:8000`, `Qwen3-Coder-30B-A3B-Instruct`) if the same Slurm
allocation is still live; otherwise relaunch fresh on a new allocation using
the exact procedure in `reports/autoba_admission.md` (same `CC=nvc++` +
`libcudart.so` shim this node's `nvidia/24.7` module requires).

**2. One campaign per task** (12 invocations; example shown for task #1 —
substitute `--domain`/`--test-id` per the table above):

```bash
/scratch/11034/atzanakak/biomni_vista/envs/biotaskbench/bin/python3 \
  scripts/run_autoba_k4_reliability.py \
  --campaign-root /scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829/01_chipseq-001_k4 \
  --biotaskbench-root /work/11034/atzanakak/biomni_bench/external_agents/bioTaskBench \
  --domain chip-seq --test-id chipseq-001 \
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

**Not executed. Requires explicit operator approval before any trajectory
starts** — this preregistration is Steps 1-3 of `prompts/autoba_reliability.md`
only; launching the campaign (Step 4) is a separate, explicit next action.

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
- This preregistration does not modify, and was not informed by, any frozen
  admission or prior campaign artifact.
