# AutoBA K=4 pilot v1 — execution and results

Status: **COMPLETE**. All 12 (amended) preregistered tasks ran to
completion: 48/48 requested trajectories attempted, 40 completed, 8 failed
and correctly classified (never silently scored). This report is the
Reliability Suite v1 analysis called for by Steps 4–5 of
`prompts/autoba_reliability.md`, over
`reports/autoba_k4_pilot_v1_preregistration.md` as amended (D-56: one task
substitution, chipseq-001 → chipseq-003, made before any valid trajectory
ran — see that report's Amendment section). Nothing beyond this pilot was
started.

## Pre-flight verification (before the corrected launch)

- Git HEAD at commit `8f0fc9b` (clean tree) at initial launch; the D-56
  amendment landed as commit `695206d` before the corrected relaunch.
- Frozen manifest re-verified byte-for-byte: SHA-256
  `6709a7762512820e3073cfe0002c0be9f56596acddd79b5f4eecf29caeb38579` matched
  before launch; the amendment is a separate manifest
  (`autoba_k4_pilot_v1_20260829_amendment_01.json`, SHA-256
  `97b400c98c9ad8ebf31e53e5fb8b557950d1ac1fdd89adcb159dc1468d6a52cd`), never
  an edit to the original.
- vLLM endpoint confirmed healthy (`Qwen3-Coder-30B-A3B-Instruct`,
  `max_model_len: 32768`) before both the initial and corrected launch.
- Slurm allocation (job `950393`, partition `gh`) had walltime until
  `2026-08-30T20:43:08` — comfortably covered the full run.
- All 12 (corrected) tasks' `generate_data.py` run once and verified against
  `context.data_files` before the corrected relaunch (see D-56).

## Execution timeline

Sequential, one task at a time, exactly as frozen. First launch
(`2026-08-29T04:01:14Z`) produced 16 invalid trajectories across 4 tasks due
to the missing-data bug (D-56) and was stopped; corrected launch ran
**17h23m** end to end (`2026-08-29T13:50:25Z` → `2026-08-30T07:13:13Z`),
inside the preregistered 24–36 h estimate.

| # | Task | Elapsed | Exit |
| - | --- | ---: | --- |
| 1 | `chip-seq/chipseq-002` | 2h00m | 0 |
| 2 | `crispr-screens/crispr-001` | 1h09m | 0 |
| 3 | `genome-assembly/assembly-002` | 0h40m | 0 |
| 4 | `long-read-sequencing/lrs-001` | 2h00m | 0 |
| 5 | `metabolomics/metab-001` | 1h10m | 0 |
| 6 | `methylation-analysis/meth-001` | 0h45m | 0 |
| 7 | `multi-omics-integration/moi-001` | 2h00m | 0 |
| 8 | `population-genetics/popgen-001` | 2h00m | 0 |
| 9 | `proteomics/prot-001` | 1h33m | 0 |
| 10 | `spatial-transcriptomics/stx-001` | 2h00m | 0 |
| 11 | `chip-seq/chipseq-003` | 0h02m | 0 |
| 12 | `crispr-screens/crispr-003` | 2h00m | 0 |

Every per-task campaign script exited 0 (the runner itself never crashed;
individual trajectory failures are recorded, not propagated as a
campaign-level crash). vLLM stayed healthy the entire run; no infrastructure
interruption occurred during the corrected launch.

## Per-trajectory results

`official_reward` is the native `harness/grader.py::grade_task` weighted
criteria score (0–1).

| Task | idx=0 | idx=1 | idx=2 | idx=3 | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| `chip-seq/chipseq-002` | 0.0 (timeout) | 0.0 (timeout) | 0.0 (timeout) | 0.0 (timeout) | de novo motif discovery; model's plan assumed a conda/MEME-Suite environment this node does not have (see Failure analysis) |
| `crispr-screens/crispr-001` | 1.0 | 1.0 | 1.0 | 1.0 | unanimous, `stable_correct` |
| `genome-assembly/assembly-002` | 1.0 | 1.0 | 0.35 | 1.0 | `unstable_recoverable` |
| `long-read-sequencing/lrs-001` | 0.1 | 0.1 | 0.1 | 0.1 | unanimous, `stable_wrong` — consistent partial-credit answer, never the full one |
| `metabolomics/metab-001` | 1.0 | 1.0 | 1.0 | 1.0 | unanimous, `stable_correct` |
| `methylation-analysis/meth-001` | 1.0 | 1.0 | 1.0 | 0.1 | `unstable_recoverable`; idx=0 is this campaign's one confirmed early-completion (`early_terminated=true`, 341s vs. the 1800s ceiling) |
| `multi-omics-integration/moi-001` | 0.1 | 0.1 | 0.1 | 0.1 | unanimous, `stable_wrong` |
| `population-genetics/popgen-001` | 0.1 | 0.1 | 0.1 | 0.1 | unanimous, `stable_wrong` |
| `proteomics/prot-001` | 0.1 | 1.0 | 0.1 | 1.0 | `unstable_recoverable`, exact 2/2 tie — see Selection failure below |
| `spatial-transcriptomics/stx-001` | 0.1 | 0.1 | 0.1 | 0.1 | all 4 score 0.1 (same substantive failure: `target_file missing`), but idx=2's glob match count differs cosmetically (`matched 2 file(s)` vs. `1`), so 3/4 form the plurality cluster and 1 is a singleton — `unstable_unrecoverable` (no run scored ≥1.0, so instability here is entirely cosmetic, not a sign of behavioral variance) |
| `chip-seq/chipseq-003` | — (execution_failure) | — (execution_failure) | — (execution_failure) | — (execution_failure) | native AutoBA crash, see Failure analysis |
| `crispr-screens/crispr-003` | 0.1 | 0.1 | 0.1 | 0.1 | unanimous, `stable_wrong` |

## Failure analysis (8 of 48 trajectories)

**`chip-seq/chipseq-002` — 4/4 timeout, 0 attempted artifacts.** This is a
genuine AutoBA/environment-mismatch finding, not an adapter bug: the
model's plan for de novo motif discovery assumed a `conda`/MEME-Suite
environment (its generated code included `source /opt/miniconda3/bin/
activate ...`), which does not exist on this node (no conda/mamba anywhere,
per `reports/autoba_tool_provisioning.md`). That line fails inside the
agent's own generated bash script, and with only 1 round completed in the
full 1800s window (versus 6–9 rounds on tasks the model is better matched
to), the trajectory never recovered. Classified `timeout` because no
attempted artifact ever existed; token counts (141–156K input tokens per
trajectory) confirm the model was actively working, not stalled on the API.

**`chip-seq/chipseq-003` — 4/4 execution_failure, ~30–40s each.** A native
AutoBA crash, entirely inside the pinned upstream source, not this
project's adapter:

```
File ".../AutoBA/src/prompt.py", line 191, in format_ai_response
    self.slow_print(response_message[key], speed=0.01)
TypeError: string indices must be integers, not 'str'
```

`response_message` was a string where AutoBA's own prompt-formatting code
expected a dict — a real parsing robustness gap in the pinned AutoBA
source (`a9f8f1244faf8b33cf1154150d612acf5026a4d9`), reproduced consistently
across all 4 independent trajectories for this specific task's prompt.
Correctly classified `execution_failure` (nonzero return code, no
early-exit) rather than silently scored as a wrong answer. No AutoBA source
file was touched to work around this, per the non-invasive-adapter rule.

Both failure modes are **genuinely about AutoBA in this environment**, not
about the harness built this pass — the same harness correctly completed 40
other trajectories across 10 different tasks with real, varied,
non-degenerate reward values.

**Selection failure: `proteomics/prot-001`.** 2/4 trajectories scored 1.0,
2/4 scored 0.1 — an exact tie. The deterministic tie-break (lowest
trajectory index among tied clusters) picked a wrong-cluster winner,
`plurality_correct=0` despite `oracle_at_k=1`. This is precisely the
selection-failure phenomenon Reliability Suite v1 is designed to surface: a
correct answer existed among the K=4 samples, but naive plurality voting
would not have selected it.

## Pooled reliability analysis (preregistered primary definitions)

Computed with `biomni_uncertainty.reliability.evaluate_reliability` (the
same completed-only-primary-agreement definition used for Biomni and
GenoMAS) over all 48 pooled records via
`scripts/aggregate_autoba_k4_pilot_v1.py`. Full output:
`/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829_reliability_report.json`.

| Metric | AutoBA (this pilot) |
| --- | ---: |
| `pass_at_1` | 0.400 [0.100, 0.700] (n=10 evaluable tasks) |
| `plurality_accuracy` | 0.400 [0.100, 0.700] (n=10) |
| `oracle_at_k` (K=4) | 0.500 [0.200, 0.800] (n=10) |
| `agreement_plurality_fraction` | 0.850 [0.750, 0.950] (n=10) |
| `selection_failure_rate` | 0.100 [0.000, 0.300] (n=10) |
| `all_wrong_rate` | 0.500 [0.200, 0.800] (n=10) |
| `agreement_to_correctness_auroc` | 0.542 |
| `agreement_to_correctness_auprc` | 0.422 |
| `agreement_risk_coverage.aurc` | 0.492 |

`chip-seq/chipseq-002` and `chip-seq/chipseq-003` have zero completed
trajectories each and are correctly excluded from every completed-only
metric's denominator (`n=10` of 12 tasks), while remaining fully visible in
failure accounting.

**Failure taxonomy** (completed-only agreement):

```
stable_correct:         2   (crispr-001, metab-001)
stable_wrong:           3   (lrs-001, moi-001, popgen-001)
unstable_recoverable:   3   (assembly-002, meth-001, prot-001)
unstable_unrecoverable: 2   (crispr-003, stx-001)
```

**Agreement is high (0.85 mean plurality fraction) but only weakly
predictive of correctness** (`agreement_to_correctness_auroc = 0.542`,
barely above chance): half of the 10 evaluable tasks are `stable_wrong` or
`unstable_unrecoverable` — AutoBA converges confidently and repeatably on
the *same* wrong answer as often as it converges on a correct one. With only
10 evaluable task instances this is a wide, hypothesis-generating estimate
(pass@1's own CI spans [0.1, 0.7]), not a confirmed finding — but it is a
real, unforced result: it comes from real execution failures and honest
scoring, not from any tuning of this pass's metric definitions, which are
byte-for-byte the same ones already used for Biomni and GenoMAS.

## Cross-agent comparison (descriptive only)

| | Biomni-R0 (BiomniEval1, held-out 120) | GenoMAS (GenoTEX, 12-task pilot) | AutoBA (this pilot) |
| --- | ---: | ---: | ---: |
| Pass@1 | 0.442 | 0.300 | 0.400 |
| Plurality accuracy | 0.617 | 0.417 | 0.400 |
| Oracle@4 | 0.792 | 0.500 | 0.500 |
| Agreement→correctness AUROC | **0.896** [0.855, 0.930] | 0.529 | 0.542 |

(Biomni-R0 numbers from `reports/rl_harness_preregistration.md`'s scope-study
anchor; GenoMAS from `reports/genomas_k4_pilot_v1_results.md`.)

The native benchmarks differ and raw accuracy is not directly comparable
across them as if all tasks had equal difficulty — the comparison that
matters is **reliability structure**, not a leaderboard. On that axis the
answer to this project's standing question is unambiguous on this evidence:

> **AutoBA's reliability profile looks like GenoMAS's, not Biomni's.**
> Agreement→correctness AUROC (0.542) sits at the same near-chance level as
> GenoMAS (0.529), both far below Biomni-R0's strong 0.896. Oracle headroom
> over plurality is minimal for both AutoBA (0.500 vs. 0.400) and GenoMAS
> (0.500 vs. 0.417), unlike Biomni-R0's larger 0.792 vs. 0.617 gap. AutoBA
> does not reveal a third reliability regime on this evidence — it
> reproduces GenoMAS's regime with a structurally different agent
> (different codebase, different execution model, different failure modes:
> a conda-environment mismatch and a native prompt-formatting crash, versus
> GenoMAS's artifact-contract and agent-control failures).

This is now **two independent agents (GenoMAS, AutoBA) showing the same
near-chance self-consistency signal**, against one (Biomni-R0) showing a
strong one. That pattern is worth taking seriously as a hypothesis about
when self-consistency is and is not a useful reliability signal (e.g.,
single-strong-model-with-official-tools vs. weaker/local-model-with-
generated-code agents) — but two 10–12-task pilots is not enough to
generalize beyond "worth a larger, purpose-built follow-up," which is
explicitly out of scope for this pass (see Stop below).

## Resource accounting

| | Total |
| --- | ---: |
| Trajectories requested | 48 |
| Trajectories completed | 40 |
| Trajectories failed (classified, excluded) | 8 (4 `timeout`, 4 `execution_failure`) |
| Input tokens | 4,897,077 |
| Output tokens | 642,040 |
| Measured runtime (sum of trajectory runtimes) | 62,541.8 s (17.4 h) |
| Wall-clock (sequential driver, corrected launch, start to finish) | 17h23m |
| Paid API cost | $0.00 (local model) |
| GPU-hours (single GH200, sequential) | ≈17.4 (well under the 24–36 h estimate — early-completion + several fast natural terminations, not solely early-completion; see Known limitation below) |

**Known limitation, not a correctness issue:** early-completion
(`workspace_fingerprint`-based) fired for only 1 of 40 completed
trajectories (`meth-001` idx=0). Inspecting a converged-and-correct
`crispr-001` trajectory's poll log shows its output file being rewritten
every 20–30s for the *entire* 1800s window even after the correct answer
was already present (108/180 polls "ready," but never for 6 consecutive
polls) — AutoBA's own review/refinement loop keeps touching the file,
resetting the 60s stability clock. Grading always runs correctly on
whatever state exists at timeout regardless (this is why `crispr-001`
still scored 4/4 correct), so this affects wall-clock cost, not data
validity. A future pass could raise `poll_seconds` or key stability on
content hash instead of mtime to see if that reduces flicker — not done
here, since it is a performance tuning question, not a scientific one, and
the frozen protocol was not to be changed mid-campaign.

## Provenance

- Preregistration (as amended): `reports/autoba_k4_pilot_v1_preregistration.md`.
- Amendment record: `DECISIONS.md` D-56;
  `autoba_k4_pilot_v1_20260829_amendment_01.json` (SHA-256
  `97b400c98c9ad8ebf31e53e5fb8b557950d1ac1fdd89adcb159dc1468d6a52cd`).
- Invalid pre-amendment trajectories (excluded, archived):
  `/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829_INVALID_missing_data_20260829/`.
- Per-task campaigns, records, native logs, worktrees:
  `/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829/{01..12}_*_k4/`.
- Driver progress log: `autoba_k4_pilot_v1_20260829.driver.log` (same
  directory).
- Pooled reliability report:
  `autoba_k4_pilot_v1_20260829_reliability_report.json` (same directory).
- No AutoBA or bioTaskBench source file was modified. No reliability metric
  definition was changed because of this pilot's outcomes.

## Stop

Per `prompts/autoba_reliability.md`'s own stop rule: **STOP here.** Do not
expand AutoBA further, do not expand GenoMAS, do not start OpenBioLLM/
BioMaster/a fourth agent, do not start or resume RL work, and do not change
the reliability suite based on these outcomes. Returning for operator
review.
