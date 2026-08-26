# GenoMAS fresh admission ladder — 2026-08-26

Executed the fresh, held-out admission ladder proposed in
`reports/genomas_artifact_contract_diagnosis.md` §"Fresh admission proposal",
following the operator's explicit instruction and stop conditions. All five
rungs completed; nothing beyond the approved ladder was launched (no K=4, no
OpenBioLLM/AutoBA/BioMaster, no RL).

## Pre-flight

- Git tree was dirty at the start of this pass; committed first
  (`c2db221`, "Diagnose and repair GenoMAS cohort_info.json artifact-contract
  failure") so a real commit — not an uncommitted tree — is the one that ran,
  per this project's own D-29 lesson.
- Local vLLM endpoint verified healthy (`Qwen3-Coder-30B-A3B-Instruct` on
  `127.0.0.1:8000`), on the same allocated GH200 job (`937512`) used
  throughout the GenoMAS admission work.
- Held-out reference bundle: verified it only ever covered
  `Alcohol_Flush_Reaction` (the K1/K4 admission task) and **not** either fresh
  trait. Fetched and checksum-attested `output/preprocess/{cohort_info.json,
  code/*.py}` for `Acute_Myeloid_Leukemia` and `Age-Related_Macular_Degeneration`
  from the same pinned `Liu-Hy/GenoTEX@9d50c9020256e8c943e02b6c0ad843017cd76cf8`
  via the new `scripts/genomas_fetch_reference.py` (manifest/verification at
  `/scratch/11034/atzanakak/genomas_admission/provenance/genotex_reference_{manifest,verification}_fresh_traits.json`,
  `verified: true`, 20/20 files). No bulk gene/clinical CSVs were pulled —
  only what the scorer reads.
- Frozen `k4_reliability_v1_20260825/**` and the admission reports were not
  touched.

## Serving-infrastructure repair (mid-ladder)

Rung 1's first attempt (unfixed 20k-context endpoint) technically produced a
defined reward after a reference-path correction, but exposed a real limit:
`Acute_Myeloid_Leukemia` has 10 GEO cohorts (vs. 1 for the admission task),
and most of them exceeded `max_model_len=20000`, timing out. Per the
operator's direction, the vLLM server was restarted with a larger context
window. That surfaced two further, purely environmental issues, both fixed
without touching any pinned agent/eval code:

1. Flashinfer's JIT build uses `$CC` (not `$CXX`) for `nvcc -ccbin`; this
   node's `nvidia/24.7` module sets `CC=nvc` (the C frontend), which nvcc
   rejects for the C++17 sampling-kernel sources it needs to compile
   (`nvcc fatal: ... nvc++ is the only NVHPC compiler that is supported`).
   Fixed by exporting `CC=.../nvc++` for the vLLM launch only.
2. The resulting link step failed with `cannot find -lcudart`: the venv's
   `nvidia-cuda-runtime-cu13` package ships only a versioned
   `libcudart.so.13`, no unversioned `libcudart.so`. Fixed with a symlink
   shim directory (`/scratch/11034/atzanakak/genomas_admission/cuda_link_shim/`)
   added to `LIBRARY_PATH`/`LD_LIBRARY_PATH` for the launch — the venv's own
   package files were never modified.

Final serving config used for rungs 1 (rerun) through 5:
`--max-model-len 32768 --gpu-memory-utilization 0.92 --enforce-eager`, same
model, same pinned `Qwen3-Coder-30B-A3B-Instruct` weights, same host/port.
The server survives independently of any single trajectory and remained up
across all five rungs.

## Runs performed

| Rung | Task | K | Campaign root |
| --- | --- | --- | --- |
| 1 | `Acute_Myeloid_Leukemia` (unconditioned) | 1 | `01_aml_unconditioned_k1_ctx32k` |
| 2 | `Acute_Myeloid_Leukemia :: Age` | 1 | `02_aml_age_k1` |
| 3 | `Age-Related_Macular_Degeneration` (unconditioned) | 1 | `03_amd_unconditioned_k1` |
| 4 | `Age-Related_Macular_Degeneration :: Gender` | 1 | `04_amd_gender_k1` |
| 5 | `Acute_Myeloid_Leukemia` (unconditioned) | 2 | `05_aml_unconditioned_k2` |

All under `/scratch/11034/atzanakak/genomas_admission/genomas_fresh_admission_ladder_20260826/`.
An earlier rung-1 attempt at the original 20k context
(`01_aml_unconditioned_k1`) is retained as an engineering record (see
`rescoring_note.md` inside it) but superseded by `01_aml_unconditioned_k1_ctx32k`.

## Results

| Run | exec_success | contract_valid | scorer_success | reward | completed | failure_class | in_tok | out_tok | runtime (s) |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |
| Rung1 k4_00 | true | true | true | **0.0** | true | — | 1,973,543 | 88,288 | 4,707.97 |
| Rung2 k4_00 | true | true | true | **1.0** | true | — | 1,999,788 | 92,365 | 4,828.96 |
| Rung3 k4_00 | true | true | true | **0.0** | true | — | 1,101,549 | 39,798 | 2,137.06 |
| Rung4 k4_00 | true | true | true | **1.0** | true | — | 1,116,893 | 38,607 | 2,130.34 |
| Rung5 k4_00 | true | true | true | **0.0** | true | — | 1,756,658 | 89,581 | 4,667.59 |
| Rung5 k4_01 | **false** | true | true | 0.0 (not evaluable) | **false** | `agent_control_failure` | — | — | — |

Totals across the six requested trajectories: **7,948,431 input / 348,639
output tokens**, **~18,472 s (~5.1 h) of measured runtime** on the five that
finished (rung5's `k4_01` has no native-log totals — see below), **$0.00
paid cost** (local model). Every `llm_input_tokens`/`llm_output_tokens`/
`runtime_seconds` value is nonzero and real, confirming the §14 controller
bookkeeping fix holds under the fresh ladder.

## Score detail (why the rewards are what they are)

- **Rung 1** (AML unconditioned, reward 0.0): filtering precision/recall/f1
  all 0, accuracy 54.55%; selection accuracy 0%. The agent flagged two
  cell-line-derived GEO cohorts (`GSE121431`, `GSE222169`) as available when
  the reference says they are not, and flagged the three genuinely available
  cohorts (`GSE222124`, `GSE249638`, `TCGA`) as unavailable — a real
  reasoning miss on ambiguous cell-line trait-availability judgments, not an
  infrastructure or scoring defect.
- **Rung 2** (AML::Age, reward 1.0): filtering accuracy 72.73% (still
  imperfect per-cohort judgments) but selection accuracy 100% — the
  trait+condition cohort-pair the agent actually picked matched the
  reference's best pick.
- **Rung 3** (AMD unconditioned, reward 0.0): filtering 0/0/0/85.71%,
  selection 0%.
- **Rung 4** (AMD::Gender, reward 1.0): filtering **100/100/100/100%**,
  selection 100%.
- **Rung 5** (AML unconditioned, K=2): `k4_00` reward 0.0 (same
  false-positive/false-negative pattern as rung 1, independently resampled);
  `k4_01` was killed mid-run by the Linux OOM killer (`dmesg`: 116 GiB
  resident, `Out of memory: Killed process ... (python)`) after ~75 minutes,
  having recorded 6 of 10 GEO cohorts. Its truncated `cohort_info.json` was
  still contract-valid and the native scorer still returned a defined
  `official_reward=0.0` for it — but this is *not* a real completed
  trajectory outcome (see next section).

Rungs 1 vs. 3 and 2 vs. 4 vs. rung-5-`k4_00` show the same trait sampled
independently swinging between 0% and 100% filtering/selection accuracy
(AMD unconditioned 0% vs. AMD::Gender 100%; AML::unconditioned 0%/0% across
two independent trajectories vs. AML::Age 100%) — exactly the kind of
trajectory-to-trajectory variance this project studies, now backed by real
native scores instead of artifact-contract noise.

## Failure found: an OOM-killed trajectory's reward is not a real outcome

Rung 5's `k4_01` is a genuine, newly-discovered failure mode, unrelated to
the artifact-contract repair: GenoMAS's own preprocessing accumulated to 116
GiB of host RAM (out of 212 GiB) on a second independent trajectory for the
same 10-cohort trait, and the Linux OOM killer terminated it with `SIGKILL`
before it reached `TCGA` or logged its final token/duration summary. The
controller correctly recorded `agent_execution_success=false`,
`failure_class="agent_control_failure"`, `failure_reason="runner_exit_-9"`.

Auditing how this propagated into `evaluate_reliability` found a real,
previously-untested gap: `correct` (and therefore `pass_at_1`, `oracle_at_k`,
`plurality_accuracy`, and the failure taxonomy) was computed from
`official_reward` alone. Because `k4_01`'s truncated-but-valid artifact still
produced a defined `official_reward=0.0` from the unchanged native scorer,
it was being silently counted as a genuine "wrong answer" trajectory —
exactly the "missing score vs. score zero" conflation this project's own
scientific-integrity rules forbid, just in a subtler form (a *defined but
illegitimate* score, not a missing one). Fixed in
`src/biomni_uncertainty/reliability.py` (commit `34ef562`): `correct` is now
gated on `completed` too, so an incomplete trajectory's reward — real or
not — never enters correctness/taxonomy computation, only
`failure_accounting`/`failure_layers`. Regression test added
(`test_incomplete_trajectory_reward_never_counts_as_a_real_outcome`).
`reliability_report_corrected.json` was regenerated for rung 5 under the
fixed code and placed alongside the original (uncorrected)
`reliability_report.json`, which is left as-is per this project's
never-retroactively-edit convention; `pass_at_1`/`oracle_at_k` now correctly
show `n=1` (one real evaluable trajectory) instead of `n=2`.

One secondary, smaller nuance was *not* changed: the failure taxonomy still
labels this instance `unstable_unrecoverable` rather than a plainer
"1 real trajectory, 1 execution failure" state, because the agreement/`keys`
computation (used for `agreement_plurality_fraction` and consensus) still
includes execution-failed trajectories' answer-cluster-keys by design —
that's the pre-existing, extensively pre-registered self-consistency
measurement used across Biomni Phase 1/2, and changing what it measures is
out of scope for this pass. Flagging it rather than silently patching it.

## Code changes (this pass, beyond the artifact-contract repair)

- `scripts/genomas_fetch_reference.py` (new): attested fetch of held-out
  `cohort_info.json`/`code/*.py` references for new traits.
- `src/biomni_uncertainty/reliability.py`: gate `correct` on `completed`.
- `tests/test_reliability.py`: regression test for the OOM-trajectory case.
- Commits: `c2db221` (pre-ladder repair, already reported in
  `genomas_artifact_contract_diagnosis.md`), `34ef562` (this pass).

## Provenance

- vLLM logs: `/scratch/11034/atzanakak/genomas_admission/vllm_logs/` (all
  attempts, including the three failed relaunches, kept for the record).
- Reference manifest/verification:
  `/scratch/11034/atzanakak/genomas_admission/provenance/genotex_reference_{manifest,verification}_fresh_traits.json`.
- `cuda_link_shim/`: a symlink-only directory, never touched vLLM/venv
  package files.
- Per-rung `records.jsonl`, `reliability_report.json`, native logs, scorer
  logs, and worktrees retained under each rung's campaign root.
- No frozen K1/K4 admission artifact was modified.

## Go / No-Go for a preregistered held-out K=4 campaign

```text
GO, with one addressed gap: GenoMAS's artifact-contract and serving pipeline
now produce real, trustworthy native scores on fresh, multi-cohort tasks.
```

Supporting evidence: 5/6 requested trajectories completed cleanly with valid
artifacts and real, internally-consistent scores (verified by hand against
the reference `cohort_info.json` for two of them); the one failure
(OOM-killed `k4_01`) was correctly classified as an execution failure and,
after this pass's fix, correctly excluded from correctness metrics.

Before preregistering a real K=4 campaign, two things are worth deciding
explicitly (not blocking, but should be a conscious choice, not a default):

1. **Memory headroom.** A second independent AML trajectory hit 116 GiB
   resident and got OOM-killed on a 212 GiB host. A K=4 campaign run
   sequentially (as this controller does) should not compound this, but a
   parallelized or multi-trait K=4 run could. Consider either investigating
   GenoMAS's per-cohort memory growth (not diagnosed here — out of scope for
   this pass) or budgeting for some execution-failure rate on rich,
   multi-cohort traits and treating it as expected infrastructure noise
   (now correctly classified, not silently miscounted).
2. **Fresh task selection for the confirmatory panel.** `Acute_Myeloid_Leukemia`
   and `Age-Related_Macular_Degeneration` were used in this admission ladder
   (K=1 x2 each plus one K=2) and are therefore no longer eligible as a
   held-out confirmatory panel, by the same rule that retired
   `Alcohol_Flush_Reaction`. A new K=4 preregistration needs its own,
   still-unused fresh task(s).

Exact next command **not executed**, gated on explicit approval per
standing instructions:

```bash
python scripts/run_genomas_k4_reliability.py \
  --campaign-root /scratch/11034/atzanakak/genomas_admission/<new_campaign_name> \
  --source /scratch/11034/atzanakak/genomas_admission/GenoMAS_run \
  --data-root /scratch/11034/atzanakak/genomas_admission/genotex_data/input \
  --reference-root /scratch/11034/atzanakak/genomas_admission/genotex_references/output \
  --endpoint http://127.0.0.1:8000 \
  --model Qwen3-Coder-30B-A3B-Instruct \
  --trait <new_unused_trait> [--condition <Age|Gender|...>] \
  --k 4 \
  --source-commit d6365a700794587b53958db3bf22bb1fb80c3451 \
  --benchmark-revision 9d50c9020256e8c943e02b6c0ad843017cd76cf8
```

(Requires a pinned held-out reference for whichever trait is chosen, fetched
the same way via `scripts/genomas_fetch_reference.py` first.)
