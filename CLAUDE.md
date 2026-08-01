# CLAUDE.md — instructions for future Claude Code sessions

## Project goal

Answer one empirical question before any adaptive controller is built:
**can inexpensive intrinsic signals from multiple Biomni trajectories identify
which biomedical-agent outputs are reliable?** Signals under test: self-consistency,
verbalized confidence, and observable trajectory effort.

## Current phase

**Phase 1 only.** Read `PROJECT_STATUS.md` first — it is the source of truth for
what is done, what is running and what is next.

Explicitly **out of scope** until Phase 2: the adaptive replanning controller,
controlled benchmark corruptions, human workflow annotation, a second agent, the
full BiomniEval1, quantized-model comparisons, closed-model API comparisons.

## Architecture

Biomni is a **pinned dependency**, never edited. Everything is an adapter.

```
manifest ─► run specs ─► [one subprocess per trajectory] ─► run dir ─► aggregate ─► analyze
```

| module | responsibility |
| --- | --- |
| `config.py` | validated YAML config; `${ENV}` expansion; cluster-placeholder detection |
| `benchmark.py` | BiomniEval1 loading; deterministic balanced manifest; ground truth written to a *separate* file |
| `sampling.py` | manifest → run specs; stable run IDs; atomic markers; resumption |
| `canonicalization.py` | raw response → confidence stripped → `<solution>` → task-aware canonical answer |
| `confidence.py` | elicitation instruction and tolerant extraction |
| `instrumentation.py` | LangChain callback + `run_with_timeout` patch + retriever wrap |
| `events.py` | append-only JSONL events, redaction |
| `runner.py` | one trajectory, isolated cwd, endpoint validation, failure classification |
| `dispatcher.py` | endpoint health, concurrency, resume, retry policy |
| `evaluation.py` | wraps the **official** `BiomniEval1._compute_reward` |
| `features.py` / `selectors.py` | consistency + behavioural features; the 10 pre-specified selectors |
| `aggregation.py` / `analysis.py` / `plotting.py` | Parquet+CSV tables, frozen statistics, figures |

Interception points were verified against the pinned commit. If you re-pin
Biomni, re-verify all four (see `DECISIONS.md` D-01) — the graph nodes are
closures inside `A1.configure()` and cannot be subclassed.

## Commands

```bash
pytest -q                                    # 246 tests, CPU only, no data lake
ruff check src tests && ruff format src tests

python -m biomni_uncertainty.cli inspect-env
python -m biomni_uncertainty.cli prepare-manifest --config configs/phase1.yaml
python -m biomni_uncertainty.cli expand-runs   --config configs/phase1.yaml --manifest manifests/phase1.jsonl
python -m biomni_uncertainty.cli status        --config configs/phase1.yaml
python -m biomni_uncertainty.cli aggregate     --config configs/phase1.yaml
python -m biomni_uncertainty.cli analyze       --config configs/phase1.yaml
python -m biomni_uncertainty.cli check-cluster --cluster-config configs/cluster.yaml

scripts/run_smoke.sh  configs/cluster.yaml configs/smoke.yaml
scripts/run_phase1.sh configs/cluster.yaml configs/phase1.yaml --dry-run
```

## Coding standards

* Python ≥3.11, `ruff` (line length 120) for both lint and format. Both must pass.
* Type hints on public functions; `from __future__ import annotations`.
* Every experiment constant lives in `configs/*.yaml`. **Never** hardcode a
  constant in a module, and never hardcode an account, partition, allocation or
  absolute site path anywhere in the repo.
* New behaviour needs a test. New task type ⇒ canonicalization tests for all
  seven required cases (correct form, extra prose, confidence appended,
  malformed, case variation, multiple candidates, missing).
* Prefer adapters over upstream edits. If a patch is truly unavoidable: keep it
  minimal, put it in `patches/`, explain why, and add a test that fails without it.

## Files that must not be edited casually

| file | why |
| --- | --- |
| `manifests/phase1.jsonl` + `.groundtruth.jsonl` | **frozen.** Hash is recorded in `reports/phase1_protocol.md`. Editing invalidates every completed run. |
| `manifests/phase1_runs.jsonl` | frozen; run IDs and run directories derive from it. |
| `configs/phase1.yaml` | changing it after runs start makes trajectories incomparable. Make a new experiment name instead. |
| `reports/phase1_protocol.md` | pre-registration. Changing a primary metric after seeing results must be documented **as a change**, not edited away. |
| `runs/**` | raw evidence. Never delete a failed run. |
| `src/.../evaluation.py` | must keep calling the official scorer; never re-implement it. |

## Scientific integrity rules

Non-negotiable, enforced by tests where possible:

* Ground truth never reaches the agent, never selects pilot instances, never
  resolves an ambiguous prediction, and is read by exactly one selector (`oracle`,
  labelled an upper bound everywhere).
* Failed runs are preserved; retries never hide the original failure.
* Missing confidence is recorded, never defaulted.
* Unavailable features are marked unavailable, never fabricated.
* Confirmatory and exploratory analyses stay separately labelled.
* Resampling unit is the task instance, never the individual trajectory.
* No proprietary LLM API is called in Phase 1.

## Updating PROJECT_STATUS.md

Update it whenever state changes — not only at the end. Keep the sections:
*Completed*, *Current blockers*, *Tests run*, *Active experiment IDs*,
*Known failures*, *Next actions*. Give experiment IDs and artifact paths, and put
dates in absolute form. If something failed, say so with the evidence.

## Preserving provenance

Every run record must keep: identity, requested seed **and** whether the seed was
actually supported, model + revision + endpoint, Biomni commit, project commit,
working-tree dirty flag, config snapshot and hash, hostname, Slurm IDs, GPU
assignment, timings, completion status, failure class, and output paths.

Never claim deterministic reproducibility unless the whole stack is deterministic.
`requested_seed` and `seed_supported` are separate fields for exactly this reason.

## Why ground truth is tracked in git

`manifests/*.groundtruth.jsonl` **is** committed. That is deliberate and not a
violation of the "never commit benchmark answers" rule, which concerns
*agent-visible* files:

* the answers are public — they come from the public `biomni/Eval1` dataset;
* the file is never passed to the agent, never used to select instances, and is
  read only by `OfficialEvaluator`;
* tracking it makes evaluation reproducible on a node with no internet access.

If you add a benchmark whose answers are **not** public, gitignore its
ground-truth file and load it from a path in `configs/cluster.yaml` instead.
