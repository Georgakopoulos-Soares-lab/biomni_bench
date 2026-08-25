# biomni-uncertainty

**Do biomedical agents know when they are wrong?**
Phase 1: intrinsic uncertainty signals in Biomni trajectories.

## Reliability Suite v1

The reusable, agent-agnostic reliability layer is frozen in
[reports/reliability_suite_v1.md](reports/reliability_suite_v1.md). Its core
evaluator is `biomni_uncertainty.reliability`; adapters retain native scoring,
canonicalization, execution, and provenance. Candidate readiness and the
strict no-large-run gate are in [reports/candidate_agent_audit.md](reports/candidate_agent_audit.md).

---

## Scientific objective

Biomedical agents such as [Biomni](https://github.com/snap-stanford/Biomni) plan
analyses, retrieve resources, call biomedical tools, execute code and produce
scientific conclusions. Repeated runs on the same task follow different
workflows and reach different answers. The long-term goal is an agent that
recognises unreliable analyses, reconsiders weak workflows, spends more
computation where it helps, and abstains when it should.

Before building any such controller, one empirical question has to be answered:

> Can inexpensive intrinsic signals from multiple Biomni trajectories identify
> which biomedical-agent outputs are reliable?

## What Phase 1 tests

| RQ | Question |
| --- | --- |
| RQ1 | **Oracle headroom.** When the first trajectory is wrong, how often is at least one of K=4 correct? |
| RQ2 | **Self-consistency.** Does agreement predict correctness? Does plurality voting beat a single run? |
| RQ3 | **Verbalized confidence.** Is stated confidence associated with correctness? Is it calibrated? |
| RQ4 | **Behavioural uncertainty.** Are tokens, steps, tool calls, retries, failures and runtime associated with correctness? |
| RQ5 | **Trajectory selection.** Can simple selectors beat first / random / plurality? |
| RQ6 | **Task dependence.** Do the relationships differ across biomedical task types? |
| RQ7 | **Prompt perturbation.** Does the confidence request change underlying task performance? |

These are hypotheses, not expectations. In a biomedical agent a longer trajectory
may signal uncertainty *or* appropriate thoroughness; stated confidence may be
miscalibrated; agreement may reflect correlated errors. A negative result is a
result.

## Design at a glance

* **Condition A (standard)** — 1 unmodified Biomni trajectory per instance.
* **Condition B (instrumented)** — 4 trajectories per instance with a final
  confidence request and full telemetry.
* 50 instances balanced across all 10 BiomniEval1 tasks → **250 trajectories**.
* Local Biomni-R0-32B served with SGLang. No proprietary API is ever called.

---

## Repository setup

```bash
git clone <this repo> biomni-uncertainty
cd biomni-uncertainty
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then edit; .env is gitignored
cp configs/cluster.example.yaml configs/cluster.yaml   # then edit
```

### Biomni environment

Biomni is used as a **pinned dependency**, never edited in place
(see [DECISIONS.md](DECISIONS.md) D-01). Clone it at a recorded commit and
install it editable into the same environment:

```bash
git clone https://github.com/snap-stanford/Biomni.git "$BIOMNI_SRC"
git -C "$BIOMNI_SRC" checkout <PINNED_COMMIT>     # see external/BIOMNI_PIN.json
pip install -e "$BIOMNI_SRC"
```

Biomni's own `biomni_env/setup.sh` builds the full E1 bioinformatics
environment; it takes >10 h and >30 GB and is **not** required to run this
pipeline. Tools whose Python dependencies are absent fail inside a trajectory and
are recorded as tool failures — which is itself measured, and reported in the
infrastructure section of the Phase-1 report rather than hidden.

The data lake (~15 GB, 76 files) and benchmark files download once into
`$BIOMNI_PATH/biomni_data/` and are shared read-only across trajectories.

### Local Biomni-R0 setup

```bash
python -m venv "$SERVER_ENV"        # separate env: see DECISIONS.md D-05
"$SERVER_ENV/bin/pip" install "sglang[all]"
huggingface-cli download biomni/Biomni-R0-32B-Preview --revision <REVISION>
```

Two facts about this model drive the serving configuration and are **not**
obvious from the model card (both in [DECISIONS.md](DECISIONS.md)):

* the weights ship in **FP32 (131 GB)**, so `--dtype bfloat16` must be passed
  explicitly (D-03);
* Biomni's own system prompt is **larger than the model's native 40,960-token
  context**, so the context ceiling has to be lifted (D-04).

---

## Running the pipeline

### 1. Inspect the environment

```bash
python -m biomni_uncertainty.cli inspect-env --output reports/environment.json
```

### 2. Freeze the manifest

```bash
python -m biomni_uncertainty.cli prepare-manifest --config configs/phase1.yaml
python -m biomni_uncertainty.cli expand-runs --config configs/phase1.yaml \
       --manifest manifests/phase1.jsonl
```

`prepare-manifest` prints the selection counts, prompt-length summary,
exclusions and a stable manifest hash, and writes **two** files: the
agent-visible manifest and a separate ground-truth file that is never passed to
the agent.

### 3. CPU / mock tests (no GPU, no data lake)

```bash
pytest -q
ruff check src tests && ruff format --check src tests
python -m biomni_uncertainty.cli prepare-manifest --config configs/phase1.yaml --dry-run
```

### 4. GPU smoke test

Two instances from different task types, two instrumented trajectories each plus
one standard trajectory — six runs, one endpoint, real evaluation, real plots.

```bash
scripts/run_smoke.sh configs/cluster.yaml configs/smoke.yaml     # interactive node
# or
sbatch --account=$A --partition=$P --nodes=1 --gres=gpu:4 --time=02:00:00 \
       slurm/smoke.sbatch configs/cluster.yaml configs/smoke.yaml
```

**Do not launch the 50-instance pilot until this succeeds.**

### 5. Two-node launch

```bash
scripts/run_phase1.sh configs/cluster.yaml configs/phase1.yaml --dry-run  # inspect
scripts/run_phase1.sh configs/cluster.yaml configs/phase1.yaml
```

The launcher inspects GPU memory and chooses **TP2 × 2 replicas per node** on
≥70 GB GPUs (TP4 × 1 below that), binds each replica to explicit CUDA devices and
distinct ports, waits until every replica answers `/v1/models`, and only then
starts the dispatcher. See [slurm/README.md](slurm/README.md).

### 6. Resumption

Re-submit the same command. Runs with a *valid* `COMPLETE` marker are skipped;
only transient infrastructure failures are re-queued. Substantive agent failures
are preserved and never silently retried.

```bash
python -m biomni_uncertainty.cli status --config configs/phase1.yaml
```

### 7. Aggregation and analysis

```bash
scripts/aggregate_results.sh configs/phase1.yaml
scripts/analyze_phase1.sh   configs/phase1.yaml
```

---

## Output locations

```
runs/<experiment_id>/
  runs/<task>/i<instance>/<condition>/t<k>/
      metadata.json      run record (identity, provenance, timing, statistics, output)
      config.json        config snapshot
      run_spec.json      exactly what was requested
      events.jsonl       append-only trajectory event log (redacted)
      final_response.txt raw final response, verbatim
      parsed_answer.json confidence + solution-block + parsed answer, every stage
      transcript.json    full message transcript
      system_prompt.txt  the effective system prompt
      llm_components.json effective model/endpoint for every LLM subcomponent
      stdout.log / stderr.log
      artifacts/         anything the agent wrote (its cwd during the run)
      COMPLETE | FAILED  atomic completion marker
  results/
      tables/*.parquet, *.csv
      figures/*.png      each with a matching tables/*.csv
      analysis.json
manifests/
  phase1.jsonl              agent-visible: prompts, NO answers
  phase1.groundtruth.jsonl  answers, evaluator only
  phase1_runs.jsonl         one line per planned trajectory
reports/
  phase0_environment.md, phase1_protocol.md, phase1_report.md
```

## Limitations

* **50 instances, 250 trajectories.** A pilot. Intervals are wide and per-task
  cells hold ~5 instances. Nothing here supports a strong claim.
* **One agent, one model.** Findings may not transfer to another biomedical
  agent or another backbone.
* **Final-answer correctness only.** A correct answer reached through an invalid
  workflow scores the same as a sound one. Workflow validity is not assessed —
  that needs the human expert annotation deferred to Phase 2.
* **Final-only confidence.** Per-step confidence is not collected; the reason is
  architectural, not an oversight (DECISIONS.md D-08). The SRLM-style selector is
  therefore an approximation and is labelled as one everywhere.
* **Sampling is stochastic; seeds are requested, not guaranteed.** Whether the
  endpoint honours a per-request `seed` is probed at run time and stored as
  `seed_supported`. We do not claim deterministic reproducibility.
* **Oracle@K is an upper bound**, not a method. It reads ground truth.
* **External databases.** Biomni tools query live biomedical databases, so a
  trajectory's result can depend on when it ran. This is recorded separately
  from LLM usage.

## Security considerations

* Only public benchmark data. No patient data, real or synthetic.
* **No proprietary LLM API is called.** Every LLM path — the agent, the tool
  retriever, database helpers — is pointed at the local endpoint, the effective
  configuration is printed and stored per run (`llm_components.json`), and the
  job scripts unset inherited provider keys. A run warns loudly if a provider key
  is present in the environment.
* Event logs are redacted: pattern-based secret removal, wholesale redaction of
  secret-bearing keys, and literal removal of any credential-looking environment
  value. No full environment dump is ever written into an event.
* Ground truth lives in a separate file that is never handed to the agent, and is
  never used to select pilot instances or to resolve an ambiguous prediction.
* Generated biomedical code runs as the invoking user (never root), in a
  per-trajectory working directory, under a configurable wall-clock timeout.
* Model weights, the data lake, `.env` and `configs/cluster.yaml` are gitignored.

## Repository layout

| path | contents |
| --- | --- |
| `src/biomni_uncertainty/` | the package (config, benchmark, sampling, canonicalization, confidence, instrumentation, events, runner, dispatcher, evaluation, selectors, features, aggregation, analysis, plotting, provenance, cli) |
| `configs/` | `base` / `smoke` / `phase1` experiment configs, `cluster.example.yaml` |
| `scripts/` | environment inspection, manifest, server launch, health wait, smoke, pilot, aggregation, analysis |
| `slurm/` | job scripts with no site-specific directives |
| `tests/` | pytest suite (CPU-only, no data lake required) |
| `reports/` | Phase-0 environment, frozen Phase-1 protocol, Phase-1 report |
| `patches/` | upstream patches — **empty**, by design |

See [DECISIONS.md](DECISIONS.md) for why things are the way they are, and
[PROJECT_STATUS.md](PROJECT_STATUS.md) for current state.
