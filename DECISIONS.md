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

---

## D-34 Residual trajectory failure re-measured: NOT improved, same known mechanism, confirmed unrelated to the evidence-channel repair

**Decided:** 2026-08-10, after D-33. Full report:
`reports/residual_failure_remeasurement.md`. Prerequisite item 3 of D-31,
performed only after items 1 and 2 (D-33) were complete, as instructed. The
old 15.5% number was **not** assumed to still apply, and no repair was begun
merely because it had once been above threshold — a small, fresh, live sample
was generated first (32 real trajectories, 8 instances, zero overlap with any
prior manifest, throwaway — not written to `manifests/`, not a registered
experiment ID), and the corrected gate was exercised against it live for the
first time (not a replay of historical artifacts, as D-29's audit was).

**Result.** **9/32 = 28.1%, 95% Wilson CI [15.6%, 45.4%].** The point estimate
is *above*, not below, the historical 15.5%, and the CI's lower bound sits
essentially at the 15% threshold itself. **Prerequisite 3 is NOT met.**
Task-matched against Phase 2B's own per-task rates on the same four tasks
(the only ones with unused reserved pool — `crispr_delivery` and
`rare_disease_diagnosis` are pool-exhausted by D-22), every "after" CI
overlaps its "before" CI: nothing here is statistically distinguishable from
the historical rate at n=8/task, in either direction.

**Mechanism, confirmed identical to Phase 1.5's diagnosis.** All 9 failures
carry `terminated_reason: "consecutive_runaway"` and `peak_input_tokens` in
32,936–40,637 — the model's ~32,768-token trained-context boundary, exactly
the mechanism `context_overflow_forensics.md` diagnosed: the guard bounds the
cost of a re-degenerating trajectory, it does not prevent the degeneration.
Nothing about this mechanism is new.

**Confirmed NOT caused by D-33's evidence-channel repair, on two independent
pieces of evidence from this same run.** Only 5 of 9 failed trajectories
called `query_pubmed` at all, and none called `query_arxiv` — the other 4
failed using only already-healthy structured database tools. More decisively:
the single worst instance (`patient_gene_detection/i0273`) failed on **all 4**
of its independent trajectories — 44% of this sample's failures from one
instance — and two of those four never called the repaired tools at all. The
same degeneration occurred with or without the repaired evidence route, which
rules out the repair as a contributing cause.

**Localization.** Failure concentrates in specific pathological instances
rather than being spread evenly — excluding `i0273` alone drops the sample to
5/28 = 17.9% [7.9%, 35.6%], closer to but still not comfortably under the
historical rate. This is the same concentration pattern already documented
for `rare_disease_diagnosis` in Phase 1.5 ("10 of its 13 failures persist even
with the repair… a residual limitation, not a repair bug") — specific
instances degenerate regardless of task identity or which tools are called.

**Decision: no broad Arm-1/2/3-style search is proposed**, per instruction —
the evidence does not call for one. This run added no new mechanistic
information; it confirmed the existing Arm-2 guard behaves exactly as
designed and confirmed the evidence-channel change is not implicated.
Re-running the 72-trajectory ablation would spend real GPU time re-measuring
something already measured.

**Smallest targeted intervention, proposed but not implemented:** screen
candidate instances for a future held-out sample with one cheap trajectory
before committing K=4, excluding ones that hit `consecutive_runaway` on that
screen — a selection-layer mitigation, since Phase 1.5 already tried and
explicitly rejected the serving-layer fix (raising the context ceiling, shown
to make things worse). Two options left for whoever designs the next
protocol: accept the current rate and size the statistical plan around it, or
adopt pre-screening and re-measure before trusting the number.

**The gate exercise itself succeeded cleanly.** Live, first-time-seen data,
correctly BLOCKED (exit code 1) on the residual-failure gate; every other gate
(chain integrity, shadow isolation, leakage, failure-override, cost
accounting) passed — nothing about D-32/D-33's changes broke the controller,
instrumentation, or gate machinery.

**Reversal condition.** None claimed — this is a measurement, not a policy.
A future prospective run must not assume this number has improved without its
own fresh measurement, and per D-29 must launch from a committed tree with the
gate's BLOCKED path already proven (done, again, here).

---

## D-35 Healthy-control validation: PASS — repaired environment does not regress previously-healthy behavior; item 3 remains failed

**Decided:** 2026-08-10, after D-34. Full report:
`reports/verify_prerequisite_control_validation.md`. Prerequisite item 4 of
D-31, performed only after items 5, 1, 2 and 3 (D-32/D-33/D-34) were
complete. **Second live-inference step of this engagement** — same live
allocation (job 3388121), no new SLURM request.

**Scope, stated precisely and not exceeded.** Does the repaired/instrumented
environment (D-33) cause a material regression on previously-healthy
instances? Not a repair of the 28.1% residual-failure problem (D-34), not a
test of VERIFY, not a new benchmark, not evidence that item 3 has passed.

**Acceptance rule frozen before the first trajectory**, in a separate
timestamped file: PASS only if reward degradation ≤10pp, completion/usable-
answer degradation ≤10pp, no new failure class affecting more than one
control, no gross unexplained cost increase — on a paired 6-instance sample
(same task prompt, same trajectory index, same `requested_seed`, same
model/budget/controller config as the matched Phase-2B baseline). If 1–2
instances dominate a small-sample effect, report BORDERLINE rather than
widen the rule.

**Controls, drawn from `manifests/phase2b.jsonl`** (reusing already-used
instances is correct for a *paired* design — pool exhaustion, which blocked
item 3's fresh sample, does not apply). Six instances, none selected because
it previously failed: `crispr_delivery/i0007` (literature/evidence, the
category most exposed to D-33 — historically used `advanced_web_search_claude`
+ `query_pubmed`, both broken pre-repair); `gwas_variant_prioritization/i0207`
and `gwas_causal_gene_gwas_catalog/i0418` (structured-database);
`lab_bench_seqqa/i0492` and `/i0379` (computational/sequence, zero and one
tool call respectively); `patient_gene_detection/i0251` (structured-database,
distinct task family).

**Result: PASS**, on the pre-declared primary comparison (trajectory index 0,
n=6): mean reward **0.500 → 0.667 (+16.7pp, an improvement)**, completion and
usable-answer **100% → 100%, unchanged**, no new failure. Every quantitative
bar clears with margin on the comparison the rule names primary.

**Supplementary (all 4 indices, n=24, reported because the rule asked for
it, not because it is the primary bar):** reward −4.2pp, completion −4.2pp,
usable-answer −8.3pp — all inside the ±10pp bars. **One new failure**
(`gwas_causal_gene_gwas_catalog/418`, index 2: healthy before, now
`budget_terminated_consecutive_runaway`) — confirmed the *identical*
mechanism D-34 already characterized (`peak_input_tokens=36,968`,
`consecutive_runaway`), affecting exactly 1 of 6 controls, not "multiple."
Combined with `seed_supported: False` (confirmed both historically and now —
this endpoint does not honor seeds deterministically), the defensible reading
is stochastic variation landing on an already-known failure mode, not a new
one introduced by D-33.

**Cost: the exact "1–2 instances dominate" case the rule anticipated
reporting rather than absorbing.** Aggregate tokens rose 1.36×, but a single
trajectory (`gwas_causal_gene_gwas_catalog/418`, index 1, **zero tool calls**)
accounts for roughly 59% of the entire increase on its own — unexplainable by
either the evidence-channel repair or the instrumentation (neither touches a
trajectory that calls no tools), and by elimination ordinary trajectory-length
variance. The primary (index-0) comparison, unaffected by this outlier's
index, shows tokens *decreasing*. Reported explicitly per instruction rather
than smoothed into a clean PASS.

**Evidence-channel behavior, confirmed live for the first time.** Every
`query_pubmed` error in this run was a **model behavioral error**, not a
package failure: `invalid syntax` (a code-generation mistake) and
`cannot import name 'query_pubmed' from 'biomni.tool.database'` (the model
guessing the wrong module path) — neither is `No module named 'pymed'`; that
failure mode is gone. Every other `query_pubmed` call succeeded, confirming
D-33's isolated 8/8 measurement inside a real, live, agent-driven trajectory.
**Retrieval-provenance instrumentation: 15/15 trajectories that made any tool
call had `retrieval_selected_identities` and `evidence_output_hash`
populated — 100% coverage, zero gaps**, confirmed by direct inspection.

**Causes distinguished, as instructed:** the repaired literature channel
shows no observable reward effect and a plausible token *reduction* (real
short abstracts vs. an error-retry loop) on the two literature-touching
trajectories; the added instrumentation is purely observational and
mechanistically cannot alter model behavior — none detected, none plausible;
the dominant explanation for both the one new failure and the cost outlier is
ordinary stochastic variation, consistent with confirmed seed
non-determinism. No inference is drawn that more tool use is automatically
better.

**Gate exercise, both paths, live for the first time.** BLOCKED re-exercised
immediately before launch (item 3's data, 28.1%, exit 1); this run's own gate
returned **`VERDICT: ALL GATES PASS`, exit code 0**, residual failure
1/24 = 4.2%. The first time this project has shown the corrected gate
producing a clean PASS on real trajectories, not only a BLOCKED.

**What PASS does and does not mean, stated without hedging.** The repaired,
instrumented environment does not cause a material regression on
previously-healthy instances and is safe to build on for that narrow
purpose. **It does not mean item 3 has improved** — D-34's 28.1% was measured
on fresh, unscreened, high-base-rate-stratified instances; this validation
was deliberately drawn from previously-healthy ones and cannot speak to the
population-wide rate either way. **Item 3 remains FAILED.** A prospective
VERIFY experiment remains blocked on that basis alone, independent of this
result. This validation does not constitute progress on it, and no attempt to
repair it was made here — that repair was explicitly out of scope for item 4
and remains a separate, undecided question.

**Reversal condition.** None claimed — this is a screening validation
(n=6/24), not a powered equivalence test. A future prospective protocol
citing this result should note its limitations (§8 of the report): best-effort
pairing under confirmed seed non-determinism, one literature-oriented
instance, five of ten tasks touched, `rare_disease_diagnosis` deliberately
excluded as the pool-exhausted high-risk stratum rather than a healthy
control.

---

## D-36 The D-29 process debt is closed: launch entrypoints refuse a dirty tree; every trajectory carries source hashes

**Decided:** 2026-08-10. **CPU-only, no GPU, no manifest, no config change.**
No frozen artifact touched. Closes the two forward-looking consequences D-29
listed but did not implement.

**Decision.**

1. **`provenance.assert_clean_tree`** — `scripts/phase2b_run.py`'s `main()` and
   `cli.py`'s `dispatch` command both call it before generating a single
   trajectory. Raises `DirtyTreeError` (→ non-zero exit) on any uncommitted
   change, **including untracked files** — an untracked new controller module,
   exactly D-29's failure mode, trips it. `--allow-dirty` exists for
   exploratory/throwaway runs only, prints a prominent warning to stderr and
   the run log, and must never be used for a confirmatory prospective run.
2. **`provenance.source_hashes`** — SHA-256 (16 hex chars) of every
   `src/biomni_uncertainty/*.py` and `scripts/*.py` file, recorded into every
   trajectory's `metadata.json` under `source_hashes` (`runner.py`,
   alongside the existing `project_git`/`biomni_git` fields). A future D-29-style
   audit is now one equality check against the current tree instead of the
   file-by-file behavioural reconstruction that D-29 required. Deliberately
   hashes every driver in `scripts/`, not just the one that happened to launch
   a given trajectory — a subprocess cannot reliably identify its own
   top-level entrypoint, so the audit surface is the whole `scripts/`
   directory.
3. **Never overwrite a script that has produced a gating decision** — recorded
   as a standing rule in `CLAUDE.md`'s provenance section, not as code. D-27's
   `scripts/phase2b_verify.py` was fixed in place before this rule existed,
   which is why the exact version that produced the false PASS could not
   later be exhibited (D-29). Going forward, a bug found in a script that
   already gated a real decision gets a new commit, never an edit that erases
   the version that ran.

**Verification, not just implementation.** The guard was exercised live
against the real dirty tree mid-development (a bogus config/manifest path,
`timeout 10`, no real endpoint or frozen artifact touched): it printed
`REFUSING TO LAUNCH: DIRTY TREE ...` and exited 1 **before** attempting to
load any config, read any manifest, or contact any endpoint — the guard sits
ahead of every side-effecting step, not just ahead of trajectory generation.

**A near-miss during this work, recorded for the record.** An earlier attempt
to exercise the guard end-to-end via a live `phase2b_run.py` invocation was
run against the **real** `configs/phase2b.yaml` / `manifests/phase2b.jsonl` /
production endpoints file, with the actual Step-0 code changes accidentally
`git stash`-ed away first (so the *old*, unguarded script ran). The process
was killed by a 30-second command timeout mid-run. **No frozen artifact was
affected** — every one of the 150 `phase2b` instances was already complete,
so `is_valid_complete` would short-circuit to `"reused"` with no trajectory
regenerated; verified directly afterward (zero new mtimes under
`phase2b/runs`, decision-log count unchanged at 150) — but the methodology
was wrong: a guard test must never point at real frozen configs or a live
endpoint. Corrected to a nonexistent-path invocation, which is sufficient to
prove the guard's ordering and cannot touch anything real.

**Tests.** `tests/test_provenance.py` (10 new): clean tree passes silently;
dirty tree raises by default; `--allow-dirty`'s warning appears on stderr and
in a given log path; an **untracked-only** dirty state still trips the guard;
a nonexistent repo path is not misread as dirty; `source_hashes` populates,
changes when a file changes, is stable when nothing changes, and is empty for
a directory with no matching files. Real temporary git repositories are used
throughout rather than mocked subprocess calls, since `git status --porcelain`
is exactly the ground truth this project has to trust. **Full suite: 433
passed.**

**Reversal condition.** None — this is infrastructure hardening, not a
scientific claim. `--allow-dirty` is the intentional escape hatch for
exploratory work (e.g. a future item-3-style diagnostic) and is not itself a
reversal of the rule; using it for anything confirmatory would be.

---

## D-37 Step 1 offline preflight: the stratum partitions reconciled; mode-A headroom is 7.1% (below the 15% floor) — reshapes Step 2

**Decided:** 2026-08-10. Full report: `reports/track_c_preflight.md`. Step 1
of the "Next steps — live GPU node" plan. **CPU-only, ~15 s, no GPU, no model
calls, no held-out instance touched.**

**1a — reconciliation, not a decision.** Two partitions of the same 150
`phase2b` instances had been quoted without stating they are different,
non-nested classifications: D-30's `evidence_state` scheme (82 unanimous /
53 substantive disagreement / 15 insufficient evidence, based on *how much
usable evidence exists*) versus a "91 unanimous / 51 split / 45
no-correct-trajectory" framing (based on *distinct-answer count* and
*outcome*, two further different axes). Recomputed directly and
cross-tabulated: the "91" figure is 82 genuine unanimous instances **plus 9
single-usable-trajectory instances** that trivially have "1 distinct answer"
but are not unanimity in any real sense (correctly classified into stratum A
by `evidence_state`); "51 split" is the 2-3-distinct-answer slice of stratum
B's full 53 (which also holds 2 four-way-disagreement instances); "45
no-correct-trajectory" is an orthogonal, outcome-based axis cutting across
all three strata, including **13 of the 82 true-unanimous instances**
(unanimously wrong). One canonical evidence_state × outcome table now exists
and is what every later step cites. **100% of recoverable headroom sits in
stratum B by construction** (`oracle == plurality` on every stratum-A and
unanimous row, asserted by test) — 0.093 [0.047, 0.140] overall, 0.264
[0.151, 0.377] on stratum B's 53 instances alone.

**1b — decisive, and it reshapes Step 2.** Mode-A eligibility (computable
from raw prompt data, no external lookup) was fixed *before* classification,
from one full prompt read per task (all 10, template-generated so one
template determines every instance of a task): **only `lab_bench_seqqa`
qualifies.** `screen_gene_retrieval` was the one case that could plausibly
have gone the other way from its name ("strongest perturbation effect")
and was resolved by reading the full prompt — no perturbation data is
supplied, only a research description and a candidate list, so it is not
mode-A like every other non-`seqqa` task. **Only 1 of stratum B's 53
instances is `lab_bench_seqqa`** — the task is already 86.7% accurate
(D-30 §9), so almost nothing is left to disagree about there. Mode-A
headroom share: **1.0 of 14.0 = 7.1%**, below the pre-registered 15% floor.
**Verdict, per the rule fixed before this number existed: "the
computational-verification route is not where the headroom is."** This
confirms, as a measured fact rather than a hunch, the reservation raised
before any of this work started: tasks with re-derivable structure are the
tasks that already work; tasks with headroom require external knowledge, not
computation.

**1c — replicates on both pools.** Degeneration (`consecutive_runaway`)
concentrates in the no-correct-trajectory bucket, not the split stratum, on
both `phase2b` (68.9% vs 27.3%, n=45/33) and `phase1_pooled` (33.3% vs
21.4%, n=18/14) — same direction, `phase1_pooled`'s gap smaller and its CIs
wide at this n. D-34's proposed pre-screening mitigation is **substantially,
though not completely, dissolved** as a bias concern: it would remove
instances with nothing to learn far more than it trims the target
population, but split-stratum instances are not immune (21-27% still
degenerate).

**Consequence for Step 2.** The two-arm adjudication design (one-shot vs.
tool-enabled) is unaffected in mechanics — it was never mode-A-specific.
What changes: the originally planned "computational vs. inferential"
task-family stratification is no longer a meaningful two-group split (one
mode-A instance total in stratum B); it is restated as
**evidence-retrievable-via-a-working-tool** (structured-database tasks, the
D-33-repaired/already-healthy route) versus **domain-judgment tasks with no
reliable retrieval route** (the tasks whose evidence needs D-33 already
found unmet). Step 2 is understood, before it runs, as principally a test of
evidence-based/inferential adjudication, not a mixed computational test.

**Tests.** `tests/test_track_c_preflight.py` (11): the exact reconciliation
point (a single usable trajectory is stratum A, not unanimity, though its
`distinct_usable` count is trivially 1); headroom is exactly zero whenever
oracle equals plurality and positive exactly when a wrong plurality misses a
present correct minority; the mode-A eligible set is pinned to exactly
`{lab_bench_seqqa}` so a future edit cannot silently widen or narrow it
without the test failing; every task has a written eligibility
justification, not a bare label. **Full suite: 444 passed.**

**Reversal condition.** None claimed — this is measurement and accounting,
not a policy choice. The mode-A eligibility classification is task-level and
fixed; revisiting it requires a new, explicitly-labelled classification pass
with its own justification, not a silent edit to `MODE_A_ELIGIBLE_TASKS`.

## D-38 Step 2 candidate-adjudication pilot: NO-GO — Step 4 not indicated, Step 5 remains gated

**Decided:** 2026-08-10. Full report: `reports/track_c_step2.md`. Step 2 of
the "Next steps — live GPU node" plan. Acceptance rule frozen before any
Arm-1/Arm-2 trajectory (floor 0.4103 / ceiling 0.6026 / gap 0.1923 on 78
pooled `B_substantive_disagreement` instances; GO if Δ's 95% CI lower bound
> 0, NO-GO if Δ's CI upper bound < gap/3 = 0.0641, else INCONCLUSIVE, where
Δ = Arm-2 majority reward − plurality floor, paired instance-clustered
bootstrap, 10,000 replicates).

**Design.** Two arms, 3 samples/instance/arm, majority-resolved (≥2-of-3
agreement), on candidates drawn only from already-completed, frozen
`phase2b`/`phase1_pooled` trajectories — zero held-out instances consumed.
Arm 1: one-shot, no tools (descriptive only). **Arm 2: the real Biomni A1
agent, adjudication-framed prompt, full tool access — the kill-shot arm.**
Arm 2 has strictly more information than a real VERIFY mode-A trajectory
ever could (D-32's `VerifyView` sees the task prompt and *one* candidate,
not the full disagreeing set), so it is a deliberate upper bound on what
VERIFY could achieve, not a lower bound.

**Result: NO-GO.** Arm 2 pooled (n=78): Δ = **−0.0769**, 95% CI **[−0.1923,
0.0385]** — the CI upper bound (0.0385) falls below the pre-registered NO-GO
bar (0.0641). The point estimate is negative: majority-resolved,
tool-enabled adjudication scores *worse* on average than plain plurality
voting on the trajectories already in hand. Replicates independently on
`phase1_pooled` alone (n=25, Δ = −0.16, CI [−0.32, −0.04], entirely
negative — a second, standalone NO-GO, not just a pooled artifact);
`phase2b` alone and both task-family cuts (evidence-retrievable vs.
domain-judgment, D-37-revised) are individually INCONCLUSIVE at n=38-53 but
point the same direction. Arm 1 (descriptive) is a clean NO-GO too (Δ =
−0.2179, CI [−0.3333, −0.1026]) — worse than Arm 2, consistent with the
rule's own framing that any recovery would require active tool work, not
passive re-selection, except that even the tool-enabled version recovers
nothing.

**Mechanism, from the same artifacts, not a post-hoc story.** Arm 2's low
mean reward is not "confidently wrong" — it is "frequently no answer at
all": 47.4% of instances (37/78) produce no majority-resolved answer (28
splits with no 2-of-3 agreement + 9 all-sample failures); 46.2% of instances
have at least one sample that answers *off-menu*, generalizing a single case
caught in Arm 2's pre-launch smoke test
(`crispr_delivery`/i0018 answered `'e'` against candidates `['c','f']` in
all 3 samples — genuinely `all_wrong`, so scoring was unaffected, but it
flagged a real instruction-compliance gap now confirmed systematic); a
**17.9% degeneration-failure rate** (`budget_terminated_consecutive_runaway`
× 42 + `dependency_failure` × 2 of 234 attempted, same
`model_context_overflow`/`budget_terminated` definition used throughout this
project) removes samples before majority resolution runs; and 96.2% of
instances show at least one *soft* runaway-generation event (survived, not
fatal — distinct from the 17.9% hard-failure rate), meaning this prompt
shape pushes the model into long-generation territory almost universally,
not just in the tail. D-33 retrieval-provenance field coverage is 59.8%
(presence-only check) — a majority of trajectories did engage the
instrumented retrieval path, so the null is not simply "the agent never used
a tool."

**Consequence.** Because Arm 2 is a deliberate upper bound on VERIFY mode-A
adjudication, this result licenses treating a NO-GO here as evidence against
the VERIFY mode-A/evidence-based-adjudication family generally, not only
against this pilot's specific framing — a real, more-constrained VERIFY
trajectory has no plausible path to succeeding where this idealized,
maximally-empowered version did not, on the same population, model, and
tooling. **Step 4 (K=2 characterization run) is not indicated** — the plan's
condition was GO or INCONCLUSIVE-leaning-GO, and this is a decisive
pooled NO-GO replicated independently on one of the two pools; per the
standing instruction, the GPU node is left idle rather than spending the
reserved ~120-instance pool on a characterization run whose premise this
pilot just falsified. **Step 5 (VERIFY implementation) remains gated** — this
finding is offered as evidence for that decision, not a substitute for the
user's separate, explicit approval, which was never conditioned on this
pilot's outcome.

**Tests.** `tests/test_track_c_adjudication_analyze.py` (11): majority
resolution requires genuine 2-of-3 agreement (a single surviving answer
after filtering failures is `no_majority`, not promoted to a majority);
GO/NO-GO/INCONCLUSIVE boundary cases against synthetic paired arrays; the
frozen `gap/3` constant is pinned against the acceptance rule's own
arithmetic so a future edit cannot silently move the NO-GO bar; the
task-family stratification is checked to partition all 10 BiomniEval1 tasks
with no overlap. Verified end-to-end against live data at two points: a
14-20/234 partial Arm-2 run (correctly reported INCOMPLETE, no verdict
computed) and the completed 234/234 run. Full suite: 455 passed.

**Reversal condition.** A materially different adjudication design (e.g. a
different prompt framing that measurably fixes the 46.2% off-menu rate, or a
non-reasoning/differently-tuned model less prone to the 96.2% soft-runaway
rate) could in principle be tested — but that is a new, separately-designed
pilot with its own frozen acceptance rule, not a reinterpretation of this
one. This result does not license lowering the NO-GO bar or re-reading the
pooled CI as "close enough."

---

## D-39 Amendment to D-38: the "upper bound" argument is retracted; the family-level NO-GO does not follow

**Decided:** 2026-08-11. **This is a labelled amendment, not an edit.** D-38
stands in place, unmodified, per the standing reversal rule fixed in D-32:
a revision to a frozen conclusion is always a new numbered entry, never a
silent rewrite of the old one. Readers of D-38 must read this entry with it.

### What is retracted

D-38 argued that Arm 2 — the real Biomni A1 agent, shown every disagreeing
candidate, adjudication-framed, full tool access — has *strictly more
information* than a `VerifyView`-constrained VERIFY trajectory (D-32), and
therefore **upper-bounds** what VERIFY could achieve; and that a NO-GO on Arm 2
consequently licenses a NO-GO against the evidence-based-adjudication **family**
rather than only against the pilot's specific design.

**The inference is invalid and is withdrawn.** Monotonicity of
value-of-information — more input can only help — holds for an optimal
decision-maker that can costlessly ignore inputs it does not need. **A fixed LLM
under a fixed prompt is not such a decision-maker.** Additional context changes
the prompt distribution the model is actually conditioned on, and can and here
does degrade behaviour. "Strictly more information" therefore does not order the
two designs by achievable performance, and no upper bound follows.

**This is not an abstract objection; it is instantiated in D-38's own data.**
The off-menu failure mode — 46.2% of instances had at least one sample answering
outside the candidate list — is *created by* the extra information. A
`VerifyView` trajectory, which never sees a candidate list, cannot produce an
off-menu answer at all: the failure category does not exist for it. The
supposedly-dominating arm has failure modes the constrained arm structurally
lacks, which is a direct counterexample to the claimed ordering.

The remaining interface evidence points the same way, and was already reported
in `reports/track_c_step2.md` §4 before this retraction: **96.2%** of instances
showed at least one runaway generation event, **47.4%** produced no 2-of-3
majority at all, and the report's own summary of the mechanism was *"not
confidently wrong but frequently no answer."* Taken together that describes an
**operationally unstable elicitation regime**, not a demonstrated inability to
verify. D-38 read the same numbers as mechanism detail supporting a general
conclusion; they are better read as evidence that the measurement instrument was
unstable, which is precisely the condition under which a null is uninformative
about the underlying capability.

### What is *not* retracted

* **D-38's empirical result stands, unchanged and unreinterpreted.** Arm 2
  scored Δ = **−0.0769**, 95% CI **[−0.1923, 0.0385]** against the frozen
  plurality floor, a NO-GO under the acceptance rule frozen before the first
  trajectory. Arm 1 stands at Δ = −0.2179, CI [−0.3333, −0.1026]. The
  `phase1_pooled` replication stands. No number moves, and no bar moves.
* **The scope of the claim is what changes.** The surviving claim, which
  becomes the manuscript's claim, is exactly this and no more:
  **free-form, same-model, tool-enabled candidate adjudication failed under a
  maximally-informed but operationally unstable regime.** Every qualifier in
  that sentence is load-bearing — free-form (not structured-output),
  same-model (verifier and generator are one checkpoint, so their errors are
  correlated by construction), and operationally unstable (the interface
  metrics above).
* **Step 5 (`VerifyView` mode-A implementation) remains cancelled**, and this
  retraction does not revive it. It is cancelled on **independent** evidence:
  D-37 measured mode-A-eligible headroom at **7.1%** of stratum B's total,
  below the pre-registered 15% floor, because only `lab_bench_seqqa` qualifies
  as mode-A and only 1 of 53 stratum-B instances is that task. That finding is
  a property of the benchmark's task structure and is untouched by anything
  argued here.

### What this changes downstream

The manuscript may no longer claim that verification-by-adjudication is closed
off as a family. `reports/track_c_step2.md` §5 and the write-up draft's Track-C
section both carried the retracted framing and are corrected in the same batch
of work as this entry (Stage 0.3).

The **K=2 characterization run** is still not performed — but its justification
is now scope, not this argument. It is excluded by the current plan, not
licensed away by a family-level NO-GO that no longer stands.

**Stage C** exists precisely because of this retraction: it removes the two
confounds named above — same-model and unstable-interface — and re-asks the
question under conditions where a null would be interpretable. Its stop rule
(`reports/stage_c_stop_rule.md`) was committed **before** this entry and before
any Stage A number existed, so the retraction cannot be read as clearing ground
for an open-ended search.

### How the error arose, recorded because the class matters

The argument had the shape of a proof — "strictly more information, therefore an
upper bound" — and proof-shaped reasoning received less scrutiny than a
measurement would have. The premise needed for the conclusion (an
information-monotone decision-maker) was never stated, and would have been
visibly false if it had been. The general lesson matches D-27's: a step that
*looks* like it cannot be wrong is exactly the step that gets checked least,
and this project's own instrumentation had already recorded the disconfirming
evidence before the claim was made.

**Reversal condition.** None applies to the retraction itself — an invalid
inference does not become valid on further evidence. The *empirical* question
it over-claimed on is reopened, and is what Stage C tests, under that file's
frozen stop rule.

---

## D-40 Stage A decomposition: the adjudication null survives, its scope narrows, and "30% unreachable" is a loose upper bound

**Decided:** 2026-08-11. Full report: `reports/stage_a_decomposition.md`.
Drivers `scripts/stage_a_decomposition.py` (A.1-A.4) and
`scripts/stage_a_label_triage.py` (A.5). **CPU only, no GPU, no model calls, no
new instances, no LLM used to adjudicate any label.** Interpretation rules for
every analysis were written into each script's docstring before the
corresponding numbers existed, and `reports/stage_c_stop_rule.md` was committed
(`63c179b`) before this work began — so none of the below could be, or was,
used to soften a Stage C stop that was already fixed.

**A.1 — the adjudication null is not an aggregation artifact.** No alternative
aggregation of Arm 2's own samples is materially above the plurality floor:
dropping the 2-of-3 requirement entirely buys **+0.013 [−0.090, +0.115]**, and
**Oracle@3 over Arm 2's own three answers reaches only 0.513** against the
candidate pool's own oracle ceiling of 0.6026. Arm 2's answer set is *worse*
than the set it was asked to adjudicate, so no aggregation rule could have
rescued it. D-38's verdict is not re-litigated and no verdict is recomputed
against any alternative aggregation — these are mechanism analyses only.

**A.2 — D-39's retraction now has quantitative content.** `Δ = (capture −
harm)/n` reconciles exactly for every selector (asserted by test over 200
randomised cases). Arm 2: capture 7, harm 13, and **69.2% of that harm is
interface harm** (`no_majority` 7, `off_menu` 1, `trajectory_failure` 1) against
only **4** `wrong_in_menu` — above the 50% bar fixed in advance, so the
pre-registered reading is that the null is substantially an elicitation failure
rather than a demonstrated inability to judge. The tempting counterfactual
(7 captured vs 4 judgment-harmed ⇒ an interface-perfect adjudicator is net
positive) is stated as Stage C's motivation and explicitly **not** claimed: it
assumes interface-harmed instances would revert to their plurality outcome,
which is untested.

**A.2, independently — the controller captured nothing.** Against fixed K=4 the
Phase-2B controller has **capture = 0** across all 150 prospective instances: it
never once converted a fixed-K=4 error into a correct answer, and its entire
difference is harm. This is a strictly stronger statement of the Phase-2B
failure than the headline −0.033.

**A.3 — the selectivity belongs to the agreement signal.** At matched coverage,
agreement-thresholded fixed K=4 matches or beats the controller everywhere
comparable (0.895 at coverage 0.507 vs 0.877 at 0.433; 0.719 vs 0.711 at an
identical 0.807), and on the overlapping coverage domain its AURC is better
(0.058 vs 0.075). Per the rule fixed in advance, **selectivity is attributed to
the agreement signal, not to the controller**, and any selective-prediction
claim in the manuscript must be stated that way. Sharpest form: at a 5% or 10%
error budget the controller reaches **zero** coverage while agreement counting
reaches 30.7% at 2.2% error. *(Raw full-domain AURC inverts this and is not
reported: the controller's reachable coverage is a strict subset of fixed
K=4's, so the integrals are over different domains.)*

**A.4 — no usable separating signal in cheap traces.** Seven instrumented trace
features, instance-clustered AUROC on the 53 disagreement instances. The
pre-registered rule is technically triggered by `total_output_tokens`
(CI [0.300, 0.4998]) — by **0.0002**, in the negative direction (longer is
worse, a degeneration proxy), and it does not survive Bonferroni adjustment for
the seven tests. That adjustment was added **after** seeing the nominal result
and is labelled post hoc; the mechanical verdict string is reported unchanged
rather than restated to fit it. Substantive reading: no usable separating
signal. Per the stop rule §8 this *interprets* a future Stage C null and never
reverses it.

**A.5 — "30% unreachable" is an upper bound on a generation limitation, and a
loose one.** The enumeration problem governs this analysis: on 9 of 10 tasks the
prompt supplies a candidate list containing the correct answer (35 of the 45
instances), so a bare "mentioned" test is near-vacuous. Three measures:
`never_mentioned` **7/45**; `mentioned` 38/45 (an upper bound, contaminated);
and the enumeration-robust **`singled_out` — mentioned more often than the
average wrong candidate — at 18 of 35 assessable instances (51%)**. On half the
assessable no-correct instances the model discussed the correct answer
preferentially and committed something else. Separately, **3 instances are
genuine extraction failures** (a trajectory with no parseable answer whose own
solution block commits the correct one; verified by reading the text, clearest
at `gwas_causal_gene_gwas_catalog/492`, *"Most likely causal gene: LONP1"*
parsing to `NaN`). A looser count of 14 is reported but **not** claimed, because
solution blocks are long prose reports that discuss several candidates while
committing one.

**A.5a returned 0 scoring artifacts**, and only after a test caught that the
normaliser was weaker than intended — a single strip pass leaves `'BRCA1'.` as
`BRCA1'` and would have let a real artifact through. Gene-symbol synonymy is
**NOT DONE** (no offline alias table; a guessed list would manufacture the
corrections it is meant to detect) and is the one place the artifact count could
still be an undercount. **A.5c** finds 44 of the 45 on tasks requiring external
knowledge and 1 on the only structurally determinate task (`lab_bench_seqqa`),
independently reproducing D-37's mode-A finding; the two are pinned to each
other by test.

**Corrected scoring.** Official and audit-corrected differ only by the 3
extraction failures — `singled_out` is deliberately not used to re-score
anything, since considering an answer is not producing it. No-correct 45 → 42
(30.0% → 28.0%); Oracle@4 0.700 → 0.720; selection headroom **0.093 → 0.113**.

**Two bugs found and fixed during this work, recorded because both would have
manufactured favourable results.** (a) The `screen_gene_retrieval` candidate
regex matched the prose instruction ("From the following list of candidate
genes, select ...") instead of the `Candidate genes:` line, yielding two garbage
candidates and making `singled_out` vacuously true for all 11 of that task's
instances; the pooled figure fell from 24 to 18 once fixed. (b) `analysis.
grouped_bootstrap` rebuilds a DataFrame per replicate and made the script
unrunnable; replaced with a vectorised instance-clustered bootstrap using the
identical resampling scheme.

**Not done, and not delegated.** Stale-label checks, incorrect-label
adjudication and multiple-defensible-answer judgments need domain reviewers,
who are unavailable. They are not approximated and **not handed to an LLM**.
Some unknown share of the remaining 42 may be label problems; this audit cannot
distinguish them, and the manuscript says so.

**Tests.** `tests/test_stage_a.py` (15): the capture/harm identity over 200
randomised cases and the four-cell partition; the screen_gene_retrieval regex
bug pinned directly; equal enumeration must NOT read as `singled_out` while
preferential discussion must; token-boundary matching (`IL5` must not match
inside `IL5RA`); `<observation>` stripping; normalisation equivalence including
the quote-then-period case that the weak normaliser missed; and every task
carrying a real written determinacy justification rather than a label.
**Full suite: 474 passed.**

**Reversal condition.** A.1, A.2 and A.3 are accounting over frozen artifacts
and are not reversible by argument. A.5b's `singled_out` measure is a proxy for
"the answer was distinguished in reasoning" and would be superseded by a
domain-reviewer audit of the same instances, which is the stated missing piece —
not by a differently-tuned string heuristic.

---

## D-41 Pre-commit shrink guard: the third instance of tooling silently discarding work

**Decided:** 2026-08-11. Hook: `scripts/git_hooks/pre-commit`. Tests:
`tests/test_shrink_guard.py` (7). **No GPU, no analysis, no frozen artifact
touched.**

**The pattern, which is the point of this entry.** Three separate incidents in
this project share a shape — a routine action silently destroying or hiding
something, with no signal that anything was wrong:

* **D-27** — a monitoring gate compared `failure_class` for exact equality
  against a string the runner never emitted, and so reported 0.0% residual
  degeneration in every run it ever checked, including two that were above the
  pre-registered halt threshold.
* **D-29** — the controller under prospective test was untracked in git at run
  time, so no commit could honestly be cited as having produced the result.
* **2026-08-11 (this entry)** — `DECISIONS.md`, 1585 lines and the project's
  entire decision record, was reduced to the single character `w` in the working
  tree by an editor mishap. `git add -A && git commit` was one keystroke from
  committing the loss. It was caught only because `git status` was read before
  staging, and recovered with `git restore` since HEAD was intact.

Individually these are three anecdotes. Together they are a pattern worth
stating in the manuscript's reproducibility section: **the failure mode that
actually threatens this kind of work is not a wrong number, it is a silent
one.**

**Decision.** A pre-commit hook refuses any commit in which a **tracked** file
shrinks to under **10%** of its committed size (floor configurable via
`BIOMNI_SHRINK_FLOOR_PCT`; files under 200 bytes are ignored, since the
percentage is meaningless there). Installed with
`git config core.hooksPath scripts/git_hooks`.

**The override is explicit and logged, never silent:**
`BIOMNI_ALLOW_SHRINK=1 git commit ...` proceeds, writes a timestamped record of
what shrank to `.git/shrink_guard.log`, and prints a warning to stderr. A guard
that can be bypassed without leaving a trace is not meaningfully different from
no guard.

**Deliberately NOT flagged**, because a guard that cries wolf gets disabled and
then protects nothing: newly-added files (no committed size to shrink from),
deliberate deletions (`git rm` is not this failure mode, and conflating them
would train people to keep the override on), and files below the byte floor.
A 50% deletion is a large edit, not a wipe, and is allowed.

**The failure path is exercised, per D-27's lesson.** The 7 tests drive the
real hook through real `git commit` invocations in temporary repositories — no
mocking of git, because the commit's exit status is the behaviour being relied
on. They cover the motivating case (4000 bytes → 1 character, refused),
ordinary edits, a 50% deletion, the override and its log record, new files,
deliberate deletions, and the byte floor. **Verified live in this repository as
well**: a real tracked file was truncated to one byte, `git commit` was refused
with a non-zero exit and a correct diagnostic, and the file was restored intact
with nothing committed.

**Reversal condition.** None claimed — this is infrastructure hardening, not a
scientific claim. If the 10% floor proves to cry wolf in practice it should be
tuned via `BIOMNI_SHRINK_FLOOR_PCT` rather than removed, since a guard people
disable is strictly worse than a slightly noisy one.

---

## D-42 Pre-Stage-C items: A.6 NULL, A.7 reachability pre-registered, A.8 shows the arm was re-solving, and A.5b's 51% becomes a band

**Decided:** 2026-08-11. Reports: `reports/stage_a_decomposition.md` (addenda),
`reports/a6_decision_rule.md`, `reports/stage_c_stop_rule.md` Amendment 1,
`reports/a5b_review_sheet.md`. **CPU only, no GPU, no model calls.** The two
blocking items (A.6, A.7) are complete, so Stage C is unblocked.

**A.6 — semantic discriminability probe: NULL.** Decision rule frozen and
committed (`2051a7f`) before any AUROC or feature value existed, fixing the
feature family, the primary feature and the Bonferroni correction in advance —
the failure mode A.4 exhibited. The **leakage barrier** is the load-bearing
part: A.5b's `singled_out` takes ground truth as an *input*, which is valid for
an audit and invalid for a feature a capsule computes at inference time. It is
reformulated label-free as how preferentially a trajectory discusses **its own
committed answer**, enforced structurally (a three-argument extraction
signature, forbidden columns dropped before extraction, label re-attached only
as the AUROC target) and asserted by a test that feature values are
**invariant under permuting the labels**.

Result on 263 usable trajectories across the 78: the primary feature
`own_answer_share` scores **AUROC 0.504**, corrected CI [0.313, 0.670] — chance.
`hedging_near_answer` clears the *nominal* bar (inverse direction) and dies
under the pre-declared correction, so it is multiplicity noise by a rule fixed
in advance rather than by argument afterwards.

**The finding that matters: `singled_out` carried A.5b only because it was
handed the correct answer.** Its label-free analogue carries nothing. A Stage C
capsule cannot expose this signal because at inference time the signal does not
exist. A.4's null now extends across both the structural and the semantic
feature classes, so a Stage C NO-GO is attributable to the traces on positive
evidence rather than by elimination.

**A.7 — 31 of the 78 (39.7%) are unreachable by construction**, defined without
heuristics as *oracle over committed candidates == 0*: no verifier scoring
committed candidates can reach them, yet they occupy denominator slots. Both
denominators are now pre-registered in the stop rule as **Amendment 1**, before
Stage C runs: **primary unchanged** (all 78, bar 0.0641, still decides the
verdict) and **secondary** (reachable subset n=47, floor 0.6809, ceiling 1.0,
bar 0.1064) which decides nothing and exists only so a null on the full 78 can
be read correctly. Declared in advance this is a limitation; discovered
afterwards it would read as a denominator chosen to fit.

**Correction to the framing the item was requested under:** the flagged set is
**18, not 21** — the 3 extraction failures are a strict *subset* of the 18
singled-out, not disjoint from them. 6 of the 18 lie inside the frozen 78 and
all 6 are unreachable.

**A.8 — matched-K oracle, and a stronger basis for D-39.** A.1 compared Arm 2's
Oracle@3 against the pool's Oracle@**4**. Recomputed at matched K *and* matched
population (the 67 instances with ≥3 usable trajectories, since Oracle@3 is
undefined below that — correcting the same denominator error A.7 exists to
avoid): pool **0.6455** vs Arm 2 **0.5522**, difference **−0.093**. The gap
survives matching at its original magnitude, and licenses a cleaner claim than
information monotonicity: **selection from a set cannot produce something worse
than the set's best element**, so Arm 2 was **re-solving the task, not
adjudicating between the candidates**. That is a structural fact about the
outputs rather than an argument about decision-makers, and it is now the primary
support for D-39's retraction.

**A.5b's 51% becomes a band — post hoc, and it matters.** *Computed after seeing
the A.5b result and labelled post hoc.* The `singled_out` threshold is a ratio
strictly above 1.0, and that boundary carries real weight: 18 instances at
ratio > 1.0, but 13 at ≥ 1.1, 11 at ≥ 1.25, 8 at ≥ 1.5 and **7 at ≥ 2.0**.
**Five of the 18 sit within 10% of parity** — `screen_gene_retrieval/160` at
62 vs 60.5, `crispr_delivery/7` at 15 vs 14.6 — where the measure cannot
distinguish preferential discussion from option-by-option enumeration, the very
artifact it was built to exclude. The claim is therefore restated as a band,
**20%–51%**, with the qualitative conclusion holding across all of it and the
precise fraction claimed nowhere.

**Operator review sheet generated, not adjudicated.**
`reports/a5b_review_sheet.md` puts all 18 in front of the operator with ground
truth, committed answers, automated counts and excerpts, and blank verdict
fields. This is a **reading-comprehension** check, not a domain judgment, so it
does not fall under A.5's deferred reviewer categories. **This project did not
adjudicate it**; the agreement rate is computed and reported only when the
completed sheet comes back, and the 51%/band figure is corrected or withdrawn
accordingly.

**Manuscript changes made on the back of the above.** `capture = 0` replaces
−0.033 as the controller's headline, with a methods paragraph arguing that
Δ ≈ 0 is ambiguous between "changes nothing" and "captures as much as it
harms" and that capture/harm therefore belongs alongside Δ in any selector
comparison. The S1 safety claim is **dropped entirely** rather than weakened,
since with capture = 0 the controller has no positive contribution at any
coverage. A.3's attribution result becomes the abstract's positive claim.
A.5b's two claims are split by provenance in §3: the singled-out band is a
generation-and-commitment claim whose instances remain **unreachable by any
selector**, while only the 3 extraction failures move any score
(30.0%→28.0%, headroom 0.093→0.113).

**Tests.** `tests/test_stage_a6.py` (14), including the label-permutation
invariance check and pins on the frozen family/primary/correction constants.
**Full suite: 495 passed.**

**Reversal condition.** A.6's null and A.8's matched-K gap are accounting over
frozen artifacts and are not reversible by argument. A.5b's band is explicitly
provisional pending the operator review sheet, which is the one outstanding
input.

---

## D-43 Stage C verdict: NO-GO (C2) and INCONCLUSIVE (C1) — the experimental program ends

**Decided:** 2026-08-12. Reports: `reports/stage_c_stop_rule.md` (Amendments
1–2), `reports/stage_c_preregistration.md` (+ ADDENDUM 1), `reports/tables/
stage_c/stage_c_verdict_{c1,c2}.json`, `reports/tables/stage_c/
stage_c_report_{c1,c2}.json`. Driver: `scripts/stage_c_run.py` +
`scripts/stage_c_analyze.py` + `scripts/stage_c_report.py`. Frozen 78
`B_substantive_disagreement` instances, zero held-out consumed, zero new
Biomni trajectories generated.

> **Headline.** Neither cell clears the pre-registered bar. C2 (same-model
> interface control) is a decisive **NO-GO**: Δ = −0.0641, 95% CI
> [−0.1667, 0.0384], upper bound below the 0.0641 bar. C1 (cross-family
> primary) is **INCONCLUSIVE**: Δ ≈ 0.0000, 95% CI [−0.1154, 0.1025] — neither
> harmful nor recovering headroom. Per the stop rule's §6, **both outcomes
> independently end the experimental program.** This is not a close call
> requiring judgment; two frozen thresholds both land on stop.

### 1. Primary verdict, both cells, computed once

| | C1 `gemma-4-31B-it` (cross-family) | C2 `Biomni-R0-32B` (same-model) |
| --- | ---: | ---: |
| n | 78 | 78 |
| validity (1 − comparison error rate) | 1.0000 | 1.0000 |
| unresolved ties | 0 | 0 |
| selector mean reward | 0.4103 (32/78) | 0.3462 (27/78) |
| plurality floor (frozen) | 0.4103 | 0.4103 |
| **Δ** | **−0.0000** | **−0.0641** |
| 95% CI | [−0.1154, 0.1025] | [−0.1667, 0.0384] |
| NO-GO bar (gap/3) | 0.0641 | 0.0641 |
| **verdict** | **INCONCLUSIVE** | **NO-GO** |
| secondary, reachable-47, Δ | −0.0000, CI [−0.1277, 0.1276] vs bar 0.1064 | −0.1064, CI [−0.2554, 0.0212] vs bar 0.1064 |

Secondary decides nothing on either cell, exactly as Amendment 1 specifies.
C1's selector mean landing at exactly 32/78 = 0.410256... is a coincidence of
integer counts against the frozen floor's own 0.4103, not identity by
construction — the locally-computed descriptive-plurality baseline used for
the capture/harm decomposition (§3 below) differs materially (mean 0.2949),
confirming C1's selections are not simply reproducing plurality.

**GO was structurally unreachable for both cells**: GO requires the CI lower
bound to exceed 0, and neither cell's does (C1 −0.1154, C2 −0.1667), independent
of the validity and task-heterogeneity conditions.

### 2. Two bugs caught and fixed before either number existed

Both are recorded because the class matters, and because neither touched a
result that had already been seen:

* **Reward-lookup/candidate-construction divergence** (`9905804`).
  `stage_c_analyze.py`'s reward lookup duplicated `stage_c_run.py`'s pool
  filter and got it wrong — restricting **both** pools to
  `condition == "instrumented"`, where `stage_c_run.py` correctly leaves
  `phase2b` unfiltered (D-37's shadow trajectories are part of the frozen
  candidate sets). Crashed on the very first `stage_c_analyze.py` invocation
  (`no reward for candidates ['c']` on `crispr_delivery/18`) — a crash, not a
  silently wrong number. Fixed by factoring the trajectory-table construction
  into `scripts/stage_c_population.py`, one source of truth both scripts
  import.
* **Bash brace-parsing bug in the batch launcher** (`1386f23`), caught at
  server-startup, before any comparison was scored:
  `"${C2_OVERRIDE:-{...}}"`'s default value contained JSON braces, and bash
  ended the parameter expansion at the first balancing brace, silently
  swallowing the one closing `rope_scaling`. `max_position_embeddings` landed
  *inside* `rope_scaling` instead of at the top level, the D-04 context
  override never applied, and SGLang refused the requested 65536 context.
  Fixed with a plain single-quoted assignment plus a launch-time JSON
  validation step that asserts a top-level `max_position_embeddings` before
  any server starts.

Neither bug reached a scored comparison; both are infrastructure defects
caught by the discipline the project already has (fail loudly, fix forward,
never silently retry into a plausible-looking wrong number).

### 3. Mechanism / secondary findings — §9, reported after the verdict, decides nothing

| | C1 | C2 |
| --- | ---: | ---: |
| capture / harm (local descriptive plurality baseline) | 15 / 6 | 16 / 12 |
| harm breakdown | 6 wrong-in-menu, 0 tie, 0 unreachable | 12 wrong-in-menu, 0 tie, 0 unreachable |
| candidate-ranking AUROC | **0.6345** (177 candidates, 53 correct) | **0.5218** (near chance) |
| intransitivity rate (n=19 eligible, N≥3 only) | **1/19 = 5.3%** | **10/19 = 52.6%** |
| risk-coverage AURC | 0.4762 | 0.6130 |
| PPT secondary (re-aggregation, decides nothing) | Δ = +0.0384 (still under bar) | Δ = −0.0641 (identical to round-robin) |
| unconstrained on-scale mass (this run's endpoints) | 0.99999996 | 0.6299 |

**Harm is 0% interface-attributable for both cells** — zero unresolved ties,
zero comparison errors — which is exactly the condition Stage C was built to
produce and did: whatever separates the two cells here, it is not elicitation
instability.

**C2's intransitivity rate (52.6%) is the sharpest single finding in this
table.** A verifier that flips its own pairwise preference into a cycle on
more than half of the instances where a cycle is even possible is not
producing a coherent ranking, and this is measurable without touching a
reward. It is consistent with — and likely explains much of — C2's low
unconstrained on-scale mass (0.630): a noisier underlying score distribution
produces less transitive pairwise comparisons. C1's 5.3% rate is close to
what a coherent ranker should show.

### 4. Reading through the pre-registered addenda (Amendment 2 / ADDENDUM 1)

**A1.1 — the family-neutral capability anchor.** Gate 1's C1−C2 margin was
**69.5 pp** of oracle headroom recovered on MedAgentBench, where family was
held constant (neither cell is Claude Opus 4.8, the generating model). Here,
in the same units (fraction of the gap recovered): C1 ≈ 0.0%, C2 ≈ −33.4%, a
margin of **≈33.3 pp** — **materially smaller** than the 69.5 pp anchor, not
comparable to it and not larger. Per A1.1's pre-registered third branch, this
leans toward the direction the General AgentBench self-trace hypothesis
predicts (a model judging its own execution traces somewhat better than pure
capability difference alone would predict) — **stated only as that**, bounded
exactly as pre-registered: it rests on an assumption (verifier capability
ranking is stable between mechanically-checkable and judgment tasks) that this
very result gives some reason to doubt, since the margin compressed. It does
not change either verdict, and no numeric threshold was ever attached to this
reading, by design.

**A1.2 — the C2 asymmetry, applied.** C2's NO-GO is **ambiguous**, exactly as
pre-registered: gate 1 already showed C2 recovers only 23.6% of headroom on a
clean, mechanically-checkable corpus with zero interface error, so this NO-GO
is not distinguishable from "this checkpoint is a weak verifier generally" —
it does **not** license concluding that D-39's retraction was wrong. C1's
result is the more informative one for that question: cross-family **and**
demonstrably strong on gate 1 **and** zero interface error, and it still lands
at Δ ≈ 0, not positive. D-39's retraction is not undone by this — the
retraction was about an invalid *inference* (information monotonicity), which
remains invalid regardless — but the empirical question the retraction
reopened is now answered for this population: removing both confounds named in
D-39 does not recover headroom.

### 5. Interpretation, against the table fixed in the preregistration §10

The best-supported row: **"all cells fail, and A.4/A.6 found trace features at
AUROC ≈ 0.5 → supports a broader trajectory-verification gap: the traces, not
the verifier."** A.4 and A.6 already found no separating signal in cheap
structural or semantic trace features. C1 — cross-family, strong on an
independent benchmark, zero interface error, scoring the **full** rich capsule
rather than a cheap feature — still does not clear the bar, though it does not
harm either (its 177-candidate AUROC of 0.6345 shows *some* signal, just not
enough to consistently outrank plurality at the instance level). Taken
together this triangulates toward the candidate pool itself carrying limited
separating signal for this judgment task, largely independent of verifier
capability (C1 proved itself capable elsewhere) or interface stability (both
cells: 0% comparison-error rate).

**Task heterogeneity, descriptive only, not decision-relevant** (GO was
already foreclosed by both CIs): `gwas_causal_gene_gwas_catalog` was the
weakest task for both cells (0.10 accuracy, n=10, the largest single-task
subgroup); `lab_bench_dbqa` the strongest for both (0.875 / 0.75, n=8).

### 6. Stop semantics — applied exactly, per §6 of the stop rule

**The experimental program ends.** Stage C ran once, per cell, as specified.
No verifier model beyond the two pre-registered cells. No prompt or criteria
search. No debate/persona/ensemble variants. No re-aggregation shopping — PPT
is reported above as mechanism analysis and was never substituted into either
verdict. No bar movement — both bars (0.0641, 0.1064) are exactly as frozen.
No temperature/diversity variants. No expansion to another benchmark.

**The manuscript ships with Stage C as a bounded negative result**, per §6's
table: C2's NO-GO and C1's INCONCLUSIVE, read through Amendment 2's
family-neutral anchor and asymmetry pre-registrations, converging on the
traces-not-the-verifier reading already supported by A.4/A.6.

### 7. What does not follow from this entry

* No fourth cell, no capability-ceiling cell, no re-run at a different K or
  granularity.
* The deferred capability covariate (§8 of the preregistration, 156 K=1
  Biomni trajectories) remains **deferred**. It was scheduling, not a
  finding, before this verdict, and this verdict does not change that — the
  program has already ended per §6, so there is no longer a pending
  conditioning question for it to resolve. It is not launched.
* D-38's empirical result and D-39's retraction both stand, unchanged. What
  changes is that the empirical question D-39 reopened is now closed by this
  entry, not left open pending Stage C.

**Reversal condition.** None applies to the stop itself — per §6, NO-GO and
INCONCLUSIVE both end the program by construction, and that is not reversible
by further analysis of this data. A future *separately pre-registered* study
on a different population or with different verifiers is not a reversal of
this entry; it would be new work, subject to its own north-star check.

---

## D-44 Scope study opened as separate work; Solver B1 PASSES its frozen capability gate

**Decided:** 2026-08-13. Design: `reports/scope_study_preflight.md` (§§0–9
frozen at `e40c773` before inference; results appended after). Drivers:
`scripts/scope_pool_audit.py`, `scripts/prepare_scope_gate_manifest.py`,
`scripts/scope_gate_analyze.py`, `scripts/scope_gate_paired.py`. Tests:
`tests/test_scope_gate.py` (29). Artifacts: `reports/tables/scope_study/`.

> **Headline.** A new, separately pre-registered **scope-and-boundary study** is
> opened. **D-43 is untouched** — no cell, no bar, no artifact, and a disjoint
> population. Tonight was preflight plus one GPU gate. `mistralai/
> Mistral-Small-3.1-24B-Instruct-2503` **PASSES** and is frozen as Solver B; it
> operates the Biomni scaffold *better* than Biomni-R0 does (completion 0.958 vs
> 0.917, usable 0.917 vs 0.833, degeneration 0.042 vs 0.083, `<solution>` block
> well-formed on every completed run) at **2.9× lower cost**. **Zero fresh
> scope-study instances were consumed.** B2 was not run: the frozen rule reaches
> it only through FAIL.

### 1. Why this is not a Stage-C rescue

D-43's own reversal condition anticipates it: *"a future separately
pre-registered study on a different population or with different verifiers is
not a reversal of this entry."* This study takes a **different population** (the
never-used pool, disjoint from Stage C's frozen 78), a **different primary
question** (does the reliability-detection / error-correction separation
replicate across solver families?), and adds a **second solver**, which is the
one axis Stage C held fixed. Nothing recomputes, rescues or reinterprets D-43.

### 2. The reserved pool is 220, not 233 — a correction to the record

D-22 and `reports/phase2_protocol.md` §3.1 both record 233 reserved
(433 − 50 − 150). Reconstructed from artifacts rather than prose — the parquet,
every manifest, and every run directory on disk — the true figure is **220**.
Thirteen instances were consumed after those documents were written by two runs
that never wrote a manifest: `verify_prereq_diag3` (8, D-34's deliberately fresh
unscreened sample) and `phase2b_smoke` (5). Neither was a scientific error; the
bookkeeping simply was never decremented. **Any future document citing 233 is
citing a stale number**, and the scope study's exclusion set is the full
213-instance consumed set.

`crispr_delivery` and `rare_disease_diagnosis` are **confirmed exhausted** (0
each), exactly as D-22 declared it would spend them. Eight families remain, and
a 15 × 8 = 120 design is feasible with 100 instances to spare.

### 3. The rubric is frozen, and its confound is stated rather than smoothed

Three tiers assigned from the task definition and the official `_compute_reward`
criterion only: Tier 1 `lab_bench_seqqa`; Tier 2 six families; Tier 3
`screen_gene_retrieval`. **Task identity and tier are fully confounded at both
extremes** — each singleton tier is one family, so a Tier-1-vs-Tier-3 contrast is
numerically identical to a two-task contrast. The secondary analysis therefore
cannot support "verifiability causes recovery" and is not permitted to; it stays
secondary, no monotonic law is pre-registered, and MedAgentBench remains an
external anchor rather than a fourth point in a within-Biomni fit.

The ordering is disclosed because it matters: tiers were fixed before any
per-task accuracy was computed, and the per-task numbers computed afterwards are
*suggestive* of the hypothesis (Tier 1 at 0.867, Tier 3 at 0.067). That is
exactly why the rubric is not revised in light of them.

### 4. Solver B1/B2, and a confound surfaced before it could bite

The obvious B1 was the already-served `gemma-4-31B-it`. It was rejected on a
design ground the brief did not anticipate: the study fixes the verifier at the
frozen Stage-C C1 `gemma-4-31B-it`, so a gemma Solver B would be **same-model**
with the verifier where Solver A is **cross-family** — confounding solver family
with solver–verifier relatedness on precisely the axis D-43 measured as large
(candidate-ranking AUROC 0.6345 vs 0.5218; intransitivity 5.3% vs 52.6%). Put to
the operator, who chose the three-family design.

**B1 = `mistralai/Mistral-Small-3.1-24B-Instruct-2503` @ `68faf511…`;
B2 = `google/gemma-4-31B-it` @ `842da379…`. No B3.** Selected on family
independence, availability, ungated reproducibility, servability on the pinned
SGLang 0.5.16 without a stack change, context feasibility and resource fit —
never on accuracy, which did not exist for either candidate at freeze time. The
newer Mistral-Small-3.2 was downloaded and rejected on inspection: it ships only
a Mistral-format tokenizer and SGLang 0.5.16 has no `mistral` tokenizer mode.

### 5. The gate: PASS, with the accuracy gap stated honestly

24 already-consumed Phase-2B instances, 3 per family, selected label-free by
keyed hash, with two fatal guards asserting no never-used instance is touched.
24 executed in 735 s from commit `e40c773`, clean tree, 61 source hashes per
trajectory, **no interface repair used**.

| | B1 | Solver A (same 24) |
| --- | ---: | ---: |
| completion | **0.9583** | 0.9167 |
| usable answer | **0.9167** | 0.8333 |
| `solution_block_ok` | **1.0000** | 1.0000 |
| degeneration | **0.0417** | 0.0833 |
| infrastructure failure | **0.0000** | 0.0000 |
| accuracy | 0.3750 | 0.5833 |
| mean wall seconds | **106.5** | 309.7 |

**No FAIL and no CAPABILITY-CONFOUNDED condition is met → PASS.**

**The accuracy gap is not established at this n, and is not claimed.** Paired on
the same 24 instances: difference **−0.2083, 95% CI [−0.4583, +0.0417]** (10,000
instance-clustered replicates), exact McNemar on 11 discordant pairs
**p = 0.2266**. The gate can establish that B1 is not a floor-effect solver —
which is what it was built to decide — and cannot establish that it is weaker.
§6.4's interpretation rule still binds: if the matched study shows Solver B
materially weaker, that must be labelled, and normalized headroom recovery does
not cure it.

**A positive control on the bars:** Solver A's own K=1 trajectories on the same
24 instances were run through the same adjudicator and also return PASS. A gate
whose bars excluded the reference solver would be miscalibrated in the direction
that matters most.

### 6. What this does not license

* **B2 was not run and must not be**, unless a *future* candidate meets the
  frozen FAIL criterion. B1 passing closes the fallback branch.
* **No fresh scope-study manifest exists.** Spending 120 of the 220 never-used
  instances is an operator decision, and the main study needs its own
  pre-registration — hypotheses, bars and stopping semantics frozen and committed
  before its first trajectory, exactly as tonight's design was.
* The gate's per-task cells hold **three instances**. Nothing in them supports a
  per-task or per-tier claim, and in particular they are not a preview of the
  verifiability secondary.
* The 24-instance cross-solver error structure (6 both / 3 B1-only / 8 A-only /
  7 neither) is reported only to show the matched comparison is **not
  degenerate**. It is not a finding.

**Reversal condition.** B1's freeze as Solver B reverses if a serving or
scaffold defect specific to this checkpoint is later found to have depressed the
gate — in which case the gate is re-run under the corrected configuration on the
same 24 instances, and the correction is committed first. A disappointing
accuracy in the matched study is **not** a reversal condition and does not
reopen the choice.

---

## D-45 The matched scope study is frozen and launched, built to survive allocation expiry

**Decided:** 2026-08-13, **before the first `scope_main` trajectory existed.**
Pre-registration: `reports/scope_study_preregistration.md`. Population:
`manifests/scope_main.jsonl` (hash `89bf4189…`). Launcher:
`scripts/scope_main_run.sh`. Tests: `tests/test_scope_main.py` (15).

> **Headline.** 120 fresh instances, 15 per eligible family, **zero overlap**
> with any prior work, spending 120 of the 220 never-used and leaving **100**.
> Both solvers get the identical manifest, K=4, **960 trajectories**. H1, its
> operational definition, the verdict table, the capability-confound bar and the
> stopping semantics are all fixed in advance. The run is **designed to span
> allocations**, and the provenance guard that makes that safe is the reason
> this entry exists.

### 1. Why the operator's green light changed the scope

The preflight deliberately withheld the fresh manifest: spending 120 irreplaceable
instances on a solver whose scaffold capability was unproven would have been the
expensive mistake. D-44 resolved that — B1 PASSED, and operates the scaffold more
cleanly than the incumbent. With the uncertainty discharged, holding the pool back
buys nothing, and the operator authorised the study.

### 2. The design decision that mattered: one tree for a multi-allocation run

≈55 GPU-hours of trajectory time will not reliably fit one allocation, so the run
**will** be interrupted and resumed. That is precisely the condition that produced
D-29 — a prospective run whose execution commit could not afterwards be named.

Three mechanisms, enforced rather than intended:

* **Trajectory-level resume is exact.** `sampling.pending_specs` skips a run only
  when its COMPLETE marker exists **and** all four artifacts are present **and**
  `metadata.completed` is true; a trajectory interrupted mid-write is re-run, not
  silently skipped. This already existed and is relied on, not reinvented.
* **`LAUNCH.json` pins the tree.** First launch records the commit and manifest
  hash; every resume **refuses** if HEAD moved or the manifest changed.
  `--allow-commit-drift` exists, logs loudly, and a run using it is no longer
  attributable to one tree. **Standing instruction: do not commit while the run
  is in flight.**
* **The D-36 dirty-tree guard is never bypassed**, on first launch or on resume.

The launcher is also idempotent about serving: it probes each port before
launching, rewrites endpoints from the *current* hostname (the one thing that
genuinely changes between allocations), and extracts the serving override from
YAML via python rather than writing JSON braces in bash — D-43 lost a server start
to exactly that shell bug, and it cannot recur here.

### 3. What is fixed in advance

* **H1** — the separation replicates iff, for **both** solvers, detection is
  established (agreement→correctness AUROC CI lower bound > 0.5) and correction
  is **not** (verifier absolute gain CI lower bound > 0). Four-row verdict table:
  REPLICATED / NOT REPLICATED (correction solver-specific) / NOT REPLICATED
  (detection absent for B) / MIXED.
* **Capability-confound bar** — paired Pass@1 difference (B − A) with 95% CI
  upper bound < **−0.15** labels the cross-family claim CAPABILITY-CONFOUNDED.
  The difference and CI are reported either way. The gate's n=24 estimate was
  −0.2083 [−0.4583, +0.0417]: past the bar with an interval spanning it, which
  is why the gate is explicitly **not** the test.
* **Denominator guard** carried unchanged from the preflight.
* **Secondaries stay secondary**: the tier analysis is descriptive with tier and
  task identity confounded at both extremes, and the cross-solver overlap is
  reported against a chance-overlap baseline from each solver's own marginal —
  overlap that merely reflects two marginals is not shared difficulty.

### 4. Two phases, and what Phase 2 may not change

Phase 1 is the 960 trajectories. Phase 2 is verifier scoring with the **frozen
Stage-C C1** gemma at unchanged port, capsule allowlist, criteria, granularity,
repeats and aggregation. Phase 2 needs an adapter so the capsule builder reads
`scope_main_{a,b}` trees rather than `phase2b`/`phase1_pooled`; that adapter
changes **which traces are read and nothing about how they are scored**. Any
verifier parameter that turns out to need changing is a new pre-registration.

### 5. What this does not license

No instances added after a result is seen, no K>4, no third solver, no second
verifier, no pooling of arms, no best-arm reporting, no bar movement, and no
re-run of a completed arm. Resuming an interrupted dispatch is infrastructure
recovery and is expected by design.

**Reversal condition.** The population and both arms are frozen. A serving or
scaffold defect discovered mid-run that demonstrably corrupts one arm would
require discarding that arm's affected trajectories and re-running **them**, with
the defect and the fix committed first — never a silent re-run, and never a
change to the manifest, which is a new experiment by definition.

---

## D-46 Matched scope study COMPLETE: H1 NOT REPLICATED — correction is solver-specific

**Decided:** 2026-08-21. Design: `reports/scope_study_preregistration.md`
(frozen `fbd73a3`, before any Phase-2 trajectory existed). Drivers:
`scripts/scope_main_verifier_run.py`, `scope_main_detection_analysis.py`,
`scope_main_h1_verdict.py`. Artifacts: `reports/tables/scope_study/
scope_main_h1_verdict.json`, `h1_per_instance_{a,b}.csv`,
`detection_report_{a,b}.json`.

> **Headline.** Phase 1 (960 trajectories, both arms) and Phase 2 (9,744
> verifier comparisons, 0 errors, 0 unresolved ties) are both complete.
> **Both solvers show reliability detection established** (agreement→
> correctness AUROC 0.8956 for Arm A, 0.8144 for Arm B, both CIs clear of
> 0.5). **Error correction is established for Arm A only** (gain +0.0833, CI
> [0.0083, 0.1583]) and **not for Arm B** (gain −0.0167, CI [−0.0917,
> 0.0583]). Per the frozen four-row rule, **H1 is NOT REPLICATED**: the
> separation this study set out to test does not hold uniformly across
> solver families — it holds for the new solver (B) and not for the
> incumbent (A), the reverse of what a naive reading of D-43 might predict.
> **A verified mechanism finding qualifies Arm A's result**: restricted to
> genuinely-contested instances, Arm A's gain CI does not exclude zero.

### 1. Phase 1 — final counts, zero retried

| | valid/480 | terminal failures |
| --- | ---: | ---: |
| Arm A `Biomni-R0-32B` @ `71432eb3…` | 391 | 89 `model_context_overflow` (18.5%) |
| Arm B `Mistral-Small-3.1-24B` @ `68faf511…` | 418 | 62 `model_context_overflow` (12.9%) |

Zero unresolved trajectories in either arm — every one reached a terminal
state (valid-complete, or FAILED with a non-retryable class). No terminal
failure was retried, repaired, or excluded from any denominator, matching the
pre-registration verbatim: an instance with zero usable trajectories scores 0
under every selector alike, the same "non-answer never wins a tie" convention
(D-18) `selectors.select_plurality` already enforces for the baseline. This
was verified directly against `is_valid_complete` and each `FAILED` marker's
recorded `failure_class`, not inferred from a stale progress read.

One operational note, recorded because CLAUDE.md's scientific-integrity rules
require it be visible rather than smoothed over: the two Phase-2 scoring
processes were briefly launched non-detached and were killed when the
underlying session dropped mid-run. **No data was lost** — every completed
comparison had already been written to the per-comparison cache
(`cache_{a,b}.json`) before the interruption, so resuming from the cache
picked up exactly where it left off rather than rescoring anything. Both
processes were then relaunched `setsid`+`nohup`+`disown`'d directly on the
compute node for the remainder of the run, matching how every other
long-running process in this project is launched.

### 2. Phase 2 — verifier scoring, unchanged method

Capsule adapter (`scope_main_verifier_run.py`) is a **new file**, never an
edit to `scripts/stage_c_run.py` (which produced D-43's gating decision).
Imports `stage_c_capsule.build_capsule`/`render_capsule` and
`stage_c_verifier_port` unmodified; reads `reports/stage_c_criteria.md`
verbatim; copies the round-robin/Bradley-Terry loop from
`stage_c_run.py::cmd_score` with exactly one generalization Stage C's
by-construction population never needed: handling instances with 0 or 1
usable candidate (Stage C's frozen 78 was pre-filtered to substantive
disagreement; this study's 120 were not filtered that way).

**Sanity-checked before touching any scope-study data**: the adapter's exact
capsule-construction code path was run against `phase2b/crispr_delivery/18`
(an already-scored Stage-C instance) and diffed byte-for-byte against the
frozen `reports/tables/stage_c/` capsules — both candidates identical.

**Result: 3,408 (Arm A) + 6,336 (Arm B) = 9,744 comparisons, 0 comparison
errors, 0 unresolved ties on both arms.** Validity = 1.0000 for both.

### 3. The H1 verdict, computed exactly as pre-registered

| | Arm A | Arm B |
| --- | ---: | ---: |
| Pass@1 / plurality / Oracle@4 | 0.4417 / 0.6167 / 0.7917 | 0.3833 / 0.4083 / 0.5583 |
| headroom | 0.175 | 0.150 |
| agreement→correctness AUROC | 0.8956 [0.8552, 0.9302] | 0.8144 [0.7521, 0.8697] |
| **detection established** (CI lo > 0.5) | **yes** | **yes** |
| verifier selected mean | 0.7000 | 0.3917 |
| absolute verifier gain | **+0.0833**, CI [0.0083, 0.1583] | −0.0167, CI [−0.0917, 0.0583] |
| **correction established** (CI lo > 0) | **yes** | **no** |
| denominator guard | passed (headroom 0.175 ≥ 0.10, n=21 ≥ 5) | passed (headroom 0.150 ≥ 0.10, n=18 ≥ 5) |
| normalized recovery | 47.62% | −11.11% |

**H1 verdict: NOT REPLICATED** — "correction is solver-specific (established
for one arm, not the other)", the frozen table's second row. Both arms clear
the detection half; only Arm A clears the correction half.

**Capability-confound check** (paired Pass@1 diff, B−A): −0.0583, 95% CI
[−0.1752, +0.0583]. Upper bound is far from the −0.15 bar → **not
capability-confounded**. Consistent with, though slightly larger than, the
capability gate's n=24 point estimate (−0.2083, CI spanning the bar) — the
gate correctly flagged this as unresolved at n=24 and declined to conclude
either way; n=120 resolves it in the direction the gate's point estimate
pointed, still comfortably clear of the confound bar.

### 4. A verified mechanism finding that qualifies Arm A's result

Decomposing Arm A's net capture (10 = 15 captured − 5 harmed, over all 120)
by candidate-count bucket:

| bucket | n | capture | harm | net |
| --- | ---: | ---: | ---: | ---: |
| zero candidates | 4 | 0 | 0 | 0 |
| **trivial (exactly 1 usable candidate)** | 69 | 5 | 0 | **5** |
| scoreable (≥2 usable candidates) | 47 | 10 | 5 | 5 |

**Half of Arm A's net capture (5 of 10) comes from the trivial bucket, where
the verifier cannot lose by construction** — with only one parseable
candidate, the verifier trivially selects it. But this is not automatically
equal to the plurality baseline: `selectors.select_plurality`'s tie-break
scope spans **all four trajectories**, including unparseable ones (each its
own singleton cluster per `cluster_key_for`), and ties are broken by lowest
`trajectory_index`. **Verified directly against real data, not asserted**:
all 5 of Arm A's trivial captures (and Arm B's 1) are on `patient_gene_detection`,
where the single usable answer sits at a *later* trajectory index than one or
more unparseable trajectories, so the plurality baseline's tie-break picks the
non-answer over the correct answer — a mistake the verifier's narrower,
parseable-only candidate scope structurally cannot make.

**Restricted to the 47 genuinely-contested instances (≥2 real candidates),
Arm A's gain is +0.1064 with 95% CI [−0.0426, 0.2553] — does not exclude
zero.** Arm B's restricted gain is −0.0435, CI [−0.1739, 0.0725] — also
includes zero, consistent with the full-population finding.

**This does not change the primary verdict, which is reported exactly as the
pre-registration specifies** — Δ over all 120, unmodified, exactly as D-38's
`gap/3` and every other frozen decision rule in this project is applied
without re-aggregation shopping. It is reported because "correction
established for Solver A" would otherwise be read as demonstrated
adjudication skill, and half the measured effect is a plurality-baseline
tie-break artifact rather than the verifier discriminating between
genuinely disagreeing answers. **Flagged, not fixed**: a future reuse of this
comparison should either restrict the plurality baseline's tie-break scope to
parseable candidates only, or give the verifier an explicit abstain/no-answer
option so the two selectors' candidate scopes match. Per this study's scope
and the operator's explicit instruction, no further experiment was run to
correct this.

### 5. What this licenses and rules out for the uncertainty-aware harnessed-RL phase

* **Reliability detection generalises across solver family.** Both an
  incumbent same-lineage-as-generator-family solver and a genuinely
  independent one show a strong, CI-clear agreement→correctness signal
  (0.82–0.90 AUROC). A future controller's detection half does not need to be
  re-validated per solver family before being trusted at this level.
* **Error correction via this specific verifier method does NOT generalise
  across solver family, and the direction is solver-specific in a way not
  predicted in advance.** A harnessed-RL design that assumes "the frozen C1
  verifier recovers headroom" as a general property inherited from Arm A's
  result would be wrong for an independent solver family (Arm B: null,
  point estimate negative) — and, per §4, is not even robustly established
  for Arm A once the tie-break artifact is set aside.
* **No general-purpose "verifier corrects errors" claim survives this study.**
  Any future RL phase that wants a correction signal to bootstrap from must
  either (a) demonstrate it fresh for its own specific solver, not assume
  transfer from this result, or (b) use a mechanism other than this
  LLM-as-a-Verifier method, since neither arm's genuinely-contested subset
  clears the correction bar.
* **The plurality-vs-verifier candidate-scope asymmetry (§4) is a
  measurement-definition problem, not a solver-family finding**, and must be
  fixed in the harness before any future study reuses this comparison design
  — otherwise a future "correction established" result cannot be trusted
  without the same post-hoc decomposition this entry required.

### 6. Stop, per operator instruction

No further uncertainty experiment or RL experiment was started after this
analysis. Both trajectory-generation servers and the verifier server have
been shut down; all four GPUs on the allocation are free. Every manifest,
hash, log, verifier configuration and generated scoring artifact from this
study is preserved on disk and in this commit — nothing was deleted.

**Reversal condition.** None applies to the H1 verdict itself — it is
computed exactly as pre-registered and is not revisited by further analysis
of this data. The §4 mechanism finding is a flagged design defect, not a
reversal condition of any conclusion above; fixing it and re-running is new
work, subject to its own north-star check, exactly as D-43's and D-45's
reversal conditions already state for this line of study.

---

## D-47 RL-signal preflight opened: pre-registration frozen before any mixed-reward number exists

**Decided:** 2026-08-21. Design: `reports/rl_signal_preflight_preregistration.md`.
No `mixed_reward`, AUROC, enrichment ratio, or simulation number has been
computed as of this entry.

**What this is.** A new, third question on top of the scope study's frozen
120-instance / K=4 / two-solver-family trajectory set (D-44/D-45/D-46), which
is **reused as data, not reopened as a decision**. The scope study asked (1)
does agreement detect correctness, and (2) does a verifier correct errors — and
answered both (detection generalizes, correction doesn't robustly). This asks
a genuinely different question: does the same agreement signal identify
prompts whose K=4 rollouts contain useful within-prompt reward variation — the
raw material a GRPO-style update needs. Not "sample uncertain prompts more at
inference time" (already failed prospectively, Phase 2B/D-26) — this is about
which prompts are informative **for training**, evaluated offline from
already-consumed trajectories only.

**Verified before writing the predictor definition, not assumed:** every one of
the 120 instances in both arms has exactly 4 trajectory rows in
`results/tables/instrumented.csv`, including every terminal
`model_context_overflow` failure, each scored `reward=0.0` and given its own
singleton cluster key. The reward vector is therefore always a full length-4
vector for every instance in both arms with no exclusion and no special case —
checked directly against the aggregated tables before the representation
choice was written into the preregistration, per the brief's explicit
instruction not to silently drop or hand-wave terminal failures.

**Primary predictor: `plurality_fraction`** (already computed by
`features.compute_consistency`, already written to `results/tables/
instances.csv`) — the per-instance analogue of the trajectory-level
`agreement_fraction` signal that carried Phase 1's and the scope study's own
detection results. `U = 1 - plurality_fraction`, a monotonic re-expression
only. No new learned uncertainty score. `pairwise_agreement` is a labelled
secondary robustness check and never enters the GO rule.

**GO rule, frozen as a compound bar, not a bare AUROC point estimate**, per
arm independently:

* (a) `AUROC(U, mixed_reward)` 95% CI (10,000 instance-bootstrap replicates,
  seed 20260821) **lower bound > 0.5**;
* (b) the lowest-agreement natural stratum (`plurality_fraction == 0.25`,
  fixed now rather than an arbitrary quantile cut, since the K=4 predictor
  only takes 4 distinct values) shows `P(mixed_reward)` enrichment **≥ 1.5x**
  the base rate, with the stratum's own CI lower bound exceeding the base
  rate;
* (c) in the offline simulation, uncertainty-ranked sampling at a **25%**
  budget captures more `mixed_reward` instances than uniform's CI-supported
  expectation at that budget.

**Denominator guard**: fewer than 10 `mixed_reward` instances in an arm →
INCONCLUSIVE regardless of point estimates, in the spirit of D-44/45/46's
normalized-recovery guard. **NO-GO** requires either no CI-supported
discrimination at all, or the high-uncertainty stratum performing at or below
chance enrichment (actively uninformative, not merely weak).

**Cross-solver interpretation table fixed now** (§7 of the preregistration):
GO+GO licenses a cross-solver uncertainty-guided-RL hypothesis; GO on one arm
only narrows the claim to that solver; NO-GO/INCONCLUSIVE on both means the
current uncertainty-guided curriculum hypothesis does not proceed.

**What this does not authorise.** A GO here authorises drafting an RL protocol
(epoch-1-identical, prompt-prioritization-only intervention, already scoped in
the accompanying report) — never launching training, which needs its own
explicit operator approval. No Stage-C, adjudication, diversity-by-resampling,
or adaptive-K branch is reopened.

**Reversal condition.** None applies to the frozen predictor, outcome, or GO
thresholds — they are checked against the result, not adjusted by it. A
different predictor or bar would be new work, subject to its own
pre-registration, exactly as this project requires everywhere else.

---

## D-48 RL-signal preflight COMPLETE: both arms NO-GO — uncertainty does not identify RL-informative prompts

**Decided:** 2026-08-21. Design: `reports/rl_signal_preflight_preregistration.md`
(frozen `ad0af40`, before any `mixed_reward` number existed). Drivers:
`scripts/rl_signal_preflight_analyze.py`, `rl_signal_prioritization_sim.py`,
`rl_signal_verdict.py`. Artifacts: `reports/tables/rl_signal_preflight/
rl_signal_final_verdict.json`, `<output_root>/rl_signal_preflight/
rl_signal_{report,simulation}_{a,b}.json`, `rl_signal_per_instance_{a,b}.csv`,
`rl_signal_budget_curve_{a,b}.csv`.

> **Headline.** Offline analysis of the scope study's already-frozen 120-
> instance/K=4 trajectory set (D-44/45/46), reused as data only. **Both arms
> return NO-GO** on the frozen compound rule. Arm A (Biomni-R0) shows real,
> CI-supported rank discrimination (AUROC 0.685, CI [0.577, 0.786]) but **the
> pre-registered highest-uncertainty stratum shows enrichment at or below
> chance** (0.96x). Arm B (Mistral) shows neither CI-supported discrimination
> (AUROC 0.594, CI [0.496, 0.690] — lower bound just under 0.5) nor enrichment
> (0.85x). **Both arms show the identical non-monotonic (inverted-U) pattern**:
> full agreement is structurally never mixed; enrichment peaks at *moderate*
> disagreement (1.4–1.6x); and falls back to at-or-below baseline at *maximal*
> disagreement — the stratum a naive "sample the most uncertain prompts" policy
> would actually target. **The current uncertainty-guided curriculum
> hypothesis is not supported and does not proceed for either solver.**

### 1. Population and representation — verified, not assumed

The scope study's 120 instances per arm, reused wholesale — no new instance,
no new inference. Verified directly against `results/tables/instrumented.csv`
before the predictor was even defined: every instance in both arms has
**exactly 4 trajectory rows**, including every terminal
`model_context_overflow` failure, each scored `reward=0.0` with its own
singleton cluster key. The reward vector is therefore a full length-4 vector
for all 120 instances in both arms, with **no exclusion and no special case**
— `mixed_reward`, `reward_variance`, `oracle_positive` and `selection_failure`
apply uniformly.

### 2. Primary predictor and outcome, exactly as frozen

`U = 1 - plurality_fraction` (already computed by `features.compute_
consistency`, the per-instance analogue of the trajectory-level
`agreement_fraction` signal behind every prior detection result in this
project). `mixed_reward := 0 < sum(r) < 4`. No new learned uncertainty score.

### 3. Per-arm numbers

| | Arm A (Biomni-R0) | Arm B (Mistral) |
| --- | ---: | ---: |
| n_mixed_reward / n_all_correct / n_all_wrong | 67 / 28 / 25 | 47 / 20 / 53 |
| base rate `P(mixed_reward)` | 0.558 | 0.392 |
| **AUROC(U, mixed_reward)** | **0.685**, CI [0.577, 0.786] | 0.594, CI [0.496, 0.690] |
| **(a) discrimination CI-supported** | **yes** | no |
| highest-uncertainty stratum (`agreement=0.25`) `P(mixed_reward)` | 0.536, CI [0.357, 0.714] | 0.333, CI [0.205, 0.487] |
| enrichment ratio at that stratum | **0.959** | **0.851** |
| **(b) enrichment ≥ 1.5x, CI-supported** | **no** | no |
| 25%-budget capture diff (uncertainty − uniform expectation) | −0.75, CI [−4.75, 4.75] | −0.75, CI [−5.5, 4.25] |
| **(c) budget-verified capture** | **no** | no |
| reward-variance Spearman ρ | 0.337, CI [0.161, 0.507] | 0.154, CI [−0.006, 0.312] |
| selection-failure rate / AUROC | 0.175 / 0.760 [0.664, 0.844] | 0.150 / 0.656 [0.544, 0.761] |

**Verdict, per arm, per the frozen rule: NO-GO, NO-GO.**

### 4. The stratum table is the important finding, not a footnote

| agreement level (`plurality_fraction`) | Arm A `P(mixed)` | Arm A enrichment | Arm B `P(mixed)` | Arm B enrichment |
| --- | ---: | ---: | ---: | ---: |
| 1.00 (unanimous) | 0.000 | 0.00x | 0.000 | 0.00x |
| 0.75 | 0.844 | **1.51x** | 0.591 | **1.51x** |
| 0.50 | 0.781 | **1.40x** | 0.636 | **1.62x** |
| 0.25 (maximal disagreement) | 0.536 | 0.96x | 0.333 | 0.85x |

`agreement=1.0` is **structural, not empirical**: if all four trajectories
share one canonical answer they share one reward, so `mixed_reward` is
impossible by construction — this row is a check on the definition, not a
finding. The finding is the **hump shape** across the other three: both
solvers peak at *moderate* disagreement (one clear majority plus a minority,
or two even pairs) and *decline* at maximal (four-way) disagreement, where a
plausible mechanism is that four genuinely different guesses are often four
different wrong answers on hard multi-candidate tasks (`gwas_variant_
prioritization`, `screen_gene_retrieval`), not "some right, some wrong."

**This is exactly why the pre-registered stratum, fixed before any number
existed, was the maximal-disagreement one — and exactly why the compound GO
rule does not reduce to a bare AUROC check.** Arm A's AUROC alone (0.685,
clearing its CI bar) would read as real signal; picking the *best-performing*
stratum after seeing this table (`agreement=0.75`, 1.51x) instead of the
pre-registered one would have been exactly the bar-shopping this document was
frozen to prevent. The frozen stratum is reported, and it fails.

### 5. What this does and does not conflate

Restated because the brief is explicit about it: **`agreement → correctness`
(D-46: AUROC 0.896 / 0.814, both established) and `agreement → RL reward
contrast` (this entry: NO-GO, NO-GO) are separate findings and are not
conflated.** The first is a detection result about individual trajectories'
correctness. The second is a prompt-level result about whether the same
signal identifies useful within-prompt training variation. They can, and here
do, point in different directions — a real detection signal does not imply a
useful curriculum signal.

### 6. Steps 6–8, 10 (RL protocol draft, matched-compute design, post-RL
evaluation plan, harness engineering) — not performed, per the brief's own
"if and only if GO" instruction

No RL protocol was drafted. No harness engineering was started. Nothing about
Agent Lightning/verl integration exists in this repository as of this entry.
This is a deliberate stop, not an oversight: the brief is explicit that these
steps are conditional on a GO, and both arms returned NO-GO.

### 7. Model recommendation — descriptive only, not licensed by any GO

Offered because the brief requests it regardless of outcome, and scoped
honestly: **this is not a recommendation for uncertainty-guided RL** (nothing
licenses that for either solver). It is a descriptive comparison of which
solver's prompt pool carries more learnable signal for a **plain,
uniform-sampling** GRPO run, if the operator chooses to pursue one despite
this preflight's result.

**Biomni-R0's prompt pool carries substantially more GRPO-learnable signal on
this population**: 55.8% mixed-reward vs Mistral's 39.2%, and — the more
important number for GRPO specifically, where an all-wrong group contributes
exactly zero policy-gradient signal at every step it is sampled — Biomni-R0's
all-wrong rate is 20.8% against **Mistral's 44.2%**. Nearly half of Mistral's
prompt pool on this population is dead weight for GRPO; Biomni-R0's is a
quarter. Against this: Biomni-R0 is ~2.9x slower per trajectory and has a
higher context-overflow rate (18.5% vs 12.9%, D-46), both real engineering
costs at RL scale, and Mistral's smaller footprint is easier on rollout+
training GPU memory. **On the numbers actually in hand, Biomni-R0 is the more
RL-training-rich substrate for a plain GRPO experiment on this task pool**; the
speed and memory costs are real and should weigh into any actual compute
budget, not into which pool has more signal to learn from.

### 8. What this rules out and what remains open

* **Ruled out**: the specific hypothesis that agreement-based uncertainty
  (via `plurality_fraction`) identifies which prompts are RL-informative, for
  either Biomni-R0 or Mistral, on this population. Not ruled out: some other
  operationalization of uncertainty (e.g. a signal specifically sensitive to
  the moderate-disagreement regime rather than monotonic in disagreement)
  might behave differently — but that would be a new predictor and a new,
  separately pre-registered study, not a re-analysis of this one.
* **Not addressed at all**: whether a *uniform-sampling* GRPO run would work
  on either solver. This preflight only tested whether uncertainty *improves
  targeting* over uniform sampling — it says nothing about whether RL itself
  would help, which remains an open, separate, and much larger question.

**Reversal condition.** None applies to the frozen predictor, outcome, or GO
thresholds — checked against the result, not adjusted by it, exactly as
D-47 states. A different predictor, a non-monotonic-aware stratification
scheme, or a different outcome definition (e.g., graded rather than binary
mixed-reward) would be new work, subject to its own pre-registration.

---

## D-49 Harnessed-GRPO pre-registration frozen: engineering audit + design, no training run

**Decided:** 2026-08-21. Design: `reports/rl_harness_preregistration.md`.
No RL training has occurred. Split verified: `scripts/rl_harness_split_audit.py`,
`reports/tables/rl_harness/split_audit.json`.

**What this is.** Following D-48's NO-GO on uncertainty-guided prioritization,
this opens the simpler question the closure licenses next: can **plain**
harnessed GRPO (uniform sampling, fixed K, official reward only, no verifier,
no new correction mechanism) improve Biomni-R0 itself, and does it move the
reliability/uncertainty behaviour characterised in Part I (Phase 1, the scope
study)? Six sub-questions, each mapped to a specific pre/post endpoint.

**Engineering audit, verified rather than assumed:**

* **Nothing installed yet.** `pip list` on both project environments shows no
  verl, Agent Lightning, PEFT, DeepSpeed, Ray, or vLLM. Network egress to
  PyPI/GitHub confirmed reachable. Nothing blocks starting from zero.
* **Agent Lightning + verl is a good fit, conceptually.** verl supports GRPO
  natively and an SGLang rollout backend — the same server binary already
  pinned throughout this project. Agent Lightning's proxy sits exactly at the
  `base_url` Biomni's `A1` agent already points at (`source="Custom"`), so
  the **only configuration that changes is the URL** — no Biomni code change,
  respecting D-01. Multi-turn credit assignment (Biomni averages ~14 LLM
  calls per trajectory) uses the standard scheme: one masked training
  sequence per rollout, one trajectory-level reward broadcast to every
  assistant-turn span. Finer per-turn credit assignment is explicitly out of
  scope — "no new correction mechanism" rules it out regardless.
* **The serious blocker: full-parameter GRPO fine-tuning of the 32B model does
  not fit in 4×96GB H100 (384 GB total)**, independent of rollout serving —
  bf16 weights (64 GB) + fp32 AdamW master weights and two moment buffers
  (384 GB) totals 448 GB, before activations or the rollout engine's own
  memory. **Mitigation: LoRA, not a smaller model.** A rank-16–64 LoRA's
  trainable-parameter optimizer state is a few GB; the frozen base weights can
  be shared with the rollout engine's own resident copy under verl's
  hybrid-engine design. This keeps Biomni-R0-32B as the primary candidate,
  per the brief's own instruction, because the blocker has a standard
  mitigation rather than requiring a smaller model.
* **Context-overflow safeguards (`budget.py` R2–R5) are preserved by
  construction**: they execute inside `runner.py`'s LangGraph instrumentation,
  upstream of the HTTP call to whichever `base_url` is configured — routing
  that call through an Agent Lightning proxy instead of directly to SGLang
  changes nothing about when or whether they fire.
* **Official evaluator preserved exactly** — reward is
  `OfficialEvaluator`/`BiomniEval1._compute_reward`, computed after each
  trajectory as always; the only new step is forwarding the scalar to the RL
  reward channel.
* **Cost is dominated by rollout wall-time, not the RL update.** At this
  project's own measured per-trajectory time (≈310–374s) and established
  concurrency (4), the frozen pilot config (64 rollouts/step) costs roughly
  1.5 hours of rollout wall-time per step before backward/optimizer time.

**Train/held-out split, verified disjoint, no new manifest built:**

| pool | n | source |
| --- | ---: | --- |
| training | 200 | `manifests/phase1.jsonl` ∪ `manifests/phase2b.jsonl` |
| held-out eval | 120 | `manifests/scope_main.jsonl` (Biomni-R0's already-characterised Arm A population) |
| overlap | 0 | verified |
| reserved, untouched | 100 | the never-used pool (D-45); not spent here |

Reusing the scope study's own 120 instances as the held-out set means the
**pre-RL half of every endpoint is already computed** (D-46/D-48: Pass@1
0.442, plurality 0.617, Oracle@4 0.792, agreement→correctness AUROC 0.896
[0.855, 0.930], selection-failure 0.175 [0.108, 0.25]) — only a post-RL K=4
rerun on the identical instances is needed, using the identical frozen
analysis code already committed.

**Frozen pilot configuration**: LoRA GRPO on Biomni-R0-32B; uniform sampling
over the 200-instance training pool (no uncertainty-guided sampling, per
D-48); K=4 (matching Part I, not 8, to bound rollout cost); batch size 16
prompts/step (64 rollouts/step); ≈2 epochs over the training pool (≈25
optimizer steps, ≈1,600 total training rollouts); official binary reward
only — no verifier, no confidence term, no adaptive K.

**Primary endpoint**: Δ_reward = post-RL − pre-RL (0.4417) held-out mean
reward, paired instance-clustered bootstrap, 10,000 replicates, seed
`20260821`. **GO** requires the CI lower bound `> 0` **and** the safety check
(H-RL2b: agreement rising with no accuracy gain, or accuracy dropping) not
firing — a plain reward-CI check alone is explicitly insufficient, mirroring
D-47's own refusal to accept a bare point estimate.

**What this does not authorise.** Engineering smoke tests only — environment
build, a dummy-reward optimizer-step check, one real trajectory routed through
the Agent Lightning proxy to confirm trace capture and reward attachment. **No
scientific RL training run starts without separate, explicit operator
approval.**

**Reversal condition.** None applies to the frozen split, config, or GO rule
— checked against the result, never adjusted by it. A different LoRA rank,
batch size, or K chosen *before* training starts and stated as such is a
configuration decision within this pre-registration's own frozen table; chosen
*after* seeing a training curve, it is a new experiment.
