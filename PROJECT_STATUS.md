# PROJECT_STATUS

## AutoBA K=4 pilot v1 — COMPLETE (2026-08-29/30, D-55/D-56)

**Completed.** AutoBA (admitted 2026-08-28 as the project's third distinct
biomedical agent, `reports/autoba_admission.md`: clean K=1 score 1.000 + tiny
K=4 smoke 4/4 correct/agreeing on bioTaskBench `assembly-001`) now has all
three engineering prerequisites its admission report flagged as missing
before a scientific campaign:

- **Reliability Suite v1 schema mapping** —
  `src/biomni_uncertainty/adapters/autoba.py` (`autoba_row`,
  `answer_cluster_key`, `classify_autoba_failure`) plus the campaign runner
  `scripts/run_autoba_k4_reliability.py`, mirroring GenoMAS's
  runner-script pattern. `reliability.py`'s metric definitions unchanged.
- **Token accounting** — `scripts/autoba_biotaskbench_agent.py` wraps the
  local vLLM client to record `response.usage` per call (never fabricated
  when unavailable), flushed on both normal completion and SIGTERM.
- **Early-completion detection** —
  `adapters/autoba.py::run_with_early_completion` + `workspace_fingerprint`,
  a content-fingerprint poll/terminate loop run from the campaign script
  (bioTaskBench's own `harness/runner.py` ships the same poll/`done_check`
  mechanism but never wires it up for its own `--agent-cmd` path). **Two
  real bugs were found and fixed against a live trajectory**, not left as
  known gaps: bare file existence is not a safe "done" signal (a live run
  terminated on an unfinished placeholder); a loose glob criterion can lock
  onto a stray file while the real named deliverable is still missing (a
  live run terminated at score 0.1 with the scored file never created).
  Both are covered by regression tests reproducing the exact failure shape
  with real subprocesses (`tests/test_adapters_autoba.py`, 31 new tests, all
  green; full existing suite still green in a freshly-built `.venv`).

Seven pip-only bioinformatics packages (pysam, scikit-allel, MACS3, QUAST,
NanoStat, Scanpy, Squidpy) were installed and independently verified into
the execution venv (`/scratch/11034/atzanakak/genomas_admission/venv`) —
`reports/autoba_tool_provisioning.md`. This node has no `conda`/`mamba`/`R`
and no bioinformatics domain modules; R-only tools (HOMER, MEME suite,
DESeq2/edgeR/limma/methylKit/ChIPseeker) and several standalone C/C++
binaries (bedtools, samtools, VCFtools, PLINK — the last is additionally
aarch64-incompatible) remain unavailable. No task is excluded from the
candidate pool on that basis: every task's grading criteria score output
files' structure/values, never tool provenance (the same property already
established for `assembly-001`, which listed QUAST yet was solved in pure
pandas), so an unavailable tool means a Python-native substitute is needed,
not that the task is unexecutable.

A 12-task x K=4 (48-trajectory) confirmatory panel was frozen via a
mechanical, pre-outcome selection rule spanning genome assembly, sequence
processing, alignment/mapping, variant/genomic analysis, tabular/statistical
bioinformatics, and tasks exercising a confirmed-installed real tool —
`reports/autoba_k4_pilot_v1_preregistration.md`, original manifest SHA-256
`6709a7762512820e3073cfe0002c0be9f56596acddd79b5f4eecf29caeb38579`. A
post-fix K=1 verification smoke re-running the already-admitted
`assembly-001` task validated the full pipeline end-to-end before launch.

**Launched** 2026-08-29 with explicit operator approval (referencing commit
`8f0fc9b` and the manifest SHA-256 above). **One post-launch amendment,
before any valid trajectory ran (D-56):** the campaign was stopped ~9.5
hours in when the first four tasks' results showed 16/16 trajectories
failing with `failure_class=timeout` and zero attempted artifacts — root
cause was an engineering oversight, not AutoBA performance: 11 of the 12
frozen tasks (all but the already-admitted `assembly-001`) had never had
their `generate_data.py` setup step run, so their workspaces had no input
data. Fixed by running `generate_data.py` for all 12 corrected-panel tasks;
while auditing all 34 tasks' generators for this fix, `chip-seq/chipseq-001`
was found to also require `samtools`/`bedtools`/`HOMER` (unavailable) at
data-generation time and was replaced with `chip-seq/chipseq-003` via the
same mechanical selection rule (`chipseq-002` moves into slot 1). The 16
invalid trajectories are excluded from the campaign and archived (not
deleted) at
`autoba_k4_pilot_v1_20260829_INVALID_missing_data_20260829/`. Recorded as a
separate amendment manifest
(`autoba_k4_pilot_v1_20260829_amendment_01.json`, SHA-256
`97b400c98c9ad8ebf31e53e5fb8b557950d1ac1fdd89adcb159dc1468d6a52cd`), not by
editing the original frozen manifest. The corrected campaign was relaunched
2026-08-29T13:50:25Z via `scripts/run_autoba_k4_pilot_v1.sh` and ran to
completion at 2026-08-30T07:13:13Z (17h23m, within the 24-36h estimate).

**Results (`reports/autoba_k4_pilot_v1_results.md`):** 40/48 trajectories
completed, 8 failed and correctly classified (4 `timeout` on
`chipseq-002`'s de novo motif discovery — the model's plan assumed an
unavailable conda/MEME-Suite environment; 4 `execution_failure` on
`chipseq-003` — a genuine native AutoBA crash,
`TypeError: string indices must be integers, not 'str'` in
`AutoBA/src/prompt.py::format_ai_response`, reproduced across all 4
independent trajectories). Pooled reliability (n=10 evaluable tasks):
Pass@1 0.400, plurality accuracy 0.400, Oracle@4 0.500,
agreement→correctness AUROC **0.542** (near chance). One selection failure
found (`prot-001`, exact 2/2 tie, correct answer existed but was not
selected). Descriptive cross-agent comparison:
**AutoBA's reliability profile matches GenoMAS's (near-chance AUROC 0.529
vs. 0.542) far more than Biomni-R0's (strong AUROC 0.896)** — this project
now has two independently-built agents (GenoMAS, AutoBA) showing a
near-chance self-consistency signal against one (Biomni-R0) showing a
strong one, a pattern worth a future purpose-built follow-up but not
something this small a pair of pilots can generalize from on its own.

**Current blockers.** None. The pilot is complete and the prompt's own stop
rule applies (see Next actions).

**Tests run:** `pytest -q` in a freshly-built `.venv` (Python 3.11.8) —
full suite green except two modules requiring optional dependencies not in
this project's own `pyproject.toml` (`test_budget.py` needs `langchain_core`,
`test_rl_harness_local_agent.py` needs `httpx`; both are separate
environments' dependencies per README, not a regression) and
`test_mock_end_to_end.py` (needs the separately-cloned `biomni` package,
also per README). `ruff check`/`ruff format --check` clean on all changed
files.

**Active experiment IDs:** `autoba_k4_pilot_v1_20260829` (COMPLETE, one
amendment applied before any valid trajectory).

**Known failures:** the 16 pre-amendment trajectories are a known,
diagnosed, and fixed engineering failure (D-56), excluded from the
campaign's scientific accounting. The 8 in-campaign failures (4 `timeout`,
4 `execution_failure`) are genuine AutoBA/environment findings, documented
in `reports/autoba_k4_pilot_v1_results.md`, not open issues to fix.

**Next actions:** per `prompts/autoba_reliability.md`'s own stop rule,
**none within AutoBA/GenoMAS/RL scope right now.** Do not expand AutoBA
further, do not expand GenoMAS, do not start OpenBioLLM/BioMaster/a fourth
agent, do not start or resume RL work, and do not change the reliability
suite based on these outcomes. Returned for operator review.

---

## Reliability benchmark branch — specification and CPU implementation ready (2026-08-25)

`reports/reliability_suite_v1.md` freezes the K=4 reliability protocol,
metrics, failure taxonomy, bootstrap rule, and JSON report contract before a
new multi-agent outcome. `src/biomni_uncertainty/reliability.py` provides the
agent-agnostic evaluator and its focused tests cover plurality, oracle,
taxonomy, and explicit scorer-failure handling. The candidate audit and gated
three-agent recommendation are in `reports/candidate_agent_audit.md`.

No live agent smoke was attempted in this session: `nvidia-smi` cannot reach a
driver on the current host. Biomni remains the only immediately
admission-ready implementation; CellVoyager and BioMaster require the stated
native-scorer/credential gates. No large benchmark run has been launched.

**Last updated:** 2026-08-25 (**Vista compatibility implementation is ready,
but the required end-to-end smoke is hardware-blocked; no scientific RL
run.**) The obsolete `agentlightning==0.3.0` interface remains incompatible
with verl 0.9.0, but the current upstream source at
`8435586d147b4cf7bff33e687d7317149e79cbb8` has a native-verl trainer and
local proxy/controller architecture. Commit `c5d7e33` adapts the unchanged
Biomni subprocess/evaluator boundary to that local-runner API, adds a
reproducible three-import compatibility patch for verl 0.9.0, and provides a
one-GH200 detached Vista smoke launcher. The Python 3.12, model, and data
assets are rooted under `/scratch/11034/atzanakak/biomni_vista`; the GCC 14.2
and CUDA 13.0 toolchain issue is resolved and the current native-verl trainer
reaches actor/FSDP initialization. The allocated Vista job exposes exactly one
95.6-GiB GH200. Its BF16 FSDP actor occupies 71.8 GiB, while vLLM must create a
second full BF16 dummy model (about 65 GiB) before its hybrid sleep/offload
mechanism can run. Two detached K=2 smoke attempts consequently stopped at
that bootstrap (both CUDA OOM; Ray host memory reached 210.94/212.75 GiB and
211.90/212.75 GiB). vLLM CPU offload of 45/55 GiB is accepted on the command
line but cannot help this initial dummy allocation. A current-stack,
one-GPU end-to-end smoke therefore has no supported path; it requires at
least two visible GH200 GPUs, or a separately reviewed sequential
deallocate/reload trainer design. It must not be reported as passed until its
artifacts show a real update and subsequent rollout.

The prior blocker was precisely diagnosed: `agentlightning`'s own copy of a verl `TaskRunner` imports
`verl.workers.fsdp_workers.{ActorRolloutRefWorker,AsyncActorRolloutRefWorker,
CriticWorker}`, which verl 0.9.0 no longer has (unified into
`engine_workers.py`). A related one-line import (`create_rl_sampler`) was
patched; this one is not a one-liner — real due diligence on downgrading verl
instead (0.8.0: same problem; 0.6.0: has the old API but its own
`transformers` incompatibility cascades further) showed that path reopens the
exact multi-hour vLLM weight-sync hang D-50 already fixed, with no bound on
where it stops. Deliberately stopped rather than hand-patching agentlightning's
internal training-loop classes under time pressure. Environment reverted to
D-50's known-good state. Everything upstream of agentlightning's verl glue is
independently proven: the Biomni-via-subprocess design and reward path (D-50 +
D-51's 14 new tests, real `OfficialEvaluator`), and LoRA GRPO training
mechanics in isolation (D-50, verl 0.9.0 + vLLM 0.24.0 directly, no
agentlightning). No RL training has occurred. See *Harnessed-GRPO
pre-registration* below and **D-49/D-50/D-51**. Previously, 2026-08-21
(RL-signal preflight complete, D-48):)

---

## Harnessed-GRPO pre-registration — FROZEN, no training run (2026-08-21, D-49)

**Design:** `reports/rl_harness_preregistration.md`. **Full suite: 632
passed.** No RL training has occurred; no scientific RL result exists.

**Engineering audit, verified:**

* No verl/Agent Lightning/PEFT/DeepSpeed/Ray/vLLM installed anywhere yet —
  starting from zero, nothing blocks it (network to PyPI/GitHub confirmed).
* **Agent Lightning + verl fits this project's existing design almost exactly
  unchanged**: its proxy sits at the same `base_url` Biomni's `A1` agent
  already points at (`source="Custom"`) — only the URL value changes, no
  Biomni code edit (D-01 preserved). verl's SGLang rollout backend reuses the
  same server binary pinned throughout this project.
* **Serious blocker found and mitigated, not worked around by downgrading the
  model**: full-parameter GRPO fine-tuning of Biomni-R0-32B needs ≈448 GB
  (bf16 weights + fp32 AdamW master/moments) against 384 GB total on 4×96GB
  H100. **LoRA** keeps trainable-parameter optimizer state to a few GB and
  keeps Biomni-R0-32B as the primary candidate.
* Context-overflow safeguards (`budget.py` R2–R5) and the official evaluator
  are both preserved by construction — neither requires new engineering.
* Cost is dominated by rollout wall-time (Biomni trajectories are slow), not
  the RL update itself: the frozen pilot config costs roughly 1.5 GPU-hours
  of rollout time per training step.

**Split, verified disjoint, no new manifest built:**

| pool | n | source |
| --- | ---: | --- |
| training | 200 | `manifests/phase1.jsonl` ∪ `manifests/phase2b.jsonl` |
| held-out eval | 120 | `manifests/scope_main.jsonl` (Biomni-R0's already-characterised population) |
| reserved, untouched | 100 | never-used pool; not spent |

Reusing the scope study's 120 instances as held-out means **the pre-RL half of
every endpoint is already computed** (D-46/D-48) — only a post-RL K=4 rerun on
the identical instances is needed.

**Frozen pilot config**: LoRA GRPO, uniform sampling (no uncertainty
guidance, per D-48), K=4, batch 16 prompts/step (64 rollouts/step), ≈25
optimizer steps (≈1,600 total training rollouts), official binary reward
only. **GO** requires the held-out reward-gain CI lower bound > 0 **and** the
safety check (agreement rising with no accuracy gain, or accuracy dropping)
not firing.

**Next actions, in order:**

1. ~~Build the verl + Agent Lightning environment~~ **DONE** (D-50):
   `/scratch/11034/atzanakak/envs/rl_harness` — verl 0.9.0, agentlightning
   0.3.0, vllm 0.24.0 (pinned down from 0.27.1 — see D-50 for why), flash-attn
   2.8.3.post1.
2. ~~Engineering smoke test: route one real Biomni trajectory through the
   Agent Lightning proxy~~ **DONE, GREEN** (D-50): trace capture (161 spans,
   full message/token content), reward/answer flow intact, R2–R5 confirmed
   firing (not just present in config) on a second run against the
   budget-enabled config.
3. ~~A synthetic/dummy-reward optimizer-step check~~ **DONE, GREEN** (D-50):
   LoRA GRPO on Qwen2.5-0.5B/GSM8K, 2 steps, real gradient updates, correct
   FSDP↔vLLM weight sync (0.999 rollout/training policy correlation).
4. ~~Wire the components into one runnable pipeline~~ **CODE DONE, GPU
   RUN BLOCKED** (D-51): `scripts/rl_harness/` — dataset loader, `BiomniLitAgent`,
   `rl_score_one.py`, `rl_harness_pilot_launcher.py`. 14 new tests, all
   green. Blocked on the agentlightning/verl version gap above — see D-51
   for the exact diagnosis and why a further verl downgrade was not pursued.
5. **Next**: either wait for/request an agentlightning release matching
   verl's current unified-engine layout, or scope a *separate* session to
   reproduce agentlightning's `TaskRunner` role/resource-pool construction
   against verl 0.9.0's `engine_workers.py` directly — real engineering work,
   not a quick patch. Only after that: launch of the frozen pilot training
   run (D-49 §B.2) still requires **separate, explicit operator approval** —
   not yet given, and not yet reachable regardless.

**No GPU server is currently running for this work.**

---

## RL-signal preflight — COMPLETE, both arms NO-GO (2026-08-21, D-48)

**Pre-registration:** `reports/rl_signal_preflight_preregistration.md`, frozen
`ad0af40` before any `mixed_reward` number existed. **Full suite: 623 passed.**

Reuses the scope study's frozen 120-instance/K=4 trajectory set as data only —
no new inference, no new instance. Question: does agreement-based uncertainty
identify prompts whose rollouts carry useful within-prompt reward variation
(the raw material a GRPO update needs), as distinct from whether it detects
correctness (already answered, D-46).

| | Arm A (Biomni-R0) | Arm B (Mistral) |
| --- | ---: | ---: |
| n_mixed_reward / all_correct / all_wrong | 67 / 28 / 25 | 47 / 20 / 53 |
| AUROC(U, mixed_reward) | **0.685** [0.577, 0.786] | 0.594 [0.496, 0.690] |
| (a) discrimination CI-supported | **yes** | no |
| highest-uncertainty-stratum enrichment | 0.96x | 0.85x |
| (b) enrichment ≥ 1.5x, CI-supported | no | no |
| (c) 25%-budget capture beats uniform | no | no |
| **verdict** | **NO-GO** | **NO-GO** |

**The stratum table is the finding, not a footnote.** Both solvers show the
same inverted-U: enrichment peaks at *moderate* disagreement (1.4–1.6x) and
falls back to at-or-below baseline at *maximal* (four-way) disagreement — the
exact stratum a "sample the most uncertain prompts" policy would target, and
the one fixed in advance for the GO check, precisely to prevent picking the
best-looking stratum after seeing the table.

**Steps requiring a GO were not performed**: no RL protocol drafted, no
matched-compute design, no post-RL evaluation plan, no harness engineering.
**A descriptive (not GO-licensed) model note**: Biomni-R0's prompt pool
carries more GRPO-learnable signal on this population (55.8% mixed-reward,
20.8% all-wrong — dead weight for GRPO) than Mistral's (39.2% mixed-reward,
44.2% all-wrong), at the cost of ~2.9x slower rollouts and a higher
context-overflow rate. This bears on a *plain* uniform-sampling GRPO run, not
on the (unsupported) uncertainty-guided one.

**No RL training, no new experiment. All prior GPU servers remain shut down.**

---

## Scope-and-boundary study — preflight complete, Solver B frozen (2026-08-13, D-44)

**Design:** `reports/scope_study_preflight.md`. **Tables:**
`reports/tables/scope_study/`. **Full suite: 577 passed.**

**Boundary.** D-43 is closed and is not altered, recomputed, rescued, overturned
or reinterpreted. This is separate work on a **disjoint population** (the
never-used pool, not Stage C's frozen 78), with a new primary question — *does
the separation between reliability detection and successful error correction
replicate under an independent solver family?* — and a pre-registered secondary
question about criterion verifiability. D-43's own reversal condition anticipates
exactly this kind of follow-on.

### Frozen before any inference, committed at `e40c773`

* **Remaining-pool table, rebuilt from artifacts.** 433 total, **213 consumed,
  220 never used**. `crispr_delivery` and `rare_disease_diagnosis` **confirmed
  exhausted**; 8 families remain; **15 × 8 = 120 is feasible with 100 to spare**.
  **Correction to the record: the reserved pool is 220, not the 233 in D-22 and
  `phase2_protocol.md` §3.1** — 13 instances were consumed later by
  `verify_prereq_diag3` (8) and `phase2b_smoke` (5), neither of which wrote a
  manifest. Any document citing 233 is stale.
* **Criterion-verifiability rubric**, from task definition and the official
  `_compute_reward` only: Tier 1 `lab_bench_seqqa`; Tier 2 six families; Tier 3
  `screen_gene_retrieval`. **Tier and task identity are fully confounded at both
  extremes** and the secondary analysis is bound by that. MedAgentBench stays an
  external anchor.
* **Solver B1 / B2**, chosen on independence, availability and servability, never
  on accuracy. The obvious choice (`gemma-4-31B-it`, already served) was rejected
  because the study fixes the verifier at the frozen Stage-C C1 gemma, which
  would have made Solver B same-model with the verifier where Solver A is
  cross-family. Operator chose the three-family design.
* **24-instance capability gate** over already-consumed Phase-2B instances, plus
  frozen **PASS / FAIL / CAPABILITY-CONFOUNDED** bars and the
  **normalized-headroom denominator guard** (absolute ≥ 0.10 **and** ≥ 5
  recoverable instances, else the ratio is reported `undefined`).
* Dirty-tree launch guard **exercised on the real entrypoint** first: exit 2.

### Gate result — **PASS**

| | B1 `Mistral-Small-3.1-24B` | Solver A, same 24 |
| --- | ---: | ---: |
| completion | **0.9583** | 0.9167 |
| usable answer | **0.9167** | 0.8333 |
| degeneration | **0.0417** | 0.0833 |
| infrastructure failure | 0.0000 | 0.0000 |
| accuracy | 0.3750 | 0.5833 |
| mean wall s / trajectory | **106.5** | 309.7 |

B1 operates the scaffold **more cleanly than Biomni-R0 does** and at **2.9×
lower cost**, with a well-formed `<solution>` block on every completed run and no
interface repair used. **The accuracy gap is not established at n=24 and is not
claimed:** paired difference −0.2083, 95% CI **[−0.4583, +0.0417]**, exact
McNemar p = 0.2266. Solver A run through the same adjudicator also returns PASS —
a positive control on the bars.

**`mistralai/Mistral-Small-3.1-24B-Instruct-2503` @ `68faf511…` is frozen as
Solver B. B2 (`gemma-4-31B-it`) was NOT run** — the frozen rule reaches it only
through FAIL.

Both approvals have since been granted; see below.

---

## Matched scope study — COMPLETE (2026-08-21, D-46)

**Pre-registration:** `reports/scope_study_preregistration.md`, committed before
the first trajectory existed. **Phase 1 and Phase 2 both finished. Full suite:
607 passed** (plus 15 Phase-2 tests, see D-46).

**Phase 1 (trajectory generation) — final counts.**

| | valid/480 | terminal failures | rate |
| --- | ---: | ---: | ---: |
| Arm A `Biomni-R0-32B` | 391 | 89 `model_context_overflow` | 18.5% |
| Arm B `Mistral-Small-3.1-24B` | 418 | 62 `model_context_overflow` | 12.9% |

Zero non-terminal/unresolved trajectories; both terminal-failure counts and
rates fall inside the project's historical residual-failure band. No terminal
failure was retried, repaired, or excluded from any denominator — an instance
with zero usable trajectories scores 0 under every selector alike (D-18's
"non-answer never wins a tie" convention, unchanged).

**Phase 2 (verifier scoring) — 0 comparison errors, 0 unresolved ties, both
arms.** 3,408 comparisons (Arm A) + 6,336 (Arm B) = 9,744, all via the frozen
Stage-C C1 port, unchanged criteria/K/aggregation. Capsule adapter
sanity-checked byte-for-byte against a real Stage-C capsule before touching any
scope-study data (see D-46).

### H1 verdict: **NOT REPLICATED** — correction is solver-specific

| | Arm A (Biomni-R0) | Arm B (Mistral) |
| --- | ---: | ---: |
| Pass@1 / plurality / Oracle@4 | 0.4417 / 0.6167 / 0.7917 | 0.3833 / 0.4083 / 0.5583 |
| agreement→correctness AUROC | **0.8956** [0.855, 0.930] | **0.8144** [0.752, 0.870] |
| **detection established** | **yes** | **yes** |
| verifier gain over plurality | **+0.0833**, CI [0.0083, 0.1583] | −0.0167, CI [−0.0917, 0.0583] |
| **correction established** | **yes** | **no** |
| normalized recovery | 47.6% (guard passed) | −11.1% (guard passed) |

Both arms show detection established; correction is established for Arm A only
→ **H1 NOT REPLICATED** (the frozen four-row rule's "correction solver-specific"
row). Capability-confound check: paired Pass@1 diff (B−A) = −0.0583, CI
[−0.1752, +0.0583] — **not** capability-confounded (upper bound far from the
−0.15 bar).

**A mechanism finding qualifies Arm A's "correction established" result, and is
reported prominently rather than folded into the headline.** Restricted to the
47 instances where the verifier judged between ≥2 genuinely disagreeing
candidates, Arm A's gain drops to +0.1064 with CI **[−0.0426, 0.2553]** —
**does not exclude zero**. Half of Arm A's net capture (5 of 10) comes from a
verified structural artifact on `patient_gene_detection`: `select_plurality`'s
tie-break scope spans all 4 trajectories including unparseable singletons,
while the verifier's candidate scope is parseable-answers-only, so it can never
make the specific mistake the plurality baseline makes when an earlier-indexed
parse failure ties against a later-indexed correct answer. **The frozen primary
verdict is reported unmodified**; this decomposition decides nothing but means
"correction established for Solver A" should not be read as demonstrated
adjudication skill without this caveat. Flagged as a design-level asymmetry
worth fixing before any future reuse of this comparison — not fixed now, per
scope.

### Artifacts

`reports/tables/scope_study/scope_main_h1_verdict.json`,
`h1_per_instance_{a,b}.csv`, `detection_report_{a,b}.json`,
`detection_per_instance_{a,b}.csv`. Raw: `<output_root>/scope_main_verifier/`
(capsules, selections, per-comparison caches, port self-tests, score metadata).

### Server / allocation state

Verifier server (gemma) and both trajectory-generation servers have been shut
down; no GPU process is running. Nothing further is scheduled — see D-46 for
what this does and does not license next.

---

<details>
<summary>Previous status header (2026-08-11)</summary>

**Last updated:** 2026-08-11 (**Stage 0, Stage A, and all pre-Stage-C items closed** — A.6 NULL, A.7 reachability pre-registered in the stop rule, A.8 shows Arm 2 was re-solving not adjudicating, shrink guard installed (D-41), A.5b's 51% restated as a 20–51% band pending operator review. **Stage C is unblocked**; it runs in a separate session under its frozen rule + Amendment 1. Previously: **Stage 0 and Stage A closed** — D-39 retraction, Stage C stop rule frozen first, write-up reframed, and the A.1–A.5 decomposition complete (**D-40**). The paper is submittable on this material. Stage C runs in a separate session under its frozen stop rule. The live-GPU-window plan below is superseded and closed.)

</details>

## Current plan: Stage 0 → Stage A → (separate session) Stage C

The paper is submittable after Stage 0 + Stage A. **No GPU work, no inference,
in either stage.** Stage B (expert label audit) is not being run — no domain
reviewers available; its expertise-free subset is folded into A.5 and the
domain-judgment portion is an explicit limitation.

### Stage 0, closed (2026-08-11)

**0.1 — Stage C's stop rule is frozen and committed first**
(`reports/stage_c_stop_rule.md`, commit `63c179b`), deliberately ahead of any
Stage A number. Once alternative aggregations of Arm 2 exist, a Stage C NO-GO
becomes negotiable; precommitting while the numbers are unknown is what keeps
this from reading as another rescue attempt. Fixes two verifier cells
(substitution permitted, expansion forbidden), an interface-validity
precondition with exactly one bounded repair, D-38's decision rule reused
verbatim so no bar-shopping is possible, NO-GO **and** INCONCLUSIVE both ending
the program, and an explicit list of closed rescue moves.

**0.2 — D-39** amends D-38 without editing it, per D-32's standing rule.
Retracted: that Arm 2 upper-bounds verification and therefore licenses a
family-level NO-GO. Information monotonicity requires a decision-maker that can
ignore irrelevant input; a fixed LLM under a fixed prompt is not one — and the
data contains a direct counterexample, since the 46.2% off-menu failure mode is
*created by* the extra information and cannot exist for a verifier never shown a
candidate list. **Unchanged:** every D-38 number. **Surviving claim:** free-form,
same-model, tool-enabled adjudication failed under a maximally-informed but
operationally unstable regime. Step 5 stays cancelled on independent evidence
(D-37's 7.1% mode-A headroom), untouched by the retraction.

**0.3 — write-up corrected** (`reports/writeup_draft.md`), reframed around
generation / selection / execution reliability / selective deferral instead of
phase chronology. Substantive corrections: the 45 no-correct instances are no
longer conflated with stratum B's 53 (generation limitation is *not* established
for the 45 — A.5 tests it); 0.093 restated as a fixed-pool K=4 candidate-
*selection* ceiling, not a ceiling on any family of methods; the structural
result stated with its four conditions and its scope asserted by test
(`tests/test_structural_scope.py`, 4 tests, each dropping one condition and
showing the collapse stops holding); process findings moved to a
reproducibility-and-deviations section; ends on a scientific conclusion.

**"Zero high-confidence wrong claims" is removed from the abstract and
corrected in the body.** Verified against the frozen decision log: the
controller made **0 of 150** online claims meeting the ≥3-agreement definition,
so the rate is *undefined*, not 0%. All **121** of its ACCEPTs carried support
exactly 2 (max support observed = 2), and the band is unreachable *by
construction* — three agreeing trajectories requires two of the first three to
have agreed, which terminates earlier. It is a theorem about the stopping rule,
not a safety finding. The defined comparison: fixed K=4 made 76 confident calls
and was wrong on 8 — 10.5%, 95% Wilson CI [5.4%, 19.4%].

**Full suite: 459 passed.**

### Pre-Stage-C items, closed (2026-08-11, D-41/D-42)

**Both blocking items done, so Stage C is unblocked.**

**A.6 (blocking) — semantic discriminability probe: NULL.** Rule frozen at
`2051a7f` before any AUROC existed, fixing family/primary/correction in advance.
Leakage barrier enforced structurally and asserted by a label-permutation
invariance test. Primary feature `own_answer_share` scores AUROC **0.504**
(corrected CI [0.313, 0.670]). **`singled_out` carried A.5b only because it was
given the correct answer** — its label-free analogue carries nothing, so a Stage
C capsule cannot expose it. A.4's null now spans structural *and* semantic
features.

**A.7 (blocking) — 31 of 78 (39.7%) unreachable by construction.** Both
denominators pre-registered in `stage_c_stop_rule.md` **Amendment 1**: primary
unchanged (78, bar 0.0641, decides the verdict); secondary (reachable n=47, bar
0.1064) decides nothing. Framing correction: the flagged set is **18, not 21**
— the 3 extraction failures are a subset of the 18 singled-out.

**A.8 — matched-K oracle.** Pool Oracle@3 **0.6455** vs Arm 2 **0.5522** on the
same 67 instances, difference **−0.093**. Selection cannot fall below a set's
best element, so **Arm 2 was re-solving, not adjudicating** — a cleaner basis
for D-39 than information monotonicity.

**A.5b's 51% is now a band (post hoc).** 18 instances at ratio > 1.0 but only 7
at ≥ 2.0, and five within 10% of parity where enumeration is indistinguishable
from preference. Restated **20–51%**; qualitative conclusion holds throughout,
precise fraction claimed nowhere. `reports/a5b_review_sheet.md` is generated for
**operator** adjudication — deliberately not adjudicated here.

**D-41 — pre-commit shrink guard**, refusing commits where a tracked file drops
below 10% of its committed size, with a logged override. Third instance of the
same pattern (D-27's silent gate, D-29's untracked controller, DECISIONS.md
reduced to one character). Failure path exercised in 7 tests and verified live.

**Manuscript:** `capture = 0` replaces −0.033 as the controller headline (+ a
methods paragraph on why capture/harm belongs beside Δ); the S1 safety claim is
**dropped** rather than weakened; A.3's attribution becomes the abstract's
positive claim; A.5b's two claims split by provenance.

**Full suite: 495 passed.**

---

### Stage A, closed (2026-08-11, D-40) — existing-data decomposition

Full report: `reports/stage_a_decomposition.md`. CPU only, no GPU, no model
calls, no new instances, **no LLM used to adjudicate any label**. Every
interpretation rule was written into its script's docstring before the
corresponding numbers existed.

**A.1** — the adjudication null is **not** an aggregation artifact. Dropping the
2-of-3 requirement buys +0.013 [−0.090, +0.115]; Oracle@3 over Arm 2's own
answers reaches only 0.513 against the pool's 0.6026 ceiling, so Arm 2's answer
set is worse than the set it was adjudicating and no aggregation could rescue
it. D-38's verdict is not recomputed against any alternative aggregation.

**A.2** — `Δ = (capture − harm)/n` reconciles exactly for every selector.
**69.2% of Arm 2's harm is interface harm** (vs only 4 `wrong_in_menu`), above
the 50% bar fixed in advance: D-39's retraction has real quantitative content.
Independently: **the controller's capture against fixed K=4 is 0** — it never
converted a fixed-K=4 error into a correct answer on any of 150 instances.

**A.3** — **the selectivity belongs to the agreement signal, not the
controller.** Agreement-thresholded fixed K=4 matches or beats it at every
comparable coverage, and at a 5%/10% error budget the controller reaches zero
coverage while agreement counting reaches 30.7% at 2.2% error.

**A.4** — no usable separating signal in cheap traces. The one nominal hit
clears the bar by 0.0002 and dies under Bonferroni (post-hoc check, labelled).

**A.5** — **"30% unreachable" is a loose upper bound on a generation
limitation.** Enumeration-robust `singled_out` is **18 of 35** assessable
instances (51%): the model discussed the correct answer preferentially and
committed something else. Plus **3 genuine extraction failures**. Corrected
scoring: no-correct 45 → 42 (30.0% → 28.0%), Oracle@4 0.700 → 0.720, selection
headroom **0.093 → 0.113**. A.5a found 0 scoring artifacts; gene-symbol synonymy
NOT DONE (no offline alias table, not approximated). Stale-label and
defensible-answer judgments need domain reviewers, are not done, and are **not**
delegated to an LLM.

Two bugs found and fixed, both of which would have manufactured favourable
results: a candidate-extraction regex that matched prose instead of the gene
list (inflating `singled_out` from 18 to 24), and a normaliser too weak to see
`'BRCA1'.` as `BRCA1` (which would have hidden real scoring artifacts).

**15 new tests. Full suite: 474 passed.**

---

### Stage C, CLOSED (2026-08-12, D-43) — NO-GO (C2) and INCONCLUSIVE (C1); the experimental program ends

**Verdict computed. The experimental program ends per stop rule §6. Full
detail: D-43.** Method: LLM-as-a-Verifier (arXiv 2607.05391,
`github.com/llm-as-a-verifier/llm-as-a-verifier`), training-free, scoring
candidates by the expectation over score-token logits.

**Primary verdict, both cells, run once:**

| | C1 `gemma-4-31B-it` (cross-family) | C2 `Biomni-R0-32B` (same-model) |
| --- | ---: | ---: |
| Δ | −0.0000 | **−0.0641** |
| 95% CI | [−0.1154, 0.1025] | [−0.1667, 0.0384] |
| validity / comparison errors / unresolved ties | 1.0000 / 0 / 0 | 1.0000 / 0 / 0 |
| **verdict** | **INCONCLUSIVE** | **NO-GO** |

Both outcomes independently trigger §6's stop. **Sharpest mechanism finding**:
C2's pairwise preferences are cyclic on **52.6%** of the 19 instances where a
cycle is possible (vs C1's 5.3%) — C2 is not producing a coherent ranking, at
zero interface-error rate, consistent with its much lower unconstrained
on-scale mass (0.630 vs C1's 1.000). Read through the pre-registered addenda:
A1.2 makes C2's NO-GO **ambiguous** (cannot distinguish "interface wasn't
D-38's problem" from "weak verifier"); C1's INCONCLUSIVE — cross-family,
strong on gate 1, zero interface error — is the more informative result and
still does not recover headroom. Best-supported reading, matching the
preregistration's §10 table: **a broader trajectory-verification gap** — the
candidate pool itself carries limited separating signal for this judgment
task, consistent with A.4's and A.6's prior null trace-feature findings.

**Two infrastructure bugs caught and fixed before either verdict number
existed** — a reward-lookup/candidate-construction divergence (`9905804`) and
a bash brace-parsing bug in the batch launcher (`1386f23`) — neither reached a
scored comparison. Detail in D-43 §2.

**Deferred capability covariate: still not launched, and now moot for Stage
C.** The program has already ended per §6; there is no longer a pending
conditioning question for the covariate to resolve. No fourth cell, no
capability-ceiling cell, no re-run at a different K or granularity. D-38's
result and D-39's retraction both stand unchanged — what changes is that the
empirical question D-39 reopened is now closed by D-43.

**Full per-instance tables:** `reports/tables/stage_c/
stage_c_{verdict,per_instance,report}_{c1,c2}.{json,csv}`.

---

Everything below this line describes the run that produced the verdict above
and is kept for provenance.

**Design frozen before any BiomniEval1 score exists:**
`reports/stage_c_stop_rule.md` **Amendment 2** (cell identities, C2's role
substitution, method departures, §4's health bars mapped onto a scoring
interface) and `reports/stage_c_preregistration.md` (capsule, criteria,
scoring config, decision rule, reporting, interpretation, budget).

**Cell count stays at two.** A three-cell design was proposed in the Stage C
brief; §3/§7.1 of the stop rule forbid raising the count, and the brief itself
declares that file binding. The operator chose to keep two cells with the
brief's roles:

| cell | role | model | revision |
| --- | --- | --- | --- |
| C1 | different lineage, **cross-family primary** | `google/gemma-4-31B-it` | `842da3794eaa0b77d5f08bae87a17459d91ff475` |
| C2 | same model, **interface control** | `biomni/Biomni-R0-32B-Preview` | `71432eb3d5e583bee757e0f9437a17e711e8e3d1` |

C2's role is a substitution beyond identity (it replaces `Qwen/Qwen3-32B` in the
*same lineage, no agent RL* role), recorded as an operator decision in
Amendment 2. Consequence, stated as a limitation: **no cell now tests whether
agent-task RL cost verification ability**, and none is added later.

**Gate status.**

| gate | state |
| --- | --- |
| 1 — port valid on the reference method's own public data | **PASS** — see below |
| 2 — capsule-able evidence exists in the traces | **PASS**, verified against live `phase2b` and `phase1_pooled` event logs |
| 3 — token logprobs through SGLang, per model | **PASS** for both cells, after a port fix |
| 4 — cells/criteria/format/rule/budget frozen | **PASS** (the two documents above) |
| 5 — clean tree, D-36 guard, GPU allocation | **PASS**, ran on `c563-001`, launch commit `1386f23`, clean tree |
| 6 — explicit operator approval | **GRANTED** 2026-08-11 |

**Verdict computed 2026-08-12. See D-43 for the full result. All six gates
closed.**

| commit | contents |
| --- | --- |
| `b90f519` | pre-verdict freeze — Amendment 2, pre-registration + ADDENDUM 1, the port, gate 1 |
| `c75aa77` | capsule + criteria + runner + frozen analysis, and the capsules themselves |
| `247a1d2` | batch launcher, D-36 guard on the score entrypoint, run provenance |
| `1c3a8ea` | login-node submit helper |
| `aa17f9b` | the §9 reporting analyses |
| `1386f23` | fix: bash brace parsing silently dropped the D-04 context override |
| `9905804` | fix: reward-lookup/candidate-construction pool-filter divergence |
| (this commit) | D-43 verdict, PROJECT_STATUS update |

**Capsules built and frozen:** 78 instances → **177 capsules → 244 directed
pairs → 5,856 comparisons per cell**, matching the pre-registered figure
exactly. **0 truncated.**

**ADDENDUM 1** to the pre-registration records three interpretation
pre-registrations that gate 1 made formulable, all written before any verdict
number: (A1.1) gate 1 as a **family-neutral capability anchor** — MedAgentBench
traces are Claude Opus 4.8's, so neither cell is same-model there, which is
what makes the 69.5 pp C1−C2 headroom margin a clean capability measurement;
the BiomniEval1 margin is read against it, with the stability assumption
between mechanically-checkable and judgment tasks stated as attackable, and no
numeric threshold attached, because attaching one would create a second
decision rule; (A1.2) **a C2 null is ambiguous, a C2 success is not** — C2
recovered only 23.6% on a corpus where the interface was demonstrably healthy,
so a C2 failure cannot distinguish "the interface was not D-38's problem" from
"this checkpoint is a weak verifier"; (A1.3) if `gemma-4-31B-it` cannot operate
the Biomni scaffold the capability covariate is reported **UNAVAILABLE**, never
as a floor-effect capability estimate.

**Two corrections made before any scoring, disclosed rather than silently
applied** (both to constants that appear in no frozen document, were
introduced in uncommitted code, and were changed while no outcome existed):
capsule section **order** was wrong — truncation cuts the tail and the failure
summary rendered last, so a capsule at the ceiling lost exactly the evidence
the `#alignment` criterion is defined over; and `MAX_CAPSULE_CHARS`
30,000 → 50,000, because at 30,000 **40% of capsules (71/177) were truncated**
while the largest capsule is 47,193 chars, so 50,000 truncates nothing and the
ceiling is a context-safety net rather than a content budget.

**Frozen-population fidelity, worth recording because it nearly went wrong.**
The runner reproduces the stratum construction exactly: `phase2b` **unfiltered**,
`phase1_pooled` **instrumented-only**. Phase 2B's evaluation-only shadow
trajectories are part of the candidate sets D-37 froze and therefore of the
frozen floor (0.4103) and ceiling (0.6026); filtering them out — which the
Phase-2 shadow-exclusion rule superficially suggests — would have silently
changed the candidate sets and made Δ incomparable with D-38. That rule binds a
*controller* choosing what to do next; it does not retrospectively redefine a
frozen population.

**Capability covariate: DEFERRED, now moot.** It was scheduling, not a
finding, and the programme has since ended per D-43/§6 — there is no longer a
pending conditioning question for it to resolve. **Not launched.**

**Gate 1 result (2026-08-11): PASS.** Full 300-task MedAgentBench, published
configuration unmodified (g20, criteria `query`/`consistency`/`structure`, K=8,
pivots=2, seed 0, 12.0 comparisons/task), **0 comparison errors** in either run,
both exit 0, reference checkout `4c5cdaf`.

| verifier | rate | swing correct | oracle headroom recovered |
| --- | ---: | ---: | ---: |
| published, Gemini 2.5 Flash (Vertex) | 73.3% | ~32.9/38 | 64.6% |
| **`gemma-4-31B-it` (C1)** | **74.7%** | **37/38** | **93.1%** |
| `Biomni-R0-32B` (C2) | 71.3% | 27/38 | 23.6% |

Pass@1 210.60/300 (62.1% on the 38 swing tasks), Oracle 225/300 = 75.0%.

**The open-weight port reproduces and exceeds the published gain.** Per brief §3
this settles the disjunction the gate was built to settle: the method is **not**
a property of the proprietary verifier, it transfers to open weights, and a
BiomniEval1 null would therefore be about BiomniEval1 rather than about a broken
implementation.

**Not a controlled comparison**, as pre-registered: no Vertex anchor was run, the
verifier model differs, and n = 38 swing tasks, so C1's +4 tasks over the
published figure is suggestive and nothing more.

**What the C1-vs-C2 gap here is, and is not.** It is a large verifier-capability
difference — 93.1% vs 23.6% of the same headroom, on the same data, port,
criteria and configuration — consistent with the format-compliance measurement
below. It is **not** evidence on Stage C's cross-family question: the
MedAgentBench trajectories were generated by Claude Opus 4.8, so *neither*
verifier is same-model with respect to them, and the same-model/cross-family
contrast does not exist in this run. Amendment 2's declaration that the
direction is **open** stands untouched.

**Gate 1 also found a real defect, and it is the reason the gate exists.** The
reference implementation names SGLang as supported but constrains its score
position with vLLM's `structured_outputs`. SGLang's `ChatCompletionRequest`
declares no `model_config`, so pydantic's default `extra="ignore"` drops the
field **without error**. Measured on the project's own endpoint, on-scale
probability mass:

| constraint sent | Biomni-R0-32B | gemma-4-31B-it |
| --- | ---: | ---: |
| none | 0.5995769755 | 0.9999995854 |
| `structured_outputs` (vLLM) | 0.5995769755 — **bit-identical** | 0.9999995156 |
| `regex` (SGLang) | **0.9884** | **1.0000** |

Unported, the expectation would be taken over a fragment of the distribution
and, on failure, fall back to a flat 0.5 — a tie indistinguishable from a
verifier that cannot separate two candidates. `scripts/stage_c_verifier_port.py`
fixes the mechanism, narrows the alphabet from 40 tokens to the 20 bare letters
so the returned support is complete (measured cost: mean |ΔR| = 0.0005, max
0.0015 over 12 real comparisons), and **raises instead of silently tying**.

**A model-level observation from the same measurement:** Biomni-R0-32B puts
only ~0.60 of its mass on scale tokens unconstrained, gemma-4-31B-it ~1.0. The
format-compliance instability D-38 hit is a property of that checkpoint, and
the cross-family model does not share it.

**Departures from the published configuration**, both frozen in Amendment 2:
full round-robin instead of PPT (N ≤ 4 here — 59 instances with 2 unique
candidates, 17 with 3, 2 with 4 — so all 244 directed pairs are cheap and the
ring seed drops out; PPT reported as a faithful secondary at zero extra
compute), and a biomedical criteria decomposition at the published cardinality
of three. Intransitivity is reported, with the honest caveat that a cycle needs
N ≥ 3 and so it is **defined on only 19 of 78 instances**.

**Reproduction anchor skipped:** the published MedAgentBench figure uses Gemini
2.5 Flash via Vertex and no credentials exist here. Per brief §3 the port's
absolute number is reported against the published one and labelled **not a
controlled comparison**. This does not amend the standing rule against
proprietary dependencies — that rule binds on a comparator inside the candidate
pool, and both cells are open-weight.

**Budget** (frozen, ceiling 40,000 comparisons + 200 Biomni trajectories):
gate 1 is 10,944 comparisons per model — the reference runner scores only the
**38 swing tasks** of 300, not all 300; the Stage C verdict is 5,856 per cell;
the capability covariate is 78 K=1 trajectories per model.

**Artifacts:** `/scratch/11034/atzanakak/biomni_unc_runs/stage_c_port_validation`.
**Reference checkout:** `/scratch/11034/atzanakak/repos/llm-as-a-verifier`
@ `4c5cdaf`, pinned and never edited. **14 new tests. Full suite passes.**

---

## Superseded: live-GPU-window plan (2026-08-10, closed)

Working the 6-step plan in order: Step 0 (process debt) → Step 1 (CPU
preflight: stratum reconciliation, verifiability×headroom, degeneration×
stratum) → Step 2 (GPU: candidate-adjudication pilot, 2 arms) → Step 3
(write-up, parallel) → Step 4 (conditional on Step 2: K=2 characterization) →
Step 5 (gated, not started without explicit approval). Job `3388121` still
live.

### Step 0, closed (2026-08-10, D-36) — dirty-tree guard + source hashing

`scripts/phase2b_run.py` and `cli.py dispatch` both refuse to launch (exit
non-zero) from an uncommitted tree, including untracked-file-only dirtiness —
exactly D-29's failure mode. `--allow-dirty` is the logged exploratory-only
escape hatch. Every trajectory's `metadata.json` now carries `source_hashes`
(SHA-256 of every `src/biomni_uncertainty/*.py` and `scripts/*.py` file), so
a future D-29-style audit is one equality check instead of a reconstruction.
"Never overwrite a gating script" recorded as a standing rule in `CLAUDE.md`.
10 new tests (433 total), guard verified live against the real dirty tree
(nonexistent-path invocation, exits before touching config/manifest/endpoint).

**Process note, recorded honestly:** an earlier guard-verification attempt
pointed at the *real* `phase2b.yaml`/`phase2b.jsonl`/production endpoints
with the actual Step-0 changes accidentally stashed away first, and was
killed by a command timeout mid-run. No frozen artifact was affected (all 150
`phase2b` instances were already complete, so the run would only have
short-circuited to "reused" for each; verified: zero new mtimes, decision-log
count unchanged at 150) — but the methodology was wrong and is not to be
repeated. Corrected to a nonexistent-path check, which proves the guard's
ordering without risk.

### Step 1, closed (2026-08-10, D-37) — preflight complete; 1b reshapes Step 2

`reports/track_c_preflight.md`. CPU-only, ~15 s.

**1a (reconciliation).** Two previously-quoted stratum partitions of the same
150 instances are different, non-nested classifications, now reconciled into
one canonical table. The "91 unanimous" figure = 82 genuine unanimous + 9
single-usable-trajectory instances (correctly stratum A, not unanimity); "51
split" = the 2–3-distinct-answer slice of stratum B's full 53; "45
no-correct-trajectory" is an orthogonal outcome axis including 13 of the 82
true-unanimous instances (unanimously wrong). **100% of recoverable headroom
sits in stratum B by construction** — 0.093 [0.047, 0.140] overall, 0.264
[0.151, 0.377] on stratum B's 53 instances.

**1b (decisive).** Mode-A eligibility fixed *before* classification from one
full prompt per task: **only `lab_bench_seqqa` qualifies**, and only 1 of
stratum B's 53 instances is that task (it's already 86.7% accurate — almost
nothing left to disagree about). **Mode-A headroom share: 7.1%, below the
15% floor.** Verdict, per the pre-fixed rule: **"the computational-verification
route is not where the headroom is."** Confirms, as measurement, the
reservation raised before this work started.

**1c (replicates on both pools).** Degeneration concentrates in the
no-correct-trajectory bucket, not the split stratum: `phase2b` 68.9% vs
27.3%; `phase1_pooled` 33.3% vs 21.4% — same direction, smaller gap, wide
CIs at n=14–18. D-34's pre-screening idea is substantially, not completely,
de-risked on the bias objection.

**Consequence for Step 2 (already applied there):** the two-arm design
(one-shot vs. tool-enabled adjudication) is unaffected in mechanics. The
"computational vs. inferential" stratification is no longer meaningful (one
mode-A instance in stratum B); restated as
evidence-retrievable-via-a-working-tool vs. domain-judgment-with-no-reliable-
route. Step 2 is now understood as testing evidence-based adjudication, not
mixed computational verification.

11 new tests (444 total). No frozen artifact touched.

### Step 2, closed (2026-08-10, D-38) — candidate-adjudication pilot: NO-GO

Full report: `reports/track_c_step2.md`. Acceptance rule frozen before any
trajectory (floor 0.4103 / ceiling 0.6026 / gap 0.1923 over 78 pooled
stratum-B instances; GO if Δ's 95% CI lower bound > 0, NO-GO if Δ's CI upper
bound < gap/3 = 0.0641, else INCONCLUSIVE).
`scripts/track_c_adjudication_pilot.py` (`prep`/`arm1`/`arm2`, committed
`cddf96c`) built the 78-instance candidate set from frozen `phase2b` +
`phase1_pooled` trajectories only — zero held-out instances touched.

**Arm 1** (one-shot, no tools, 234/234 complete) — descriptive NO-GO (Δ =
−0.218, CI [−0.333, −0.103]).

**Arm 2** (tool-enabled agent, the kill-shot arm — strictly more information
than a real VERIFY trajectory ever has, D-32) — 234/234 attempted, 190
succeeded / 44 failed (17.9% degeneration-failure rate, same
`model_context_overflow`/`budget_terminated` definition used throughout).
**Pooled verdict: NO-GO** — Δ = −0.077, 95% CI **[−0.192, 0.038]**, entirely
below the 0.0641 bar, point estimate negative. Replicates independently on
`phase1_pooled` alone (Δ = −0.16, CI entirely negative). Mechanism: 47% of
instances produce no majority-resolved answer at all (not "confidently
wrong" but "frequently no answer"); 46% of instances have at least one
off-menu sample; 96% show at least one soft runaway-generation event.

**Consequence.** Because Arm 2 upper-bounds any real VERIFY mode-A
trajectory, this licenses treating the result as evidence against the
VERIFY mode-A/evidence-based-adjudication family generally, not only this
pilot's framing. **Step 4 (K=2 characterization) is not indicated** — the
node is left idle per the standing instruction rather than spending the
reserved ~120-instance pool on a premise this pilot falsified. **Step 5
(VERIFY implementation) remains gated** on the user's separate, explicit
approval — this finding is evidence for that decision, not a substitute for
it.

`scripts/track_c_adjudication_analyze.py` (committed `95cf660`) implements
the frozen rule end-to-end and was verified against live partial data
(14–20/234) before the full run completed, then re-run against the
completed 234/234 result. 11 new tests. **Full suite: 455 passed.**

Step 3 write-up (`reports/writeup_draft.md`) updated the same day with the
real Step-2 result in §7 — every section is now final, nothing left as a
placeholder.

**Next:** none of Steps 0–4 remain open. Step 5 is the only remaining item
in the live-GPU-window plan, and it does not proceed without the user's
separate explicit "yes."

## VERIFY prerequisites — all five adjudicated (2026-08-10)

| item | verdict | evidence |
| --- | --- | --- |
| 5 — RESAMPLE/VERIFY definition | ✅ DONE | D-32, `reports/verify_definition.md` |
| 1 — evidence-channel repair | ✅ DONE | D-33, `reports/evidence_channel_repair.md` |
| 2 — retrieval provenance | ✅ DONE | D-33 (same report) |
| 3 — residual failure re-measured | ❌ **FAILED — 28.1% [15.6%, 45.4%]** | D-34, `reports/residual_failure_remeasurement.md` |
| 4 — healthy-control validation | ✅ **PASS** | D-35, `reports/verify_prerequisite_control_validation.md` |

**A prospective VERIFY experiment is BLOCKED**, independent of item 4's
result. Item 4 passing establishes the repaired environment is safe to build
on; it does not touch item 3's already-measured 28.1% residual failure rate,
which remains the open, unresolved blocker. No repair of item 3 was started
automatically — that decision is separate and has not been made.
**Phase:** **PHASE 2B COMPLETE.** Track A does not survive prospective test as
frozen. Full report: `reports/phase2_report.md`. `reports/phase2_plan.md` §1's
decision rule for "both co-primary hypotheses fail" selects **Track C**
(diversity and difficulty) as the pre-registered next step.
Phases 1, 1.5 and 2A are complete, frozen and independently re-verified.

**The open decision recorded below is now closed (D-28):** the Controller-v2
redesign named in `reports/phase2_report.md` §11 was adjudicated offline against
a bar written down before the analysis ran, and **rejected**. Track C stands as
selected. Awaiting operator approval before any Track-C work begins.

## Post-Phase-2B review (2026-08-10) — independent, CPU only, no GPU

Two new reports, written by a session that read the repository rather than the
project history. **No frozen Phase-0/1/1.5/2A/2B artifact was modified.**

| document | contents |
| --- | --- |
| `reports/post_phase2b_assessment.md` | independent re-derivation of every Phase-2B headline number; what was and was not falsified; which Phase-1/1.5/2A claims survive; confirmatory vs post-hoc separation; the pre-stated bar (§5) a redesign had to clear |
| `reports/controller_v2_offline_assessment.md` | 18 parameter-free policies replayed over both available pools; adjudication against that bar; **Recommendation B — move directly to Track C** |
| `scripts/controller_v2_offline.py` + `tests/test_controller_v2_rules.py` | the driver (CPU only, ~40 s) and 13 tests, including that `v1_frozen` reproduces the frozen controller exactly |

**Verification performed.** Full suite **382 passed**, ruff clean. H1/H2,
coverage, the selective table, matched compute, S4 and the sensitivity analysis
all reproduce **exactly** from stored artifacts via an independent script; the
frozen controller re-simulated offline matches the online decision log on
**0/150 mismatches**, all 150 hash chains verify, manifest hash re-verifies.

**The corrected halt gate's failure path is now exercised end to end** — the
check D-27 specified but never ran. `scripts/phase2b_verify.py` post-fix returns
**exit code 1** and `VERDICT: BLOCKED` on `phase2b_smoke` (9/24 = 37.5%) and on
`phase2b` (93/600 = 15.5%); every other gate passes in both. Run read-only
against the frozen run trees via a redirected output root, so no frozen artifact
was touched.

**Why the redesign was rejected** (full reasoning: D-28):

1. The candidate rule (refuse a bare 2-of-4 plurality) is **4.7–5.7 pp worse
   than Controller v1** on both pools — 2-of-4 is 35–42% accurate, not 0%, so
   refusing it trades an expected 0.40 for a certain 0.
2. No rule clears the pre-stated bar: best margin over same-cost blind
   allocation is **+1.2 pp** at the realized order (CI spans 0) against a
   required ≥3 pp, and the whole `phase2b` effect is **two instances of 150**
   (eight of ten tasks tie fixed K=2 exactly).
3. **Structural:** `v1_no_abstain`, `v2_majority_no_abstain` and
   `v2_usable_majority_no_abstain` are the *identical policy* (asserted by
   test). Inside {ACCEPT, CONTINUE, ABSTAIN} with CONTINUE = resample, the
   2-of-2/2-of-4 distinction can only act by spending more (impossible at the
   K=4 ceiling) or by abstaining (net-negative). The hypothesis cannot express
   itself without a `VERIFY`/`REPAIR` action.

**What survives and what it points at.** The only self-funding adaptive
component is **failure-driven continuation** (escalate only when no usable
answer exists: 0.593 at mean K **2.13** vs fixed K=2's 0.580 at 2.00 — an
observation, not a result; the margin is two instances). `final_confidence ==
1.00` remains a validated *signal* (S4) but adds no decision value on top of
consensus history and does **not** enter a controller. The headroom that
remains is not reachable by voting: **30% of instances (45/150) have no correct
trajectory at all**, and on the 51 instances with 2–3 distinct answers the
correct answer is present but **in the minority** (Oracle@4 0.625/0.636 vs
plurality 0.375/0.273). That is the Track-C question, reached from the
controller side.

**Two process gaps found.** Gap 1 is now **audited and documented** (see the next
section); gap 2 is **deliberately not repaired**. Neither affects the Phase-2B
result, which reproduces exactly from artifacts.

* **The code that ran Phase 2B is not in git.** Every run records
  `project_git.commit = 2c0bfc1, dirty = true`. → Audited, D-29,
  `reports/phase2b_provenance.md`.
* **The residual-failure halt condition is still tripped** at 15.5% (12.0%
  excluding `rare_disease_diagnosis`). Roughly one trajectory in seven is dead,
  and the post-hoc decomposition shows **15 of Controller v1's 29 abstentions
  had ≤1 usable trajectory** — i.e. the abstention rule fired mostly on failure,
  not on disagreement. **Not repaired; stands exactly as measured.** Any next
  prospective run needs this under threshold first.

## Track C — first diagnostic (2026-08-10) — **NO-GO for diversity-by-resampling** (D-30)

CPU only, ~4 min, no GPU, no model calls; no prompt, temperature, tool, model or
generation change. Report: `reports/track_c_diversity_diagnostic.md`. Driver:
`scripts/track_c_diversity.py`. Reusable primitives:
`src/biomni_uncertainty/diversity.py`. Tests: `tests/test_diversity.py` (19).
17 tables + 1 figure at `<output_root>/track_c/results/`. The three-way
interpretation rule was fixed in the script's docstring **before** any outcome
association was computed.

**Verdict: Outcome B (correlated upstream, noisy downstream), secondary
component of Outcome C. Do not build a diversity mechanism.**

| finding | value |
| --- | --- |
| **plan Jaccard, disagreeing vs agreeing pairs** | 0.546 vs 0.538, **+0.008 [−0.040, +0.058]** — against a "different question" control of **0.301** |
| composite workflow distance | +0.020 [−0.034, +0.074] (below the pre-registered 0.05 bar) |
| **P(other correct \| this one wrong) by distance quartile** | 0.308 / 0.190 / 0.263 / 0.359 — **non-monotone**; high−low **+0.056 [−0.074, +0.180]** vs a ≥10 pp bar |
| **correct-minority isolation from the wrong plurality** | **−0.037 [−0.131, +0.046]** — wrong sign, 6/4 split, n=10 |
| tool-sequence similarity, disagree vs agree | −0.105 [−0.207, −0.005] — real divergence, but tool choice is barely question-specific (0.442 vs a 0.396 control) and it predicts nothing |

**Failure vs disagreement, kept separate** (150 instances): 82 unanimous,
**53 substantive disagreement (B)**, **15 insufficient evidence (A)**. Stratum A
is an infrastructure problem — the same phenomenon as the 15.5% residual failure
rate — and is excluded from every diversity statistic.

**Three findings that reframe the track:**

* **35.7% of trajectories make zero tool calls**, and are *more* accurate (0.724)
  than tool-using ones (0.652).
* **The evidence channel is substantially broken**: 30.0% of 1,395 tool calls
  error, concentrated where a VERIFY action would live — `query_pubmed` **68.9%**,
  `advanced_web_search_claude` **77.0%**, `query_scholar` **80.0%** — while
  structured databases work (Ensembl 6.6%, ClinVar 6.4%, GWAS Catalog 7.3%).
  Known Phase-0 limitation (E1 environment skipped); its cost is now quantified.
* **Retrieval content was never logged** (counts only, never names) — evidence
  overlap is unmeasurable from these traces. Top instrumentation priority.

**What a VERIFY action must do differently from RESAMPLE** (§11 of the report):
change the plan by construction, not by sampling; check the computation rather
than re-ask for a conclusion; repair or avoid the literature channel; log
retrieval by name; never spend a verification trajectory on stratum A.

## Phase-2B provenance recovery (2026-08-10) — D-29

A pre-registered prospective experiment ran from an uncommitted working tree.
**No commit in this repository is the Phase-2B execution commit**, and none is
claimed to be. Full audit: `reports/phase2b_provenance.md`. Script:
`scripts/phase2b_provenance_audit.py` (CPU only, read-only). Tests:
`tests/test_phase2b_provenance_audit.py` (8). Machine-readable:
`<output_root>/phase2b_provenance/`.

| class | n | what it means |
| --- | ---: | --- |
| **ESTABLISHED** | 14 | run-time version pinned by a cryptographic or behavioural attestation |
| **CHANGED_AFTER** | 3 | known to differ from what ran, change identified |
| **UNPROVEN** | 4 | exact run-time bytes unrecoverable; circumstantial evidence only |

**Attested:** `configs/phase2b.yaml` — stored `config_hash` `ee5f8cd3…`
recomputes bit-exactly (after restoring the three `${ENV}` expansions the
snapshot records; without that step the check false-alarms).
`manifests/phase2b.jsonl` — recomputes to the protocol's frozen `7cb5da3a…`.
`controller.py`/`policy.py` — **434/434 committed decision records reproduce
exactly**, including the free-text `reason` strings, with 150/150 chains
verifying. The untracked driver's output — **600/600 trajectory identities**
(`run_id`, `requested_seed`, `prompt_hash`, `run_dir`) recompute from tracked
code. `biomni_src` clean at `400c1f36…`.

**Changed after the run:** `phase2b_verify.py` (the D-27 gate fix — the buggy
version that produced the false PASS is gone and cannot be exhibited),
`phase2b_analyze.py`, `tests/test_phase2b_analyze.py`. None participates in
trajectory generation or scoring.

**Unrecoverable:** `scripts/phase2b_run.py`, `run_phase2b.sh`,
`phase2b_supervise.sh`, `tests/test_controller.py`. **mtime is circumstantial,
never proof** — asserted by test.

**Logged observation (not a correction to D-27):** the supervisor log ends
2026-08-02 at `WAITING_FOR_SMOKE`; the full run started 2026-08-09 with
`phase2b_supervise.sh` modified 4 minutes earlier. The supervisor that logged on
2026-08-02 did not launch the full run.

The working tree was committed as an explicitly-labelled **post-hoc provenance
recovery snapshot**, not as the execution commit. No frozen artifact was
modified and no history was rewritten.

## Phase 2B result (2026-08-10) — prospective test: BOTH CO-PRIMARY HYPOTHESES FAIL

150 held-out instances, 600 trajectories, run 2026-08-09→10 (8.5 h, 0 errors, 0
chain-verification failures). Full write-up, all numbers, all mechanisms:
`reports/phase2_report.md`.

| hypothesis | result | verdict |
| --- | --- | --- |
| **H1** reward retention (δ=0.05 margin vs fixed K=4) | −0.033, 95% CI [−0.067, −0.007] | **FAIL** |
| **H2** cost reduction (mean K < 3.0) | 2.893, 95% CI [2.760, **3.033**] | **FAIL** (narrowly) |

**Per protocol §7.5, this is the pre-registered falsification outcome.**
Stated plainly, not reframed: the frozen mandatory-K2-plus-abstention
controller does not reproduce fixed-K=4 reliability prospectively.

**Mechanism, not just verdict** (§4 of the report, from pre-registered
deliverables): the controller is accurate when it answers (0.711 among the
80.7% it accepts) but abstains on 19.3% of instances, each scored 0 by the
mandated accounting. The sharper finding: `mandatory_k2` accepts the instant
two trajectories agree, so **every** acceptance has identical support (=2) —
this erases the difference between a confident 2-of-2 stop (87.7% accurate)
and a reluctant 2-of-4 plurality (**35.0% accurate — below fixed K=1's blind
51.3%**), and the rule as frozen does not abstain on that weak state. A
same-cost matched-compute baseline (spend the identical trajectories with no
adaptivity at all) beats the controller outright (0.592–0.593 vs 0.573).

**A separate, serious process finding.** `scripts/phase2b_verify.py`'s
residual-failure-rate gate had an exact-string-match bug
(`"budget_terminated"` vs the runner's actual
`"budget_terminated_consecutive_runaway"`) that silently reported 0.0% in
*every* run. The true rate was **37.5%** in the smoke test and **15.5%** in
the full run — both above the pre-registered 15% halt threshold. Under the
corrected gate, the smoke test's true rate should have **blocked** the
(operator-approved) compressed auto-launch (DEV-2) before the full run's 8.5
GPU-hours were spent. **This does not explain the H1/H2 failure** — recomputed
excluding `rare_disease_diagnosis` (33.0% of the excess failure rate, also the
task deliberately oversampled per D-22), H1/H2 fail almost identically
(−0.032, mean K 2.856). Bug fixed and regression-tested; incident logged in
`reports/phase2_protocol.md` DEV-4, `DECISIONS.md` D-26/D-27.

**What survives.** Two secondary results are genuine, independent of the
headline failure: **S1** — 0% confidently-wrong for the controller vs 5.3% for
fixed K=4 (a real safety property); **S4** — `final_confidence == 1.00`
correct 89.8% (44/49) vs 65.1% (267/410) for the rest, a clean prospective pass
for the hypothesis D-19 explicitly deferred to this phase. Both are candidates
for a redesigned controller, to be tested in a **new, separately
pre-registered** prospective run — never as a retroactive fix to this one.

**Deliverables:** `reports/phase2_report.md`; 14 tables + 3 figures +
`phase2b_results.json` at `<output_root>/phase2b/results/`;
`tests/test_phase2b_analyze.py` (13 tests, including a regression test for the
gate bug); `scripts/phase2b_analyze.py`. Full suite: **369 passed.**

## Phase 2B — frozen protocol (2026-08-02, no inference run)

| item | value |
| --- | --- |
| Experiment ID | `phase2b` (new) |
| Protocol | `reports/phase2_protocol.md` — written before any prospective outcome exists |
| Manifest | `manifests/phase2b.jsonl`, **hash `7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd`** |
| Instances | **150 held-out**, overlap with Phase 1 asserted **= 0** at build time |
| Trajectories | 600 (K=4/instance; ~422 consumed, ~178 hidden shadows) |
| Config | `configs/phase2b.yaml` (serving identical to `phase1_5.yaml`; only benchmark + controller differ) |
| Controller | mandatory K=2 → agreement stop → up to K=4 → abstain when no two of four agree. **No fitted parameter.** |
| Co-primary | H1 non-inferiority vs fixed K=4 at δ=0.05; H2 mean-K CI upper < 3.0. Both required. |
| Power | 0.99 / 0.99 at n=150, simulated from the Phase-2A difference distribution; ≥0.84 even if disagreement is 3× worse |
| Compute | 600 trajectories, **~12–23 h**, 2×12 h jobs on one 4×H100 node, ≈80–96 GPU-hours |

**Held-out pool.** BiomniEval1 is 433 instances, all split `val` (no official
held-out split). Phase 1 used 50, so **383 were never run**; Phase 2B takes 150
and reserves 233. Allocation is deliberately **not** uniform:
`crispr_delivery` takes all 5 that remain in the entire benchmark (pool-limited),
`rare_disease_diagnosis` takes all 25 remaining (the pre-declared high-risk
stratum, n=5 → n=25), and the other 8 tasks take 15 each — 3× Phase 1's cell.
This exhausts the `crispr_delivery` and `rare_disease_diagnosis` pools; that is a
deliberate, reversible-before-launch spend, flagged in the protocol §3.2.

**Shadow isolation** is enforced by ordering plus commitment, not discipline: the
controller's decision is appended to a **hash-chained append-only log and flushed
before the next trajectory is generated**, so a shadow cannot influence an
earlier decision because it did not exist when that decision was committed.
Verified after the fact from timestamps and the chain; a broken chain is a
run-level halt condition.

**Not yet written** (the implementation step that follows approval):
`scripts/run_phase2b.sh`, `configs/phase2b_smoke.yaml`, the online controller
driver, `scripts/phase2b_analyze.py`.

## Reconciliation: Phase-2A 0.577 vs Phase-1 0.620 (2026-08-02) — RESOLVED, not a bug

Phase 1's pooled plurality is 0.620; Phase 2A's fixed K=4 is 0.577, on identical
data. Investigated with `scripts/phase2a_reconcile.py` and written up in
`reports/phase2_offline_replay.md` §1.1.

**Restricting the Phase-2A replay to Phase 1's native trajectory ordering
reproduces 0.6200 bit-exactly** (as does first = 0.4800 and Oracle@4 = 0.6400).
That single fact rules out denominator, replay, failure-handling and aggregation
causes simultaneously. The entire 0.04333 gap is **4 tied instances of 50** whose
lowest-index tiebreak happened to select the correct answer all four times; the
arithmetic closes to five decimals. Across the 24 fixed orderings, K=4 plurality
ranges **0.540–0.620** and only **6 of 24** reach 0.620 — Phase 1 drew one of the
six best. Two of the four "ties" are 4-way ties where every cluster has size 1,
i.e. "plurality" degenerates to returning the first trajectory.

**0.577 is the unbiased estimate for a sequential controller** and is what every
Phase-2A comparison uses. The frozen Phase-1 report is not wrong — it reports one
realization, and it was a lucky one. Locked against regression by two tests. The
consequence is carried into Phase 2B: since a single ordering can move fixed-K=4
by 8 pp, the protocol pre-registers **both** the realized-ordering paired
comparison (primary) and the ordering-averaged one (secondary S5).

## Phase 2A result (2026-08-02) — offline sequential policy replay

`scripts/phase2a_offline_replay.py` replays 32 sequential policies over all
**24 arrival orderings** of every instance's 4 trajectories (50 instances, 200
trajectories, exhaustive — no ordering artifact). Experiment `phase2a`,
analysis-only, **no model calls**. Full write-up:
`reports/phase2_offline_replay.md`.

| policy | reward | mean K | model tokens |
| --- | ---: | ---: | ---: |
| fixed K=1 | 0.485 | 1.00 | 181,603 |
| fixed K=2 plurality | 0.525 | 2.00 | 363,207 |
| fixed K=3 plurality | 0.555 | 3.00 | 544,810 |
| **fixed K=4 plurality** (principal baseline) | **0.577** | 4.00 | 726,414 |
| **mandatory K=2, continue to 4 on disagreement** | **0.577** | **2.70** | **530,726** |
| K=1 selective (nested threshold) | 0.567 | 2.49 | 490,243 |
| failure-only escalation | 0.527 | 1.17 | 222,684 |
| *Oracle@4 — UPPER BOUND, not deployable* | *0.640* | 4.00 | 726,414 |

**Headline: mandatory-K=2 adaptive continuation reproduces fixed-K=4 exactly at
68% of the trajectories.** Paired instance-level bootstrap: reward difference
**0.000 [0.000, 0.000]**, mean-K difference **−1.297 [−1.483, −1.100]**. The
reward CI is degenerate because the two policies return the *same answer on all
50 instances* and on all 10 tasks — 100% of the fixed-K=4 gain retained, 59.1%
of the Oracle@4 headroom captured.

**Negative result, preserved: the K=1 acceptance trigger is weak.** Under nested
(leak-free) threshold selection, **3 of 5 folds chose "never accept after one
trajectory"**, and the policy that does accept early loses 1.0 reward point for
0.21 fewer trajectories. Mandatory K=2 is retained as the honest policy, exactly
as the brief anticipated. Confidence-only escalation is dominated outright
(costs nearly K=4, scores lower).

**Other findings:**

* **Fixed K=2 plurality cannot beat K=1 by voting** — two trajectories either
  agree (returning K=1's answer) or tie (tiebreak returns the first). Its +0.040
  comes entirely from replacing failed trajectories. Ties need a third opinion.
* **Failure recovery is free and attributable.** 12.5% of replays open on a dead
  or unparseable trajectory; every continuing policy resolves 100% of them to a
  real answer and 37.3% to a correct one. Fixed K=1 recovers 0%.
* **A one-sentence abstention rule.** Abstain when four trajectories give four
  different answers: 14% of cases, correct 11.9% of the time. Dropping it lifts
  accuracy 0.577 → **0.651 at 86% coverage**, with no calibration model needed.
* **Calibration fixes probabilities, not ranking.** Grouped-OOF Platt on
  verbalized confidence: ECE 0.430 → 0.047, Brier 0.424 → 0.253, AUROC
  ≈0.75 → 0.70. Isotonic (exploratory) reaches ECE 0.003.
* **Adaptive allocation works.** Mean K spent ranges 2.10 (`gwas_causal_gene_opentargets`)
  to **3.73 (`rare_disease_diagnosis`)** — the controller buys the most
  verification exactly where the agent is weakest, with no access to labels.

**`rare_disease_diagnosis`, analyzed separately** as the documented high-risk
stratum (not absorbed into any aggregate): it gains the most from verification
(0.25 → 0.50, the largest of any task), costs the most (mean K 3.73/4.00),
carries 10 of the pool's 25 failed trajectories, and has the highest
failure-recovery rate (0.150). Still 10 pp below its own Oracle@4 of 0.60.

**Recommendation: carry ONE policy into Phase 2B, not two** —
mandatory K=2 with agreement stopping, a failure override, and abstention when
no two of four agree. It has **no fitted parameter**, is best-or-tied in 99.9%
of bootstrap resamples and on 10 of 10 tasks, and sits on the reward–cost
frontier. The K=1-selective second candidate is **deliberately not recommended**:
the evidence does not support it. `final_confidence == 1.00` (26/27 correct,
n=27, found post hoc) is logged as a pre-registered *secondary hypothesis* for
2B, not a policy arm.

Three bugs were found and fixed while producing this — most importantly, **a
failed trajectory could win a plurality tie against a real answer**, which zeroed
every failure-recovery replay until caught by a test
(`reports/phase2_offline_replay.md` §13).

## Pooled reanalysis result (2026-08-02, final — entry-condition check)

`scripts/pool_and_analyze_phase1_5.py` built a 250-slot spec list identical to
`phase1_runs.jsonl` except that each of the 62 originally-failed slots whose
phase1_5 repair completed (42 of them) has its `run_dir` swapped to the repaired
run — read-only against both `phase1` and `phase1_5` (neither touched), written
to `manifests/phase1_pooled_runs.jsonl`, output to experiment `phase1_pooled`.
Reuses the exact tested pipeline (`build_tables`, every `analysis.*` function)
with no new statistics code — only the input spec list differs from Phase 1's.

**Completion: 188/250 (75.2%) → 230/250 (92.0%).**

| metric | Phase 1 (n=188) | Pooled (n=200 instrumented) |
| --- | --- | --- |
| First-trajectory reward | 0.420 | 0.480 |
| Plurality reward | 0.580 [0.44, 0.70] | 0.620 [0.48, 0.76] |
| Oracle@4 (upper bound) | 0.620 [0.48, 0.74] | 0.640 [0.50, 0.76] |
| **Oracle headroom** | 20.0 pp (34.5% rel.) | **16.0 pp (30.8% rel.)** |
| Plurality − first (paired) | +0.16 [+0.06, +0.26] | **+0.14 [+0.04, +0.26]** — still excludes 0 |
| Agreement-fraction AUROC | 0.874 [0.80, 0.94] | **0.815 [0.71, 0.91]** |
| Plurality-fraction AUROC | 0.812 | 0.769 [0.66, 0.87] |
| Confidence AUROC | 0.789 [0.69, 0.87] | 0.749 [0.66, 0.83] |
| Confidence overconfidence gap | 0.37 | **0.43 (worse)** |
| Confidence Brier / ECE | 0.367 / 0.370 | 0.424 / 0.430 (both worse) |

**Every headline effect survives** — all three go-criteria (oracle headroom,
plurality-vs-first, usable signal AUROC) still clear their thresholds with real
margin, so this **does not** flip the Track A recommendation to Track C. Effect
sizes shrink somewhat, as expected: the 42 rescued trajectories are
disproportionately the *hardest* cases (mean reward 0.357 among them), so
folding them in dilutes the signal toward a more honest baseline.

**One thing got worse, not better: calibration.** Overconfidence gap widened
(0.37→0.43), Brier and ECE both increased. Consistent with the rescued pool
being hard-and-often-wrong: if the model stayed confidently wrong on them,
calibration necessarily degrades. This is a genuine finding, not noise — the
miscalibration problem is *worse* than Phase 1 showed, not better.

Full numbers: `<output_root>/phase1_pooled/results/analysis.json` and
`results/figures/*.png` (same 13-figure set, regenerated on the pooled data).

## Repair re-run result (2026-08-02, final)

All 62 Phase-1 `model_context_overflow`/`missing_run` failures re-run under the
selected Arm 2 repair, on GPUs 0-1 only (GPUs 2-3 held a separate, unrelated job
throughout — never touched). Experiment `phase1_5`,
`manifests/phase1_5_runs.jsonl`, config `configs/phase1_5.yaml`. Each run keeps
its *exact* original task/instance/condition/trajectory_index and prompt — only
the serving config differs — with an explicit
`manifests/phase1_5_runs.original_map.json` (repaired run_id → original phase1
run_id).

**42/62 rescued (67.7%). 20/62 still fail — all via the guard's own circuit
breaker (`budget_terminated_consecutive_runaway`), not open-ended overflow.**
That is a materially different failure mode than Phase 1's: the guard is doing
its job (bounding cost after 3 consecutive degenerate generations) but cannot
force a correct answer out of a trajectory that keeps re-degenerating no matter
how it's nudged.

Rescue rate is **not uniform**:

| task | rescued / attempted |
| --- | --- |
| `crispr_delivery` | 11/11 (100%) |
| `gwas_causal_gene_pharmaprojects` | 6/6 (100%) |
| `gwas_causal_gene_gwas_catalog` | 2/2 (100%) |
| `gwas_variant_prioritization` | 1/1 (100%) |
| `screen_gene_retrieval` | 5/6 (83%) |
| `patient_gene_detection` | 8/11 (73%) |
| `lab_bench_seqqa` | 6/9 (67%) |
| `rare_disease_diagnosis` | **3/13 (23%)** |
| `lab_bench_dbqa` | **0/3 (0%)** |

`rare_disease_diagnosis` — already the worst-failing task in Phase 1 (52%
failure rate) — remains stubbornly resistant: 10 of its 13 failures persist even
with the repair. This is a **residual limitation**, not a repair bug: the
bounding guards contain the damage (no more indefinite 8k-token runaway blobs)
but this task's reasoning pattern pushes the model into repeated degeneration in
a way R1/R2/R4/R5 alone do not fix. `lab_bench_dbqa` is 0/3 but n=3 is too small
to read as a pattern rather than noise.

Mean reward among the 42 rescued: **0.357** (15 correct, 27 wrong) — expected to
be below the Phase-1 baseline (0.42), since this pool is specifically the
*hardest* cases, not a random sample.

**What this changes for the pooled analysis:** the Phase-1 K=4 instrumented pool
can now be reconstituted with 42 additional real trajectories (was 188/250
complete, now 230/250), which changes oracle-headroom, self-consistency and
signal-AUROC denominators. **Not yet re-run** — see Next Actions.

## Ablation verdict (2026-08-01, final)

All 72 trajectories done (arm1 24/24, arm2 24/24, arm3 24/24).
**Recommendation: adopt Arm 2, not Arm 3**, reversing the tentative read from the
6-run live validation below. Full numbers, decision-rule application and the
control-stratum evidence are in `reports/context_overflow_forensics.md` §10.

Headline: Arm 3 (all guards, incl. the 2048-token cap and hard budget) fully
eliminates the target failure (0/6 on `overflow_prone`, reward 0.667 vs
baseline 0.333) but **collapses reward to 0.000 on two control strata**
(`same_family_control`, `short_easy_control`) that were fine at baseline —
pooled control-reward delta **−0.278**. Arm 2 (bounding guards only, no hard
token cap) nearly matches Arm 3 on the target stratum (1/6 vs 0/6 failed) while
the controls **improve slightly** (delta **+0.056**). Per the rule fixed before
any arm ran ("accept the least invasive arm that clears both bars"), Arm 3
fails the control bar and Arm 2 is the correct choice.

Caveat stated plainly: n=6 per stratum, so these means are noisy — a couple of
wrong answers move them a lot. The *direction* (arm3 control regression, arm2
control neutrality-to-improvement) is large enough to act on; the exact deltas
are not to be treated as precise.

A real bug was found and fixed while producing this: `scripts/analyze_ablation.py`
read `reward` from raw per-run `metadata.json`, which never contains it (reward
is only computed by `cli aggregate` against ground truth, into
`results/tables/trajectories.csv`). Every reward cell was silently `nan` and the
decision section was uninterpretable until fixed by joining reward in from the
aggregated table by `run_id`. 274 tests pass; this script has no test coverage
of its own (it's a one-off analysis script, not part of the package) — flagged
as a gap, not fixed, given time constraints.

---

## Phase 1.5 status

**Diagnosis is done and it changes the repair plan.** Context overflow is *not* a
context-budget problem — it is model degeneration above ~32,768 input tokens
(this model's base is trained at 32,768; the serving override lifted the position
ceiling to 65,536 without extending usable context). Past that boundary the model
emits 8,192 tokens of degenerate repetition with no stop tag; the blob is
appended to the conversation, which guarantees the next call repeats it. **62 of
the 69 trajectories that crossed it never returned.**

Decisive numbers (`reports/context_overflow_forensics.md`):

* runaway generations: **100%** of 62 failed runs vs **3.7%** of 188 completed;
* runaway rate per call: **3.1%** below 32,768 input tokens, **94.1%** above;
* **no completed run ever exceeded 32,154 input tokens** — the upper half of the
  served window was used only by already-degenerating trajectories;
* 7/7 runs whose *system prompt alone* exceeded 32,768 degenerated on their first
  call, with zero history — rules out "long trajectories are just hard";
* median post-retrieval system prompt is **2,687 tokens**, not the 17k–41k that
  `DECISIONS.md` D-04 assumed — **prompt trimming has nothing to recover**;
* **50.4%** of measured wall-clock produced no answer.

**Repair, implemented and approved** (`context_overflow_forensics.md` §9;
`src/biomni_uncertainty/budget.py`, 24 tests, off by default so Phase-1 configs
are unchanged): `max_tokens` 8192→2048;
truncate-and-nudge on `finish_reason == "length"` instead of appending the blob;
soft budget at 24,576 / hard at 32,768 input tokens (**0 of 188 completed runs
disturbed**); cap retrieval selection; cap a single model-visible observation at
4,000 tokens with full raw output still on disk; aggregator to trust `FAILED`
when `metadata.json` is absent. **Explicitly rejected: raising the context
ceiling or increasing YaRN scaling** — the evidence says both make it worse.

### Live validation of the repair — 2026-08-01, 6 runs, PASSED

Arm 3 (all guards) run against the live endpoint on the **six worst
overflow-prone instances**, which in Phase 1 failed 22 of their 30 trajectories.
Experiment `abl_arm3`, `<output_root>/abl_arm3/runs/`.

| instance | Phase 1 (unguarded) | Arm 3 (guarded) |
| --- | --- | --- |
| | runs / failed / peak input / runaways | peak input / runaways / answer |
| `crispr_delivery/i0020` | 5 / 4 / 52,603 / 15 | 12,908 / 0 / ok |
| `crispr_delivery/i0028` | 5 / 3 / 56,898 / 23 | 24,253 / 0 / ok |
| `patient_gene_detection/i0161` | 5 / 5 / 56,678 / 17 | 29,420 / 0 / ok |
| `rare_disease_diagnosis/i0021` | 5 / 3 / 54,699 / 10 | 22,518 / 0 / ok |
| `rare_disease_diagnosis/i0099` | 5 / 3 / 57,050 / 10 | 26,841 / 1 / ok |
| `rare_disease_diagnosis/i0103` | 5 / 4 / 50,229 / 12 | 23,288 / 0 / ok |

**6/6 completed with a parseable answer; 0 failures** (Phase 1: 22/30 failed).
Peak input fell from 50k–57k to 12.9k–29.4k, and **87 runaway generations became
1**, which was truncated on the spot. Guards fired 5 runaway truncations, 9
observation truncations, 5 soft-budget nudges, 1 retrieval cap.

**The hard budget never fired.** Every trajectory stayed under 29,420 tokens
without it, meaning the *bounding* guards (R2/R4/R5) did the work on their own.
That is the open question the arm-2-vs-arm-3 comparison exists to settle, and it
now looks like arm 2 may be sufficient — which would be the less invasive repair.

Caveat: this is a **one-armed validation on 6 runs**, not the ablation. It shows
the guards work and do not break the agent; it cannot show they leave
previously-healthy trajectories unchanged. That needs arms 1 and 2.

**Still to run:** the full 3-arm ablation (72 trajectories). Manifest, configs
and run specs are built and frozen; only GPU time is missing.

**Correction to the Phase-1 record:** the 2 "missing runs" are not missing. Both
have full directories and `FAILED` markers reading `model_timeout` — killed on
the dispatcher wall clock after 18 consecutive runaway generations. Correct
accounting: **62 failures, 0 missing**. `crispr_delivery` failure rate is 44%,
not 36%.

---

## Forest Check — 2026-08-10, after the post-Phase-2B review

**1. What scientific uncertainty was resolved?**
Two. First, whether the Phase-2B failure pointed at a fixable rule or at a
fixable *framing*. It is the framing: the 2-of-2 / 2-of-4 distinction cannot act
inside an action set whose only non-terminal move is "resample", and refusing
the weak state is arithmetically worse than accepting it under the mandated
accounting. Second, whether `final_confidence == 1.00` — which passed its
prospective test — should enter a controller. It should not; its value sits
entirely in the state that is already 87.7% accurate.

**2. Did the main research claim change?**
Narrowed again, and honestly. "Cheap intrinsic signals can guide verification
effort" now holds only in the weak form *"continuing after a trajectory dies
pays for itself; continuing after a disagreement does not."* The stronger claim
— that consensus structure can allocate compute profitably — has now failed
prospectively once and offline once, on independent pools.

**3. Is the next task necessary for the central contribution?**
Yes, and it is deliberately the cheap one. The north star asks whether an agent
can recognise unreliable conclusions; the measurement in §7 of the offline
assessment says the recoverable errors are **minority-held**, which no
recognition-and-voting scheme reaches. Testing whether disagreement is
substantive (different plans/tools) or cosmetic (noisy final answers) is the
precondition for Track C being a real research direction rather than a slogan.

**4. Are we overfitting to implementation details or the original pilot?**
This was the live risk and the discipline held: the adjudication bar was written
before the analysis ran, the leading candidate was rejected despite a positive
point estimate, and the cross-pool check (`phase1_pooled` vs `phase2b`) is what
exposed the effect as two instances. The recurring trap — reading a narrow
offline CI as a strong result — was named explicitly and is now on record twice.

**5. What is the simplest decisive next experiment?**
CPU-only trace analysis of the 51 split `phase2b` instances plus the Phase-1/1.5
traces: do disagreeing trajectories differ in plan and tool path, or only in the
final answer? Zero GPU hours, and it determines whether Track C has a mechanism
to build on.

---

## Forest Check — 2026-08-02, after the Phase-2A offline replay

**1. What scientific uncertainty was resolved?**
Two. First, whether a sequential controller can reach fixed-K=4 reliability at
roughly K=2 compute — the north star's stated target result. It can: 0.577 at
mean K 2.70, the same answers on all 50 instances. Second, whether the K=1
escalation trigger — named in `phase2_entry_assessment.md` §4 as "genuinely
open" — is solvable with the signals available. On this data it is not, and
three of five folds say so unprompted.

**2. Did the main research claim change?**
Sharpened, not changed. The claim is now specifically that **mandatory
verification plus agreement-based early stopping** is where the value is, and
that single-trajectory uncertainty is not. That is a narrower and more defensible
claim than "uncertainty signals guide allocation", and it is the one the data
supports. Two Phase-1 framings weaken further: verbalized confidence survives
only as a rank (calibration is a repair, not an improvement), and every
effort/length signal is unusable once failures are excluded.

**3. Is the next task necessary for the central contribution?**
Yes. Everything above is offline replay against trajectories that already exist;
no policy influenced generation. The contribution claimed in the north star is a
*prospective, cost-aware reliability controller*, and only Phase 2B tests that.

**4. Are we overfitting to implementation details or the original pilot?**
This was the live risk and the mitigation held: the recommended policy has **no
fitted parameter at all**. Everything that *was* fitted — calibration, the K=1
threshold — was evaluated with nested grouped cross-validation and then
**recommended against**, because the honest procedure declined to accept. The
one tempting artifact (confidence==1.00, 26/27 correct) was found post hoc and is
explicitly demoted to a pre-registered secondary hypothesis rather than promoted
into the policy.

**5. What is the simplest decisive next experiment?**
The frozen prospective run on ~100 held-out instances with one policy and hidden
shadow trajectories through K=4. One policy, not two: adding the K=1-selective
arm would spend prospective power on a component already shown to be weak.

---

## Forest Check — 2026-08-01, after the context-overflow forensics

**1. What scientific uncertainty was resolved?**
Whether the 24% data loss was an agent property or a configuration artifact. It
is substantially the latter: the failure begins above the model's trained context,
is reproducible from a bloated system prompt alone with no agent history, and
never occurs in the region where completed trajectories live. This also killed
the expensive repair options (bigger context, prompt rewriting) before any GPU
time was spent on them.

**2. Did the main research claim change?**
No. Oracle headroom, the plurality gain and the agreement AUROC all reproduce
exactly, and the oracle headroom can only grow after repair. One *framing* claim
is retracted: the Phase-1 report's "not a configuration mistake" (§5) is wrong.
Two claims are now flagged as bias-exposed and must be re-measured on repaired
data — `agreement_fraction` AUROC 0.874 (computed over surviving trajectories
only) and the inverted length signals (partly a restatement of the failure being
repaired).

**3. Is the next task necessary for the central contribution?**
Yes. The controller must act after trajectory 1, and every K=1 signal Phase 1
measured is either missing 42% of the time (confidence) or confounded with the
failure being repaired (length, wall time). The controller cannot be designed
against these numbers as they stand.

**4. Are we overfitting to implementation details or the original pilot?**
Live risk. The mitigation is the stopping rule: the repair is capped at the six
changes in §9, none of which touches the task prompt, the confidence instruction,
temperature, or the retriever's ranking. Prompt trimming was on the brief's
priority list and is **not being done**, because the measurement said there was
nothing there. If the repair grows beyond an inference-serving fix, the north
star has been lost.

**5. What is the simplest decisive next experiment?**
The 72-trajectory ablation. It tests the mechanism directly on the cases that
failed, keeps matched controls that previously succeeded, and costs under two
node-hours. Everything larger waits on its result.

---

## Headline result

**GO.** Oracle headroom 20.0 pp (relative error reduction 34.5%). Plurality
beats first-trajectory by +0.16 with a 95% CI `[+0.06, +0.26]` that excludes
zero. Agreement-fraction is the strongest uncertainty signal measured (AUROC
0.874), stronger than verbalized confidence (0.789), which is itself
discriminative but severely miscalibrated (mean stated 0.96 vs actual accuracy
0.59). Full detail: `reports/phase1_report.md`.

The largest data-quality issue is a **24% context-overflow rate** — the
top engineering priority before Phase 2.

---

## Completed

### Phase 0 (steps 1–10) — see prior entries below, all done.

### Phase 1 pilot — run to completion

* Launched 2026-07-31 19:25 CDT, detached (`setsid`, PPID 1). Relaunched
  19:33 at dispatcher concurrency 8 (measured throughput at concurrency 4
  would not finish inside the allocation; 8 gave 379 tok/s vs 190, KV usage
  well under capacity).
* **Finished 2026-08-01 05:38 CDT.** 248/250 runs present, 188/250 (75.2%)
  completed. All 250 runs accounted for (2 truly missing run directories).
* Full pipeline ran automatically: dispatch → aggregate → analyze → 13
  figures + tables, via `scripts/run_detached.sh`.
* **Correction:** "2 truly missing run directories" above is wrong — see the
  Phase-1.5 correction and `reports/phase1_report.md` errata E1.

### Post-pilot bug fixes (found by reading real pilot data, not the smoke test)

1. **Canonicalization gap** — Biomni states gene-symbol answers symbol-first
   ("**PDGFRB** is identified as the most likely causal gene...") far more
   often than label-first ("answer: PDGFRB"); the old parser only matched
   label-first and marked 32 trajectories `ambiguous` (all in the three
   `gwas_causal_gene_*` tasks, 44–52% of those tasks). Fixed with a new
   symbol-first-conclusion regex; **reparsed every stored raw response with
   `scripts/reparse_pilot.py`** (no model calls — data was already on disk):
   31/32 resolved cleanly. This meaningfully moved every headline number
   (first 0.36→0.42, plurality 0.50→0.58, headroom 24pp→20pp). The report
   reflects the **corrected** numbers; the fix and its effect are documented
   in `reports/phase1_report.md` §3 for full transparency.
2. **Context-overflow misclassification** — a second 400-error phrasing
   ("the input (N tokens) is longer than the model's context length") wasn't
   recognised by the classifier; 2 runs were mislabelled `unknown_failure`.
   Fixed and relabelled from the already-recorded error text.
3. **Confidence parse-rate denominator** — the missingness plot divided by
   all planned runs instead of runs that actually requested confidence,
   understating the rate (found on smoke data, fixed before the pilot ran).
4. **`system_prompt.txt` truncation** — the audit copy was cut to 20k of
   ~190k chars by the event-log redactor, hiding the confidence instruction
   from the record (verified functional behavior was unaffected; fixed for
   auditability, mid-pilot).
5. **Resumption append bug** — `events.jsonl` is append-only, so a resumed
   run would have interleaved two attempts. Fixed by archiving a prior
   attempt to `attempt<N>/` before re-running (this mattered in practice: the
   concurrency-4→8 relaunch exercised this path for real).

All five are regression-tested. Full list of earlier (pre-pilot) fixes is
preserved below.

### Reports

* `reports/phase0_environment.md` — complete.
* `reports/phase1_protocol.md` — frozen before the pilot; deviations logged
  (concurrency change, one-replica layout, failure-class addition) rather than
  edited away.
* `reports/phase1_report.md` — **complete, all real numbers**, no
  placeholders remain. Go/No-Go: **GO**.
* `reports/phase2_plan.md` — decision rule; this pilot's outcome selects
  **Track A (adaptive controller)**, with context-overflow fix and
  confidence recalibration flagged as prerequisites.

---

## Current blockers

**No analysis blockers.** Phase 2B is complete and its follow-up decision is
closed (D-28: Track C, no Controller v2). The project is waiting on **operator
approval** to begin Track C, which is a gate, not a blocker.

**Two blockers on any future prospective run**, both found in the 2026-08-10
review and neither yet closed:

1. **Uncommitted code.** The Phase-2B controller and drivers are untracked; runs
   record `project_git.dirty = true`. Commit before the next prospective run so
   the code that produces a pre-registered result is recoverable from history.
2. **Residual trajectory failure rate 15.5%**, above the 15% halt threshold
   (12.0% excluding `rare_disease_diagnosis`). This is the halt condition the
   D-27 gate bug hid, and it is entangled with controller behaviour: 15 of
   Controller v1's 29 abstentions had ≤1 usable trajectory.

---

## Tests run

| check | result |
| --- | --- |
| `pytest -q` | **409 passed** (382 + 8 phase2b_provenance_audit + 19 diversity) |
| `ruff check src tests scripts` | clean |
| `ruff format --check src tests scripts` | clean except one pre-existing drift in the untouched `tests/test_resumption.py` (a ruff-version line-wrap difference; left alone rather than reformatting a frozen test file) |
| Import check inside the Biomni environment | OK |
| Manifest dry run | OK — 50 instances, 5 per task, stable hash |
| **Phase-2B manifest build** | OK — 150 held-out instances, overlap with Phase 1 **= 0** (asserted), hash `7cb5da3a…`, dataset fingerprint identical to Phase 1 |
| **Phase-2A/Phase-1 reconciliation** | **RESOLVED** — native-ordering replay reproduces Phase-1's 0.6200 bit-exactly; gap is 4 tied instances, not a bug (`scripts/phase2a_reconcile.py`) |
| Mock end-to-end | 20 passed, 13 figures |
| GPU smoke test | passed — 6 runs, aggregation, analysis, 13 figures |
| **GPU pilot (250 runs)** | **complete** — 188/250 completed, full analysis, report written |
| **Repair live validation (6 runs, arm 3)** | **passed** — 6/6 completed where Phase 1 failed 22/30; 87 runaways → 1 |
| **Repair ablation (72 runs, 3 arms)** | **complete** — see `reports/context_overflow_forensics.md` §10. Decision: Arm 2. |
| **Repair re-run, all 62 Phase-1 failures (arm 2)** | **complete** — 42/62 rescued (67.7%); 20/62 hit the `max_consecutive_runaway` circuit breaker, concentrated in `rare_disease_diagnosis` (10/13 still fail). |
| **Pooled reanalysis (230/250, entry-condition check)** | **complete** — oracle headroom 16.0pp, plurality-first +0.14 [0.04,0.26], agreement AUROC 0.815. All go-criteria hold; calibration measurably worse (0.37→0.43 overconfidence gap). |
| **Phase-2A offline replay (32 policies x 50 instances x 24 orderings)** | **complete, CPU only** — mandatory K=2 matches fixed K=4 (0.577) at mean K 2.70; K=1 trigger weak (3/5 folds refuse); abstention rule found. One policy recommended for 2B. |
| **Phase-2B smoke (6 instances, `phase2b_smoke`)** | **completed** 2026-08-02; 6/6 terminated, 0 errors, chain intact. Gate script bug (D-27) means its reported "0 fatal failures" was wrong — true residual failure rate was 37.5%, above threshold. |
| **Phase-2B full prospective run (150 instances, 600 trajectories)** | **completed** 2026-08-10, 8.5 h, 0 errors, all 150 decision chains verify, 0/150 online-vs-recomputed integrity mismatches. **H1 FAIL, H2 FAIL** — see `reports/phase2_report.md`. |

All bugs found and fixed (pre-pilot + post-pilot + post-ablation) are listed
with detail in `reports/phase0_environment.md` §8, `reports/phase1_report.md`
§3, and `reports/context_overflow_forensics.md` §10e (the `analyze_ablation.py`
reward-join bug).

---

## Active experiment IDs

| id | config | state |
| --- | --- | --- |
| `smoke` | `configs/smoke.yaml` | complete, not pooled with pilot results |
| `phase1` | `configs/phase1.yaml` | **COMPLETE and frozen.** Results at `<output_root>/phase1/results/`. Report: `reports/phase1_report.md` (+ errata). Never re-run. |
| `abl_arm1` | `configs/ablation_arm1.yaml` | ablation control (Phase-1 behaviour). **24/24 complete**, 19 ok / 5 failed |
| `abl_arm2` | `configs/ablation_arm2.yaml` | bounding only, no input budget. **24/24 complete**, 22 ok / 2 failed — **selected repair** |
| `abl_arm3` | `configs/ablation_arm3.yaml` | bounding + soft/hard budgets. **24/24 complete**, 23 ok / 1 failed — rejected, harms control reward |
| `phase1_5` | `configs/phase1_5.yaml` | repair re-run of all 62 Phase-1 failures under Arm 2. **62/62 attempted, 42 ok / 20 failed.** Map to originals: `manifests/phase1_5_runs.original_map.json`. |
| `phase1_pooled` | — (analysis-only, no config of its own) | pooled Phase-1 + phase1_5 spec list, **230/250 complete (92.0%)**. Not a run experiment — `manifests/phase1_pooled_runs.jsonl` + `scripts/pool_and_analyze_phase1_5.py`. Entry-condition check: **PASS**, all go-criteria hold. |
| `phase2a` | — (analysis-only, no config of its own) | offline sequential policy replay on `phase1_pooled`. **No model calls, no GPU.** 32 policies x 50 instances x 24 orderings. `scripts/phase2a_offline_replay.py`; results at `<output_root>/phase2a/results/`. Report: `reports/phase2_offline_replay.md`. |
| `phase2b` | `configs/phase2b.yaml` | **COMPLETE.** Prospective controller evaluation, 150 held-out instances (`manifests/phase2b.jsonl`, hash `7cb5da3a…`), 600 trajectories, run 2026-08-09→10. **Both co-primary hypotheses FAIL** — `reports/phase2_report.md`. Analysis: `scripts/phase2b_analyze.py`, results at `<output_root>/phase2b/results/`. |
| `phase2b_smoke` | `configs/phase2b_smoke.yaml` | **Complete**, 2026-08-02, 6 instances on reserved pool (+1 reused Phase-1 instance for `rare_disease_diagnosis`, DEV-1 — never pooled into analysis). |
| `track_c_diversity` | — (analysis-only, no config of its own) | **Complete**, 2026-08-10. Structural diversity of the 600 Phase-2B traces at four levels (answer / plan / tool path / evidence), plus a different-question control. **CPU only, ~4 min, no GPU, no model calls, no generation change.** `scripts/track_c_diversity.py`; results at `<output_root>/track_c/results/`. Report: `reports/track_c_diversity_diagnostic.md`. **Verdict: Outcome B — NO-GO for diversity-by-resampling.** |
| `controller_v2_offline` | — (analysis-only, no config of its own) | **Complete**, 2026-08-10. 18 parameter-free policies replayed over `phase2b` (realized order + all 24 orderings) and `phase1_pooled` (all 24). **CPU only, ~40 s, no model calls, no GPU, no held-out instance consumed.** `scripts/controller_v2_offline.py`; results at `<output_root>/controller_v2_offline/results/` (12 tables). Report: `reports/controller_v2_offline_assessment.md`. **Verdict: Recommendation B, no Controller v2.** |

---

## Known failures (final)

* `model_context_overflow`: 60/250 (24.0%) — dominant failure mode, concentrated
  in `rare_disease_diagnosis` (52%), `patient_gene_detection` (44%),
  `crispr_delivery`/`lab_bench_seqqa` (36% each); zero in two GWAS tasks.
  Flagged as the top Phase-2 engineering priority.
* `confidence_parse_failure`: 17 — model answered but confidence block was
  missing/malformed.
* `agent_parse_failure`: 8 (6 genuinely ambiguous, 2 unparseable) — down from
  40 before the canonicalization fix.
* ~~`missing_run`: 2~~ — **corrected 2026-08-01.** Both runs have full
  directories and `FAILED` markers reading `model_timeout`; they were killed on
  the dispatcher wall clock after 18 consecutive runaway generations. Same
  pathology as the 60 above. Correct total: **62 failures, 0 missing**
  (`reports/context_overflow_forensics.md` §7; aggregator fix R6).

---

## Next actions

**All write-up items complete.** Ablation (Arm 2 selected) → repair re-run
(42/62 rescued) → pooled reanalysis → formal E1–E6 adjudication → both reports
written. What remains is decisions, not artifacts:

1. ~~Pool the 42 rescued trajectories into the Phase-1 K=4 set.~~ **Done.**
2. ~~Write `reports/phase1_completion_bias_analysis.md` and
   `reports/phase1_repaired_report.md`.~~ **Done**, 2026-08-02. The former
   formalizes observed-completion vs. intention-to-evaluate vs. matched-paired;
   the latter mirrors `phase1_report.md`'s structure with pooled numbers as
   primary and includes the calibration-got-worse and length-signal-was-
   partly-circular findings in full.
3. ~~Adjudicate entry conditions E1–E6.~~ **Done formally** —
   `reports/phase2_entry_assessment.md` §8. **5 of 6 met; E1 (residual failure
   <5%) measured at 8.0–8.3%, not met as literally stated** but does not block
   Track A since E4 (the condition that would flip the recommendation) passed
   cleanly. Recorded honestly rather than rounded to a pass.
4. ~~Open decision on `rare_disease_diagnosis`'s residual failure rate.~~
   **Decided 2026-08-02 (option (a), by direction):** treat it as a documented,
   task-scoped high-risk stress-test stratum, analyze it separately, and do not
   let it imply uniform performance across tasks. Do **not** spend more effort
   trying to fully solve it before Track A. Phase 2A honours this —
   `reports/phase2_offline_replay.md` §10 reports it as its own section.
5. ~~Offline policy replay on the pooled K=4 pool.~~ **Done**, 2026-08-02 —
   experiment `phase2a`, `reports/phase2_offline_replay.md`.

6. ~~Reconcile Phase-2A's 0.577 against Phase-1's 0.620.~~ **Done** — resolved,
   not a bug; see the reconciliation section above and
   `reports/phase2_offline_replay.md` §1.1.
7. ~~Commit the Phase-2A milestone.~~ **Done**, `fd91d26`. No Phase-1 or
   Phase-1.5 artifact modified; the frozen `phase1` manifest hash re-verifies.
8. ~~Select held-out instances, freeze and hash the manifest, write
   `reports/phase2_protocol.md` before any prospective outcome exists.~~
   **Done**, 2026-08-02 — 150 instances, hash `7cb5da3a…`, protocol frozen.

9. ~~Write the Phase-2B implementation~~ **Done** — `scripts/phase2b_run.py`
   (online controller driver, hash-chained decision log),
   `configs/phase2b_smoke.yaml`, `scripts/phase2b_verify.py` (gate checks;
   had a bug, see below), `scripts/run_phase2b.sh`,
   `scripts/phase2b_supervise.sh`. 25 controller tests.
10. ~~Run the smoke test~~ **Done**, 2026-08-02. Gate script reported clean;
    was actually wrong (D-27) — true residual failure rate 37.5%, should have
    blocked the next step.
11. ~~Launch the full prospective run~~ **Done**, 2026-08-09→10, 150 instances,
    600 trajectories, 8.5 h, 0 errors.
12. ~~Analysis and `reports/phase2_report.md`~~ **Done**, 2026-08-10.
    **Both co-primary hypotheses FAIL.** No policy tuning occurred after
    outcomes were seen — the frozen controller is reported exactly as it ran.

### VERIFY prerequisites — in progress (2026-08-10, operator-approved)

**Nothing is running. No GPU job, no new manifest, no prompt change, no
diversity mechanism, no VERIFY implementation.** `reports/verify_prerequisites.md`
(D-31) lists five scientific prerequisites for a constructed-verification pilot
to be valid. Working through them in dependency order:

| # | item | status |
| --- | --- | --- |
| **5** | freeze the RESAMPLE-vs-VERIFY definition | **DONE 2026-08-10 — D-32, `reports/verify_definition.md`** (done first, out of numeric order: its audit criteria set item 2's requirements) |
| **1** | repair the literature/evidence channel | **DONE 2026-08-10 — D-33, `reports/evidence_channel_repair.md`** |
| **2** | instrument retrieval identity/content | **DONE 2026-08-10 — D-33** (addressed together with item 1) |
| **3** | re-measure residual failure on the repaired environment | **DONE 2026-08-10 — D-34, `reports/residual_failure_remeasurement.md`. NOT MET: 28.1% [15.6%, 45.4%], not improved** |
| **4** | validate against healthy controls | **DONE 2026-08-10 — D-35, `reports/verify_prerequisite_control_validation.md`. PASS — no material regression; item 3 remains FAILED regardless** |

**Item 5, closed.** VERIFY is a distinct trajectory type + controller action,
gated by five conditions (starts from a specific candidate claim; tests the
claim rather than re-solving the task; differs from the candidate's method **by
construction**, not by temperature; never sees ground truth; cannot copy the
original's reasoning — enforced structurally by a new `VerifyView`/
`FORBIDDEN_VERIFY_FIELDS` barrier *and* by a post-hoc audit). Three modes kept
deliberately minimal: A (computational re-derivation), B (evidence, gated on
item 1's repair), C (adversarial, B's query strategy inverted). The audit is a
**rejection test against D-30's own measured RESAMPLE band** (plan Jaccard
0.540 [0.515, 0.566], tool-seq similarity 0.409 [0.358, 0.463], query Jaccard
0.328 [0.287, 0.372]) — not an arbitrary threshold, per instruction. The
strongest audit (evidence-identity overlap) is left uncalibrated on purpose,
pending item 2's data. `VerifyView`'s forbidden list is **stricter** than
`TrajectoryView`'s: it also excludes the original's stated confidence, to
prevent anchoring a VERIFY verdict on it — relevant because S4 is a live
candidate signal.

**Items 1+2, closed.** Two tools genuinely repaired by installing missing pure
Python packages: `query_pubmed` (68.9% error → **0/8, 100% success** on real
Phase-2B queries after `pip install pymed`) and `query_arxiv` (→ **0/8, 100%**
after `pip install arxiv`). Three excluded on direct evidence: `query_scholar`
(installing `scholarly` does not fix it — a version mismatch with its own
`free_proxy` dependency makes it fail deterministically, 8/8, and the
underlying free-proxy-scraping mechanism is inherently fragile regardless);
`advanced_web_search_claude` (never tested — requires a proprietary Anthropic
API key, rejected per the standing rule against that dependency and the
confound it would introduce); and **`search_google`, a new finding** — D-30
read it as healthy (3.4% error) but direct testing found **0/8 (0%) succeed,
zero exceptions raised**, because the scraper returns empty silently and the
old failure classification only catches exceptions. **VERIFY's evidence route
is therefore `query_pubmed` + `query_arxiv` + the 8 already-healthy structured
databases — no general web-search tool is currently reliable.**

Retrieval provenance instrumented in the same pass: `retrieval_end` now logs
`selected_identities` (actual resource names) alongside counts;
`code_execution_end`/`tool_call_end` now carry a content hash of tool output
(block-level, not call-level — Biomni's execution model doesn't allow finer
attribution, stated not hidden). `diversity.py` exposes
`retrieval_identity_jaccard`/`evidence_output_jaccard`, kept **outside**
`SIMILARITY_COMPONENTS` so D-30's `workflow_distance` is not silently
redefined. **14 new regression tests** (423 total, up from 409) prove the
fields are populated. No frozen artifact touched; environment change only
(3 packages installed) plus source instrumentation.

## Item 3, closed (2026-08-10, D-34) — residual failure re-measured: NOT improved

**First live-GPU step of this engagement**, launched only after explicit
approval given the real cost involved. Job `3388121` (the same job that
served Phase 2B) was still live, so no new allocation was requested. 8 fresh
instances (zero overlap with any prior manifest; `crispr_delivery` and
`rare_disease_diagnosis` excluded — their pools are exhausted by D-22), config
byte-identical to `configs/phase2b.yaml`, 32 real trajectories, ~62 min wall
clock. **Throwaway: no file written to `manifests/` or `configs/`, no
experiment ID registered.**

**Result: `9/32 = 28.1%`, 95% Wilson CI **[15.6%, 45.4%]** — the point
estimate is *above* the historical 15.5%, and the CI's lower bound sits at the
threshold itself. Prerequisite 3 is **NOT met.** Task-matched against Phase
2B's own rates on these same four tasks, every CI overlaps — nothing here is
statistically distinguishable from before at this sample size, in either
direction.

**Mechanism, confirmed identical to Phase 1.5's diagnosis and confirmed
unrelated to D-33's repair.** Every failure carries
`terminated_reason: "consecutive_runaway"` with `peak_input_tokens` at
32,936–40,637 — the model's ~32,768-token trained-context boundary, exactly
the known degeneration mechanism. Only 5/9 failed trajectories even called
`query_pubmed`, none called `query_arxiv`; the single worst instance
(`patient_gene_detection/i0273`, 4/4 trajectories failed, 44% of this
sample's failures) failed identically whether or not it used the repaired
tools — ruling out the evidence-channel repair as a cause. Excluding that one
instance: 5/28 = 17.9% [7.9%, 35.6%] — closer to, still not comfortably under,
threshold.

**No broad Arm-1/2/3-style search proposed**, per instruction — the evidence
confirms an already-diagnosed mechanism rather than pointing at anything new.
**Smallest targeted intervention proposed, not implemented:** screen candidate
instances with one cheap trajectory before committing K=4 in a future
protocol, excluding ones that hit `consecutive_runaway` — a selection-layer
mitigation, since Phase 1.5 already tried and rejected the serving-layer fix
(raising the context ceiling made things worse).

**The gate exercise succeeded cleanly on live, first-time-seen data**: exit
code 1, `VERDICT: BLOCKED`, correctly triggered by the residual-failure gate;
every other gate (chain integrity, shadow isolation, leakage, failure
override, cost accounting) passed — D-32/D-33's changes broke nothing
upstream.

**Consequence: do not launch a real prospective run assuming this number has
improved.** It has not, on the evidence available.

## Item 4, closed (2026-08-10, D-35) — healthy-control validation: PASS

**Second live-GPU step**, approved separately. Same live allocation (job
3388121), no new SLURM request. 6 previously-healthy Phase-2B instances
re-run under the D-33-repaired environment via `scripts/phase2b_run.py` (same
controller-driven flow as item 3, so the same gate applies unmodified),
matching task prompt / trajectory index / `requested_seed` to the historical
baseline. Acceptance rule frozen in a separate file before the first
trajectory. 24 trajectories, ~54 min wall clock, 0 chain failures.

**PASS**, on the pre-declared primary comparison (trajectory index 0, n=6):
mean reward **0.500 → 0.667 (+16.7pp, an improvement)**, completion and
usable-answer **100% → 100%, unchanged**, no new failure. Every quantitative
bar clears with margin on the comparison the rule names primary.

**Supplementary (all 4 indices, n=24):** reward −4.2pp, completion −4.2pp,
usable-answer −8.3pp — all inside the ±10pp bars. One new failure
(`gwas_causal_gene_gwas_catalog/418`, index 2) confirmed the *identical*
mechanism D-34 already characterized (`peak_input_tokens=36,968`,
`consecutive_runaway`), affecting 1 of 6 controls, not "multiple" — combined
with `seed_supported: False` (confirmed both before and now), the defensible
reading is stochastic variation on an already-known mechanism. **Cost is the
exact "1–2 instances dominate" case the rule anticipated**: aggregate tokens
rose 1.36×, but one zero-tool-call trajectory accounts for ~59% of the entire
increase — unexplainable by the repair or the instrumentation, reported
explicitly rather than smoothed over.

**Evidence-channel confirmed live for the first time.** Every `query_pubmed`
error in this run was a model behavioral error (wrong import path, one syntax
mistake) — not `No module named 'pymed'`; that failure mode is gone. Every
other call succeeded. **Retrieval-provenance instrumentation: 15/15
trajectories with any tool call had both new fields populated — 100%
coverage, zero gaps.**

**Gate exercised on both paths, live, for the first time**: BLOCKED
re-confirmed on item 3's data (28.1%, exit 1) immediately before launch; this
run's own gate returned **`VERDICT: ALL GATES PASS`, exit code 0** (1/24 =
4.2%).

**What PASS does not mean, stated without hedging: item 3 remains FAILED.**
D-34's 28.1% was measured on fresh, unscreened, high-base-rate instances;
this validation was deliberately drawn from previously-healthy ones and says
nothing about the population-wide rate. **A prospective VERIFY experiment
remains blocked on item 3 alone**, regardless of item 4's result. No attempt
to repair item 3 was made here.

### Closed 2026-08-10 (D-30): Track C's first diagnostic — NO-GO for diversity

See the Track-C section above. Outcome B: trajectories that disagree have the
same plans as trajectories that agree, and workflow independence does not
predict error correction.

### Closed 2026-08-10 (D-28): Track C, no Controller v2

~~Whether to pursue the §11 redesign as a new prospective run, or take Track C
as literally selected, is the open decision.~~ **Resolved.** The redesign was
adjudicated offline against a bar written down first
(`reports/post_phase2b_assessment.md` §5) and **rejected**
(`reports/controller_v2_offline_assessment.md`, Recommendation B; D-28). Track C
stands as pre-registered. No Controller-v2 was built, no manifest created, no
GPU job launched.

**Awaiting operator approval before any Track-C work begins.** When it does, the
first step is deliberately **CPU-only, not GPU**: on the 51 `phase2b` instances
with 2–3 distinct answers (plus Phase-1/1.5 traces, all preserved), measure
whether disagreement reflects genuinely different plans and tool paths or merely
noisy final answers. If it is noise, independent verification has nothing to
work on and Track C itself needs reframing — and that costs zero GPU hours to
find out. Only after that should any diversity mechanism be built.

Before any *prospective* run of any kind: commit the Phase-2B code (runs record
`project_git.dirty = true`), and bring the residual trajectory failure rate
under the 15% halt threshold (currently 15.5%).

Deferred, not started: expanding the pilot for tighter CIs; transfer to a second
agent; expert workflow annotation; Phase 2C controlled-failure study (does not
proceed on this controller as frozen — see `reports/phase2_report.md` §11);
adding test coverage for `scripts/analyze_ablation.py` and
`scripts/pool_and_analyze_phase1_5.py` (one-off analysis scripts outside `src/`,
flagged as a gap, not closed here). `scripts/phase2a_offline_replay.py` and
`scripts/phase2b_analyze.py` are also outside `src/`, but the logic they drive
lives in `src/biomni_uncertainty/{policy,calibration,controller}.py` and **is**
covered (67 tests across policy/calibration/controller + 13 for
phase2b_analyze's own arithmetic).

---

## Documents added in Phase 1.5

| document | contents |
| --- | --- |
| `reports/context_overflow_forensics.md` | full diagnosis, counterfactuals, proposed repair R1–R6, ablation design, §10 ablation result |
| `reports/phase2_entry_assessment.md` | independent verification of every headline number; completion-bias exposure per claim; entry conditions E1–E6 (§6) and their post-repair adjudication (§8) |
| `reports/phase1_completion_bias_analysis.md` | the completion-bias phenomenon on its own terms: observed-completion vs intention-to-evaluate vs matched-paired, quantified |
| `reports/phase1_repaired_report.md` | pooled (230/250) headline numbers, mirrors `phase1_report.md`'s structure, does not replace it |
| `reports/research_north_star.md` | the central question, the target result, the five questions, standing constraints |
| `scripts/context_forensics.py` | reproduces the forensics from stored traces; no model calls, no GPU |
| `reports/forensics/*` | per-run and per-call token ledgers |

## Documents and code added in Phase 2A

| item | contents |
| --- | --- |
| `reports/phase2_offline_replay.md` | the Phase-2A report: method, re-measured K=1 signals, calibration, the K=1 negative result, policy comparison, failure recovery, abstention, task stratification, stability, limitations, bugs, recommendation |
| `src/biomni_uncertainty/policy.py` | sequential policy replay: `TrajectoryView` (the leakage barrier), `InstancePool` (rewards held apart), task-aware resolution and agreement, the policy set, exhaustive-ordering replay |
| `src/biomni_uncertainty/calibration.py` | grouped out-of-fold Platt / isotonic / small-logistic calibration, instance-normalized weights, Brier/ECE/reliability, `within_fold_auroc` |
| `scripts/phase2a_offline_replay.py` | the driver; CPU only, ~1 min, no model calls |
| `tests/test_policy.py`, `tests/test_calibration.py` | 55 tests: replay, ordering, calibration grouping, cost accounting, abstention accounting, failure overrides, leakage prevention |
