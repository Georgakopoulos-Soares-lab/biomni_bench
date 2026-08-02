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
