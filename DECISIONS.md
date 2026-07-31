# Design decisions

Each entry records what was decided, what was considered instead, and why.
Decisions made *after* seeing results are marked as such; none of the entries
below were.

---

## D-01 Wrapper repository, no upstream edits

**Decision.** Biomni is used as a pinned dependency (`pip install -e` from a
clone at a recorded commit). Every behavioural change is an *adapter*: a
LangChain callback, an instance-level method wrap, or a module-attribute patch
inside the already-imported `biomni.agent.a1` namespace. `patches/` is empty.

**Alternatives.** (a) Fork Biomni and edit `a1.py` directly. (b) Subclass `A1`
and override `configure()`.

**Why.** (a) makes the experiment un-reproducible against upstream and invites
drift. (b) would require duplicating ~350 lines of `configure()` — the graph
nodes are closures defined inside it — which is exactly the kind of copy that
silently diverges. The three things we need to observe (LLM calls, code
execution, retrieval) each have a single clean interception point, so adapters
suffice.

**Interception points, verified against commit `400c1f3`:**

| signal | mechanism |
| --- | --- |
| LLM requests, tokens, finish reason | `BaseCallbackHandler` on `agent.llm.callbacks` |
| Code execution (python/R/bash) | patch `biomni.agent.a1.run_with_timeout` — the single choke point of the graph's `execute` node |
| Biomni tool calls | `biomni.utils.parse_tool_calls_with_modules` over each `<execute>` block |
| Tool retrieval | wrap `agent.retriever.prompt_based_retrieval` |

---

## D-02 The benchmark has no held-out split

**Decision.** Sample from `split == "val"`, and record that no held-out split
exists.

**Finding.** The `biomni/Eval1` parquet has 433 rows across 10 tasks and
**every row has `split == "val"`**. `BiomniEval1.get_task_stats` counts a
`train` split that contains zero rows in this release.

**Consequence.** There is no train/test separation to preserve, so the
"prefer a held-out split" rule is vacuous here. The manifest report records
`held_out_split_available: false` so this cannot be misread later.

---

## D-03 Serve the model in bfloat16, explicitly

**Decision.** Always pass `--dtype bfloat16` to SGLang.

**Finding.** `biomni/Biomni-R0-32B-Preview` ships its weights in **FP32**:
`model.safetensors.index.json` reports `total_size = 131,048,493,056` bytes
(131 GB) across 27 shards, and the shard headers are `F32`. `config.json` says
`"torch_dtype": "float32"`.

**Why it matters.** The command on the model card and in Biomni's README omits
`--dtype`, so SGLang follows `config.json` and tries to allocate ~131 GB of
weights (~65 GB per GPU at TP2) before any KV cache. `--dtype bfloat16` halves
that to 65.5 GB total (32.8 GB per GPU at TP2), which is the intended serving
precision for a model whose base is Qwen3-32B.

**Not done.** No weight quantization. Phase 1 uses full official weights so that
calibration, trajectory diversity and tool-use behaviour are not confounded.

---

## D-04 Context length: 65536, with the model card's YaRN override at factor 1.0

**Decision.** Serve with `--context-length 65536` and the model card's
`--json-model-override-args '{"rope_scaling":{"rope_type":"yarn","factor":1.0,
"original_max_position_embeddings":32768}, "max_position_embeddings": 131072}'`.

**Measurement that forced this** (tokenized with the model's own tokenizer):

| prompt | tokens |
| --- | --- |
| Biomni system prompt, pre-retrieval (all 224 tools, 76 data-lake items, all know-how) | **43,891** |
| Retrieval prompt sent on LLM call #1 | 12,460 |
| Post-retrieval system prompt, 25% of tools selected | 16,949 |
| Post-retrieval system prompt, 50% of tools selected | 27,199 |
| Post-retrieval system prompt, 100% of tools selected | 41,010 |

The model's native `max_position_embeddings` is **40,960**. The pre-retrieval
system prompt alone already exceeds it. Even after retrieval, a 27k-token system
prompt plus `max_tokens = 8192` leaves under 6k tokens for the entire
conversation — one or two steps. Biomni's retrieval prompt explicitly instructs
the model to "be generous" and to "include as many database tools as possible",
so large selections are the expected case, not the tail.

So the preference for "original context behaviour unless overflow is
demonstrated" resolves to: overflow *is* demonstrated, before any GPU time was
spent.

**Why factor 1.0 is not a context-extension hack.** With YaRN at `factor = 1.0`
the transform is the identity on the RoPE frequencies: the interpolation term is
`inv_freq / 1.0 = inv_freq`, the extrapolation term is `inv_freq`, so blending
them returns `inv_freq` unchanged; and the attention temperature is
`0.1·ln(1.0) + 1 = 1.0`. Nothing about short-trajectory behaviour changes. The
override only lifts the position ceiling. This is also the exact command
published on the model card and in Biomni's README.

**Residual risk, recorded honestly.** Positions between 40,960 and 65,536 were
not seen during training and are reached by pure extrapolation. This is an
**experimental parameter** and is listed as such in `reports/phase1_protocol.md`.
Trajectories are instrumented with `finish_reason`, so truncation shows up in the
results rather than hiding.

**Rejected.** `factor > 1.0` — the model card warns it "might degrade
performance on tasks with shorter trajectories", which is most of this benchmark.

---

## D-05 Two Python environments

**Decision.** A serving environment (SGLang + its pinned torch) and an agent
environment (Biomni + LangChain + this package) are separate virtualenvs.

**Why.** SGLang pulls a specific torch/CUDA stack and a large transitive
closure. Sharing one environment means a serving upgrade can silently change the
agent's `transformers`/`langchain` versions mid-experiment. The dispatcher passes
`--python` explicitly, so which interpreter runs a trajectory is recorded, not
inferred.

---

## D-06 The confidence block goes *inside* `<solution>`

**Decision.** The elicitation instruction asks for the confidence block after
the task answer but **within** the same `<solution>` block.

**Why it cannot go after.** `A1.__init__` builds its LLM with
`stop_sequences=["</execute>", "</solution>"]`. Generation halts at
`</solution>`, so a confidence block placed after the closing tag would never be
generated at all.

**Protection of the task answer.** `parse_final_response` strips the confidence
block *before* the task answer is parsed, so a malformed or duplicated block
cannot corrupt answer extraction. There is a test for exactly this
(`test_malformed_confidence_still_yields_answer`).

---

## D-07 Confidence is injected via the system prompt, not the task prompt

**Decision.** The instruction is appended to Biomni's system prompt by wrapping
`agent._generate_system_prompt`, so the benchmark prompt handed to the agent is
byte-identical between conditions A and B.

**Why.** Condition A exists to measure whether elicitation perturbs task
performance. If the elicitation text were appended to the task prompt, the two
conditions would differ in the task prompt itself and `prompt_hash` would no
longer be comparable. The wrap (rather than a one-time string append) is
necessary because `A1.go` regenerates the system prompt after tool retrieval.

---

## D-08 Per-step confidence is NOT implemented in Phase 1

**Decision.** `confidence.mode` supports `none | final_only | per_step`, but
Phase 1 runs `final_only`. `per_step` is not implemented.

**Why.** Biomni has no structured tool-call channel to attach metadata to. Every
step is free text that must contain exactly one of `<execute>` or `<solution>`,
and the LLM is stopped at those tags. Eliciting a per-step confidence would mean
introducing a third tag into the same free-text channel — precisely the "brittle
prompt parsing / modification of tool-call syntax" that the protocol says not to
force. There is no callback or metadata mechanism upstream that carries it.

**Consequence for the SRLM-style selector.** Only final confidence is available,
so the selector is labelled **"SRLM-style final-confidence approximation"**
everywhere, and is explicitly not a reproduction of step-level SRLM.

**Not done.** A post-hoc confidence probe (re-asking the model after the fact)
was considered and skipped for Phase 1. If it is added later it must never be
described as contemporaneous self-verbalized confidence.

---

## D-09 One trajectory per process

**Decision.** The dispatcher runs each trajectory as a `cli run-one` subprocess,
and `runner.run_trajectory` raises if called twice in one interpreter.

**Why.** `biomni.tool.support_tools.run_python_repl` execs generated code into a
**module-global** `_persistent_namespace`. Two trajectories in one process would
share variables, so one trajectory could read or overwrite another's state. The
process `cwd` is also moved into `<run_dir>/artifacts` so files the agent writes
land inside its own run directory.

---

## D-10 Canonicalization normalizes, and reports what the normalization bought

**Decision.** Each parse keeps both the canonical answer (sent to the official
evaluator) and the raw extracted token. Both are scored; `reward` and
`strict_reward` are stored side by side.

**Why.** The official evaluator's semantics differ per task — `.upper()` for gene
symbols, `.lower()` for the CRISPR letter, but a **case-sensitive** `==` for
rsIDs, and `==` on a string OMIM id. Normalizing the rsID prefix to lowercase, or
coercing an integer `OMIM_ID` to a digit string, grants credit that a literal
string comparison would not. Rather than argue about whether that is fair, both
numbers are computed and the difference is reportable.

**Ground truth is never consulted** to resolve an ambiguous prediction. Where the
benchmark prompt enumerates the legal options, that option list is used for
disambiguation — it comes from the prompt, which the agent also saw.

---

## D-11 Unparseable answers are singleton clusters

**Decision.** A trajectory with no parseable answer forms its own agreement
cluster keyed by `run_id`.

**Alternative.** Pool all unparseable trajectories into one cluster.

**Why.** Pooling would manufacture consensus: four trajectories that each failed
in a different way would look like unanimous agreement and could win a plurality
vote. `n_unparseable` is reported per instance.

---

## D-12 Failed answer parsing is an agent failure; a failed evaluator is not

**Decision.** A completed trajectory whose answer cannot be parsed scores 0.0
with status `unparseable_answer`. An evaluator *exception* yields `reward = None`
with status `evaluator_failure`.

**Why.** The first is a substantive result — the agent did not produce a usable
answer — and belongs in the accuracy denominator. The second is infrastructure
breakage and must not be silently laundered into a wrong answer, which would bias
every downstream comparison.

---

## D-13 Resampling unit is the task instance

**Decision.** All bootstrap intervals resample task instances. Trajectory-level
association analyses use a cluster (grouped) bootstrap over instances, and the
exploratory learned selector uses `GroupKFold` on the instance.

**Why.** The K trajectories of one instance share a prompt, a task and a
difficulty; treating them as 200 independent observations would shrink every
interval by roughly a factor of two.

---

## D-14 Retries never hide the original failure

**Decision.** Only failure classes in
`execution.retry_policy.retryable_failure_classes` (model server, model timeout,
external resource) are re-queued. Both the failed and the retried attempt are
recorded, and failed run directories are never deleted.

**Why.** Automatically retrying a substantive agent failure and keeping only the
success would silently inflate measured accuracy and destroy exactly the failure
signal Phase 1 is trying to characterise.

---

## D-15 File-per-run records, not a shared database

**Decision.** Each run writes its own directory; aggregation is a separate,
deterministic pass into Parquet + CSV.

**Why.** SQLite on a shared network filesystem corrupts under concurrent writers.
Completion markers are written temp-file-plus-rename, and a `COMPLETE` marker is
only trusted when the required artifacts are present *and* `metadata.json` says
`completed: true` — which prevents an interrupted copy-back from being mistaken
for a finished run.

---

## D-16 Deviations from the original brief

| brief assumption | reality | handling |
| --- | --- | --- |
| Held-out split exists | all rows are `val` | D-02, recorded in the manifest report |
| 4 GPUs ≈ 80 GB → TP2 × 2 replicas | 96 GB H100s | same layout; the launcher's `auto` threshold is ≥ 70 GB |
| Two nodes available | this session has one node | layout is unchanged (TP2 × 2 replicas); with one node the pilot simply takes longer. `slurm.nodes` is a config value. |
| Prefer native context | native 40,960 is too small for Biomni's own system prompt | D-04, measured before any GPU time |
| Model served in BF16 | weights ship as FP32 | D-03 |
| `hle` is a benchmark task | supported by the evaluator, **0 instances** in this release | canonicalizer supports it; it cannot appear in the manifest |
