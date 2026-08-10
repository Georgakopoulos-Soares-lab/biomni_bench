# Design decisions

Each entry records what was decided, what was considered instead, and why.
Decisions made *after* seeing results are marked as such; none of the entries
below were.

---

## D-01 Wrapper repository, no upstream edits

**Decision.** Biomni is used as a pinned dependency (`pip install -e` from a
clone at a recorded commit). Every behavioural change is an *adapter*: a
LangChain callback, an instance-level method wrap, or a module-attribute patch
inside the already-imported `biomni.agent.a1` namespace. `patches/` is empty.

**Alternatives.** (a) Fork Biomni and edit `a1.py` directly. (b) Subclass `A1`
and override `configure()`.

**Why.** (a) makes the experiment un-reproducible against upstream and invites
drift. (b) would require duplicating ~350 lines of `configure()` — the graph
nodes are closures defined inside it — which is exactly the kind of copy that
silently diverges. The three things we need to observe (LLM calls, code
execution, retrieval) each have a single clean interception point, so adapters
suffice.

**Interception points, verified against commit `400c1f3`:**

| signal | mechanism |
| --- | --- |
| LLM requests, tokens, finish reason | `BaseCallbackHandler` on `agent.llm.callbacks` |
| Code execution (python/R/bash) | patch `biomni.agent.a1.run_with_timeout` — the single choke point of the graph's `execute` node |
| Biomni tool calls | `biomni.utils.parse_tool_calls_with_modules` over each `<execute>` block |
| Tool retrieval | wrap `agent.retriever.prompt_based_retrieval` |

---

## D-02 The benchmark has no held-out split

**Decision.** Sample from `split == "val"`, and record that no held-out split
exists.

**Finding.** The `biomni/Eval1` parquet has 433 rows across 10 tasks and
**every row has `split == "val"`**. `BiomniEval1.get_task_stats` counts a
`train` split that contains zero rows in this release.

**Consequence.** There is no train/test separation to preserve, so the
"prefer a held-out split" rule is vacuous here. The manifest report records
`held_out_split_available: false` so this cannot be misread later.

---

## D-03 Serve the model in bfloat16, explicitly

**Decision.** Always pass `--dtype bfloat16` to SGLang.

**Finding.** `biomni/Biomni-R0-32B-Preview` ships its weights in **FP32**:
`model.safetensors.index.json` reports `total_size = 131,048,493,056` bytes
(131 GB) across 27 shards, and the shard headers are `F32`. `config.json` says
`"torch_dtype": "float32"`.

**Why it matters.** The command on the model card and in Biomni's README omits
`--dtype`, so SGLang follows `config.json` and tries to allocate ~131 GB of
weights (~65 GB per GPU at TP2) before any KV cache. `--dtype bfloat16` halves
that to 65.5 GB total (32.8 GB per GPU at TP2), which is the intended serving
precision for a model whose base is Qwen3-32B.

**Not done.** No weight quantization. Phase 1 uses full official weights so that
calibration, trajectory diversity and tool-use behaviour are not confounded.

---

## D-04 Context length: 65536, with the model card's YaRN override at factor 1.0

**Decision.** Serve with `--context-length 65536` and the model card's
`--json-model-override-args '{"rope_scaling":{"rope_type":"yarn","factor":1.0,
"original_max_position_embeddings":32768}, "max_position_embeddings": 131072}'`.

**Measurement that forced this** (tokenized with the model's own tokenizer):

| prompt | tokens |
| --- | --- |
| Biomni system prompt, pre-retrieval (all 224 tools, 76 data-lake items, all know-how) | **43,891** |
| Retrieval prompt sent on LLM call #1 | 12,460 |
| Post-retrieval system prompt, 25% of tools selected | 16,949 |
| Post-retrieval system prompt, 50% of tools selected | 27,199 |
| Post-retrieval system prompt, 100% of tools selected | 41,010 |

The model's native `max_position_embeddings` is **40,960**. The pre-retrieval
system prompt alone already exceeds it. Even after retrieval, a 27k-token system
prompt plus `max_tokens = 8192` leaves under 6k tokens for the entire
conversation — one or two steps. Biomni's retrieval prompt explicitly instructs
the model to "be generous" and to "include as many database tools as possible",
so large selections are the expected case, not the tail.

So the preference for "original context behaviour unless overflow is
demonstrated" resolves to: overflow *is* demonstrated, before any GPU time was
spent.

**Why factor 1.0 is not a context-extension hack.** With YaRN at `factor = 1.0`
the transform is the identity on the RoPE frequencies: the interpolation term is
`inv_freq / 1.0 = inv_freq`, the extrapolation term is `inv_freq`, so blending
them returns `inv_freq` unchanged; and the attention temperature is
`0.1·ln(1.0) + 1 = 1.0`. Nothing about short-trajectory behaviour changes. The
override only lifts the position ceiling. This is also the exact command
published on the model card and in Biomni's README.

**Residual risk, recorded honestly.** Positions between 40,960 and 65,536 were
not seen during training and are reached by pure extrapolation. This is an
**experimental parameter** and is listed as such in `reports/phase1_protocol.md`.
Trajectories are instrumented with `finish_reason`, so truncation shows up in the
results rather than hiding.

**Rejected.** `factor > 1.0` — the model card warns it "might degrade
performance on tasks with shorter trajectories", which is most of this benchmark.

---

## D-05 Two Python environments

**Decision.** A serving environment (SGLang + its pinned torch) and an agent
environment (Biomni + LangChain + this package) are separate virtualenvs.

**Why.** SGLang pulls a specific torch/CUDA stack and a large transitive
closure. Sharing one environment means a serving upgrade can silently change the
agent's `transformers`/`langchain` versions mid-experiment. The dispatcher passes
`--python` explicitly, so which interpreter runs a trajectory is recorded, not
inferred.

---

## D-06 The confidence block goes *inside* `<solution>`

**Decision.** The elicitation instruction asks for the confidence block after
the task answer but **within** the same `<solution>` block.

**Why it cannot go after.** `A1.__init__` builds its LLM with
`stop_sequences=["</execute>", "</solution>"]`. Generation halts at
`</solution>`, so a confidence block placed after the closing tag would never be
generated at all.

**Protection of the task answer.** `parse_final_response` strips the confidence
block *before* the task answer is parsed, so a malformed or duplicated block
cannot corrupt answer extraction. There is a test for exactly this
(`test_malformed_confidence_still_yields_answer`).

---

## D-07 Confidence is injected via the system prompt, not the task prompt

**Decision.** The instruction is appended to Biomni's system prompt by wrapping
`agent._generate_system_prompt`, so the benchmark prompt handed to the agent is
byte-identical between conditions A and B.

**Why.** Condition A exists to measure whether elicitation perturbs task
performance. If the elicitation text were appended to the task prompt, the two
conditions would differ in the task prompt itself and `prompt_hash` would no
longer be comparable. The wrap (rather than a one-time string append) is
necessary because `A1.go` regenerates the system prompt after tool retrieval.

---

## D-08 Per-step confidence is NOT implemented in Phase 1

**Decision.** `confidence.mode` supports `none | final_only | per_step`, but
Phase 1 runs `final_only`. `per_step` is not implemented.

**Why.** Biomni has no structured tool-call channel to attach metadata to. Every
step is free text that must contain exactly one of `<execute>` or `<solution>`,
and the LLM is stopped at those tags. Eliciting a per-step confidence would mean
introducing a third tag into the same free-text channel — precisely the "brittle
prompt parsing / modification of tool-call syntax" that the protocol says not to
force. There is no callback or metadata mechanism upstream that carries it.

**Consequence for the SRLM-style selector.** Only final confidence is available,
so the selector is labelled **"SRLM-style final-confidence approximation"**
everywhere, and is explicitly not a reproduction of step-level SRLM.

**Not done.** A post-hoc confidence probe (re-asking the model after the fact)
was considered and skipped for Phase 1. If it is added later it must never be
described as contemporaneous self-verbalized confidence.

---

## D-09 One trajectory per process

**Decision.** The dispatcher runs each trajectory as a `cli run-one` subprocess,
and `runner.run_trajectory` raises if called twice in one interpreter.

**Why.** `biomni.tool.support_tools.run_python_repl` execs generated code into a
**module-global** `_persistent_namespace`. Two trajectories in one process would
share variables, so one trajectory could read or overwrite another's state. The
process `cwd` is also moved into `<run_dir>/artifacts` so files the agent writes
land inside its own run directory.

---

## D-10 Canonicalization normalizes, and reports what the normalization bought

**Decision.** Each parse keeps both the canonical answer (sent to the official
evaluator) and the raw extracted token. Both are scored; `reward` and
`strict_reward` are stored side by side.

**Why.** The official evaluator's semantics differ per task — `.upper()` for gene
symbols, `.lower()` for the CRISPR letter, but a **case-sensitive** `==` for
rsIDs, and `==` on a string OMIM id. Normalizing the rsID prefix to lowercase, or
coercing an integer `OMIM_ID` to a digit string, grants credit that a literal
string comparison would not. Rather than argue about whether that is fair, both
numbers are computed and the difference is reportable.

**Ground truth is never consulted** to resolve an ambiguous prediction. Where the
benchmark prompt enumerates the legal options, that option list is used for
disambiguation — it comes from the prompt, which the agent also saw.

---

## D-11 Unparseable answers are singleton clusters

**Decision.** A trajectory with no parseable answer forms its own agreement
cluster keyed by `run_id`.

**Alternative.** Pool all unparseable trajectories into one cluster.

**Why.** Pooling would manufacture consensus: four trajectories that each failed
in a different way would look like unanimous agreement and could win a plurality
vote. `n_unparseable` is reported per instance.

---

## D-12 Failed answer parsing is an agent failure; a failed evaluator is not

**Decision.** A completed trajectory whose answer cannot be parsed scores 0.0
with status `unparseable_answer`. An evaluator *exception* yields `reward = None`
with status `evaluator_failure`.

**Why.** The first is a substantive result — the agent did not produce a usable
answer — and belongs in the accuracy denominator. The second is infrastructure
breakage and must not be silently laundered into a wrong answer, which would bias
every downstream comparison.

---

## D-13 Resampling unit is the task instance

**Decision.** All bootstrap intervals resample task instances. Trajectory-level
association analyses use a cluster (grouped) bootstrap over instances, and the
exploratory learned selector uses `GroupKFold` on the instance.

**Why.** The K trajectories of one instance share a prompt, a task and a
difficulty; treating them as 200 independent observations would shrink every
interval by roughly a factor of two.

---

## D-14 Retries never hide the original failure

**Decision.** Only failure classes in
`execution.retry_policy.retryable_failure_classes` (model server, model timeout,
external resource) are re-queued. Both the failed and the retried attempt are
recorded, and failed run directories are never deleted.

**Why.** Automatically retrying a substantive agent failure and keeping only the
success would silently inflate measured accuracy and destroy exactly the failure
signal Phase 1 is trying to characterise.

---

## D-15 File-per-run records, not a shared database

**Decision.** Each run writes its own directory; aggregation is a separate,
deterministic pass into Parquet + CSV.

**Why.** SQLite on a shared network filesystem corrupts under concurrent writers.
Completion markers are written temp-file-plus-rename, and a `COMPLETE` marker is
only trusted when the required artifacts are present *and* `metadata.json` says
`completed: true` — which prevents an interrupted copy-back from being mistaken
for a finished run.

---

## D-16 Deviations from the original brief

| brief assumption | reality | handling |
| --- | --- | --- |
| Held-out split exists | all rows are `val` | D-02, recorded in the manifest report |
| 4 GPUs ≈ 80 GB → TP2 × 2 replicas | 96 GB H100s | same layout; the launcher's `auto` threshold is ≥ 70 GB |
| Two nodes available | this session has one node | layout is unchanged (TP2 × 2 replicas); with one node the pilot simply takes longer. `slurm.nodes` is a config value. |
| Prefer native context | native 40,960 is too small for Biomni's own system prompt | D-04, measured before any GPU time |
| Model served in BF16 | weights ship as FP32 | D-03 |
| `hle` is a benchmark task | supported by the evaluator, **0 instances** in this release | canonicalizer supports it; it cannot appear in the manifest |

---

## D-17 D-04's prompt sizing was wrong; the repair is a budget, not a bigger window

**Decided 2026-08-01, AFTER seeing Phase-1 results.** Marked as such per the rule
at the top of this file. Evidence: `reports/context_overflow_forensics.md`.

**What D-04 assumed.** That Biomni's post-retrieval system prompt would be
17k-41k tokens, extrapolated from selecting 25-100% of the 224 available tools,
and that the native 40,960-token ceiling was therefore too small. On that basis
the served context was raised to 65,536 with the model card's YaRN override.

**What actually happened**, measured over 250 runs and 3,344 model calls:

* the retriever selects a **median of 5 of 224 tools**, giving a median
  post-retrieval system prompt plus task prompt of **2,687 tokens** - not 17k-41k;
* **no completed trajectory ever exceeded 32,154 input tokens**, so the upper
  half of the served window was never used by a working run;
* above ~32,768 input tokens the model degenerates into unterminated repetition:
  runaway rate is **3.1% below that boundary and 94.1% above**, and 7 of 7 runs
  whose system prompt alone exceeded it degenerated on their *first* call.

**Why the boundary is 32,768.** Qwen3-32B, this model's base, is trained at
32,768 tokens of context; the `max_position_embeddings: 40960` in `config.json`
is that context plus one 8,192-token generation, not a 40,960-token context.
D-04's *mathematics* stands - YaRN at factor 1.0 is exactly the identity on the
RoPE frequencies - but the override therefore lifted the position ceiling
**without extending usable context**. Its practical effect was to convert a hard
400 rejection at 40,960 into silent behavioural collapse starting at 32,768,
with room for the resulting repetition loop to run for another 30k tokens.

**Decision.** Do **not** raise the context ceiling and do **not** increase YaRN
scaling; both add capacity exclusively above the boundary where the model no
longer works. Instead bound the trajectory (`trajectory_budget` in
`config.py`, implemented in `budget.py`): cap `max_tokens` at 2,048, truncate an
unterminated generation instead of appending it, cap the retrieval selection and
a single model-visible observation, and enforce a soft 24,576 / hard 32,768
input-token budget that terminates in a *controlled* state.

**Alternatives rejected.** (a) Larger context window - would have converted 60
fast failures into 60 slower ones. (b) YaRN factor > 1.0 - the model card warns it
degrades short trajectories, which is most of this benchmark. (c) Trimming tool
and dataset descriptions, which was first on the original repair list - the
median prompt is 2,687 tokens, so there is nothing to recover, and it would
perturb agent behaviour for no measured gain.

**Consequence for Phase 1.** The report's framing of overflow as "genuine agent
behavior ... not a configuration mistake" (§5) is retracted; see the errata
appended to `reports/phase1_report.md`. The Go/No-Go verdict is unaffected.

---

## D-18 A non-answer never wins a plurality tie

**Decided:** 2026-08-02, during Phase 2A. **Status:** confirmatory for Phase 2;
does not alter any frozen Phase-1 number.

D-11 makes an unparseable answer its own singleton cluster so that unrelated
failures cannot manufacture a consensus. That is right, and it is not enough for
a *sequential* controller. Under the Phase-1 tiebreak — largest cluster, ties to
the lowest index — an observed prefix of `[dead run, correct answer]` is a 1–1
tie that the dead run wins because it arrived first, and the controller returns
nothing when it was holding a good answer.

**Decision.** In `policy.resolve`, a trajectory that did not complete, or that
completed without a parseable answer, can never *win* the plurality. It remains a
singleton cluster and still counts against the support fraction — two failures
out of four is weaker evidence than none out of two — but any real answer beats a
non-answer regardless of arrival order.

**Why this is legitimate.** The distinction is drawn from `completed` and
`answer_parse_status`, both observable online with no ground truth. It is a
capability the controller genuinely has, not a peek at the label.

**How it was found.** Not by inspection. A test asserted that failure-only
escalation recovers failed trajectories; it recovered none, on all 150 replays
that opened on a failure, because every one resolved to the failure. Recorded
because it is the class of bug that silently understates every continuing policy
while looking like a real negative result.

**Scope.** `policy.py` only. `selectors.py` and every Phase-1 number are
untouched — Phase 1 always resolved at fixed K=4, where this arises far less
often, and those results are frozen.

---

## D-19 One policy goes to Phase 2B, not two

**Decided:** 2026-08-02, after seeing the Phase-2A results. Marked as decided
after seeing data, per the exploratory/confirmatory rule.

The brief permits up to two candidate policies for prospective testing: a robust
mandatory-K=2 policy, and *optionally* a K=1-selective policy "if the evidence
supports it."

**Decision.** Carry **one**: mandatory K=2 with agreement-based stopping, a
failure override, and abstention when no two of four trajectories agree. Do not
carry a K=1-selective arm.

**Why.** Under nested, leak-free threshold selection, three of five folds chose
"never accept after one trajectory," and the policy that does accept early loses
1.0 reward point to save 0.21 trajectories. A prospective arm costs statistical
power on ~100 instances; spending it on a component this analysis already
measured as weak is the wrong trade. The recommended policy also has **no fitted
parameter**, so there is nothing about it to re-validate out of sample.

**What is carried instead.** `final_confidence == 1.00` on a parseable answer was
correct 26 of 27 times. That threshold was chosen *after* seeing the table, on
n=27, and the nested procedure — which is not permitted to look — declined to
find it in three folds. It is registered in `reports/phase2_protocol.md` as a
**secondary hypothesis to be tested prospectively**, not as a policy arm. If it
survives a frozen test it becomes a Phase-3 policy; if it does not, nothing was
spent.

**Reversal condition.** If the prospective run shows mandatory K=2 spending
materially more than ~2 trajectories per instance, the K=1 trigger becomes worth
revisiting — but on new data, not by re-reading this one.

---

## D-20 Pooled out-of-fold AUROC is not reported as a discrimination estimate

**Decided:** 2026-08-02, during Phase 2A.

Concatenating out-of-fold predictions and computing one AUROC over the pool is
standard practice and is **wrong for a ranking metric** when each fold fits its
own intercept: predictions from different folds are not on a common scale, so the
pooled ranking mixes them. Measured here, the K=1 confidence calibrator scores a
pooled OOF AUROC of **0.515** against a mean within-fold AUROC of **0.700**.
Reporting the pooled figure alone would have supported the false conclusion that
calibrated confidence carries no signal.

**Decision.** Discrimination is reported as the mean (and range) of **within-fold**
AUROC. Calibration quality — Brier, ECE, reliability curves — is reported pooled,
which is correct for those because they are scale-referenced. Both numbers stay
in `p2a_k1_calibration.csv` so the discrepancy is visible rather than resolved
silently. Implemented as `calibration.within_fold_auroc` and regression-tested.

---

## D-21 Phase-2A's 0.577 and Phase-1's 0.620 are the same result under two conventions

**Decided:** 2026-08-02, after reconciling the two numbers
(`scripts/phase2a_reconcile.py`, `reports/phase2_offline_replay.md` §1.1).

Phase 1 scored plurality **once**, in the order the trajectories happened to be
generated, breaking ties by lowest trajectory index. Phase 2A scores **all 24
arrival orderings** and averages, because a sequential controller has no
privileged order — "index 0" is just whichever sample returned first.

Restricting the Phase-2A replay to Phase 1's native ordering reproduces
**0.6200 bit-exactly**, along with first = 0.4800 and Oracle@4 = 0.6400. That
single check rules out every mechanical cause simultaneously: same denominator,
same reward column, same clustering. The whole 0.04333 gap is **4 tied instances
of 50** whose lowest-index tiebreak happened to pick the correct answer all four
times; the arithmetic closes to five decimals.

**Decision.** The **ordering-averaged** value is the estimate of record for any
sequential-policy claim. A single fixed ordering is one draw: across the 24,
K=4 plurality ranges **0.540–0.620**, and only 6 of 24 reach 0.620. Phase 1 drew
one of the six best.

**What is *not* decided.** `reports/phase1_report.md` and
`reports/phase1_repaired_report.md` stay frozen and are **not** corrected. They
report a realization accurately and their conclusions (headroom, plurality gain,
signal AUROC) do not depend on the four tied instances. This is a difference of
convention between a fixed-K selector study and a sequential-policy study, not
an error in either.

**Worth recording separately:** in two of the four, *every* cluster has size 1 —
four trajectories, four different answers. "Plurality" there is `select_first`
wearing a plurality label. That state is exactly what Phase 2B abstains on.

**Consequence.** Since one ordering can move fixed-K=4 by 8 pp, Phase 2B
pre-registers both the realized-ordering paired comparison (primary) and the
ordering-averaged comparison (secondary S5), so neither can be chosen after the
fact. Locked against regression by two tests in `tests/test_policy.py`.

---

## D-22 Phase-2B allocates 150 held-out instances unequally, on purpose

**Decided:** 2026-08-02, before any prospective inference.

BiomniEval1 has 433 instances, all in split `val` — there is no official
held-out split. Phase 1 used 50, leaving **383 never run**. Phase 2B takes 150
and reserves 233.

**Decision.** Explicit per-task quotas rather than the round-robin balancing
Phase 1 used: `crispr_delivery` **5** (every instance that remains in the entire
benchmark), `rare_disease_diagnosis` **25** (every instance that remains), and
**15** for the other eight tasks — three times Phase 1's cell.

**Why not balanced.** Balance is impossible and would cost information.
`crispr_delivery` has 5 left; the choice is take all five or drop the task, and
no future phase can ever give it a large sample. `rare_disease_diagnosis` is the
pre-declared high-risk stratum — lowest reward, highest residual failure rate,
and the task where the controller offline spends the most (mean K 3.73/4.00) and
recovers the most failures. Phase 1 could only report it at n=5 (±20 pp); n=25
gives ±10 pp on the stratum whose behaviour most needs demonstrating.

**Cost of the decision, stated in advance.** It exhausts both pools, and it makes
`rare_disease_diagnosis` 16.7% of the sample against 6.9% of the benchmark, so
the pooled reward will sit below the benchmark's natural composition. That is a
**level** effect, not a **contrast** effect: every primary comparison is paired
on the same instances, so H1 and H2 are unaffected. A composition-weighted
reward is reported as a secondary descriptive figure.

**Reversal condition.** Reversible before launch and only before launch. After
the manifest hash is used for inference, changing the sample requires a new
experiment ID.

---

## D-23 Shadow isolation is enforced by commit ordering, not by discipline

**Decided:** 2026-08-02, before any prospective inference.

Phase 2B generates all four trajectories per instance so that fixed-K and oracle
baselines are paired on the same instances. The controller must never see the
ones it did not ask for. "The code does not pass them" is not an adequate
guarantee — it is unverifiable after the fact and it fails silently.

**Decision.** Generation and decision are interleaved, and each decision is
**committed before the next trajectory exists**:

1. trajectory *j* is generated; only `1..j` exist on disk;
2. the controller is invoked with exactly those *j*;
3. its action is appended to a **hash-chained, append-only decision log and
   flushed**, each record carrying the previous record's hash;
4. only then may trajectory *j+1* be generated;
5. once the controller terminates at depth *k*, trajectories `k+1..4` are
   generated as shadows under a separate subtree, tagged `role=shadow`.

A shadow cannot influence an earlier decision because it **did not exist** when
that decision was committed, and a decision cannot be rewritten afterwards
without breaking the chain.

**Why this is better than an access-control argument.** It is checkable from
artifacts alone: every shadow's start timestamp must post-date the commit of its
instance's final decision, and the chain must verify end to end. Both are
run-level halt conditions (`reports/phase2_protocol.md` §11), not warnings.

**Cost.** It serializes generation *within* an instance. With 150 instances at
concurrency 8 the run stays work-bound rather than latency-bound, so the cost is
scheduling complexity, not throughput.

---

## D-24 The matched-compute baseline is a real allocation, not an interpolation

**Decided:** 2026-08-02, before any prospective inference.

Phase 2A compared the adaptive policy against an equal-cost fixed allocation by
**interpolating** the fixed-K curve at mean K = 2.70 (≈0.546). That is an
estimate of a policy nobody can run — you cannot spend 2.7 trajectories on an
instance.

**Decision.** Phase 2B's matched-compute baseline is runnable. Let the controller
consume **B** trajectories over **N** instances; set `m = floor(B/N)` and
`r = B − mN`. The baseline spends `m+1` trajectories on a uniformly random subset
of `r` instances and `m` on the rest — **exactly B trajectories**, allocated
without looking at anything. Its per-instance value is the exact expectation over
that randomization,

```
value_i = (1 − r/N)·reward_i(fixed K=m) + (r/N)·reward_i(fixed K=m+1)
```

which pairs cleanly in the instance-level bootstrap and carries no Monte-Carlo
noise. A concrete realized draw at seed 20260802 is reported alongside it.

**The anti-tuning clause.** `m` and `r` are a deterministic function of the
controller's realized cost, computed **before any reward is examined**. Written
down now so the baseline's budget cannot be adjusted once the rewards are known.

---

## D-25 Phase 2B tests non-inferiority, not superiority

**Decided:** 2026-08-02, before any prospective inference.

The Phase-2A finding is that mandatory K=2 returns the *same answers* as fixed
K=4 for 32% fewer trajectories. The claim is therefore about **cost at equal
accuracy**. Testing it as a superiority hypothesis would be testing something
nobody claims and that the offline data predicts will fail (the expected
difference is exactly zero).

**Decision.** Two co-primary hypotheses, both required:

* **H1, non-inferiority in reward** against fixed K=4, margin **δ = 0.05**;
  declared when the lower bound of the 95% paired bootstrap CI exceeds −0.05.
* **H2, cost reduction**; declared when the 95% CI upper bound on mean
  trajectories per instance is below 3.0.

Neither alone supports the headline claim. Two co-primary endpoints in
conjunction need no multiplicity adjustment.

**Why δ = 0.05.** It matches the scale of Phase 1's pre-registered 5 pp
go-threshold; it is well inside the fixed-K=4 − fixed-K=1 gain (9.2 pp offline),
so a policy giving up δ would forfeit more than half the reason to sample at all;
and it is achievable at n=150 (power 0.99, and ≥0.84 even if the prospective
disagreement rate is 3× worse than offline).

**Fixed before the sample was drawn**, so it cannot be widened to fit a result.

---

## D-26 Phase 2B's prospective test fails both co-primary hypotheses — reported as failure, not reframed

**Decided:** 2026-08-10, immediately after the frozen analysis pipeline ran
against the completed prospective run (`reports/phase2_report.md`).

H1 (reward retention, δ=0.05): controller − fixed K=4 = −0.033, 95% CI
[−0.067, −0.007] — entirely below the −0.05 margin's *sign*, i.e. the CI does
not clear the required lower bound. **FAIL.** H2 (cost, mean K < 3.0): mean K
2.893, 95% CI upper bound 3.033. **FAIL**, narrowly.

**Decision.** Report both as failures, exactly as `reports/phase2_protocol.md`
§7.5 pre-registered for this outcome: *"Both fail: Track A's premise does not
survive prospective test, and `reports/phase2_plan.md` §1 selects Track C."*
No threshold was widened, no metric substituted, no result reframed as a
partial success after seeing it.

**Why the result is trusted rather than attributed to noise or a data-quality
problem.** Two independent checks rule out the obvious escape hatches:
(a) a sensitivity analysis excluding `rare_disease_diagnosis` — the task
responsible for most of the elevated residual-failure rate found in D-26's
sibling incident (see D-27, `reports/phase2_protocol.md` DEV-4) — reproduces
almost the same H1/H2 numbers (−0.032, mean K 2.856); (b) S5's ordering-averaged
offline replay of the same 600 trajectories shows the same direction
(0.577 vs fixed K=4's 0.613). The failure is real, not an artifact of the
realized order or of the one bad task.

**What the failure mechanism actually is**, established from three
pre-registered deliverables, not a post hoc story: the controller is accurate
when it answers (0.711 among the 80.7% it accepts) but abstains on 19.3% of
instances, each charged 0 by the protocol-mandated accounting
(`reward_abstain_zero`); the selective-risk table shows every acceptance has
identical support (=2, by construction of "stop the instant two agree"), which
erases the distinction between a confident 2-of-2 stop (87.7% accurate) and a
reluctant 2-of-4 plurality (35.0% accurate — *below* fixed K=1's blind 51.3%);
and the same-cost matched-compute baseline (D-24) beats the controller outright
(0.592–0.593 vs 0.573) — a non-adaptive policy that looks at nothing does
better than the adaptive one at equal spend.

**What is not touched.** Two secondary results survive cleanly and are carried
forward as findings independent of the headline failure: S1 (0% confidently-wrong
for the controller vs 5.3% for fixed K=4 — a genuine safety property) and S4
(`final_confidence == 1.00` correct 89.8% vs 65.1%, n=49/410 — the K=1 signal
flagged as a hypothesis in D-19 now has a clean prospective pass and is a
legitimate Phase-3 candidate).

**Consequence.** Phase 2C (controlled-failure study) does not proceed on this
controller as frozen. The concrete next step this analysis points to — abstain
or escalate on the weak "2-of-4" state instead of accepting it — is a
**redesign**, to be evaluated in a **new, separately pre-registered prospective
run**, never as a retroactive edit to this one.

---

## D-27 A halt condition tripped and was not caught — the gate script had an exact-match bug

**Decided:** 2026-08-10, discovered during Phase-2B analysis
(`reports/phase2_protocol.md` DEV-4).

`scripts/phase2b_verify.py`'s residual-failure-rate gate checked
`failure_class in ("model_context_overflow", "budget_terminated")` against a
runner that records `"budget_terminated_consecutive_runaway"` — an exact
match that could never succeed. The gate reported 0.0% in both the smoke test
(true rate 37.5%) and the full run (true rate 15.5%), both above the
pre-registered 15% halt threshold from `reports/phase2_protocol.md` §11.

**Decision.** Fix the match to a prefix check
(`str(failure_class).startswith(("model_context_overflow",
"budget_terminated"))`), add a regression test keyed to the exact string this
bug missed (`tests/test_phase2b_analyze.py::test_halt_condition_matches_the_budget_terminated_prefix_not_exact_string`),
and report the incident with the same prominence as the substantive result
it sits beside (D-26) rather than as a footnote.

**Why this is not "fixed, move on."** Per DEV-2, the (operator-approved)
compressed launch procedure trusted this exact gate to decide whether 8.5
GPU-hours got spent automatically. Under the corrected gate, the smoke test's
true 37.5% residual-failure rate would have **blocked** that launch. The
process gap that matters is not just the string comparison — it is that
**no test exercised the failure path before the gate was trusted with an
unattended launch decision.** The smoke test that validated the pipeline had
zero failures in its own right (0/24 by chance), so the bug's blind spot was
never exercised until real data hit it.

**Why it does not retroactively change the D-26 verdict.** A sensitivity
analysis excluding the task responsible for most of the excess rate
(`rare_disease_diagnosis`, 33.0% vs 12.0% for the rest) reproduces H1/H2
almost unchanged. The bug hid a real data-quality issue; it happened not to
be the issue that determined the outcome.

**Reversal condition.** None retroactively — the run is not re-launched under
the corrected gate. Any *future* prospective run must pass
`scripts/phase2b_verify.py` post-fix before an automated launch decision is
trusted again.

---

## D-28 The Controller-v2 redesign is rejected on offline evidence; Track C stands

**Decided:** 2026-08-10, after Phase 2B was complete and reported. Marked as
decided after seeing data, per the exploratory/confirmatory rule — but the
adjudication bar was written down in `reports/post_phase2b_assessment.md` §5
**before** the offline analysis in `reports/controller_v2_offline_assessment.md`
was run, so the criteria could not be adjusted to fit the outcome.

`reports/phase2_report.md` §11 named a redesign candidate: abstain or escalate
on the weak "2-of-4 plurality" state instead of treating it as a plain ACCEPT.
The question was whether that deserved one new prospective run before the
project moves to Track C, which `reports/phase2_plan.md` §1 already selected.

**Decision.** **No.** Recommendation **B — move directly to Track C.** No
Controller-v2 is built, no new manifest is created, no GPU job is launched.

**Why — three independent reasons, in increasing order of importance.**

1. *The candidate is worse than the incumbent it was meant to fix.* Replayed
   over 18 parameter-free policies on both available pools, the strict-majority
   rule (accept 2-of-2, 2-of-3, 3-of-4; refuse 2-of-4) scores **−4.7 pp**
   against Controller v1 on `phase2b`, **−5.7 pp** ordering-averaged, and
   **−5.0 pp** on `phase1_pooled`. The 2-of-4 state is 35–42% accurate, not 0%;
   refusing it converts an expected 0.40 into a certain 0 under the
   protocol-mandated `reward_abstain_zero` accounting.
2. *No rule of this shape clears the pre-stated bar.* The best candidate beats
   same-cost blind allocation by **+1.2 pp** at the realized order (95% CI
   spanning 0), against a required ≥3 pp, and its margin over fixed K=2
   collapses from +1.3 pp on `phase2b` to **+0.17 pp** on `phase1_pooled`. The
   whole `phase2b` effect is **two instances of 150**, in two tasks; the other
   eight tasks are exactly tied with fixed K=2.
3. **The distinction is structurally unactionable.** `v1_no_abstain`,
   `v2_majority_no_abstain` and `v2_usable_majority_no_abstain` are the
   *identical policy* — same decision on every instance under every ordering,
   asserted in `tests/test_controller_v2_rules.py`. Inside the action set
   {ACCEPT, CONTINUE, ABSTAIN} where CONTINUE means only *resample*, knowing
   support is 2-of-4 rather than 2-of-2 can only (a) buy more trajectories —
   impossible, 2-of-4 is only reachable at the K=4 budget ceiling — or
   (b) trigger abstention, which reason 1 shows is net-negative. There is no
   third channel. A prospective Controller-v2 run would not be testing a weak
   hypothesis; it would be testing one that cannot express itself.

**What is carried forward instead.**

* *The only self-funding adaptive component is failure-driven continuation.*
  Escalating **only** when an instance has produced no usable answer scores
  0.593 at mean K **2.13** versus fixed K=2's 0.580 at 2.00 — reproducing Phase
  2A §8's failure-recovery finding as the sole surviving piece of adaptivity.
  Recorded as an observation, **not** as a result: the margin is two instances.
* *`final_confidence == 1.00` does not enter a controller.* It passed its
  prospective test as a **signal** (S4, D-19) and that stands. Tested here as a
  decision rule on existing data, as required before any use: its incremental
  value sits entirely inside the 2-of-2 state that is already 87.7% accurate
  (0.952 vs 0.841) and vanishes in the weak states where a controller would need
  it (2-of-3: 0.600 vs 0.613). It stays a secondary prospective analysis.
* *Where the headroom actually is.* On `phase2b`, 30% of instances (45/150) have
  **no correct trajectory at all**, and on the 51 instances with 2–3 distinct
  answers the correct answer is **present but in the minority** — Oracle@4 0.625
  and 0.636 against plurality's 0.375 and 0.273. Voting cannot reach 25–36 pp of
  headroom by construction. That is the Track-C question, reached from the
  controller side rather than assumed.

**Reversal condition.** One, stated precisely: a `VERIFY` or `REPAIR` action
that generates genuinely independent evidence rather than another correlated
sample. With such an action the consensus-history distinction becomes actionable
and the minority-held headroom becomes addressable, and the controller question
reopens on its own terms. Absent that, further stop-rule work is measuring the
same ~1 pp with more machinery.

**Process preconditions attached to any future prospective run** (from
`reports/post_phase2b_assessment.md` §0, both found during this review):
every Phase-2B run records `project_git.dirty = true` and the controller that
produced the result is **untracked in git**, so the exact code is not
recoverable from history — commit before the next run; and the corrected halt
gate's *failure* path has now been exercised end to end for the first time
(exit code **1**, `VERDICT: BLOCKED`, on both `phase2b_smoke` at 37.5% and
`phase2b` at 15.5%), which is the check D-27 specified but never ran.

---

## D-29 Phase-2B ran from an uncommitted tree; provenance is recovered where the artifacts allow and recorded as unrecoverable where they do not

**Decided:** 2026-08-10, after the post-Phase-2B review found that all 600
Phase-2B run records carry `project_git.dirty = true` and that
`src/biomni_uncertainty/controller.py` — the file implementing the controller
under test — was never committed. Full audit:
`reports/phase2b_provenance.md`; script `scripts/phase2b_provenance_audit.py`;
tests `tests/test_phase2b_provenance_audit.py`.

**The failure.** A pre-registered prospective experiment executed from a working
tree that version control did not capture. **No commit in this repository is the
Phase-2B execution commit**, and none may be described as one.

**Decision.** Recover what the preserved artifacts prove, classify every
Phase-2B-relevant file into `ESTABLISHED` / `CHANGED_AFTER` / `UNPROVEN`, and
commit the working tree as an explicitly-labelled **post-hoc provenance recovery
snapshot** that is *not* claimed to be the execution commit. Do not rewrite
history, do not backdate, do not touch a frozen artifact.

**What the audit established** (14 files `ESTABLISHED`, 3 `CHANGED_AFTER`,
4 `UNPROVEN`):

* **`configs/phase2b.yaml` is cryptographically attested.** The stored
  `config_hash` `ee5f8cd3…` recomputes bit-exactly from the current file and the
  full config snapshot is identical — *once the three `${ENV}` expansions
  recorded in the snapshot are restored*. Without that restoration the check
  produces a false alarm; the audit does the restoration and the report says why.
* **`manifests/phase2b.jsonl` is cryptographically attested**, recomputing to
  `7cb5da3ac345…`, the value frozen in the protocol before inference.
* **`controller.py` and `policy.py` are attested behaviourally.** All **434/434**
  committed decision records reproduce exactly against the current files —
  action, the **free-text `reason` string** generated by policy f-strings,
  support, agreement flag, resolved cluster key, and the ordered observed
  `run_id` list — with 150/150 hash chains verifying. This proves behavioural
  identity on the domain the run visited; it does **not** prove byte identity,
  and it is cited that way.
* **The untracked driver's output is pinned even though its bytes are not.**
  All **600/600** trajectory identities recompute from tracked code plus the
  attested config and frozen manifest: `run_id` via `sampling.make_run_id`
  (including the `shadow` condition, which `expand_runs` does not produce),
  `requested_seed = 2000 + 100 + index`, `prompt_hash`, and `run_dir`.
  Orchestration is attested only by output invariants, not by source.
* **The pinned dependency is clean.** `biomni_src` is still at `400c1f36…` with
  a clean tree, and all 600 runs recorded `dirty = false` for it.

**What is known to have changed after the run.** `scripts/phase2b_verify.py`
(the D-27 gate fix, 04:36:14 vs the run ending 03:03:59 — so the version that
produced the false PASS is gone and cannot be exhibited),
`scripts/phase2b_analyze.py` and `tests/test_phase2b_analyze.py` (04:41:49,
before the stored tables were written at 04:42:31, and independently
reproduced). None of the three participates in trajectory generation or scoring.

**What remains unrecoverable.** `scripts/phase2b_run.py`, `run_phase2b.sh`,
`phase2b_supervise.sh` and `tests/test_controller.py` have no cryptographic
record. **mtime is treated as circumstantial and never as proof** — a timestamp
is settable — and `tests/test_phase2b_provenance_audit.py` asserts that mtime
alone can never promote a file to `ESTABLISHED`.

**Why this does not weaken the Phase-2B result.** The result reproduces exactly
from stored artifacts: H1, H2, coverage, the selective table, matched compute,
S4 and the sensitivity analysis were all recomputed independently, and the
frozen controller re-simulated offline matches the online decision log on
**0/150** instances. The gap is in *source auditability*, not in the numbers.
That distinction is stated in every artifact that carries this finding.

**An observation logged, not a correction.** `logs/phase2b_supervisor.log` ends
2026-08-02 12:10:41 at `WAITING_FOR_SMOKE`, the smoke finished 12:32, and the
full run started **2026-08-09 18:33** with `phase2b_supervise.sh` modified
18:29:03 that day. The supervisor that logged on 2026-08-02 did not launch the
full run. D-27's substantive point is unaffected — the gate reported a false
PASS, nothing blocked, and no test had exercised its failure path — but the word
"auto-launch" should not be read as implying a recoverable supervisor decision.

**Consequences, to be written into the next protocol.** Commit before launch and
record the commit; make the launcher refuse a dirty tree and exit non-zero;
hash every imported source file into `metadata.json` at run start so this audit
becomes one equality check; never overwrite a tool that produced a gating
decision — fix forward in a commit.

**Not addressed here, deliberately.** The second prospective blocker stands
exactly as measured: residual trajectory failure **15.5%** (93/600), above the
pre-registered 15% threshold. No repair was attempted.

---

## D-30 Track C's first diagnostic is NO-GO for diversity-by-resampling: trajectories that disagree have the same plans

**Decided:** 2026-08-10, from `reports/track_c_diversity_diagnostic.md`
(experiment `track_c_diversity`, CPU only, no GPU, no model calls, nothing about
prompts/temperature/tools/generation changed). The three-way interpretation rule
was written into `scripts/track_c_diversity.py`'s docstring **before any outcome
association was computed**, so the label could not be fitted to the result.

**Question.** When Biomni trajectories disagree, are they performing
meaningfully different analyses, or following correlated reasoning paths and
producing noisy different final answers?

**Decision. Outcome B (correlated upstream, noisy downstream), with a secondary
component of Outcome C. NO-GO for "generate more diverse trajectories" as the
Track-C intervention.** Do not build a diversity mechanism.

**The decisive numbers**, all instance-clustered bootstraps on 150 held-out
instances / 566 both-usable within-instance pairs:

* **Plans are identical whether or not the conclusions agree**: plan Jaccard
  0.546 (disagreeing pairs) vs 0.538 (agreeing), difference **+0.008, 95% CI
  [−0.040, +0.058]** — against a "different question, same task" control of
  **0.301**. The control is what makes this readable: the metric has real
  discriminative power, and it finds no difference. **Divergence happens
  downstream of the plan, not in it.**
* Composite workflow distance: +0.020 [−0.034, +0.074]. Below the 0.05 bar and
  CI covering 0 ⇒ Outcome B by its pre-registered criterion.
* **Independence does not predict correction.** P(the other trajectory is
  correct | this one is wrong), by workflow-distance quartile: 0.308 / 0.190 /
  0.263 / 0.359 — **non-monotone**. High-minus-low **+0.056, 95% CI [−0.074,
  +0.180]**, against a pre-registered ≥10 pp bar.
* **A correct minority is not more isolated** from the wrong plurality than that
  plurality is from itself: **−0.037, 95% CI [−0.131, +0.046]**, the wrong sign,
  splitting 6/4 across only 10 instances.
* Outcome A is rejected on both of its conditions. Tool paths *do* diverge when
  answers do (tool-sequence similarity −0.105, CI excluding 0) — that is the
  Outcome-C component — but the control shows tool choice is barely
  question-specific at all (0.442 within-instance vs **0.396** on unrelated
  questions), so it is variation within a task-level habit, and it buys nothing.

**Failure is separated from disagreement, and stays separated.** Of 150
instances: 82 unanimous, **53 substantive disagreement (B)**, **15 insufficient
evidence (A: fewer than two usable trajectories)**. Stratum A is reported as an
agent/infrastructure reliability problem and is excluded from every diversity
statistic. It is the same phenomenon as the unresolved 15.5% residual failure
rate, and 12 of its 15 instances have no correct trajectory to find.

**Three findings that reframe the track.**

1. **35.7% of trajectories make zero tool calls**, and they are *more* accurate
   (0.724) than tool-using ones (0.652). Correct answers on this benchmark come
   largely from parametric memory, not from evidence retrieval.
2. **The evidence channel is substantially broken**: 30.0% of 1,395 tool calls
   error, concentrated exactly where a VERIFY action would live —
   `query_pubmed` **68.9%**, `advanced_web_search_claude` **77.0%**,
   `query_scholar` **80.0%** — while structured databases work (GWAS Catalog
   7.3%, Ensembl 6.6%, ClinVar 6.4%). This is the known Phase-0 decision to skip
   the full E1 environment (`reports/phase0_environment.md`), whose cost has now
   been quantified against the mechanism it blocks;
   `reports/phase2_plan.md` §2.3 anticipated precisely this.
3. **Retrieval content was never logged** — only counts of selected tools, never
   names. Evidence overlap is therefore unmeasurable from these traces. This is
   the single most valuable thing to instrument before any Track-C run.

**What a useful VERIFY action must do differently from RESAMPLE**, which is the
deliverable this diagnostic existed to produce: change the *plan* by
construction rather than by sampling; check the *computation* rather than
re-ask for a conclusion (the clearest case in the sample has four trajectories
sharing a near-verbatim plan, Jaccard up to 0.931, returning four different
answers to one deterministic ORF computation); repair or avoid the literature
channel; make retrieval mandatory and logged by name; and never spend a
verification trajectory on stratum A.

**Not decided here.** Whether to run a constructed-verification pilot. That
would be a new prospective design needing its own pre-registration, and per D-29
a committed tree and a residual failure rate under the 15% threshold before it
launches. **No GPU work, no new manifest, no prompt change was performed.**

---

## D-31 A constructed-verification pilot has five scientific prerequisites, none yet started

**Decided:** 2026-08-10, immediately after D-30. Full note:
`reports/verify_prerequisites.md`. **Design note only — no code, config, or
manifest.**

D-30 found exactly one intervention the evidence supports: a verification
trajectory whose plan differs *by construction*, not by resampling. Before
building that, this decision records that three of D-30's own headline numbers
sit on measurement infrastructure already known to be compromised, so building
`VERIFY` on top of it would test the infrastructure, not the hypothesis — the
same distinction `research_north_star.md` draws between necessary unblocking
work and scope creep.

**Decision.** Treat the following as prerequisites to a *valid* experiment, not
general cleanup, and do not start implementing any of them without separate
approval:

1. **Repair the literature/evidence channel.** 30.0% overall tool-call error,
   concentrated exactly where VERIFY would operate (`query_pubmed` 68.9%,
   `advanced_web_search_claude` 77.0%, `query_scholar` 80.0%) against 6–11% on
   structured databases. Root cause is missing imports (`pymed`, `anthropic`,
   a misnamed function), not query design — a narrow fix, not the full E1
   environment Phase 0 already declined as disproportionate.
2. **Instrument retrieval identity/content, not counts.** `retrieval_end`
   currently logs only `{tools: N, data_lake: N, ...}`. Without recording
   *which* evidence was retrieved, "VERIFY used independent evidence" is
   unfalsifiable — the identical gap the hash-chained decision log was built to
   close for shadow isolation (`controller.py`'s own rationale).
3. **Bring residual failure under the 15% halt threshold** (currently 15.5%,
   D-29). Otherwise a VERIFY-vs-RESAMPLE contrast risks the same confound D-30
   §4 separated out for Controller v1: failure mistaken for disagreement.
4. **Validate 1–3 against previously-healthy controls before trusting them**,
   using the method already validated in this project — Phase 1.5's Arm-3
   regression (reward collapsed to 0.000 on two control strata that were fine
   at baseline) is the standing cautionary example for why a repair that fixes
   the target failure can silently break something that worked.
5. **Fix an operational, checkable VERIFY-vs-RESAMPLE definition before
   generating a single trajectory under either label**, reusing
   `diversity.py`'s plan-Jaccard metric as an after-the-fact audit, and a
   `TrajectoryView`-style visibility barrier so VERIFY cannot reproduce the
   plan it is meant to check by reading it.

**Why now, not folded into D-30.** D-30 is a completed, defensible diagnostic
on its own terms. Conflating "here is what we found" with "here is what to
build next" would blur exactly the confirmatory/exploratory line this project
insists on everywhere else.

**Reversal condition.** None of the five is claimed to be sufficient on its
own; together they are the floor for validity, not a guarantee the pilot will
show anything. The pilot's own launch still requires D-29's preconditions
(committed tree, gate re-exercised) independently of this list.

**Status.** Nothing started. Awaiting direction on whether, and in what order,
to begin.

---

## D-32 The RESAMPLE-vs-VERIFY distinction is frozen before any environment work begins

**Decided:** 2026-08-10. Full specification: `reports/verify_definition.md`.
**Specification only — no code, config, or manifest.** Completes prerequisite
item 5 of D-31, done first and out of dependency order deliberately: the audit
criteria this note fixes determine what item 2's retrieval-provenance
instrumentation must record, so item 5 gates item 2 rather than following it.

**Decision.** VERIFY is a distinct trajectory type, triggered by a distinct
controller action (`policy.Decision.action == "VERIFY"`, alongside `ACCEPT`/
`CONTINUE`/`ABSTAIN`), required to satisfy five conditions or it is not VERIFY
whatever it is labelled: starts from a specific candidate claim (not the bare
task); tests that claim rather than re-solving the task; differs from the
candidate's method **by construction** — imposed by the harness, not left to
temperature, because D-30 showed divergence does not occur on its own; never
sees hidden ground truth; and must not copy the original trajectory's
reasoning, enforced both structurally (§3) and by a post-hoc audit (§5).

**`VerifyView`**, modelled on `policy.TrajectoryView`/`FORBIDDEN_VIEW_FIELDS`:
permits only `task_prompt`, `candidate_answer`, `verification_mode`, an
optional structured claim decomposition, and its own run id. A new
`FORBIDDEN_VERIFY_FIELDS` list, stricter than `FORBIDDEN_VIEW_FIELDS`, adds the
original transcript/plan/tool-calls/code (structurally prevents copying) and
**the original's stated confidence** (prevents anchoring a supposedly
independent judgement on it — relevant because S4, `final_confidence == 1.00`,
is a live candidate signal and must not be partly re-derived through VERIFY).

**Three modes, kept minimal per the north star's standing constraint against
building machinery ahead of evidence:** A (computational — independently
re-derive a quantity from raw inputs, verdict by comparison, not by
wording — the diagnostic's `lab_bench_seqqa/i0027` case is its target);
B (evidence — retrieve from a source distinct from the candidate's, gated on
`reports/verify_prerequisites.md` item 1's evidence-channel repair, since a
68–80%-error channel would make an `inconclusive` verdict indistinguishable
from infrastructure failure — D-30 §4's confound recurring one level up);
C (adversarial — B's query strategy inverted, explicitly seeking
disconfirmation). All three require a `confirmed`/`refuted`/`inconclusive`
verdict with a stated basis, and **none may return `confirmed` on agreement
alone** — that would be RESAMPLE wearing a VERIFY label.

**The audit criterion is a rejection test against a measured null, not an
arbitrary constant**, per the brief's explicit instruction. The null is D-30's
own RESAMPLE reference band — same-instance trajectory pairs, agreeing or not,
land at plan Jaccard 0.540 [0.515, 0.566], tool-sequence similarity 0.409
[0.358, 0.463], query Jaccard 0.328 [0.287, 0.372]. A mode-B/C VERIFY
trajectory passes only if its query or tool-sequence similarity to the
candidate falls **below the band's lower CI bound**, not merely numerically
lower. Mode A's audit is structural (a code execution deriving the checked
value from inputs), not lexical. The strongest audit — evidence-identity
overlap — **cannot be computed yet** and is left uncalibrated on purpose,
pending real data from item 2's retrieval-identity instrumentation; this
document is now that instrumentation's requirements source.

**A failed audit is logged, never silently discarded or silently
recategorized as RESAMPLE** — the same discipline `reward_abstain_zero`
already enforces for abstention.

**What remains open, explicitly.** Whether VERIFY beats RESAMPLE (an efficacy
question, not addressed here); controller wiring for when VERIFY fires;
mode-selection policy; and the §5.3 numeric evidence-overlap threshold, held
uncalibrated until there is data to calibrate it from.

**Reversal condition.** Frozen for the purpose of proceeding to prerequisite
item 2. Any later revision — including after seeing VERIFY trial data — must
be an explicit, labelled amendment, never a silent edit, matching the standing
rule for every other frozen protocol in this project.

---

## D-33 Evidence-channel repair: two tools fixed, three excluded on evidence, retrieval provenance instrumented

**Decided:** 2026-08-10. Full report: `reports/evidence_channel_repair.md`.
Prerequisite items 1 and 2 of D-31, addressed together since a route is only a
valid VERIFY evidence source if it is both reliable and auditable.
**CPU-only, no GPU, no agent driver, no manifest.** Environment change only:
`pymed`, `arxiv`, `scholarly` (+`free_proxy`) installed into `biomni_unc`; two
source files instrumented; no upstream Biomni code touched.

**Repaired (local dependency, reproducibly fixed, no proprietary or fragile
mechanism):**

* `query_pubmed` — `from pymed import PubMed` was failing on a missing local
  package (`No module named 'pymed'`, D-30's 68.9% error). `pip install pymed`
  (a thin wrapper over NCBI's public E-utilities, no key required). **8/8
  (100%) real Phase-2B queries succeeded after the fix**, tested directly
  against the tool function, no agent involved.
* `query_arxiv` — same class of fix (`arxiv` package, public API, no key).
  **8/8 (100%)**.

**Excluded, each for a reason confirmed by direct measurement, not assumed:**

* `query_scholar` — installing `scholarly` does **not** fix it: a version
  mismatch between `scholarly` 1.7.11 and its own `free_proxy` 1.2.2 dependency
  makes `FreeProxies()` raise deterministically
  (`TypeError: FreeProxy.get_proxy_list() missing 1 required positional
  argument: 'repeat'`), reproduced identically on every trial (**0/8, 100%
  error**). Even pinned to compatible versions, the underlying mechanism —
  scraping Google Scholar through free, unauthenticated rotating proxies — is
  inherently fragile. Repair rejected as disproportionate and non-durable;
  no open substitute exists; excluded.
* `advanced_web_search_claude` — requires `anthropic` + `ANTHROPIC_API_KEY`.
  **Never tested.** Repair rejected outright per instruction and per the
  standing rule against proprietary API dependencies (`CLAUDE.md`, extended
  from Phase 1): it would add an unaccounted-for closed model to a testbed
  whose subject is an open-weights agent, and would confound any VERIFY result
  with "a stronger model did the verifying" — a different, larger, explicitly
  deferred experiment (`reports/phase2_plan.md` §2.9).
* **`search_google` — a new finding, not anticipated going in.** D-30 read it
  as healthy (3.4% error, 2/59). Direct testing on 8 real queries plus a
  maximally-easy control query found **0/8 (0%) succeeded, with zero
  exceptions raised** — the underlying `googlesearch-python` scraper returns
  an empty generator, most likely because Google serves non-browser-like
  requests a blocking/consent response rather than results. **The old
  error-rate metric missed this entirely** because the tool catches its own
  exceptions and returns an empty string, which the runner's failure
  classification counts as `status: "ok"`. This is exactly the "empty vs
  error" distinction this diagnosis was designed to surface, and it removes
  what would otherwise have been VERIFY's fallback general-search route.

**Consequence.** VERIFY's evidence route is `query_pubmed` + `query_arxiv` +
the eight already-healthy structured databases (unchanged, not re-tested — no
reason to expect drift, and re-testing everything already healthy would be the
"install everything" scope explicitly ruled out). **No general web-search tool
is currently reliable for VERIFY.** This is a real coverage limit, not a gap in
the repair: tasks whose evidence need is general web search may have no
currently-reliable independent-evidence route.

**Retrieval provenance instrumented**, closing the gap D-30 §10.2 and
`reports/verify_definition.md` §5.3 both flagged: `retrieval_end` now logs
`selected_identities` (actual resource names, mirroring
`retriever._format_resources_for_prompt`'s three input shapes) alongside the
existing counts; `code_execution_end`/`tool_call_end` now carry a content hash
of tool output (`output_hash`/`evidence_output_hash`), stated as **block-level,
not call-level** — Biomni tools execute inside one `<execute>` block, so a
block calling more than one tool cannot have its hash attributed to a single
call, and that limitation is documented rather than hidden. `diversity.py`
exposes `retrieval_identity_jaccard` and `evidence_output_jaccard`, kept
**outside `SIMILARITY_COMPONENTS`** so D-30's already-reported
`workflow_distance` is not silently redefined by data that postdates it.
Traces from every prior run (Phase 1 through Phase 2B) have empty
identity/hash fields, which read as "not comparable," never "no overlap" —
the same discipline the rest of `diversity.py` already enforces, now checked
by test for these two fields specifically.

**Regression tests: 14 new** (`tests/test_instrumentation.py`, 9;
`tests/test_diversity.py`, +5), proving the fields are populated, not merely
present in the code — including that identical output hashes identically and
different output does not, that empty output hashes to `None` rather than a
collision-prone placeholder, and that the two new metrics never enter
`workflow_distance`. **Full suite: 423 passed.**

**What remains open.** Coverage for non-literature evidence needs; whether the
repaired channel changes behaviour on healthy controls (item 4, next);
whether residual failure has moved (item 3); the §5.3 audit threshold, still
uncalibrated pending real VERIFY trial data.

**Reversal condition.** None of the three exclusions is permanent by
assumption — each was decided on direct evidence and could be revisited if
that evidence changes (e.g., a compatible `scholarly`/`free_proxy` pairing is
released, or a non-scraping open search API becomes available). Any reversal
must cite new measurement, not merely a change of mind.
