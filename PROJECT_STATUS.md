# PROJECT_STATUS

**Last updated:** 2026-07-31
**Phase:** Phase 0 complete through step 8; GPU smoke test in progress (step 9).

---

## Completed

### Step 1 — Inspection
- Cloned Biomni, pinned at `400c1f366b96a35ca253e13c9b06c5076af41d65`
  (2026-01-14, package version `0.0.8`). Recorded in `external/BIOMNI_PIN.json`.
- Read and verified against the checked-out source: `README.md`,
  `biomni/config.py`, `biomni/llm.py`, `biomni/agent/a1.py` (3001 lines),
  `biomni/model/retriever.py`, `biomni/eval/biomni_eval1.py`,
  `biomni/tool/support_tools.py`, `biomni/utils.py`, `biomni_env/`.
- Architecture found (differs from the brief's assumptions in several places —
  all recorded in `DECISIONS.md`):
  - `A1` is a **LangGraph `StateGraph`** with two nodes, `generate` and
    `execute`, defined as **closures inside `A1.configure()`** — so subclassing
    cannot override them.
  - The LLM is a LangChain `ChatOpenAI` built with
    `stop_sequences=["</execute>", "</solution>"]`. Final answers arrive inside
    `<solution>…</solution>`.
  - "Tools" are plain Python functions called **inside generated code**, not
    structured tool calls. There is no tool-call channel to attach metadata to.
  - `run_python_repl` execs into a **module-global namespace** ⇒ one trajectory
    per process.
  - The tool retriever is called with `llm=self.llm`, so it shares the agent's
    client — but `default_config` must also be set, because other components
    build their own client from it.

### Step 2 — Scaffolding
- Repository `biomni-uncertainty` with validated Pydantic config, provenance
  capture, dev tooling.
- `patches/` is **empty**: no upstream edit was required.

### Step 3 — Benchmark integration
- BiomniEval1 loaded via the official interface. **433 instances, 10 tasks,
  every row `split == "val"`** (no held-out split exists — `DECISIONS.md` D-02).
- Deterministic keyed-hash balanced sampling with documented redistribution.
- Task-aware canonicalization for all 10 release tasks + `hle`
  (evaluator-supported, 0 instances in this release).

### Step 4 — Instrumentation
- LangChain callback (LLM telemetry from endpoint `usage`), `run_with_timeout`
  patch (code execution), retriever wrap. Redacted append-only JSONL events.
- Per-run isolation, atomic markers, resumption with a validity check that
  rejects a `COMPLETE` marker whose artifacts are missing.

### Step 5 — Confidence elicitation
- Final-only confidence, emitted **inside** `<solution>` (it would otherwise
  never be generated — the stop sequence cuts generation at `</solution>`).
- Injected through the **system prompt**, so the benchmark prompt is
  byte-identical between conditions A and B.
- Per-step confidence **not implemented**; the reason is architectural
  (`DECISIONS.md` D-08), and the SRLM-style selector is labelled an
  approximation everywhere.

### Step 6 — Evaluation and selectors
- Wrapper around the **real** `BiomniEval1._compute_reward` (asserted by test).
- All 10 pre-specified selectors + the exploratory grouped-CV learned selector.
- Oracle@K over all size-K subsets and over first-K prefixes, both labelled.

### Step 7 — Aggregation and analysis
- Deterministic Parquet + CSV aggregation; frozen statistics; 13 figures, each
  with a machine-readable table.
- Validated end-to-end on mock data.

### Step 8 — Local model serving
- SGLang 0.5.16 / torch 2.11.0+cu130 in a separate serving environment.
- Model downloaded: 131 GB, revision `71432eb…`.
- Two serving facts established **before** spending GPU time:
  - weights ship **FP32** ⇒ `--dtype bfloat16` is mandatory (D-03);
  - Biomni's system prompt is **43,891 tokens** pre-retrieval and 17k–41k
    post-retrieval, against a native context of **40,960** ⇒ the context ceiling
    must be lifted (D-04).
- Startup validation prints and stores the effective model/endpoint for the
  primary agent, tool retriever, database helpers and any critic
  (`llm_components.json` per run).

### Step 10 (partial) — Manifest frozen
- `manifests/phase1.jsonl` — 50 instances, exactly 5 per task across all 10 tasks.
- **Manifest hash:** `44854f87b3a0d2e0c00bf4fe06c8879e5636b8a470b8803a5b3e6a2db850fff9`
- **Run manifest hash:** `894aeb948a27becdbd1e0d11210954cef59fb604345cc014e5f9c33b9ddad606`
- 250 planned runs (200 instrumented + 50 standard). No exclusions.
- Ground truth in a separate file, never handed to the agent.

---

## Current blockers

None blocking. One environmental constraint:

- This session holds **one** node (4 × H100 96 GB), not two. GPUs 2–3 are
  occupied by an unrelated job of the user's, so the smoke test uses GPUs 0–1
  as a single TP2 replica. The two-node path is implemented and configurable
  (`slurm.nodes`); with one node the pilot simply takes longer.

---

## Tests run

| check | result |
| --- | --- |
| `pytest -q` | **210 passed** |
| `ruff check src tests` | clean |
| `ruff format --check src tests` | clean |
| Import check inside the Biomni environment | OK — `biomni 0.0.8`, 224 tools across 22 modules |
| Manifest dry run | OK — 50 instances, 5 per task, hash stable across repeated runs |
| Mock end-to-end (fake endpoint + fake benchmark + full pipeline) | **20 passed**, 13 figures generated |
| GPU smoke test | **in progress** |

Bugs found and fixed by the test suite (both real, both now regression-tested):
1. Gene-symbol candidate matching failed on trailing punctuation (`"SON."`), and
   a loose fallback then extracted the word `"with"` from prose. Fixed: strip
   trailing punctuation; never invent an answer when the prompt enumerates
   candidates and none appear.
2. `dict()` over a pandas `GroupBy` raised `TypeError` (it exposes a `keys`
   attribute, so the mapping protocol is taken). Fixed with `dict(iter(...))`.

---

## Active experiment IDs

| id | config | state |
| --- | --- | --- |
| `smoke` | `configs/smoke.yaml` | GPU smoke test running (6 runs: 2 instances × (2 instrumented + 1 standard)) |
| `phase1` | `configs/phase1.yaml` | **frozen, not launched** — awaiting approval (250 runs) |

---

## Known failures

None yet from real runs. Anticipated and instrumented for:

- Biomni tools whose Python dependencies are absent in this lightweight
  environment will fail inside trajectories. These are recorded as tool failures
  and will be reported in the infrastructure section of the Phase-1 report, not
  hidden. If infrastructure failures dominate biological reasoning failures, that
  is itself a Phase-1 stop criterion.
- Positions above 40,960 are reached by extrapolation (D-04). `finish_reason` is
  captured per LLM call so truncation surfaces in the results.

---

## Next actions

1. Finish the GPU smoke test; inspect logs and outputs by hand.
2. Write `reports/phase0_environment.md` with the real endpoint validation and
   GPU topology.
3. Write `reports/phase1_protocol.md` (frozen manifest hash, conditions, primary
   metrics, selectors, analysis plan, limitations) **before** the pilot.
4. Print the planned run count, GPU layout and any unresolved cluster
   placeholders, then **pause for approval** before launching the 250-run pilot.
5. After approval: launch, monitor, resume if needed, aggregate, run the frozen
   analysis, complete `reports/phase1_report.md`.
