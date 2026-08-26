# GenoMAS K=4 pilot v1 — preregistration (NOT LAUNCHED)

Status: **`PREREGISTERED_NOT_LAUNCHED`**. No K=4 trajectory has been started.
This document, plus the machine-readable manifest at
`/scratch/11034/atzanakak/genomas_admission/genomas_k4_pilot_v1_20260826_preregistration_manifest.json`,
freezes every protocol parameter before any execution, per instruction. Do
not launch from this preregistration without explicit approval.

## Why this pilot exists

`reports/genomas_fresh_admission_ladder_20260826.md` closed out GenoMAS
admission: the artifact-contract repair, the serving-infrastructure fixes,
and the reliability-code audit all hold up under real, multi-cohort fresh
tasks. That ladder used exactly three traits
(`Alcohol_Flush_Reaction`, `Acute_Myeloid_Leukemia`,
`Age-Related_Macular_Degeneration`), all now spent as admission material and
therefore ineligible for a confirmatory panel. This pilot selects a fresh,
larger, structurally diverse 12-task panel for the first real preregistered
K=4 reliability campaign.

## Task selection

**Excluded** (already used): `Alcohol_Flush_Reaction`, `Acute_Myeloid_Leukemia`,
`Age-Related_Macular_Degeneration`.

**Selection rule** (mechanical; no gold answer or reference `cohort_info.json`
was read before the list below was frozen — only `metadata/task_info.json`'s
`conditions` field and the agent-visible local `genotex_data/input/{GEO,TCGA}`
directory listings, exactly the inputs GenoMAS itself would see):

1. Tier each of the 129 remaining admitted GenoTEX traits by local GEO-cohort
   directory count: **low** 1–2, **medium** 3–6, **high** 7–11 (this
   tri-partition follows the data's own natural clustering — 33 traits at
   1–2 cohorts, 20 at 3–6, and a sharp majority mass at 7–11 including a
   60-trait spike at exactly 10).
2. Flag TCGA availability by substring match against
   `genotex_data/input/TCGA/*` directory names (the same heuristic used
   throughout the fresh admission ladder).
3. Walk the 12 cells of `{unconditioned, conditioned} × {low, medium, high}
   × {TCGA-available, GEO-only}` in that fixed nested order.
4. In each cell, take the **alphabetically-first** trait matching that
   cell's tier/TCGA-availability not already assigned to an earlier cell —
   guaranteeing 12 distinct traits, no repeats.
5. A "conditioned" cell is paired with `condition=Age` (present in 127 of
   129 candidate traits' `conditions` lists; never chosen per-trait based on
   any outcome).

Every one of the 6 (tier × TCGA-availability) cells had at least 4 candidate
traits before selection, so no fallback logic was needed.

## The 12 tasks

| # | Task | Condition | Tier | GEO cohorts | TCGA cohort |
| - | --- | --- | --- | ---: | --- |
| 1 | `Bile_Duct_Cancer` | — | low | 2 | `TCGA_Bile_Duct_Cancer_(CHOL)` |
| 2 | `Angelman_Syndrome` | — | low | 1 | — |
| 3 | `Colon_and_Rectal_Cancer` | — | medium | 3 | `TCGA_Colon_and_Rectal_Cancer_(COADREAD)` |
| 4 | `Alopecia` | — | medium | 5 | — |
| 5 | `Adrenocortical_Cancer` | — | high | 10 | `TCGA_Adrenocortical_Cancer_(ACC)` |
| 6 | `Allergies` | — | high | 10 | — |
| 7 | `Ocular_Melanomas` | Age | low | 2 | `TCGA_Ocular_melanomas_(UVM)` |
| 8 | `Ankylosing_Spondylitis` | Age | low | 2 | — |
| 9 | `Lower_Grade_Glioma` | Age | medium | 4 | `TCGA_Lower_Grade_Glioma_(LGG)` |
| 10 | `Aniridia` | Age | medium | 3 | — |
| 11 | `Bladder_Cancer` | Age | high | 10 | `TCGA_Bladder_Cancer_(BLCA)` |
| 12 | `Alzheimers_Disease` | Age | high | 10 | — |

Each TCGA match was manually spot-checked against the real
`genotex_data/input/TCGA/` directory names (not just the substring-match
heuristic's say-so) — all six are genuine, correct matches (e.g.
`Ocular_Melanomas` → `TCGA_Ocular_melanomas_(UVM)`, not a coincidental
substring hit).

## Held-out reference artifacts

Fetched and checksum-verified **after** the task list above was frozen, via
`scripts/genomas_fetch_reference.py` (same tool, same pinned
`Liu-Hy/GenoTEX@9d50c9020256e8c943e02b6c0ad843017cd76cf8` revision, same
minimal footprint — only `cohort_info.json` + `code/*.py`, never the bulk
gene/clinical CSVs):

- Manifest: `/scratch/11034/atzanakak/genomas_admission/provenance/genotex_reference_manifest_k4_pilot_20260826.json`
- Verification: `/scratch/11034/atzanakak/genomas_admission/provenance/genotex_reference_verification_k4_pilot_20260826.json`
  — `verified: true`, 87/87 files.

## Frozen protocol

All of the following are locked in the machine-readable manifest
(`genomas_k4_pilot_v1_20260826_preregistration_manifest.json`,
`frozen_protocol`):

- **K = 4** per task (48 trajectories total across 12 tasks).
- **GenoMAS source commit:** `d6365a700794587b53958db3bf22bb1fb80c3451` (unchanged, pinned; never modified by any of this pass's fixes).
- **GenoTEX revision:** `9d50c9020256e8c943e02b6c0ad843017cd76cf8`.
- **Model:** `Qwen3-Coder-30B-A3B-Instruct`, local weights at
  `/scratch/11034/atzanakak/biomni_vista/biotaskbench/models/Qwen3-Coder-30B-A3B-Instruct`,
  checksummed against `provenance/qwen3_coder_safetensors.sha256`
  (manifest SHA-256 `5ddcc304930ae6cf1ba3c41bb6d2a6104ab8cf8a08fd1279953439f40ac39e47`),
  same weights used throughout admission and the fresh ladder.
- **vLLM serving configuration:** `--dtype bfloat16 --gpu-memory-utilization 0.92
  --max-model-len 32768 --trust-remote-code --enforce-eager`, plus the two
  environment fixes this node's `nvidia/24.7` module requires (`CC=nvc++`
  override and a `libcudart.so` symlink shim on `LIBRARY_PATH`/`LD_LIBRARY_PATH`)
  — see the launch command below and
  `reports/genomas_fresh_admission_ladder_20260826.md` for why they're needed.
- **Sampling parameters:** `temperature=0.7`, `max_tokens=2048`, `top_p` unset
  (native default); `requested_seed` = trajectory index, `seed_supported=false`
  (unchanged — the local transport adapter never exposed seed control).
- **Failure definitions:** the 4-layer taxonomy
  (`agent_execution_success → artifact_contract_valid → native_scorer_success
  → scored`), plus the new `RLIMIT_AS`-bounded `agent_control_failure` for
  any trajectory that would otherwise run away in memory (150 GiB cap per
  trajectory — see Memory/OOM risk below).
- **Primary agreement definition:** plurality/consensus computed only over
  `completed=true` trajectories (this pass's `reliability.py` fix); all-runs
  behavior preserved separately and explicitly as `*_legacy_all_runs`.
- **Scorer:** unchanged, pinned `GenoMAS/eval.py::evaluate_dataset_selection`,
  invoked via `scripts/genomas_score_smoke.py` (`tasks=["selection"]`)
  against the held-out reference fetched above.
- **Resource configuration:** single GH200 GPU (TACC Vista, partition `gh`),
  sequential execution — one task campaign and one trajectory at a time.
  Parallel trajectories are explicitly **not** this pilot's default (see
  Memory/OOM risk).

## Expected trajectories

12 tasks × K=4 = **48 trajectories**.

## Runtime / token estimate

Based on the three fresh-ladder anchor points (all under this same 32k-context,
`gpu-memory-utilization=0.92` serving config):

| Anchor | Cohorts | Runtime | Input tok | Output tok |
| --- | ---: | ---: | ---: | ---: |
| `Age-Related_Macular_Degeneration` (medium-analog, 6 GEO) | 6 | ~2,130–2,137 s | ~1.1M | ~39–40K |
| `Acute_Myeloid_Leukemia` (high-analog, 10 GEO + TCGA) | 10 | ~4,668–4,829 s | ~1.76–2.0M | ~88–92K |

Projected per-trajectory cost by tier (low tasks have fewer cohorts than
either anchor, so extrapolated downward; medium/high map onto the anchors
directly):

| Tier | Trajectories (4 tasks × K=4) | Est. runtime each | Est. tokens each (in/out) |
| --- | ---: | ---: | --- |
| low (1–2 cohorts) | 16 | ~400–1,000 s | ~0.4–0.7M / ~15–25K |
| medium (3–6 cohorts) | 16 | ~1,200–2,200 s | ~0.7–1.1M / ~25–40K |
| high (7–11 cohorts) | 16 | ~3,500–4,900 s | ~1.5–2.0M / ~70–92K |

**Rough totals: ~34–45 hours of sequential GPU wall-clock**, ~35–60M input
tokens, ~1.4–2.4M output tokens, **$0.00 paid cost** (local model). These are
extrapolations from 2 anchor points, not a calibrated model — treat as
planning-order-of-magnitude, not a commitment.

**This exceeds the current Slurm allocation's remaining time** (job `937512`
had ~3h36m left when this was written) **by roughly an order of magnitude.**
A fresh allocation with walltime comfortably above the high end of the
estimate (recommend 48h, matching this cluster's max walltime seen so far)
must be requested before launch; vLLM will need to be relaunched fresh on
the new allocation using the exact launch command below (the server does
not survive a job boundary).

## Memory / OOM risk

Rung 5 of the fresh ladder (`Acute_Myeloid_Leukemia` K=2) had one trajectory
OOM-killed at 110.8 GiB resident / 237.9 GiB virtual, diagnosed as GenoMAS's
own per-cohort memory growth within one long-lived process — not a
Slurm/cgroup limit (`ReqMem=1M` is nominal; the kernel's own
`constraint=CONSTRAINT_NONE`/`global_oom` record confirms a genuine
whole-node exhaustion) and not competing memory use (vLLM's host-side
footprint was ~150 MB at the time). Full diagnosis in
`reports/genomas_fresh_admission_ladder_20260826.md`.

Mitigation already in place for this pilot (committed, tested): each agent
subprocess now runs under an `RLIMIT_AS` cap
(`--max-memory-gb 150`, `biomni_uncertainty.adapters.genomas.memory_rlimit_preexec_fn`).
A trajectory that runs away hits a local, clean `MemoryError` — classified
as `agent_control_failure`, excluded from correctness/agreement per this
pass's audit fix — instead of risking another indiscriminate whole-node OOM
that could kill the shared vLLM server.

Residual risk for this pilot:

- **High-tier tasks are the highest risk** (that's exactly where the one
  observed failure happened; `Adrenocortical_Cancer`, `Allergies`,
  `Bladder_Cancer`, `Alzheimers_Disease` — all 10-GEO-cohort tasks — are the
  most exposed of the 12). Budget for some non-zero `agent_control_failure`
  rate there; it is now correctly classified and excluded from correctness
  metrics rather than silently corrupting them.
- **Sequential execution only** is this pilot's assumption. At 150 GiB cap
  per trajectory on a 212 GiB host, even two concurrent high-tier
  trajectories could collectively approach the node's real capacity.
  Parallelizing this pilot to shorten the ~34–45 h wall-clock estimate is a
  legitimate future option but needs its own explicit resource re-budgeting
  (e.g. a lower per-trajectory cap sized to the intended concurrency) — not
  assumed here.

## Exact launch commands (NOT EXECUTED)

**1. Start the endpoint** (on a fresh allocation; do not reuse a vLLM
process that predates this session's environment fixes):

```bash
PATH=/scratch/11034/atzanakak/biomni_vista/envs/biotaskbench/bin:$PATH \
CC=/home1/apps/nvidia/Linux_aarch64/24.7/compilers/bin/nvc++ \
LIBRARY_PATH=/scratch/11034/atzanakak/genomas_admission/cuda_link_shim:$LIBRARY_PATH \
LD_LIBRARY_PATH=/scratch/11034/atzanakak/genomas_admission/cuda_link_shim:/scratch/11034/atzanakak/biomni_vista/envs/biotaskbench/lib/python3.12/site-packages/nvidia/cu13/lib:$LD_LIBRARY_PATH \
vllm serve /scratch/11034/atzanakak/biomni_vista/biotaskbench/models/Qwen3-Coder-30B-A3B-Instruct \
  --served-model-name Qwen3-Coder-30B-A3B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --dtype bfloat16 --gpu-memory-utilization 0.92 --max-model-len 32768 \
  --trust-remote-code --enforce-eager
```

**2. One campaign per task** (12 invocations; example shown for task #1,
substitute `--trait`/`--condition`/`--campaign-root` per the table above —
omit `--condition` entirely for the six unconditioned tasks, per the
`normalize_condition_arg` fix):

```bash
cd /work/11034/atzanakak/biomni_bench/biomni-uncertainty
python scripts/run_genomas_k4_reliability.py \
  --campaign-root /scratch/11034/atzanakak/genomas_admission/genomas_k4_pilot_v1_20260826/01_bile_duct_cancer_k4 \
  --source /scratch/11034/atzanakak/genomas_admission/GenoMAS_run \
  --data-root /scratch/11034/atzanakak/genomas_admission/genotex_data/input \
  --reference-root /scratch/11034/atzanakak/genomas_admission/genotex_references/output \
  --endpoint http://127.0.0.1:8000 \
  --model Qwen3-Coder-30B-A3B-Instruct \
  --trait Bile_Duct_Cancer \
  --k 4 \
  --max-memory-gb 150 \
  --source-commit d6365a700794587b53958db3bf22bb1fb80c3451 \
  --benchmark-revision 9d50c9020256e8c943e02b6c0ad843017cd76cf8
```

Repeat for the remaining 11 tasks, incrementing the campaign-root prefix and
substituting the trait/condition from the table above.

**Not executed. Requires explicit approval before any trajectory starts.**

## Provenance

- Preregistration manifest (machine-readable, this document's source of
  truth for frozen parameters):
  `/scratch/11034/atzanakak/genomas_admission/genomas_k4_pilot_v1_20260826_preregistration_manifest.json`
  (SHA-256 `71a9adab37c1489750b9e84210940c2a6de5fa804fa96d5c599eb76eb5df6399`).
- Reference manifest/verification: see "Held-out reference artifacts" above.
- This preregistration does not modify, and was not informed by, any frozen
  admission or ladder artifact.
