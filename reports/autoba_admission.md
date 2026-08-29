# AutoBA admission — audit, K=1 smoke, tiny K=4 smoke

Date: 2026-08-28/29. Status: **ADMITTED to a K=1/tiny-K=4 admission smoke,
not yet to a scientific campaign.** No larger AutoBA campaign has been
launched. This is the first admission pass for AutoBA as the project's third
distinct biomedical agent (after Biomni and GenoMAS).

## 1. Audit

| Item | Finding |
| --- | --- |
| Source commit | `a9f8f1244faf8b33cf1154150d612acf5026a4d9` (pinned, matches `configs/reliability_suite_v1.yaml`), staged at `/work/11034/atzanakak/biomni_bench/external_agents/AutoBA` |
| License | MIT |
| Benchmark reused | bioTaskBench (`GPTomics/bioTaskBench` `c9206d570098349143fec3d14d97699928a3bb13`, already audited in `reports/BIOTASKBENCH_ADMISSION_AUDIT.md` for a different agent, mini-SWE-agent) — public, 34 deterministic-graded tasks, no LLM judge |
| Native/official scorer | `harness/grader.py::grade_task` — deterministic file/column/range/set-overlap/correlation checks, unchanged, called directly |
| Ground truth isolation | Reference values live in each task's `expected/` dir and inside `task.json`'s `range`/`partial_range` fields, which the harness never copies into the agent's workspace; the agent only ever sees `context.data_files` and `prompt` |
| Repeatable / stochastic sampling | Yes — each invocation is an independent process/trajectory; the harness's `--agent-cmd` model supports arbitrary repetition |
| Answer canonicalization | The scored artifact is a structured TSV file on disk, graded by column/value, not free text — no canonicalization needed |
| Full trajectory logging | AutoBA writes every round's `{N}_response.json`, generated `{N}.sh`, and `executor_response.json` into the task workspace; all preserved |
| Model/provider replaceable | Yes — AutoBA natively supports Ollama (`ollama_*` engine names) **and** a real OpenAI-compatible client (`openai.OpenAI`), the latter reused to point at local vLLM (see §2) |
| Paid API required | **No** — confirmed a full trajectory runs end-to-end against a local vLLM `Qwen3-Coder-30B-A3B-Instruct` endpoint, $0.00 |
| External DB/tool/API dependencies | AutoBA's own code-generation prompts assume a rich pre-installed bioinformatics tool environment (`softwares_config/` lists ~10 pinned tools: bowtie2, bwa, hisat2, samtools-adjacent tools, etc.) and a `mamba activate abc_runtime` environment that does not exist on this node. The one task exercised here (`assembly-001`) is solvable in pure Python/pandas, so this was not a blocker for *this* smoke, but it is an open question for bioTaskBench tasks whose `expected_tools` genuinely require a real bioinformatics binary (see §6) |
| CPU RAM / GPU memory | Trivial — a single GH200 already running the shared Qwen3-Coder vLLM endpoint from prior GenoMAS work is sufficient; AutoBA's own generated code for this task never touched the GPU |

## 2. Non-invasive adapter

`scripts/autoba_biotaskbench_agent.py`, invoked as bioTaskBench's
`--agent-cmd`. Translates one bioTaskBench `task.json` into AutoBA's own
`data_list`/`goal_description` format and back; no bioTaskBench harness/grader
file and no AutoBA source file is edited. Four patches, all applied by
monkeypatching already-imported names or already-constructed objects, fully
documented in the script's own module docstring:

1. **LLM transport** — the `OpenAI` name AutoBA imports into `src.agent` is
   replaced with a factory that builds a client pointed at the local vLLM
   endpoint instead of the real OpenAI API. `model_engine="gpt-4"` is passed
   at construction only to satisfy AutoBA's own hardcoded engine-validity
   check (which otherwise calls `exit()`); immediately after construction,
   the instance's `model_engine`/`gpt_model_engines` are corrected to the
   real served model name.
2. **Execution environment** — `CodeExecutor.code_prefix` hardcodes
   `mamba activate abc_runtime`; no conda/mamba exists on this node at all.
   Patched post-construction to instead activate the existing pandas/numpy
   venv used elsewhere in this project.
3. **Shell invocation mode** — `CodeExecutor.execute` hardcodes
   `bash -i -e` (interactive). `-i` has no purpose here except making bash
   try to set up job control, which fails with no controlling TTY in any
   headless harness (`Inappropriate ioctl for device` / `no job control in
   this shell`). That noise lands in stderr, which AutoBA's own
   executor-response step feeds back to itself as part of judging whether
   its own code succeeded — see §4. Patched by replacing the whole method
   (class-level, before construction) with a byte-for-byte copy that drops
   `-i`; nothing else about the method changes.
4. **Import-time stubs** — `src.agent`/`src.build_RAG_private`
   unconditionally import Meta's `llama` package (which itself needs
   `fairscale`, with no prebuilt wheel for this node's aarch64) and
   `llama_index` with two embedding extras, solely to support AutoBA's
   local-LLaMA and RAG code paths, neither of which this run uses
   (`rag=False`, OpenAI/vLLM transport only). Stubbed in `sys.modules`
   before import rather than installed; nothing stubbed is ever called.

## 3. K=1 admission smoke — `genome-assembly/assembly-001`

Task chosen because it is solvable in pure Python (no external bioinformatics
binary required, `requires_internet: false`), has a fully deterministic
multi-criteria grader, and is one of the two tasks the prior BioTaskBench
audit already vetted as tool-light. Data generated once from the task's own
seeded `generate_data.py` (`contig_count=60, total_length=1708558,
n50=33689`) — a deterministic setup step, not a source or scorer change.

Three real, end-to-end attempts, each a genuine LLM-driven trajectory against
the live vLLM endpoint:

| Attempt | Result | Diagnosis |
| --- | --- | --- |
| 1 (1800s timeout) | score 0.100, `output_exists` only | Model chose `seqkit` (not installed), correctly self-diagnosed the failure, began repairing, ran out of time before finishing |
| 2 (3600s timeout) | score 0.100, still timed out | Model *did* pivot to a correct pure-Python/pandas one-liner on round 2 — but stalled there for the full hour. Its own executor-response step kept judging the (correct) script as failed because of the benign `bash -i` non-TTY warnings in stderr |
| 3 (1800s, `-i` fix applied) | **score 1.000**, `attempted=true` | Reached round 6, correct `assembly_stats.tsv` written: `contig_count=60, total_length=1708558, n50=33689`, exactly matching the generator's own values |

Root cause of attempts 1–2's failure mode (`bash -i` triggering false-negative
self-assessment) confirmed and fixed narrowly (§2, patch 3) — not by changing
AutoBA's prompts, retry logic, or task semantics, and not by lowering the bar
for what counts as success. This is a real AutoBA robustness finding, not an
artifact of the adapter: any fully automated (non-interactive) deployment of
native AutoBA would hit the same thing.

## 4. Tiny K=4 smoke — same task, 4 independent trajectories

All 4 completed. **Unanimous agreement, unanimous success:**

| Run | Score | Rounds | `contig_count` | `total_length` | `n50` | Wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.000 | 8 | 60 | 1,708,558 | 33,689 | ~1800s (external timeout) |
| 2 | 1.000 | 9 | 60 | 1,708,558 | 33,689 | ~1800s (external timeout) |
| 3 | 1.000 | 9 | 60 | 1,708,558 | 33,689 | ~1800s (external timeout) |
| 4 | 1.000 | 8 | 60 | 1,708,558 | 33,689 | ~1800s (external timeout) |

- **Execution failures: 0/4.** **Scoring failures: 0/4.** **Agreement: 4/4
  identical on every scored field** (only the free-text, ungraded
  `assembly_id` column differs cosmetically between runs).
- **All four hit the external 1800s timeout rather than exiting cleanly**,
  despite having already written the correct file. AutoBA's own loop does
  not reliably recognize task completion and stop; the harness's hard
  timeout is doing real work as a backstop, not just a safety net. This
  inflates measured wall-clock cost — true "useful work" time per trajectory
  is shorter than 1800s but not independently measurable from what this pass
  captured. bioTaskBench's harness already exposes a `done_check`/
  `done_stable_seconds` mechanism (unused here, not exposed via the CLI) that
  a future campaign should wire up to detect the target file landing and
  stabilizing, then terminate early.
- **Token/cost accounting is a known gap, not fixed in this pass.** AutoBA's
  own `get_single_response` discards `response.usage` from every OpenAI-style
  call entirely (no native token logging, unlike GenoMAS's `utils/logger.py`).
  The adapter's `local_vllm_client` wrapper could capture `usage` on every
  call the same way GenoMAS's transport patch did; it does not yet. No
  paid cost either way ($0.00, local model), but per-trajectory token counts
  for this smoke are not available.

### Infrastructure interruption (unrelated to AutoBA itself)

The Slurm allocation backing the first three K=4 trajectories hard-expired
mid-way through trajectory 4 (job `944566`, 48h walltime, reached its
`EndTime` while trajectory 4 was mid-round). This killed the node, vLLM, and
the in-flight trajectory outright — not an AutoBA or adapter failure. The
partial trajectory is preserved at
`.../k4_smoke_assembly001/results_traj4_INTERRUPTED_infra_job_expired/` for
the record and excluded from the K=4 result above. A fresh allocation (job
`950393`) came up automatically; vLLM was relaunched there via the identical,
already-documented procedure (`CC=nvc++` + `libcudart.so` shim), and a
genuinely fresh trajectory 4 was run in its place — the table above reflects
that clean rerun, not the interrupted attempt.

## 5. Known limitations / recommended follow-ups (not yet addressed)

- **Untested: tasks needing a real bioinformatics binary.** `assembly-001`
  was deliberately chosen to avoid this. Any bioTaskBench task whose
  `expected_tools` are not pip-installable (e.g. `bowtie2`, `samtools`) would
  need either a real tool environment provisioned on the execution host, or
  observation of whether AutoBA's own `pip`/`mamba`-install instinct (visible
  in its own prompt rules) can install a usable substitute — neither has been
  exercised.
- **No token/cost instrumentation** (see §4). Cheap to add before a larger
  campaign; not done here since it wasn't needed to reach an admission
  verdict.
- **No early-completion detection** (see §4) — inflates wall-clock cost.
- **Import stubs are broad-brush.** `_stub_unused_heavy_imports` returns a
  `MagicMock` for *any* attribute access on the stubbed modules. This is safe
  only because `rag=False` and the local/Ollama code paths are never
  exercised; if a future campaign wants AutoBA's RAG mode, the stubs must be
  replaced with a real `llama_index` install, not extended.
- **Reliability Suite v1 import/report status: not yet built.** No
  `adapters/autoba.py`/`normalize_autoba_table`-style importer exists yet
  (unlike Biomni/GenoMAS). Straightforward given the established pattern —
  `run.json`'s `results[].score`/`attempted`/`agent_execution` map cleanly
  onto `official_reward`/`completed`/`failure_class` — but not built in this
  pass, since it wasn't required to reach a K=1/K=4 admission verdict.

## 6. Final handoff

1. **Source/environment:** AutoBA `a9f8f1244f...`, MIT. Runs fully locally: no
   paid or proprietary API at any point (confirmed against a real vLLM
   `Qwen3-Coder-30B-A3B-Instruct` endpoint).
2. **Genuinely distinct agent:** Yes — separate codebase, separate prompt/
   role design ("bioinformatician" role, plan → per-step code generation →
   execute → self-review → repair loop), separate execution model (bash
   script generation against a real filesystem workspace, not Biomni's
   tool-retrieval design or GenoMAS's multi-role author/reviewer graph).
3. **Fully local / zero cost:** Yes, $0.00.
4. **Benchmark/task/scorer:** bioTaskBench `assembly-001`
   (genome-assembly, basic), `harness/grader.py::grade_task`, unchanged.
5. **K=1 result:** score 1.000 after fixing a real, narrow, documented
   robustness bug (non-interactive-shell false-failure misreading); two
   earlier honest failed attempts preserved as evidence, not hidden.
6. **K=4 result:** 4/4 completed, 4/4 correct, 4/4 in full agreement, 0
   execution failures.
7. **Reliability Suite v1 import/report status:** not yet built (§5) — the
   data needed for it exists and is preserved, but the importer itself is a
   follow-up item.
8. **Failure types observed:** two (now-understood, now-fixed) execution-mode
   failures during admission diagnosis; one infrastructure interruption
   (Slurm allocation expiry) unrelated to AutoBA; zero failures in the final,
   clean K=1 + K=4 evidence set.
9. **Runtime/token/memory cost:** ~30 min wall-clock per trajectory (hits the
   external timeout even after finishing early — see §4); token accounting
   not instrumented this pass; GPU/host memory negligible for this task
   (shared with the already-running vLLM server, no additional GPU use by
   AutoBA's own generated code).
10. **Dataset/API/tool blockers:** none for tool-light tasks; open question
    for tasks needing real bioinformatics binaries (§5).
11. **Admit AutoBA into the multi-agent panel:** **yes**, on the strength of
    this clean K=1 + 4/4 K=4 admission evidence — as a genuinely distinct,
    fully local, zero-cost third agent.
12. **Cost estimate for a proper confirmatory K=4 campaign:** using this
    pass's ~30 min/trajectory (inflated by the no-early-exit issue) as an
    upper bound, a 12-task × K=4 panel (mirroring GenoMAS's fresh pilot
    scale) would be roughly 48 trajectories × 30 min ≈ 24 GPU-hours
    sequential, likely less once early-completion detection is wired in.
    This is a rough planning number, not a frozen estimate.
13. **Recommended next agent after AutoBA:** not evaluated in this pass —
    out of scope per explicit instruction (OpenBioLLM/BioMaster deferred).

## Go / No-Go

```text
GO: AutoBA admitted (K=1 + tiny K=4 smoke clean). Not yet ready for a
scientific confirmatory campaign -- token instrumentation, early-completion
detection, and a Reliability Suite v1 importer should land first.
```

No larger AutoBA campaign, no OpenBioLLM, no BioMaster, no RL work was
started. Stopping here for explicit approval before anything beyond this
admission pass.

## Provenance

- Adapter: `scripts/autoba_biotaskbench_agent.py`.
- K=1 evidence: `/scratch/11034/atzanakak/genomas_admission/autoba_admission/k1_smoke_assembly001{,_retry,_v3}/`.
- K=4 evidence: `/scratch/11034/atzanakak/genomas_admission/autoba_admission/k4_smoke_assembly001/` (including the preserved interrupted trajectory-4 attempt).
- bioTaskBench pinned commit: `c9206d570098349143fec3d14d97699928a3bb13` (unchanged; only its own deterministic `generate_data.py` was run, per its own documented setup step).
- AutoBA pinned commit: `a9f8f1244faf8b33cf1154150d612acf5026a4d9` (unchanged; zero AutoBA source files edited).
- `configs/reliability_suite_v1.yaml` updated to reflect this admission status.
