# biomni-uncertainty

Evaluating and improving the reliability of autonomous biomedical AI agents
through uncertainty benchmarks and trajectory-ensemble distillation.

Biomedical agents such as [Biomni](https://github.com/snap-stanford/Biomni)
plan analyses, retrieve resources, call tools, execute code, and produce
scientific conclusions — but repeated runs on the same task can follow
different workflows and reach different answers. This project measures how
reliable that process actually is, standardizes the metrics for comparing
reliability across independently developed agents, and tests whether
reliability can be improved by distilling repeated successful trajectories
back into the agent.

## Status snapshot

```text
3 biomedical agents evaluated (Biomni, GenoMAS, AutoBA)
Reliability Suite v1 implemented and frozen
200 Biomni training-eligible task instances audited
433 completed Biomni trajectories in the candidate training corpus
250 reward-positive trajectories
~4.0M output tokens / ~70.5M total input+output tokens
120-task held-out set kept disjoint from training
Trajectory-ensemble distillation: SFT stack built and smoke-tested,
  training run not yet launched
```

Numbers current as of 2026-08-30; verified against
[reports/biomni_trajectory_distillation_audit.md](reports/biomni_trajectory_distillation_audit.md)
and [PROJECT_STATUS.md](PROJECT_STATUS.md).

## Motivation

An agent that silently reaches a wrong conclusion is more dangerous in a
biomedical setting than one that visibly fails. Before building any
mechanism that asks an agent to reconsider a weak workflow, spend more
computation where it helps, or abstain when it should, one question has to
be answered empirically: do cheap, observable signals from an agent's own
behavior — repeated-run agreement, stated confidence, trajectory effort —
actually predict whether its answer is correct? This project answers that
question directly rather than assuming it.

## What this project does

- **Cross-agent reliability benchmarking** — the same reliability protocol
  run against three independently developed biomedical agents.
- **Reliability Suite v1** — a frozen, agent-agnostic evaluation layer:
  Pass@1, plurality accuracy, Oracle@K, agreement→correctness AUROC,
  confidence calibration, and a four-way failure taxonomy, computed from
  each agent's own official scorer.
- **Repeated-trajectory analysis** — K=4 (or K=2, in the online-controller
  condition) independent runs per task instance, so that reliability can be
  measured rather than assumed from a single run.
- **Stable-wrong / recoverability characterization** — every task instance
  is classified as stable-correct, stable-wrong, unstable-recoverable, or
  unstable-unrecoverable, so "the agent disagreed with itself" and "the
  agent was confidently wrong" are never conflated.
- **Trajectory-ensemble distillation** — testing whether a single-run model
  can be improved by fine-tuning on the correct trajectory from an ensemble
  of repeated runs, against a vanilla-SFT control matched on training
  exposure.

## Current status

| Stage | Outcome |
| --- | --- |
| Phase 1 — single-agent Biomni pilot | Complete — established baseline self-consistency, confidence, and behavioral reliability signals |
| Phase 1.5 — context-overflow forensics and repair | Complete |
| Phase 2A — offline replay of first-run (K=1) selection signals | Complete — K=1 signals alone do not reliably identify correctness |
| Phase 2B — prospective online reliability controller (150 held-out instances, 600 trajectories) | Complete — measured prospectively against a fixed-K=4 baseline; results informed the shift to the distillation approach below |
| Cross-agent reliability comparison — Biomni, GenoMAS, AutoBA | Complete |
| Trajectory-ensemble distillation pilot | Corpus and SFT stack built and validated; training run in preparation |

The project's current direction is trajectory-ensemble distillation
(preregistered in
[reports/biomni_distillation_pilot_preregistration.md](reports/biomni_distillation_pilot_preregistration.md)),
following from what the online-controller work in Phase 2B established about
where a fixed repeated-sampling baseline is hard to beat. Full detail on
that work, including the prospective result and the offline assessment of a
proposed redesign, is in
[reports/phase2_report.md](reports/phase2_report.md) and
[reports/controller_v2_offline_assessment.md](reports/controller_v2_offline_assessment.md).

## Agents evaluated

| Agent | Role |
| --- | --- |
| [Biomni](https://github.com/snap-stanford/Biomni) (Biomni-R0-32B) | Primary agent; full reliability characterization, online-controller and distillation experiments |
| GenoMAS (pinned commit `d6365a7`) | K=4 cross-agent reliability pilot (12 tasks) |
| AutoBA (pinned commit `a9f8f12`) | K=4 cross-agent reliability pilot (12 tasks, one task substitution — see [reports/autoba_k4_pilot_v1_preregistration.md](reports/autoba_k4_pilot_v1_preregistration.md)) |

A fourth-agent expansion, additional agent panels, and controlled failure
studies are explicitly out of scope until the current findings are acted on
— see [reports/candidate_agent_audit.md](reports/candidate_agent_audit.md)
for the full admission process and why other candidate agents were not
selected.

## Reliability Suite

[reports/reliability_suite_v1.md](reports/reliability_suite_v1.md) is the
frozen specification. In brief: every agent is wrapped by an adapter that
runs it, canonicalizes its answer without access to ground truth, and scores
it with the benchmark's own official evaluator — the suite never substitutes
LLM judging for a native scorer. From K independently requested runs per
task instance it reports Pass@1, plurality accuracy, Oracle@K, an
agreement→correctness AUROC, confidence calibration (Brier/ECE) where
available, and a four-state failure taxonomy (stable-correct, stable-wrong,
unstable-recoverable, unstable-unrecoverable). All point estimates carry
95% bootstrap confidence intervals resampled at the task-instance level.

**Cross-agent comparison** (harmonized instance-level agreement→correctness
AUROC; descriptive, not a leaderboard — the three agents use different
native benchmarks and task counts, so raw accuracy is not directly
comparable):

| | Biomni-R0 | GenoMAS | AutoBA |
| --- | ---: | ---: | ---: |
| Agreement → correctness AUROC | 0.851 (n=116/120) | 0.529 | 0.542 (n=10) |

Full detail and the methodological correction behind the harmonized numbers
are in
[reports/auroc_definition_methods_note.md](reports/auroc_definition_methods_note.md).
An earlier published comparison mixed a trajectory-level AUROC definition
for Biomni with an instance-level definition for GenoMAS/AutoBA; the table
above uses the same instance-level definition for all three. The correction
narrows Biomni's number (0.896 → 0.851) but does not change the qualitative
conclusion that Biomni's self-consistency signal is substantially stronger
than the other two agents' on the tasks tested.

## Distillation experiment

The central question: can fine-tuning on the correct trajectory from an
ensemble of repeated runs improve a model that only gets to run once?

- **Training corpus**: 200 task instances (50 from a uniform K=4 pilot, 150
  from the online-controller run at K=2), 433 completed trajectories, 250
  reward-positive. 126/200 instances (63%) have at least one officially
  correct trajectory and so support the reward-positive objective.
- **Arms**: a reward-positive ensemble-to-single SFT arm (the
  lowest-index correct trajectory per instance) versus a vanilla-SFT control
  on the same pool, trained on identical assistant-loss token exposure.
- **Held-out evaluation**: the same 120-task set used for the cross-agent
  comparison above, kept disjoint from every training instance.
- **Status**: manifests are frozen, the base checkpoint and trajectory
  representation are decided and verified against Biomni's own agent source
  (not inferred from log formatting), and a real LoRA smoke test has run to
  completion on the training hardware. Training has **not** been launched —
  single-GPU memory sufficiency at this corpus's representative sequence
  lengths (13K–31K tokens) is not yet demonstrated, and launching before
  that is closed would risk an uninterpretable result.

Full design: [reports/biomni_distillation_pilot_preregistration.md](reports/biomni_distillation_pilot_preregistration.md).

## Repository structure

```text
src/          reliability suite, agent adapters, sampling, evaluation, policy/calibration library
scripts/      experiment launchers, aggregation, analysis, and one-off audit tooling
manifests/    frozen task manifests and per-trajectory run specs
configs/      experiment configurations (a cluster.example.yaml template; the real cluster config is gitignored)
reports/      preregistrations, results, and audits — see reports/README.md for where to start
slurm/        cluster job scripts, parameterized by account/partition at submit time
tests/        pytest suite (CPU-only, no data lake or GPU required)
```

See [reports/README.md](reports/README.md) for a curated entry point into
the reports directory, [DECISIONS.md](DECISIONS.md) for why things are the
way they are, and [PROJECT_STATUS.md](PROJECT_STATUS.md) for the full,
chronological project log.

## Reproducing the analysis

```bash
git clone <this repo> biomni-uncertainty
cd biomni-uncertainty
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# CPU-only: no GPU, no data lake, no model calls
pytest -q
ruff check src tests && ruff format --check src tests

# Offline replay of the Phase-2A policy comparison (CPU, ~1 min)
python scripts/phase2a_offline_replay.py \
    --tables <output_root>/phase1_pooled/results/tables \
    --out    <output_root>/phase2a/results
```

Running an actual agent trajectory requires a local Biomni checkout pinned
to the commit in
[external/BIOMNI_PIN.json](external/BIOMNI_PIN.json), a served model
endpoint, and a cluster config — see
[DECISIONS.md](DECISIONS.md) and `configs/cluster.example.yaml` for that
setup. No proprietary LLM API is called anywhere in this project.
Large trajectory artifacts and model checkpoints are not stored in Git;
release/archival details will accompany the research output.

## Research status / limitations

- **Agent panel is uneven in scale.** Biomni's reliability characterization
  draws on hundreds of instances; the GenoMAS and AutoBA pilots are 12
  tasks each. The cross-agent AUROC comparison above should be read as
  suggestive, not conclusive.
- **One backbone model.** All Biomni results use a single fine-tuned
  32B checkpoint; findings may not transfer to another backbone.
- **Final-answer correctness only.** A correct answer reached through an
  invalid workflow scores the same as a sound one; workflow validity is not
  assessed.
- **The online reliability controller was tested and did not work.**
  Phase 2B failed both of its pre-registered co-primary hypotheses against
  a fixed-K=4 baseline, and a proposed redesign was rejected offline
  against a bar written down before the test. This project reports that
  result rather than omitting it.
- **Sampling is stochastic; seeds are requested, not guaranteed.** Whether
  an endpoint honors a per-request seed is probed at run time and recorded,
  never assumed.
- **Oracle@K is an upper bound, not a deployable method** — it reads ground
  truth and exists to characterize headroom, never to select an answer.
- **The distillation pilot has not been trained yet.** Everything in the
  "Distillation experiment" section above is corpus construction and
  engineering validation; no result exists to report.

## Citation

No paper has been published for this work yet. If you use this repository,
please cite it by URL and commit hash until a citation is added here.

## License

No license has been chosen yet for this repository.
