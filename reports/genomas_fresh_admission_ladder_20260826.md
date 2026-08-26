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

**Correction:** an earlier version of this report described the unconditioned
vs. conditioned score differences (AML unconditioned 0.0 vs. AML::Age 1.0;
AMD unconditioned 0.0 vs. AMD::Gender 1.0) as "trajectory-to-trajectory
variance." That was wrong. Unconditioned and conditioned tasks are **different
benchmark instances** — each is its own `(trait, condition)` pair with its own
question, cohort-selection target, and reference answer. A trait scoring
differently unconditioned vs. conditioned is exactly what "different tasks
have different difficulty" looks like; it says nothing about stochastic
sampling variance and is not a reliability signal in the self-consistency
sense this project studies.

The only genuine same-task repeated-trajectory data point in this ladder is
`Acute_Myeloid_Leukemia` unconditioned, independently sampled twice as a
completed trajectory (rung 1's `k4_00` and rung 5's `k4_00` — rung 5's
`k4_01` never completed, see below). **Both scored 0.0**, with the same
false-positive/false-negative pattern each time. That is a `stable_wrong`
result: no variance observed across the two real samples this ladder
happened to draw of that task. Two samples is far too few to conclude the
task is deterministically wrong rather than merely low-agreement; it only
means this ladder did not happen to observe disagreement on it.

## Failure found: an OOM-killed trajectory's reward is not a real outcome

Rung 5's `k4_01` is a genuine, newly-discovered failure mode, unrelated to
the artifact-contract repair: GenoMAS's own preprocessing accumulated to 116
GiB of host RAM (out of 212 GiB) on a second independent trajectory for the
same 10-cohort trait, and the Linux OOM killer terminated it with `SIGKILL`
before it reached `TCGA` or logged its final token/duration summary. The
controller correctly recorded `agent_execution_success=false`,
`failure_class="agent_control_failure"`, `failure_reason="runner_exit_-9"`.

Auditing how this propagated into `evaluate_reliability` found two related,
previously-untested gaps, both now fixed in
`src/biomni_uncertainty/reliability.py`:

1. **Correctness was computed from `official_reward` alone** (commit
   `34ef562`), so `k4_01`'s truncated-but-valid artifact, which still
   produced a defined `official_reward=0.0` from the unchanged native
   scorer, was silently counted as a genuine "wrong answer" trajectory in
   `pass_at_1`/`oracle_at_k`/`plurality_accuracy` — the "missing score vs.
   score zero" conflation this project's scientific-integrity rules forbid,
   in a subtler form (a *defined but illegitimate* score, not a missing
   one). Fixed by gating `correct` on `completed` as well.
2. **The primary plurality/consensus vote, and the failure-taxonomy
   agreement check, still counted every requested trajectory**, including
   execution failures. A `k4_01`-like trajectory could therefore still
   *contest or even win* the plurality vote on a coincidentally-shared
   partial-answer key, and the taxonomy's "did every trajectory land on the
   same answer" check still saw an execution failure as a second,
   disagreeing "answer" — mislabeling this instance `unstable_unrecoverable`
   (implying genuine sampling disagreement) when there was only ever one
   real trajectory to disagree with.

Both are fixed by restricting the *primary* `plurality_fraction`,
`plurality_key`, `plurality_accuracy`, `agreement_plurality_fraction`,
`selection_failure_rate`, and the taxonomy's agreement check to completed,
evaluable trajectories only. The pre-existing all-runs behavior (needed for
compatibility with anything that already consumes it, e.g. historical Biomni
tables re-run through this evaluator via `scripts/import_biomni_reliability.py`)
is preserved verbatim under explicit `*_legacy_all_runs` names
(`plurality_fraction_legacy_all_runs`, `plurality_key_legacy_all_runs`,
`plurality_tie_legacy_all_runs`, `plurality_correct_legacy_all_runs`,
`plurality_accuracy_legacy_all_runs`,
`agreement_plurality_fraction_legacy_all_runs`,
`selection_failure_rate_legacy_all_runs`) — never silently repurposed. A new
`n_completed_runs` field on each instance makes the denominator explicit.
Regression tests added:
`test_incomplete_trajectory_reward_never_counts_as_a_real_outcome`,
`test_execution_failures_cannot_win_or_contest_the_primary_plurality`,
`test_primary_and_legacy_agree_when_every_trajectory_completed` (the last
confirms primary and legacy are identical whenever nothing failed, so no
existing all-completed dataset's numbers change under the new code).

`reliability_report_corrected.json` was regenerated for rung 5 under the
fixed code and placed alongside the original (uncorrected)
`reliability_report.json`, which is left as-is per this project's
never-retroactively-edit convention. Under the fix: `pass_at_1`/`oracle_at_k`
show `n=1` (one real evaluable trajectory, not two); `plurality_fraction=1.0`
(the one completed trajectory trivially wins its own vote, `k4_01` cannot
contest it); and the taxonomy correctly reports **`stable_wrong`**, not
`unstable_unrecoverable`.

### OOM root-cause diagnosis

Three candidate causes were named to distinguish: a Slurm/cgroup memory
limit, competing memory use (e.g. vLLM), or GenoMAS's own per-cohort memory
growth. The `dmesg` OOM record settles it:

```
oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=user.slice,
  mems_allowed=0-1,global_oom,task_memcg=/user.slice/user-904628.slice/session-1233.scope,
  task=python,pid=3150535,uid=904628
Out of memory: Killed process 3150535 (python) total-vm:249489152kB,
  anon-rss:116204928kB, file-rss:18432kB, shmem-rss:0kB, pgtables:17728kB
```

- **Not a Slurm/cgroup limit.** `scontrol show job 937512` /
  `sacct -j 937512 --format=ReqMem` show `ReqMem=1M` — a nominal placeholder,
  not an enforced ceiling — and the kernel's own record says
  `constraint=CONSTRAINT_NONE` / `global_oom`: this was a whole-node OOM, not
  a per-cgroup quota being hit.
- **Not competing memory use.** The full kernel task-state dump at the OOM
  moment (`dmesg`, "Tasks state (memory values in pages)", 64 KiB pages on
  this GH200 node) shows every other process on the node was negligible:
  vLLM's API-server process 148 MB resident, `VLLM::EngineCore` 144 MB, this
  controller's own Python process 18 MB. Nothing else was competing for host
  RAM in any meaningful way.
- **GenoMAS's own per-cohort memory growth, confirmed.** The single killed
  process (`python`, pid 3150535 — the `genomas_smoke_runner.py` agent
  subprocess for `k4_01`) had grown to **110.8 GiB resident** (of 212 GiB
  total node RAM) and **237.9 GiB virtual**, with **20.4 GiB already pushed
  into swap** (`free -h` confirmed "Free swap = 0kB" at the OOM instant — swap
  was also fully exhausted). GenoMAS processes all of a trajectory's cohorts
  sequentially inside one long-lived Python process; this is consistent with
  per-cohort clinical/genetic DataFrame state (or generated-code artifacts)
  accumulating across cohort iterations rather than being released between
  them. GenoMAS's own `output/memory_tracking/*.json` was checked for a
  finer-grained growth curve, but it tracks generated-*code* reuse (an
  action-unit cache), not process RSS, and — being written only at the end of
  a run — never got flushed for the killed trajectory anyway.

Per instruction, **GenoMAS's algorithmic behavior was not modified** to
suppress this. Instead, a narrow, controller-side mitigation was added:
`biomni_uncertainty.adapters.genomas.memory_rlimit_preexec_fn` sets
`RLIMIT_AS` on each agent subprocess (`scripts/run_genomas_k4_reliability.py`,
new `--max-memory-gb` flag, default 150 GiB, recorded in the campaign
manifest's `protocol.max_memory_gb_per_trajectory`). This does not fix or
even touch GenoMAS's memory usage — it only ensures that if a trajectory
runs away again, it hits its own local, clean `MemoryError` well below the
point of threatening the rest of the node, rather than triggering another
indiscriminate global OOM that could just as easily have picked the shared
vLLM server as its victim. Tested in
`test_memory_rlimit_preexec_fn_actually_bounds_the_child_address_space`
(confirms the limit is visible in the child via `resource.getrlimit`, and
that exceeding it raises `MemoryError` locally).

## Code changes (this pass, beyond the artifact-contract repair)

- `scripts/genomas_fetch_reference.py` (new): attested fetch of held-out
  `cohort_info.json`/`code/*.py` references for new traits.
- `src/biomni_uncertainty/reliability.py`: gate `correct` on `completed`;
  primary plurality/consensus/taxonomy restricted to completed trajectories,
  with `*_legacy_all_runs` fields/metrics preserving the old all-runs
  behavior explicitly.
- `src/biomni_uncertainty/adapters/genomas.py`: `memory_rlimit_preexec_fn`.
- `scripts/run_genomas_k4_reliability.py`: `--max-memory-gb` (default 150),
  applied via `preexec_fn` to the agent subprocess; recorded in the campaign
  manifest.
- `tests/test_reliability.py`, `tests/test_adapters_genomas.py`: regression
  tests for all of the above.
- Commits: `c2db221` (pre-ladder repair, already reported in
  `genomas_artifact_contract_diagnosis.md`), plus this pass's commits (see
  `git log`).

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
