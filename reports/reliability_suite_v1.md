# Reliability Suite v1 — frozen specification

**Status:** preregistered implementation specification; frozen before a new multi-agent outcome is inspected. **Default protocol:** four independently requested runs per task (`K=4`). A run may carry a requested seed, but the record must state whether the backend actually supports it. The suite records protocol and artifacts reproducibly; it does not promise bit-identical samples.

## Scope and scoring

The unit of inference and bootstrap resampling is a benchmark instance, not a trajectory. Adapters execute agents and invoke the benchmark's official/native scorer. The core suite never replaces that scorer with LLM judging. An absent or unparseable answer is a substantive zero if the native scorer's contract defines it that way; a scorer exception is an `evaluator_failure`, retained in failure accounting and excluded from correctness denominators.

Answers are canonicalized by the adapter without ground truth. A missing or unparseable answer is a unique singleton cluster, so unrelated failures cannot manufacture agreement. Plurality ties are resolved by lowest requested run index and reported as ties.

## Primary outputs

| Metric | Definition |
|---|---|
| Pass@1 | Official binary correctness of run index 0, averaged by instance. |
| Plurality/consensus accuracy | Official correctness of the deterministic plurality-selected trajectory. |
| Oracle@K | Fraction of evaluable instances with at least one correct run; descriptive upper bound, never a deployable selection rule. |
| Agreement | Largest canonical-answer cluster size divided by the number of requested runs. |
| Agreement → correctness AUROC | AUROC of instance plurality fraction for plurality-selected correctness. |
| Verbal-confidence AUROC | AUROC of adapter-extracted confidence probability for trajectory correctness; null when unavailable. |
| Calibration | Brier score and equal-width 10-bin ECE of an explicitly probabilistic confidence field; null when unavailable. |
| Risk–coverage/selective accuracy | Sort trajectories by confidence descending; report accuracy/risk at coverages 0.1…1.0 and mean sampled risk (AURC summary). |
| Selection-failure rate | Among evaluable instances with any correct run, rate at which plurality selects a wrong answer. |
| All-wrong rate | Evaluable instances with no correct run. |
| Execution/failure rate | Requested trajectories not completed, plus failure-reason counts; scorer failures are separately counted. |

Failure state is assigned once per instance: **stable-correct** (one cluster, all evaluable runs correct), **stable-wrong** (one cluster, evaluable runs all wrong), **unstable-recoverable** (multiple clusters and at least one correct run), or **unstable-unrecoverable** (multiple clusters and no correct run). Instances with no evaluable reward remain visible in execution accounting but do not contribute a correctness state.

Point estimates receive percentile 95% CIs from 2,000 deterministic instance-level bootstrap resamples (`seed=20260825`). Metrics with fewer than two classes (AUROC) or no available confidence are `null`, not zero.

## Adapter boundary

An adapter implements, conceptually:

```python
run_agent(task, seed_or_run_index) -> trajectory, final_answer, metadata
canonicalize(task, final_answer) -> canonical_answer | None
score(task, final_answer) -> {official_reward, status, ...}
```

It writes one trajectory record for every requested run, including failures. Required provenance is `agent_name`, agent/source commit, model and immutable revision where possible, benchmark version/commit, task ID, prompt/config hash, decoding parameters, requested seed/run index, tool/environment versions, raw and canonical answer, official reward/status, termination/failure reason, token counts when available, wall time, and artifact/run directory. The generic core is `src/biomni_uncertainty/reliability.py`; it consumes these records and emits the schema below.

## Machine-readable report schema

`evaluate_reliability()` returns JSON with this stable top-level shape:

```json
{
  "schema_version": "reliability-suite-v1.0",
  "protocol": {"k": 4, "n_bootstrap": 2000, "bootstrap_seed": 20260825},
  "metrics": {"pass_at_1": {"estimate": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "n": 0}, "plurality_accuracy": {}, "oracle_at_k": {}, "agreement_plurality_fraction": {}, "agreement_to_correctness_auroc": 0.0, "verbal_confidence_auroc": null, "calibration": {"brier": 0.0, "ece_10": 0.0, "n": 0}, "risk_coverage": {"curve": []}},
  "failure_accounting": {"execution_failure_rate": 0.0, "n_requested_runs": 0, "n_evaluator_failures": 0, "by_failure_reason": {}},
  "failure_taxonomy": {"stable_correct": 0, "stable_wrong": 0, "unstable_recoverable": 0, "unstable_unrecoverable": 0},
  "instances": [{"task_id": "…", "plurality_fraction": 0.0, "plurality_correct": 0, "oracle_at_k": 0, "state": "stable_wrong"}]
}
```

`null` means unavailable/undefined. Reports also retain the input trajectory records rather than treating this summary as the sole artifact.

## Guardrails

No metric is introduced after outcomes are inspected without an explicit exploratory label. The suite evaluates uncertainty detection, correctness, calibration, selection failure, generation failure, execution failure, and recoverability separately; it does not collapse them into one score.
