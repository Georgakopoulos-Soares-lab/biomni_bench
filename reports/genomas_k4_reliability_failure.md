# GenoMAS Reliability Suite v1 — K=4 execution record

**Status: completed execution; invalid for reliability-performance inference.**
No additional agent, task panel, or RL work was launched.

## Frozen campaign

The controller wrote its manifest before trajectory zero:
`/scratch/11034/atzanakak/genomas_admission/k4_reliability_v1_20260825/campaign_manifest.json`
(SHA-256 `1968c56a2e907fc5e6efc396e3eca7fc5f14604afdaf0e7410244a8c6855cc63`).

It used the admitted pinned GenoMAS source (`d6365a700794587b53958db3bf22bb1fb80c3451`),
GenoTEX revision (`9d50c9020256e8c943e02b6c0ad843017cd76cf8`), verified
input tree, held-out native-reference slice, and local Qwen3-Coder endpoint.
The K=4 panel was the already-admitted `Alcohol_Flush_Reaction::Age` task; the
prior K=1 admission run is not included in these four records.

## Completion and cost

All four requested trajectories executed. Native logs report:

| Run | Input tokens | Output tokens | Runtime (s) |
| --- | ---: | ---: | ---: |
| k4_00 | 235,077 | 8,253 | 395.62 |
| k4_01 | 115,228 | 11,680 | 543.50 |
| k4_02 | 204,336 | 10,922 | 512.86 |
| k4_03 | 363,205 | 16,299 | 816.78 |
| **Total** | **917,846** | **47,154** | **2,268.76** |

Paid API cost was **$0.00**. The runner's nominal 420-second `--max-time` is
an upstream per-step control rather than a hard whole-trajectory wall-clock
limit; three native total-duration logs exceed 420 seconds.

## Native-score failure accounting

Each trajectory wrote a `cohort_info.json` artifact, but every artifact was a
scalar result object (for example, a TCGA no-match message) rather than the
cohort-to-metadata mapping required by `GenoMAS/eval.py`.

Consequently the unchanged native evaluator raised:

```text
AttributeError: 'str' object has no attribute 'get'
```

while reading the prediction artifact. It caught that per-task error and
emitted no selection metric. The campaign therefore has:

- requested trajectories: 4
- evaluator-unscorable trajectories: 4
- native-score failures: 4/4
- evaluable correctness records: 0
- infrastructure failures: 0 observed
- agent/artifact-contract failures: 4/4

This is not treated as a reasoning error or as an incorrect native score. The
trajectory records preserve the raw artifacts and scorer logs. The controller's
machine report records these as `native_scorer_failure`; its zero-valued cost
fields are a controller bookkeeping limitation, superseded by the native-log
totals above.

## Reliability outputs

No Pass@1, plurality accuracy, Oracle@4, selection-failure rate, all-wrong
rate, or agreement-to-correctness AUROC is defined because there are no
evaluable native rewards. The observed artifact-string plurality fraction is
0.25 (a four-way tie), but it must **not** be interpreted as reliability:
the cluster keys are invalid scorer inputs.

With one benchmark instance, any task-level bootstrap confidence interval would
also be degenerate and non-informative. In addition, this task was used for the
K=1 admission smoke, so this K=4 result is an engineering failure record, not a
confirmatory held-out reliability estimate.

## Provenance artifacts

- Controller records: `/scratch/11034/atzanakak/genomas_admission/k4_reliability_v1_20260825/records.jsonl`
  (SHA-256 `3047d95741d2610a31a7996497cceded607b8870d2d0050515b3b4a726ef11b7`).
- Controller report: `/scratch/11034/atzanakak/genomas_admission/k4_reliability_v1_20260825/reliability_report.json`
  (SHA-256 `1e686b8d5476a4206cf86f229e89b10e93fcf6ea6c1843629e6d2f5e6f0dcfbf`).
- Per-run worktrees, native logs, scorer logs, and score JSONs are retained
  under `/scratch/11034/atzanakak/genomas_admission/k4_reliability_v1_20260825`.

The experiment stops here, as requested. Any repair or new held-out K=4 panel
would require explicit approval and a new preregistered campaign manifest.
