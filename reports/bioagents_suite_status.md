# Biomedical-Agent Reliability Suite — implementation status

**Updated:** 2026-08-25. This report records an admission assessment and code
readiness only. No non-Biomni model trajectory, paid API call, benchmark-scale
job, or data download was launched.

## What was already present

The repository already contained a well-factored Biomni pipeline: native
`BiomniEval1` scoring, parsed/canonical final answers, run artifacts, manifest
and provenance machinery, and task-level bootstrap analysis. It also already
had the first version of the agent-agnostic evaluator in
`src/biomni_uncertainty/reliability.py`.

## What was implemented

- Extended the common evaluator with agreement-to-correctness AUPRC,
  agreement-based risk--coverage, explicit selection-failure counts, and
  typed infrastructure-failure counts.
- Corrected the taxonomy boundary: an instance with no evaluable native score
  remains in failure accounting and receives no reasoning taxonomy label.
- Added a non-invasive Biomni importer at
  `src/biomni_uncertainty/adapters/biomni.py` and command-line wrapper
  `scripts/import_biomni_reliability.py`. It consumes already-scored Biomni
  trajectory tables; it never reruns the agent or reimplements the scorer.
- Staged detached, pinned source snapshots outside the project repository:
  GenoMAS `d6365a7`, OpenBioLLM `77877d8`, and AutoBA `a9f8f12`.
- Added the machine-readable frozen admission manifest:
  `configs/reliability_suite_v1.yaml`.

## Candidate status

| Agent | Native scorer | Smoke status | Gate |
| --- | --- | --- | --- |
| GenoMAS / GenoTEX | `GenoMAS/eval.py` is present | Not run | Input data are a separately hosted ~42 GB bundle; local Ollama model service and a data checksum are also required. |
| OpenBioLLM / GeneTuring + GeneHop | `openbiollm/evaluate.py` is present | Not run | Local model endpoint required. Three task families route through an Ollama LLM judge, and Search/NCBI calls need a cache/provenance design before repeated sampling. |
| AutoBA / Bio-Task Bench | Bio-Task Bench has a deterministic harness grader | Not run | AutoBA has an Ollama path, but no existing Bio-Task Bench adapter; every trajectory must get an isolated tool workspace. |
| BioMaster | No matched objective benchmark/scorer established | Not run | No-go for v1 unless the published task bundle and deterministic scorer are released. |

## Recommended panel and next commands

The evidence supports **Biomni + GenoMAS + an OpenBioLLM deterministic-scored
subset** as the potential confirmatory panel, conditional on the gates above.
AutoBA remains an engineering/comparator target until its Bio-Task Bench
adapter smoke completes. Do not pool OpenBioLLM's LLM-judged task families into
the confirmatory deterministic-score analysis.

After the GenoTEX bundle has been deliberately obtained and checksummed and a
local endpoint is running on a Slurm GPU allocation, the next justified command
is a single native GenoMAS trajectory:

```bash
cd /work/11034/atzanakak/biomni_bench/external_agents/GenoMAS
python main.py --version suite_smoke_k1 --model <local-ollama-model> --quick-test --data-root <validated-genotex-root>
```

After a pre-existing Biomni `instrumented.csv` with four trajectories per task
is identified, normalize and recompute it without rerunning Biomni:

```bash
cd /work/11034/atzanakak/biomni_bench/biomni-uncertainty
python scripts/import_biomni_reliability.py <instrumented.csv> \
  --records runs/reliability_suite/biomni.records.jsonl \
  --report runs/reliability_suite/biomni.report.json --k 4
```

The locally retained ablation tables are one trajectory per task/arm, so they
are useful importer fixtures but cannot truthfully validate K=4 agreement or
Oracle metrics.
