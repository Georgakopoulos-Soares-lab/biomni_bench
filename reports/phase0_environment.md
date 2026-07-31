# Phase 0 — Environment and architecture report

**Date:** 2026-07-31
**Purpose:** record what was actually inspected, what was actually measured, and
every deviation from the assumptions the project brief started from.

---

## 1. Inspected Biomni revision

| field | value |
| --- | --- |
| repository | `https://github.com/snap-stanford/Biomni.git` |
| commit | `400c1f366b96a35ca253e13c9b06c5076af41d65` |
| commit date | 2026-01-14 20:23:42 −0800 |
| subject | Merge pull request #259 from snap-stanford/protocols_database |
| package version | `biomni 0.0.8` |
| installed as | `pip install -e <clone>` — **never edited in place** |
| tool registry | 224 tools across 22 modules |

Pin recorded in `external/BIOMNI_PIN.json`. `patches/` is empty: no upstream
modification was required.

### Files read before any code was written

`README.md`, `DETAILS.md`, `biomni_env/README.md`, `biomni_env/environment.yml`,
`biomni/config.py`, `biomni/llm.py`, `biomni/agent/a1.py` (3001 lines),
`biomni/agent/react.py`, `biomni/model/retriever.py`, `biomni/eval/biomni_eval1.py`,
`biomni/tool/support_tools.py`, `biomni/tool/tool_registry.py`, `biomni/utils.py`,
`biomni/know_how/loader.py`.

---

## 2. Actual agent and callback APIs

The brief assumed a ReAct-style agent with a callback/metadata mechanism. What is
actually there:

### 2.1 The agent is a LangGraph state machine with closure nodes

`A1.configure()` builds a `StateGraph` with two nodes, `generate` and `execute`,
**defined as closures inside `configure()`**. There is no class-level method to
override, so subclassing cannot change the loop. `configure()` is ~350 lines, so
copying it would guarantee drift. This is why instrumentation is adapter-based
(`DECISIONS.md` D-01).

```
START ─► generate ─┬─ <execute>  ─► execute ─┐
                   ├─ <think>    ─► generate │
                   └─ <solution> ─► END      │
                          ▲                   │
                          └───────────────────┘
```

### 2.2 There is no callback or metadata mechanism upstream

Biomni exposes no hooks. Everything observable had to be reached another way:

| signal | mechanism | verified |
| --- | --- | --- |
| LLM requests, token usage, finish reason, sampling params | `BaseCallbackHandler` attached to `agent.llm.callbacks` (the LLM is a LangChain `ChatOpenAI`) | ✅ real usage blocks captured in the smoke test |
| Code execution (python / R / bash) | patch `biomni.agent.a1.run_with_timeout` — the single choke point of the `execute` node | ✅ 16 executions captured in one smoke trajectory |
| Biomni tool calls | `biomni.utils.parse_tool_calls_with_modules` over each `<execute>` block | ✅ `query_gwas_catalog`, `query_ensembl`, `query_pubmed` detected |
| Tool retrieval | wrap `agent.retriever.prompt_based_retrieval` | ✅ start/end events with selection counts |

### 2.3 "Tools" are not structured tool calls

Biomni tools are ordinary Python functions that the model **imports and calls
inside generated code**. There is no tool-call channel, no JSON schema at call
time, and no place to attach per-call metadata. Consequences:

* Tool usage is observed by parsing the generated code — accurate for *which*
  tool was invoked, approximate for arguments (an argument hash of the literal
  call text is stored, never the argument values).
* **Per-step confidence is not implementable cleanly** — it would require a third
  tag in the same free-text channel that already must contain exactly one of
  `<execute>` / `<solution>`. Phase 1 therefore uses final-only confidence and
  labels the SRLM-style selector an approximation (`DECISIONS.md` D-08).

### 2.4 The final answer arrives inside `<solution>`, and generation stops there

`A1.__init__` builds its LLM with `stop_sequences=["</execute>", "</solution>"]`.
Anything the model would emit *after* `</solution>` is never generated. The
confidence block therefore has to be **inside** the solution block
(`DECISIONS.md` D-06). This was determined by reading the source, not by a failed
experiment.

### 2.5 One trajectory per process is mandatory

`biomni.tool.support_tools.run_python_repl` execs generated code into a
**module-global** `_persistent_namespace`. Two trajectories in one interpreter
would share variables. The dispatcher runs each trajectory as its own subprocess
and `runner.run_trajectory` raises if invoked twice in one interpreter.

### 2.6 Setting the model on `A1()` is not enough

`A1(llm=…, source="Custom", base_url=…)` configures the agent's own client. Other
components call `get_llm(config=default_config)` and would otherwise fall back to
`default_config.llm`, which defaults to **`claude-sonnet-4-5`**. `configure_local_only()`
sets both, and every run stores `llm_components.json` with the effective model,
base URL, temperature and stop sequences for the primary agent, the tool
retriever, database helpers and any critic. Job scripts also unset inherited
provider keys, and `run-one` warns if any provider key is present.

---

## 3. Benchmark: what the data actually contains

`biomni/Eval1` → `biomni_eval1_dataset.parquet`, columns
`instance_id, task_instance_id, prompt, task_name, split, answer`.

| task | n | answer format | official scoring |
| --- | --- | --- | --- |
| `crispr_delivery` | 10 | letter a–f | `.lower()` exact |
| `gwas_causal_gene_gwas_catalog` | 50 | gene symbol | `.upper()` exact |
| `gwas_causal_gene_opentargets` | 50 | gene symbol | `.upper()` exact |
| `gwas_causal_gene_pharmaprojects` | 50 | gene symbol | `.upper()` exact |
| `gwas_variant_prioritization` | 43 | rsID | **case-sensitive** exact |
| `lab_bench_dbqa` | 50 | letter in `[ANSWER]…[/ANSWER]` | `.upper()` exact |
| `lab_bench_seqqa` | 50 | letter in `[ANSWER]…[/ANSWER]` | `.upper()` exact |
| `patient_gene_detection` | 50 | `{'causal_gene': [ENSG…]}` | **set intersection** ≥1 |
| `rare_disease_diagnosis` | 30 | `{'disease_name':…, 'OMIM_ID':…}` | `==` on `OMIM_ID` |
| `screen_gene_retrieval` | 50 | gene symbol | `.upper()` exact |
| **total** | **433** | | |

Three findings that changed the implementation:

1. **Every row has `split == "val"`.** There is no held-out split, so the "prefer
   a held-out split" rule is vacuous. The manifest report records
   `held_out_split_available: false`.
2. **`hle` has a scoring branch but zero instances** in this release. The
   canonicalizer supports it; it can never appear in a manifest.
3. **The evaluator takes an already-parsed answer, not a raw response.** Its
   input contract — not its scoring — is what this project must reproduce. Hence
   the canonicalization layer, and a test asserting we call the real
   `BiomniEval1._compute_reward`.

Two scoring subtleties that canonicalization must respect:

* `rare_disease_diagnosis` compares `OMIM_ID` with `==` against a *string*. An
  integer `114300` scores 0. Canonicalization emits a digit string.
* `patient_gene_detection` scores 1.0 for **any** intersection, so a large
  predicted gene set inflates reward. `n_predicted` is retained as a feature and
  this is flagged in the report rather than silently exploited.

---

## 4. Environment setup status

| component | status |
| --- | --- |
| Agent environment | Python 3.12.11 venv; `biomni 0.0.8` editable, langchain / langgraph 0.3.18 / langchain-openai, pandas, pyarrow, scikit-learn, matplotlib, transformers |
| Bio tool dependencies | `biopython`, `PyPDF2`, `gget`, `pybiomart`, `gseapy`, `googlesearch-python` added **after** the first smoke trajectory showed `No module named 'Bio'` / `'PyPDF2'` failures |
| Serving environment | separate venv: `sglang 0.5.16`, `torch 2.11.0+cu130` |
| Biomni data lake | 15 GB, 76 files + benchmark folder, shared read-only |
| Model weights | 131 GB, revision `71432eb…`, on shared scratch |
| Full Biomni E1 environment | **not** installed (>10 h, >30 GB, unnecessary). Residual tool failures are measured and reported. |

The full E1 environment was deliberately skipped. That is a real limitation and
is treated as one: tool failures are counted per trajectory, and "infrastructure
failures dominate biological reasoning failures" is a pre-specified stop
criterion in the protocol.

---

## 5. Local model-serving validation

Launch command actually used (the site-specific paths come from
`configs/cluster.yaml`):

```
python -m sglang.launch_server \
  --model-path <snapshot>/71432eb3d5e583bee757e0f9437a17e711e8e3d1 \
  --host 0.0.0.0 --port 30000 --tp 2 \
  --dtype bfloat16 --mem-fraction-static 0.85 --context-length 65536 \
  --trust-remote-code \
  --json-model-override-args '{"rope_scaling":{"rope_type":"yarn","factor":1.0,"original_max_position_embeddings":32768}, "max_position_embeddings": 131072}'
```

Server report at readiness:

| quantity | value |
| --- | --- |
| weight load | 265.7 s, `Qwen3ForCausalLM`, **30.59 GB per GPU** (confirms bf16) |
| KV cache | 388,668 tokens, 23.72 GB K + 23.72 GB V per GPU |
| `context_len` | **65536** — the override took effect |
| `max_running_requests` | 3036 |
| free GPU memory after warmup | 10.10 GB |

Validation performed against the live endpoint:

* `/v1/models` answers; the served id is the snapshot path.
* A request using the **repo-id** model name (`biomni/Biomni-R0-32B-Preview`),
  which is what Biomni sends, returns HTTP 200. Usage block present
  (`prompt_tokens`, `completion_tokens`, `total_tokens`).
* **Per-request `seed` is NOT honoured.** Two identical requests with
  `seed=12345` at temperature 1.0 produced different text. The endpoint accepts
  the parameter without error, which makes this a silent no-op — exactly the
  case the brief warned about. Every run therefore stores `requested_seed`
  **and** `seed_supported: false`. *Sampling is stochastic and not explicitly
  seeded; we do not claim deterministic reproducibility.*
* The chat template enables thinking by default, so responses contain
  `<think>…</think>`. Biomni's `generate` node already handles `<think>`; no
  change was needed. `reasoning_parser` is left off so Biomni receives raw text.

### Why the context ceiling had to be lifted

Measured with the model's own tokenizer, before spending GPU time:

| prompt | tokens |
| --- | --- |
| Biomni system prompt, pre-retrieval | **43,891** |
| Retrieval prompt (LLM call #1) | 12,460 |
| Post-retrieval system prompt, 25% of tools | 16,949 |
| Post-retrieval system prompt, 50% of tools | 27,199 |
| Post-retrieval system prompt, 100% of tools | 41,010 |

The model's native `max_position_embeddings` is **40,960**. The pre-retrieval
system prompt alone exceeds it, and a typical post-retrieval prompt plus
`max_tokens=8192` leaves under 6k tokens for the whole conversation. Overflow is
demonstrated, so the ceiling is lifted using the model card's own YaRN override
at `factor = 1.0`, which is mathematically the identity on the RoPE frequencies
(interpolation term `inv_freq/1.0`, attention temperature `0.1·ln(1)+1 = 1`).
Full reasoning and the residual extrapolation risk: `DECISIONS.md` D-04.

---

## 6. GPU topology

| field | value |
| --- | --- |
| node | 1 × compute node, Slurm partition `h100` |
| GPUs | 4 × NVIDIA H100, **95,830 MiB each (~96 GB)** |
| driver / CUDA | 590.48.01 / 13.1 |
| CPUs | 96 |
| node-local scratch | 3.5 TB NVMe at `/tmp` |
| shared filesystems | Lustre `/work2` (inode-constrained), NFS `/scratch` |

Layout chosen by `launch_node_servers.sh --layout auto`: **TP2, two replicas per
4-GPU node** (the ≥70 GB branch). At the time of the smoke test GPUs 2–3 were
occupied by an unrelated job of the user's, so the smoke test used GPUs 0–1 as a
single TP2 replica. Nothing about the layout logic changed.

---

## 7. Deviations from the project brief

| brief said | reality | what was done |
| --- | --- | --- |
| Prefer a held-out split | every row is `val` | use `val`, record `held_out_split_available: false` (D-02) |
| Use BF16 official weights | weights ship **FP32, 131 GB** | pass `--dtype bfloat16` explicitly (D-03) |
| Prefer original context behaviour | native 40,960 < Biomni's own system prompt | lift ceiling to 65,536 with the model card's identity YaRN override (D-04) |
| GPUs ≈ 80 GB → TP2 × 2 replicas | 96 GB H100s | same layout; the `auto` threshold is ≥70 GB |
| Two nodes | this session has one node | layout unchanged; `slurm.nodes` is config. One node ⇒ the pilot takes longer |
| Map trajectory indices to seeds | endpoint accepts `seed` but ignores it | seeds requested and recorded; `seed_supported: false` stored per run |
| Consider per-step confidence | no metadata/callback channel exists | final-only; documented, selector labelled an approximation (D-08) |
| `hle` is a task | 0 instances in this release | supported by the canonicalizer, cannot appear in a manifest |
| A1 or "current primary agent class" | `A1`, but graph nodes are closures | adapters, not subclassing (D-01) |

---

## 8. Bugs found during Phase 0

All found by the test suite or by manual inspection of real smoke output, all
fixed and regression-tested.

1. **Gene-symbol parsing.** The candidate-token regex allowed `.` inside a token,
   so `"SON."` failed to match the candidate `SON`; a loose fallback then
   extracted the word `"with"` from prose and returned it as a gene. Fixed:
   strip trailing punctuation, and never fall back to a loose scan when the
   prompt enumerates candidates and none of them appear.
2. **`dict()` over a pandas `GroupBy`** raised `TypeError` (it exposes a `keys`
   attribute, so the mapping protocol is taken). Fixed with `dict(iter(...))`.
3. **Token counts were being redacted.** The event redactor matched the substring
   `token` in *key names*, so `input_tokens` / `output_tokens` / `total_tokens`
   were written as `[REDACTED]`. This silently destroyed the primary length
   signal — the one the SRLM-style selector, the length analysis and the
   confidence × length heatmap all depend on. Found by reading real smoke
   telemetry, not by a test. Fixed by requiring the credential word to sit on a
   token boundary (credential names are singular, `auth_token`; count names are
   plural, `input_tokens`), with a parametrized regression test over every token
   count name and every credential name.

---

## 9. Test status

| check | result |
| --- | --- |
| `pytest -q` | **~215 passed**, CPU only, no GPU, no data lake |
| `ruff check src tests` | clean |
| `ruff format --check src tests` | clean |
| Import check in the Biomni environment | OK — `biomni 0.0.8`, 224 tools, 22 modules |
| Manifest dry run | OK — 50 instances, exactly 5 per task, stable hash |
| Mock end-to-end | 20 passed; fake OpenAI endpoint + fake benchmark + full pipeline + 13 figures |
| GPU smoke test | see `reports/phase1_protocol.md` |
