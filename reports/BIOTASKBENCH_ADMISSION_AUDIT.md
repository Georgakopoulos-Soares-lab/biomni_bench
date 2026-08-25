# BioTaskBench admission audit — zero-cost local reliability validation

**Audit date:** 2026-08-25  
**Status:** admitted to a *two-task K=4 engineering/scientific smoke*, not yet
admitted to a full campaign.  No model has been downloaded and no agent task
has been run.  This document is frozen before any BioTaskBench model outcome.

## Decision

BioTaskBench meets the central scientific requirements for an independent,
fully local reliability validation surface:

- its current `biotaskbench` suite has **34** original task specifications in
  10 bioinformatics domains;
- the checked source has **no active `llm_judge` criterion** (the type exists in
  the harness but is unused by all 34 task JSON files);
- active grades are deterministic file/schema/exact/range/set-overlap/
  correlation/code-execution checks, returning a native continuous score in
  `[0, 1]`;
- the runner accepts an arbitrary agent command through environment variables
  (`BIOTASKBENCH_TASK_JSON`, `BIOTASKBENCH_TEST_DIR`,
  `BIOTASKBENCH_WORKSPACE`), so a custom mini-SWE-agent command does not modify
  task wording, ground truth, or scoring;
- the grader can be rerun separately over the preserved workspace.

It is therefore a credible *independent coding-agent/biomedical-task*
reliability system. It is not an interchangeable replication of Biomni: tasks
are constrained bioinformatics coding/data-analysis tasks rather than
Biomni-E1 tool-retrieval tasks. Cross-system comparisons should be made for
reliability relationships (agreement vs. native success, selection failure,
execution failure), not raw accuracy.

## Exact upstream pins

| Component | Pin / revision | License / interface finding |
|---|---|---|
| BioTaskBench | `GPTomics/bioTaskBench` `c9206d570098349143fec3d14d97699928a3bb13` | MIT; generic `--agent-cmd` runner; 34-task `biotaskbench` suite. |
| mini-SWE-agent | `SWE-agent/mini-swe-agent` `25941c89cfbc91eb40b3f8756348c91d9977d57e` | local OpenAI-compatible endpoint supported via LiteLLM `api_base`; full `.traj.json` trajectory serialization. |
| Qwen3-Coder-30B-A3B-Instruct | `Qwen/Qwen3-Coder-30B-A3B-Instruct` `b2cff646eb4bb1d68355c01b18ae02e7cf42d120` | Apache-2.0; 30,532,122,624 BF16 parameters / ~61.1 GB checkpoint. |
| local server | vLLM, version pinned during environment build | Qwen model card documents a vLLM OpenAI-compatible server; exact release must be compatibility-tested on Vista before smoke. |

The BF16 checkpoint is expected to fit on the 95.6-GiB GH200 with a deliberately
bounded context/KV-cache setting. It leaves roughly 34 GiB before runtime,
allocator, and KV-cache overhead; start the smoke at `max_model_len=32768` and
reduce only if the server proves memory-limited. Quantization is not admitted
for convenience because BF16 is expected to fit.

## Task/data audit

All 34 task directories contain a deterministic `data/generate_data.py` and
task-specific expected outputs. The Git snapshot deliberately does **not** ship
generated input files: all 34 currently need generator execution before they
can run. This is a setup prerequisite, not missing ground truth.

- **31 tasks** have no URL in their generator and are eligible after successful
  local deterministic generation plus schema/grader validation.
- **3 ChIP-seq tasks** (`chipseq-001`, `chipseq-003`, `chipseq-005`) request
  public ENCODE/GENCODE/blacklist source files. They are deferred from the
  offline-confirmatory manifest until their downloads, checksums where present,
  source URLs, and generated artifacts are frozen. They do not require a paid
  service or an LLM judge.
- Domain dependency metadata lists optional/expected external tools for some
  tasks (for example `samtools`, `bedtools`, `minimap2`, `plink`, `vcftools`,
  MAGeCK, Bismark). A task does not become eligible solely because its generator
  completes: the complete smoke must demonstrate its native grader and agent
  workspace on the intended environment.

`eligible_tasks.csv` is a pre-outcome, provisional manifest: 31
`candidate_offline` tasks and three `deferred_external_data` tasks. It becomes
the frozen full-campaign manifest only after data-generation hashes and
environment preflight are recorded.

## Scoring audit

The source defines seven active deterministic criterion families:

| Criterion | Native output |
|---|---|
| `file_check` / `column_check` | required artifact and schema presence |
| `exact_match` | specified exact/string match |
| `range_check` | value within a predeclared range; may have predeclared partial score |
| `set_overlap` | Jaccard or F1 against the task expected file |
| `numeric_correlation` | Pearson/Spearman against expected paired values |
| `code_executes` | generated Python/R artifact exits successfully |

Each task score is the predeclared weighted sum of criteria. Continuous scores
will be retained; the v1 binary correctness field is `native_score >= 1.0`
unless the task manifest declares a different pre-outcome threshold. A scorer
exception is an evaluator failure, never silently converted to zero.

## Agent and reproducibility admission

mini-SWE-agent is compatible without paid services: configure LiteLLM as a
local OpenAI-compatible provider against a loopback vLLM endpoint and register
zero token costs. It preserves messages/configuration/metadata in a trajectory
file. The wrapper must additionally preserve each workspace, agent stdout and
stderr, server request metadata, token counts when returned, task/run seed,
grader result, and terminal reason.

The benchmark runner already launches each agent command in an isolated
workspace and records stdout/stderr/return code. A new wrapper will copy the
native mini-SWE trajectory into the per-run artifact directory and call the
native grader only after the run exits or times out. It will make no external
network/API call after model/data acquisition.

## Smoke protocol, frozen before outcomes

Run `assembly-001` and `popgen-001`, two local-generator tasks from different
domains, at **K=4**. They avoid external source data and specialized binary
tools in the initial admission smoke while exercising numeric-domain reasoning
and deterministic graders. Each task is generated once from the pinned seed;
each trajectory receives a distinct requested model seed. The native grader is
rerun twice from the completed workspace to prove deterministic score output.

Do not launch the 31-task campaign until all eight trajectories, raw traces,
workspace snapshots, and regrade checks are reviewed. The full campaign has
been preplanned but is **not authorized by this admission audit**.

## Risks and gates

1. Vista's existing Biomni Python environment is currently dynamically broken
   outside its original module setup (`libpython3.11.so.1.0` unavailable). A
   clean dedicated Python 3.12 environment is required; this is an engineering
   blocker, not a benchmark-science failure.
2. Qwen and vLLM must be installed/downloaded into scratch and launched through
   Slurm. The first run is a bounded server-load/request smoke, not a task run.
3. mini-SWE-agent is software-engineering-oriented. Its shell/workspace policy
   must be explicitly constrained to each generated BioTaskBench workspace;
   the initial two task checks are the admission evidence for that adapter.
4. Task generators and data must be copied into a run-specific, hash-recorded
   snapshot before agent execution; never mutate the upstream audit checkout.

## Primary sources

- [BioTaskBench README](https://github.com/GPTomics/bioTaskBench): public
  34-task suite, generic agent command, data generation, and native criteria.
- [mini-SWE-agent local-model guide](https://github.com/SWE-agent/mini-swe-agent/blob/main/docs/models/local_models.md): local vLLM/LiteLLM configuration.
- [Qwen model card and revision](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct): Apache-2.0, BF16 parameter count, vLLM serving interface.
