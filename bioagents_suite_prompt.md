# Biomedical-Agent Reliability Suite — Implementation and Agent Onboarding

You are continuing an existing research project on **uncertainty and reliability in biomedical AI agents**.

Your job is to move the project forward on the **non-RL / multi-agent evaluation track** using the currently available **single GH200 (~95.6 GiB GPU memory)**.

Do not spend money on model APIs. Do not launch a large benchmark campaign yet.

## Scientific objective

We already have substantial Biomni results showing that repeated-trajectory agreement predicts correctness, while attempts to use uncertainty to correct failures have mostly failed.

The next experiment is to test whether the same reliability structure appears across **genuinely different biomedical agent systems**, not merely different LLMs inside Biomni.

Target panel:

1. Biomni — already evaluated
2. GenoMAS — first priority
3. OpenBioLLM — second priority
4. AutoBA — third priority
5. BioMaster v2 — optional/alternate if it proves easy to reproduce

The main experiment is:

```text
task
→ biomedical agent
→ K=4 independent trajectories
→ native/official scorer
→ standardized reliability analysis
```

We want to measure:

- Pass@1
- plurality accuracy
- Oracle@4
- trajectory agreement
- agreement → correctness AUROC
- risk–coverage / selective prediction
- selection-failure rate
- all-wrong rate
- stable-correct
- stable-wrong
- unstable-recoverable
- unstable-unrecoverable
- execution/tool/context failures
- tokens/runtime when available
- verbal-confidence calibration when naturally available

The scientific question is not simply which agent is most accurate.

It is:

> Do heterogeneous biomedical agents expose useful information about their own reliability through repeated stochastic behavior?

---

# Phase 0 — Inspect the existing repository before changing anything

First inspect the entire current project.

Determine:

- existing Biomni evaluation code;
- trajectory/result schemas;
- official-evaluator wrappers;
- uncertainty/reliability analysis code;
- canonicalization/plurality code;
- AUROC / calibration / risk-coverage utilities;
- experiment manifests;
- provenance conventions;
- existing environments;
- Slurm scripts;
- model-serving infrastructure;
- any partially implemented generic agent abstraction.

Do not unnecessarily rewrite functionality that already exists.

Produce a short internal assessment of:

```text
what can be reused
what needs generalizing
what is missing
```

Then proceed autonomously.

---

# Phase 1 — Build the common reliability interface

Create the thinnest possible common abstraction around heterogeneous agents.

Conceptually it should support something like:

```python
run_agent(task, trajectory_index, config) -> RunResult

score(task, RunResult) -> ScoreResult
```

Do NOT force the agents themselves into a common architecture.

Their native:

- planning;
- tools;
- multi-agent structure;
- code execution;
- retry logic;
- termination rules;
- prompts;

should remain intact.

The common layer exists only for **execution, logging, scoring and reliability analysis**.

A trajectory record should capture at least:

```text
run_id
agent
agent_commit
benchmark
benchmark_commit/version
task_id
trajectory_index
seed

model
model_revision
serving_backend
temperature
top_p
sampling settings

start_time
end_time

raw_final_answer
canonical_final_answer

official_score
official_pass

llm_input_tokens
llm_output_tokens

tool_calls
tool_results
execution_errors

termination_reason
trajectory/artifact paths

verbal_confidence if available

environment provenance
```

Avoid inventing complicated abstractions unless necessary.

Prefer adapters such as:

```text
agents/
    biomni/
    genomas/
    openbiollm/
    autoba/
```

with shared evaluation code outside the agent directories.

---

# Phase 2 — Standardize the reliability calculations

Make sure the common evaluator can compute the same statistics for every agent.

At minimum implement/verify:

### Accuracy

```text
trajectory Pass@1
task plurality accuracy
Oracle@K
```

### Reliability

For K trajectories:

```text
agreement = plurality_count / K
uncertainty = 1 - agreement
```

Compute:

```text
agreement → correctness AUROC
agreement → correctness AUPRC if useful
risk–coverage curve
```

### Failure taxonomy

Assign every task to:

```text
stable_correct
stable_wrong
unstable_recoverable
unstable_unrecoverable
```

Also track separately:

```text
execution_failure
tool_failure
context_failure
timeout
agent_control_failure
other infrastructure failure
```

Do not silently count infrastructure failures as reasoning errors.

Where possible report both:

```text
end-to-end correctness
correctness conditional on successful execution
```

### Selection metrics

Compute:

```text
Oracle@K - plurality_accuracy
```

and explicit selection-failure counts where a correct trajectory existed but the consensus answer was wrong.

Bootstrap statistical intervals by **task**, not individual trajectory.

---

# Phase 3 — GenoMAS first

This is the highest-priority new system.

Repository/project: **GenoMAS**

Benchmark: **GenoTEX**

Reasons:

- genuinely different multi-agent architecture;
- fully local LLM path;
- 1,384 public analysis problems;
- official evaluator;
- good logging/restart characteristics;
- fits the current hardware.

## Setup

Clone/pin the repository and record the exact commit.

Verify:

1. benchmark download;
2. official evaluator;
3. expected output format;
4. local-model configuration;
5. ability to run without any paid API key.

Do not replace the native scorer.

### Model

Preferred initial backbone:

```text
Qwen2.5-Coder-32B-Instruct
```

using an appropriate local backend.

BF16 is preferred if practical on the 95.6 GiB GH200.

However:

- inspect what local serving/model infrastructure already exists;
- do not duplicate massive downloads unnecessarily;
- do not blindly select a serving backend that conflicts with the environment;
- preserve enough memory for the agent's actual workload.

If the repository's documented Ollama route is easiest and reliable, use it.

If the existing project already has a better local server, adapt carefully.

## GenoMAS smoke sequence

Do NOT immediately run hundreds of tasks.

Proceed:

```text
1 task × K=1
↓
verify execution + scorer
↓
3–5 tasks × K=2
↓
verify stochastic independence and logs
↓
~10 tasks × K=4
```

Only after those succeed should you estimate the cost of a 200–256 task K=4 experiment.

Check that independent trajectories actually differ when sampling should be stochastic.

Validate official scores manually on a few examples.

Capture generated code, intermediate files and failure states.

---

# Phase 4 — OpenBioLLM

Second priority.

Use the **IELab/OpenBioLLM agent**, not the similarly named foundation model.

Native architecture includes roles such as:

```text
Router
Evaluator
Generator
Search
BLAST
EUtils
```

Benchmark:

```text
GeneTuring
GeneHop
```

Use the repository's existing automatic evaluation.

Preferred local backbone:

```text
Qwen2.5-Coder-32B-Instruct
```

because this family has already been tested by the project.

## Important external-service issue

NCBI/BLAST/EUtils calls introduce environmental nondeterminism.

For the main uncertainty experiment, investigate adding a cache that records exact external responses.

Goal:

```text
same task
same external biological information
different LLM stochastic trajectory
```

Do not modify the agent's decision about which tool to call.

Only make repeated identical external requests replayable once they have occurred.

Preserve the raw live-response cache so we can later perform a smaller live-service sensitivity experiment.

Use the same smoke sequence:

```text
1 × K=1
3–5 × K=2
~10 × K=4
```

Verify automatic scoring and logging before scaling.

---

# Phase 5 — AutoBA

Third priority.

AutoBA supports local models and is architecturally distinct, but does not have as strong a native objective benchmark.

Start with:

```text
Bio-Task Bench
```

which has deterministic bioinformatics tasks and grading.

Goal: construct a minimal adapter between the benchmark's external-agent contract and AutoBA.

Do NOT modify Bio-Task Bench's grader to make AutoBA look better.

Each trajectory must run in a fresh isolated workspace.

Preferred local backbone:

```text
Qwen2.5-Coder-32B-Instruct
```

through AutoBA's local/Ollama path unless another existing backend is clearly preferable.

Initially try:

```text
1 task × K=1
3–5 tasks × K=2
all or ~10 representative tasks × K=4
```

Since Bio-Task Bench only has ~34 tasks, ultimately running all 34 × K=4 is reasonable if the adapter works.

But do not launch it until the smoke tests are clean.

---

# Phase 6 — BioMaster v2 feasibility check

Do this only after the first three systems are understood.

BioMaster v2 is attractive because its:

```text
PLAN
EXECUTE
DEBUG
CHECK
```

workflow exposes excellent process artifacts.

Check:

- whether the current repository can run fully locally through OpenCode;
- whether a public reproducible benchmark manifest corresponding to the reported 49-task experiment actually exists;
- whether objective scoring can be reproduced;
- repository/license constraints;
- amount of adaptation needed.

If it is straightforward, make it a fourth adapter.

If reproducing the benchmark requires manually reconstructing dozens of tasks, stop and document that rather than spending days rebuilding it.

---

# Phase 7 — Reuse the existing Biomni data

Do not rerun Biomni merely for architectural cleanliness if the existing trajectories contain the required information.

Write an adapter/importer that converts existing Biomni experiment artifacts into the new standardized schema.

Verify that recomputed existing results match the previously established numbers within expected tolerance.

This is an important regression test for the new common suite.

---

# Experimental integrity requirements

## Preserve native behavior

Do not simplify an agent into generic prompting merely to make integration easier.

We are studying **agent systems**, not model APIs.

## Preserve native scoring

Use the official/native scorer whenever one exists.

Any additional canonicalization used for plurality must be separate from official correctness scoring.

## No paid APIs

No OpenAI, Anthropic, Gemini or other paid model calls.

If a candidate unexpectedly requires them, stop that candidate and document the blocker.

## Reproducibility

Freeze:

```text
git commit
benchmark version
model revision/hash
environment
container if used
sampling parameters
random seeds
tool configuration
```

Persist raw outputs.

Never retain only aggregate metrics.

## No benchmark contamination

Do not feed gold answers or grader information into the agent.

Keep scoring entirely downstream of the agent run.

## Sampling

K trajectories should be genuinely independent stochastic samples.

Do not accidentally reuse deterministic seeds, cached model outputs or identical generation state.

## External services

Persist raw responses from public APIs/databases.

We need to know whether variance comes from the model or the environment.

---

# Full experiment is NOT authorized yet

Do not launch:

```text
GenoMAS 200+ × K=4
OpenBioLLM 300 × K=4
large BioAgent Bench runs
```

until the small smokes are complete and the following are known for each agent:

```text
success rate
correctness/scorer sanity
GPU runtime
wall time
token use
disk use
external-service behavior
failure modes
estimated full-run cost
```

The point of this stage is to get the project to a **scientifically validated, ready-to-scale state**.

---

# Expected deliverables

By the end, I want:

## 1. Common reliability suite

Runnable code capable of ingesting heterogeneous biomedical-agent trajectories and computing the common metrics.

## 2. Biomni compatibility

Existing Biomni results successfully imported/recomputed through the new system.

## 3. GenoMAS integration

Ideally fully working through at least a small K=4 smoke.

## 4. OpenBioLLM integration

Ideally fully working through at least a small K=4 smoke.

## 5. AutoBA integration

At minimum a validated Bio-Task Bench adapter and smoke run.

## 6. Optional BioMaster assessment

Clear GO/NO-GO based on actual reproducibility rather than the paper claims.

## 7. Experiment manifest

Create a machine-readable manifest defining:

```text
agent
benchmark
tasks
K
model
model revision
sampling
scorer
environment
```

## 8. Status report

Write a concise report containing:

```text
What was already present

What you implemented

GenoMAS:
- setup status
- scorer status
- smoke results
- failures
- runtime
- full-run estimate

OpenBioLLM:
- same

AutoBA:
- same

BioMaster:
- feasibility / blocker

Common suite:
- implemented metrics
- tests
- compatibility with Biomni

Recommended final agent panel

Exact next command(s) required to launch the next scientifically justified experiment
```

Include paths to all important artifacts.

---

# Decision logic

Prioritize in this order:

```text
1. common suite
2. GenoMAS
3. OpenBioLLM
4. AutoBA
5. BioMaster
```

If a candidate becomes unexpectedly difficult, do not spend unlimited effort forcing it to work.

The purpose is not to reproduce every biomedical-agent paper.

The purpose is to obtain approximately **three genuinely distinct, free-to-run biomedical agents with objective scoring** that can support the same repeated-trajectory uncertainty experiment.

Scientific rigor is more important than number of integrations.

---

# What success looks like

The immediate milestone is something like:

```text
Biomni             → existing full results normalized
GenoMAS            → K=4 smoke works
OpenBioLLM         → K=4 smoke works
AutoBA             → deterministic benchmark adapter works
```

with all four producing records consumable by the same analysis pipeline.

At that point, stop before the expensive campaign and report the exact proposed frozen experiment matrix and estimated compute.

The eventual paper-level question is:

> Across heterogeneous biomedical agents, how often are failures stable versus unstable, how well does repeated-trajectory agreement predict correctness, how much recoverable capability is hidden in Oracle@K, and can uncertainty support reliable selective deployment?

Keep every engineering decision subordinate to answering that question cleanly.