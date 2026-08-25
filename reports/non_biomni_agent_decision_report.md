# Non-Biomni biomedical-agent evaluation: decision report

**Prepared:** 2026-08-25  
**Scope:** candidates for Reliability Suite v1 on Vista, excluding Biomni (already run on Stampede).  
**Hardware confirmed:** one Vista GH200 is accessible through `srun --overlap`; it has 95.6 GiB usable GPU memory. Direct shell processes in the current development session do not receive GPU device files, so all GPU work must be launched through Slurm.

## Executive decision

Do **not** buy API credits merely to run every available agent. No currently
audited non-Biomni agent provides a clean, fully local, native-scored benchmark
that is ready to be the second member of the confirmatory Reliability Suite v1
panel.

The best immediate path is either:

1. **Strict/confirmatory path — recommended:** obtain a small, project-scoped
   OpenAI API budget and run a K=4 **CellVoyager/CellBench admission smoke**.
   Retain all agent and judge artifacts; report the LLM judge as a limitation.
   Do not admit BioMedAgent, BioMaster, or BRAD until their benchmark/scoring
   gates below are satisfied.
2. **No-paid-API path:** run local-model *engineering* smokes for CellVoyager,
   BioMedAgent, BioMaster, or BRAD only after explicitly labelling them
   exploratory. These test installation, repeated runs, traces, extraction and
   evaluator wiring; they are not faithful reproductions of the upstream
   model/scoring setups and should not be pooled with the primary panel.

The distinction is important: a local model server solves an inference-cost
problem, but cannot create an absent official scorer or make a GPT judge
deterministic.

## What has been staged and checked

Public source snapshots are staged under
`/work/11034/atzanakak/biomni_bench/external_agents/`:

| Candidate | Pinned snapshot | License observed | Public benchmark data/scorer found locally |
|---|---:|---|---|
| CellVoyager | `5a61f6b` | MIT | CellBench data and execution/judge scripts; judge is GPT-based. |
| BioMaster | `6f98a63` | MIT | Workflow examples/tests; no packaged deterministic published benchmark scorer. |
| BioMedAgent reproduction | `c74911c` | no top-level license found in this reproduction | Demo assets; no BioMed-AQA evaluation bundle found; reported score is GPT semantic matching. |
| BRAD | `a6f5dba` | MIT | Agent/application only; no matched benchmark + official scorer found. |

These are source-audit snapshots, not vendored project dependencies. Pin
again if an execution is admitted.

## Candidate-by-candidate decision matrix

| Candidate | Faithful upstream run needs | Can run locally? | Reliability Suite v1 status | Decision |
|---|---|---|---|---|
| **CellVoyager / CellBench** | OpenAI API project/key; model access for `gpt-4o` or `o3-mini`; `gpt-4o` judge access; Python/conda environment. The CellBench data is already present. | Not with the supplied CellBench scripts as-is: they construct an OpenAI client and call hosted OpenAI models/judge. A local OpenAI-compatible rewrite is feasible but altered. | **Conditional admission.** Public task data and repeatable scripts exist, but correctness is an LLM-judge result. Must pin judge model, prompts, outputs and parse failures. | Best next candidate. Buy only a small bounded API budget, then run 2-instance K=4 admission smoke before any larger run. |
| **BioMedAgent / BioMed-AQA** | OpenAI key (`gpt-4o-mini` in the reproduction), Redis, Python 3.9/3.10 environment; optional Docker images for some tools; original benchmark questions/labels/scoring assets. | Yes in principle by redirecting the OpenAI-compatible client to a local server and compiling/running Redis in scratch, but that alters the original model setup. | **Not eligible now.** The public reproduction describes GPT semantic matching, and its native benchmark bundle was not found. | Do not spend API money yet. Run only an exploratory infrastructure smoke if explicitly approved. Contact original authors for released task/label/scorer assets first. |
| **BioMaster** | Node 22, Bun, Python >=3.10, OpenCode, an LLM provider, bioinformatics software/reference data, and a benchmark task/scorer released by authors. | **Yes, likely.** OpenCode supports custom/OpenAI-compatible providers, so a GH200 local serving endpoint can be used. This does not require vendor API credits. | **Not eligible now.** Workflow traces are available, but no simple public deterministic native benchmark scorer is packaged. | Best local-agent engineering target, but first obtain/verify the published 49-task benchmark bundle and scoring instructions. |
| **BRAD** | Python or container runtime, provider key or configured local backend, and a separately chosen benchmark + official scorer. | **Likely yes** with a local compatible endpoint; GPU needs are model-server dependent. | **Not eligible now.** BRAD is an application, not a matched released benchmark/scorer pair. | Keep as backup. Do not buy credits or run a reliability panel until a native evaluation surface is selected. |

## Procurement checklist

### A. Small OpenAI budget — only if choosing CellVoyager

1. Create a dedicated API Platform project for this study.
2. Add a small spend limit and alert (enough for an admission smoke, not a full
   campaign).
3. Create a **standard project API key** with access to the required models.
   Do **not** use an organization admin key.
4. Store it in a mode-600 Vista secret file, never in Git or chat:

   ```bash
   umask 077
   mkdir -p /scratch/11034/atzanakak/secrets
   read -rsp 'OpenAI API key: ' OPENAI_API_KEY; echo
   printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY" \
     > /scratch/11034/atzanakak/secrets/openai.env
   unset OPENAI_API_KEY
   chmod 600 /scratch/11034/atzanakak/secrets/openai.env
   ```

5. Tell the operator only that the file exists; never disclose its contents.

OpenAI recommends a standard API key for application requests and server-side
environment/key-management loading of the secret. [Official OpenAI API
documentation](https://developers.openai.com/api/reference/overview)

### B. Author/contact request — prerequisite for BioMaster or BioMedAgent

Ask the project authors for:

- exact benchmark task IDs/prompts and permitted data download location;
- public ground truth/labels or runnable official scorer;
- evaluation commit/tag corresponding to the paper;
- supported model/provider configuration and expected tool/reference-data
  versions;
- permission/terms for repeated stochastic evaluation and artifact logging.

Without these, an apparent “benchmark” run would be a newly designed task set,
which the v1 protocol explicitly prohibits.

### C. No-cost local exploratory path

For BioMaster first, use a locally served open-weight model behind an
OpenAI-compatible endpoint, retain the native workflow traces, and run a few
public example tasks K=4. This establishes whether the tool installation and
trace adapter work. The output must be labelled **exploratory infrastructure
smoke; no official correctness metric**.

The same is technically possible for CellVoyager or BioMedAgent, but those
results would be more distant from their upstream evaluation setup. Local
substitution is therefore not a replacement for CellVoyager's hosted-model and
hosted-judge result.

## Concrete next-step choices

Choose one:

| Choice | User action | What the project will do next | Cost / scientific value |
|---|---|---|---|
| **1. CellVoyager admission smoke** | Provision the bounded OpenAI project/key above. | Run 2 CellBench examples × K=4, then K=4 judge calls; archive raw and parsed artifacts, calculate v1 report, and stop. | Small API spend; strongest available non-Biomni comparison. |
| **2. BioMaster local engineering smoke** | No credentials needed if a suitable open model is locally staged; otherwise authorize model download. | Install locally in scratch, point OpenCode at local server, run public examples K=4, capture traces; no accuracy/reliability claim. | GPU time only; useful feasibility evidence, not paper-panel evidence. |
| **3. BioMedAgent exploratory smoke** | Provision OpenAI key, or explicitly authorize a local-model substitution; authorize scratch Redis build. | Run one no-Docker demo K=4 and produce execution/failure profile only. | API/GPU cost; low immediate benchmark value. |
| **4. Pause and seek benchmark releases** | Contact BioMaster/BioMedAgent authors using checklist B. | No GPU work until official assets are available. | Lowest cost; protects confirmatory protocol. |

## Sources

- CellVoyager documents its MIT repository, conda environment, OpenAI/Anthropic
  credentials, and public CellBench execution scripts:
  [CellVoyager upstream README](https://github.com/zou-group/CellVoyager).
- BioMedAgent's public reproduction documents GPT-4o-mini API use, Redis,
  optional tool images, and GPT semantic scoring:
  [BioMedAgent reproduction README](https://github.com/JINGEWU/BioMedAgent).
- BioMaster documents its OpenCode provider requirement, Node/Bun/Python
  dependencies, and bioinformatics/reference-data requirements:
  [BioMaster upstream README](https://github.com/ai4nucleome/BioMaster).
- BRAD documents provider-key/Docker setup and local-model hardware separation:
  [BRAD upstream README](https://github.com/Jpickard1/brad).
