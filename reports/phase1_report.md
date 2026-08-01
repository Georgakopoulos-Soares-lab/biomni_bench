# Phase 1 — Do biomedical agents know when they are wrong?

> **STATUS: PLACEHOLDERS ONLY. The pilot is running; no results exist yet.**
> Every `‹TBD›` below is filled from `results/analysis.json` and
> `results/tables/*.csv` **after** the run completes. No conclusion is written
> before the numbers exist — that is a rule of this project, not a formality.
>
> Sections 1–5 that describe *method* are complete, because they were fixed in
> `reports/phase1_protocol.md` before any trajectory was generated.

---

## 1. Executive summary

‹TBD — written last.›

**Headline numbers (to fill):**

| quantity | value | 95% CI |
| --- | --- | --- |
| First-trajectory reward | ‹TBD› | ‹TBD› |
| Standard-condition reward | ‹TBD› | ‹TBD› |
| Plurality reward | ‹TBD› | ‹TBD› |
| SRLM-style selector | ‹TBD› | ‹TBD› |
| Rank-combination selector | ‹TBD› | ‹TBD› |
| Oracle@4 (UPPER BOUND) | ‹TBD› | ‹TBD› |
| **Oracle headroom** | ‹TBD› pp | ‹TBD› |
| Confidence Brier | ‹TBD› | — |
| Confidence ECE (5 bins) | ‹TBD› | — |
| Confidence AUROC | ‹TBD› | ‹TBD› |

**Go / no-go:** ‹TBD›

---

## 2. Scientific questions

Verbatim from the protocol; none was added or dropped after seeing data.

* **RQ1 Oracle headroom.** When the first trajectory is wrong, how often is at
  least one of K=4 correct?
* **RQ2 Self-consistency.** Does agreement predict correctness? Does plurality
  voting beat a single run?
* **RQ3 Verbalized confidence.** Is stated confidence associated with
  correctness? Is it calibrated?
* **RQ4 Behavioural uncertainty.** Are tokens, steps, tool calls, retries, tool
  failures, repeated actions and runtime associated with correctness?
* **RQ5 Trajectory selection.** Can simple selectors beat first / random /
  plurality?
* **RQ6 Task dependence.** Do the relationships differ across task types?
* **RQ7 Prompt perturbation.** Does the confidence request change underlying task
  performance?

---

## 3. Methods

Full detail: `reports/phase1_protocol.md` (frozen before the pilot) and
`DECISIONS.md`. Summary:

* **Agent.** Biomni `A1` at commit `400c1f36…`, v0.0.8, unmodified. All
  instrumentation is adapter-based: a LangChain callback on the agent's LLM, a
  patch of `run_with_timeout` (the graph's single code-execution choke point),
  and a wrap of the tool retriever. `patches/` is empty.
* **Model.** `biomni/Biomni-R0-32B-Preview` @ `71432eb3…`, served locally with
  SGLang 0.5.16, TP2, **bfloat16** (the weights ship FP32), context 65,536 via
  the model card's YaRN override at factor 1.0. No proprietary API was called.
* **Conditions.** A = 1 unmodified trajectory/instance (n=50). B = 4 trajectories
  with a final confidence request (n=200). Task prompt byte-identical between
  conditions; the elicitation lives in the system prompt.
* **Sampling.** temperature 0.7 (Biomni's own default), max_tokens 8192. Seeds
  were requested and recorded, but the endpoint does **not** honour them
  (`seed_supported: false`) — trajectories are independent samples, not
  reproducible ones.
* **Evaluation.** The official `BiomniEval1._compute_reward`, unmodified. A
  task-aware canonicalization layer converts a raw response into the parsed
  answer that scorer expects; `strict_reward` on the un-normalized token is
  reported alongside so the credit granted by normalization is measurable.
* **Statistics.** Resampling unit is the **task instance**; 2,000 bootstrap
  replicates, seed 20260731; cluster bootstrap for trajectory-level associations;
  `GroupKFold` for the exploratory learned selector.

---

## 4. Benchmark composition

50 instances, exactly 5 per task, all 10 tasks in the `biomni/Eval1` release.
Manifest hash `44854f87b3a0d2e0c00bf4fe06c8879e5636b8a470b8803a5b3e6a2db850fff9`.
No exclusions. Selection used a keyed hash of (seed, task, instance id) with
manifest seed 20260731, and never consulted model output or correctness.

The release has **no held-out split** — every row is `split == "val"`.
`hle` has a scoring branch but zero instances.

Prompt length (chars): min 261, median 391, max 4680, mean 718.

‹TBD — final table of realised counts by task and split from
`results/tables/trajectories.csv`.›

---

## 5. Infrastructure and failure rates

‹TBD — from `results/status_summary.json` and figure 11.›

| quantity | value |
| --- | --- |
| Planned runs | 250 |
| Runs present / completed | ‹TBD› |
| Failure-class breakdown | ‹TBD› |
| `model_context_overflow` rate | ‹TBD› |
| Answer parse rate | ‹TBD› |
| Confidence parse rate | ‹TBD› |
| Token-usage availability | ‹TBD› |
| Mean failed code executions / trajectory | ‹TBD› |

**Known infrastructure limitation, stated in advance:** the full Biomni E1
bioinformatics environment (>10 h, >30 GB) was not installed. The commonly
imported tool dependencies were added before the pilot after the smoke test
exposed them, but residual tool failures are expected. "Infrastructure failures
dominate biological reasoning failures" is a **pre-specified stop criterion**;
§5 is where that is adjudicated, before any signal is interpreted.

---

## 6. Baseline performance

‹TBD — first-trajectory and standard-condition reward, overall and by task.›

---

## 7. Prompt-perturbation result (RQ7)

‹TBD — paired comparison of Condition A vs instrumented trajectory 0 on the same
instances: reward difference with CI, answer-change rate, confidence parse rate,
and changes in output tokens / tool calls / LLM calls / wall time. Figure 10.›

If the confidence instruction substantially harms performance, that is a
methodological finding and is reported as one, not smoothed over.

---

## 8. Oracle@K and candidate-generation headroom (RQ1)

**This is the central Phase-1 result.** Trajectory selection cannot help if
independent sampling rarely produces a correct alternative.

‹TBD — Oracle@K for K=1..4 (all-subsets and first-K-prefix, both labelled),
figure 2; plus P(at least one correct), P(disagreement), P(first wrong but
another correct), P(plurality wrong despite a correct minority), and task-level
headroom.›

Oracle is an **upper bound that reads ground truth**. It is never presented as a
usable method.

---

## 9. Self-consistency results (RQ2)

‹TBD — plurality vs first with paired CI; number of unique answers, plurality
fraction, entropy, pairwise agreement; reward by consensus size (figure 6).›

---

## 10. Confidence calibration (RQ3)

‹TBD — Brier, ECE, NLL, AUROC, AUPRC; reliability diagram with per-bin counts
(figure 4); accuracy by confidence bin (figure 5); accuracy at thresholds;
selective accuracy/coverage curve. Missing-confidence rate reported separately
and never imputed.›

---

## 11. Behavioural-signal analysis (RQ4)

‹TBD — trajectory-level AUROC per signal with cluster-bootstrap CIs (figure 13);
length vs correctness (figure 7); tool failure vs correctness (figure 8);
confidence vs length (figure 9); confidence × length heatmap (figure 12, drawn
only if every cell holds ≥3 trajectories).›

Note in advance: a longer trajectory may indicate uncertainty **or** appropriate
scientific thoroughness. Direction is reported explicitly, not implied by an
AUROC below 0.5.

---

## 12. Selector comparison (RQ5)

‹TBD — figure 1 and the paired-difference table against first / plurality /
random. Includes tie counts and missing-feature handling per selector.›

The exploratory grouped-CV learned selector is reported separately and labelled
exploratory.

---

## 13. Task-level heterogeneity (RQ6)

‹TBD — figure 3 and the per-task table. Five instances per task: descriptive
only.›

---

## 14. Failure examples

‹TBD — a small, deliberately stratified set of preserved traces: a confidently
wrong answer; a case where the plurality was wrong but a minority trajectory was
right; a tool-failure cascade; a context overflow. Quoted from
`runs/**/final_response.txt` and `events.jsonl`, with run IDs so they can be
audited.›

---

## 15. Limitations

Carried forward from the protocol, plus anything the results add.

1. **50 instances, 250 trajectories.** A pilot. One instance moves an
   instance-level rate by 2 pp; per-task cells hold 5 instances.
2. **One agent, one model.** No claim of transfer.
3. **Final-answer correctness only.** A correct answer reached through an invalid
   workflow scores identically to a sound one. Workflow validity is **not**
   assessed — that needs the expert annotation deferred to Phase 2. Nothing in
   this report licenses a claim about workflow validity.
4. **Final-only confidence.** Per-step confidence is architecturally unavailable
   in Biomni (`DECISIONS.md` D-08); the SRLM-style selector is an approximation.
5. **Seeds requested but not honoured.** Sampling is stochastic and unseeded.
6. **Lightweight tool environment.** See §5.
7. **Live external databases.** Results can depend on when a trajectory ran.
8. **Context extrapolation** above 40,960 positions.
9. **`patient_gene_detection` rewards any set intersection**, so a large
   predicted gene set inflates reward; `n_predicted` is reported.
10. **rsID normalization** grants credit a literal comparison would not;
    quantified by `strict_reward`.
11. ‹TBD — limitations the results themselves reveal.›

---

## 16. Go / no-go recommendation

‹TBD — adjudicated against the **pre-specified** criteria in
`reports/phase1_protocol.md` §8, which were fixed before the pilot ran.›

The report must separate, and will:

* failure of **candidate generation** (no correct alternative is ever produced);
* failure of **trajectory selection** (a correct alternative exists but is not
  chosen);
* failure of **uncertainty estimation** (signals do not discriminate);
* **infrastructure** failure (the environment, not the science).

A negative result is an acceptable outcome and will be reported as one.

---

## 17. Proposed Phase 2

See `reports/phase2_plan.md`, which states a **decision rule** mapping each
possible Phase-1 outcome to a Phase-2 track rather than a predetermined plan.
The applicable track is selected in §16 once the results exist.

---

## Reproduction

```bash
# environment
python -m biomni_uncertainty.cli inspect-env --output reports/environment.json

# frozen manifest (hashes must match §4)
python -m biomni_uncertainty.cli prepare-manifest --config configs/phase1.yaml
python -m biomni_uncertainty.cli expand-runs --config configs/phase1.yaml \
       --manifest manifests/phase1.jsonl

# serving + pilot
scripts/launch_node_servers.sh --model <snapshot> --endpoints-dir <dir> ...
scripts/run_detached.sh configs/cluster.yaml configs/phase1.yaml <endpoints.json> 4

# analysis
scripts/aggregate_results.sh configs/phase1.yaml
scripts/analyze_phase1.sh   configs/phase1.yaml
```

Artifacts: `<output_root>/phase1/runs/**` (raw traces, failures preserved),
`<output_root>/phase1/results/tables/*.{parquet,csv}`,
`<output_root>/phase1/results/figures/*.png`,
`<output_root>/phase1/results/analysis.json`.
