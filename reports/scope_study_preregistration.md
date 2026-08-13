# Matched scope study — pre-registration

**Written:** 2026-08-13. **Status: FROZEN.** Committed **before the first
trajectory of either arm existed.** The commit containing this file is the
launch commit; `<output_root>/scope_main/LAUNCH.json` records it, and
`scripts/scope_main_run.sh` refuses to resume from any other commit.

**Subordinate to `reports/scope_study_preflight.md`**, which holds the pool
audit, the verifiability rubric, the frozen Solver-B identity, and the
normalized-headroom denominator guard. Nothing here modifies any of them. Where
the two disagree, the preflight governs.

**D-43 / Stage C is closed and untouched.** Different population, different
question, no Stage-C cell, bar or artifact changed.

---

## 1. Hypotheses

**Primary.**

> **H1.** The separation between *reliability detection* and *successful error
> correction* replicates under an independent solver family.

Operationally, for a solver `S` on this population:

* **detection established for `S`** — the agreement → correctness AUROC has a
  95% CI **lower bound > 0.5**;
* **correction established for `S`** — the frozen verifier's **absolute gain
  over the plurality baseline** has a 95% CI **lower bound > 0**;
* **the separation holds for `S`** — detection established **and** correction
  **not** established.

H1 is supported iff the separation holds for **both** solvers.

**Secondary (pre-registered, never promoted to co-primary).**

> **H2.** Verifier headroom recovery varies with the frozen criterion-verifiability
> tier of the task.
>
> **H3.** The same questions are intrinsically hard across solver families.

## 2. Population — frozen

| item | value |
| --- | --- |
| instances | **120** — 15 from each of the 8 eligible task families |
| source | the **never-used** pool verified in preflight §2 |
| manifest | `manifests/scope_main.jsonl` |
| manifest hash | `89bf418928b4846f93cdaf7e3d009cffd8e0c514586fda05effd473353441457` |
| selection | `benchmark._rng_order(task, 20260813, never_used_ids)[:15]` — deterministic, label-free; no model output exists for these instances by construction |
| overlap with prior work | **zero**, asserted by four fatal guards in the builder, including a cross-check against every manifest on disk |
| pool remaining afterwards | **100** never-used instances |

**Both arms receive this identical manifest.** Every comparison in the study is
paired on the instance.

## 3. Design — frozen

| | Arm A | Arm B |
| --- | --- | --- |
| solver | `biomni/Biomni-R0-32B-Preview` | `mistralai/Mistral-Small-3.1-24B-Instruct-2503` |
| revision | `71432eb3d5e583bee757e0f9437a17e711e8e3d1` | `68faf511d618ef198fef186659617cfd2eb8e33a` |
| config | `configs/scope_main_a.yaml` | `configs/scope_main_b.yaml` |
| K | 4 | 4 |
| trajectories | 480 | 480 |

**960 trajectories total.** The two configs are identical field for field except
model identity, revision, and the serving override — and the override differs
**only so that both are served at the same 65536 context**: Arm A needs D-04's
YaRN identity transform to reach it from a native 40960, Arm B is natively
131072 and needs none. Temperature 0.7, `max_tokens` 8192, confidence mode
`final_only`, tool retriever on, timeouts, retry policy and per-trajectory seeds
are all shared.

**Solver B's lineage is independent of both Solver A (Qwen3) and the verifier
(Gemma)**, so neither solver is same-model with the verifier and the
error-correction contrast is not confounded by solver–verifier relatedness
(preflight §4.2).

## 4. Two phases

**Phase 1 — trajectory generation (this launch).** 960 trajectories, both arms
in parallel, resumable across allocations via `scripts/scope_main_run.sh`.

**Phase 2 — verifier scoring.** The **frozen Stage-C C1** verifier,
`google/gemma-4-31B-it` @ `842da3794eaa0b77d5f08bae87a17459d91ff475`, with the
**unchanged** port, capsule allowlist, three biomedical criteria, score
granularity G=20, K=8 repeats, full round-robin and Bradley–Terry aggregation
fixed in `reports/stage_c_preregistration.md` §§3–5. Phase 2 runs after Phase 1
completes and requires the gemma server back up.

**No verifier parameter is re-tuned for this study.** Phase 2 needs an adapter
so the capsule builder reads `scope_main_{a,b}` run trees instead of
`phase2b`/`phase1_pooled`; that adapter changes **which traces are read**, and
nothing about how they are scored. If any verifier parameter turns out to
require change, that is a new pre-registration, not an edit to this file.

## 5. Analyses — frozen

All bootstraps: **10,000 replicates, resampling the instance, seed 20260813.**
Binary reward at threshold 0.5. Reported **per solver**, then contrasted.

### 5.1 Primary 1 — reliability detection (verifier-free)

Pass@1; plurality@4; Oracle@4; available headroom (`Oracle@4 − plurality`);
agreement → correctness **AUROC** with an instance-clustered CI.

This half touches no verifier and is therefore unaffected by any question about
verifier capability or relatedness.

### 5.2 Primary 2 — error correction

Absolute verifier gain over plurality, with CI. Normalized oracle-headroom
recovery **subject to the preflight §7 denominator guard** — reported as
`undefined` wherever headroom < 0.10 **or** fewer than 5 instances are
recoverable, with the absolute gain reported in its place. On 15-instance
strata the count condition will usually bind, and that is the intended
behaviour.

### 5.3 The H1 verdict

| observed | verdict |
| --- | --- |
| separation holds for **both** solvers | **REPLICATED** |
| separation holds for A; **correction established for B** | **NOT REPLICATED — correction is solver-specific** |
| **detection not established for B** | **NOT REPLICATED — B lacks the detection half**; the arms are not comparing the same regime |
| any other combination | **MIXED**, reported as observed, with no single label |

Each arm is evaluated separately. There is no pooling across arms and no
best-arm reporting.

### 5.4 The capability-confound label — fixed now

Paired Pass@1 difference (B − A) over the 120, instance-clustered.

> If the 95% CI **upper bound < −0.15**, the cross-family claim is labelled
> **CAPABILITY-CONFOUNDED**.

The paired difference and its CI are reported **regardless of which side of the
bar they fall on**. Preflight §6.4 continues to bind: normalized headroom
recovery does not cure a capability confound.

The gate measured this at n=24 as −0.2083, 95% CI [−0.4583, +0.0417] — a point
estimate past the bar with an interval that spans it. **This study is the test,
and the gate is explicitly not it.**

### 5.5 Secondary — verifiability tier (H2)

Absolute and normalized recovery by the tier frozen in preflight §3.
**Directional and descriptive only.** No monotonic law, no trend test, no
threshold. Tier and task identity are **fully confounded at both extremes**
(one family each), so no claim of the form "verifiability causes recovery" is
available from this design and none will be made. MedAgentBench appears
separately as an external positive control, never as a point in a within-Biomni
fit.

### 5.6 Secondary — cross-solver error structure (H3)

On the matched 120: overlap in `no-correct-at-K4`, in wrong pluralities, in
substantive disagreement, in verifier failures, and in high-agreement-but-wrong;
plus the 2×2 of per-instance correctness. Reported with an instance-clustered CI
on the overlap fractions and against a chance-overlap baseline computed from
each solver's own marginal accuracy — an overlap that merely reflects two
marginals is not evidence of shared intrinsic difficulty.

## 6. Stopping semantics

**The study runs once.** 120 instances, K=4, both arms.

* No instances are added after any result is seen.
* No K>4.
* No third solver.
* No verifier beyond the frozen C1.
* No re-run of a completed arm.
* **Resuming an interrupted dispatch is infrastructure recovery, not a re-run**
  — the same distinction `stage_c_stop_rule.md` §6 draws. Resumption is expected
  here by design, because the study is larger than one allocation.

This is a **measurement** study, not a GO/NO-GO gate: it has no action it
authorises and no programme it continues. Its output is an answer to H1 with an
interval, plus two labelled secondaries.

## 7. Provenance across allocations

The study is expected to span allocations, which is exactly the condition under
which D-29's failure happened. Three mechanisms, all enforced rather than
intended:

1. **Trajectory-level resume is exact.** `sampling.pending_specs` skips a run
   only when its COMPLETE marker exists **and** all four artifacts are present
   **and** `metadata.completed` is true. A trajectory interrupted mid-write is
   re-run, never silently skipped.
2. **One tree for the whole run.** `scripts/scope_main_run.sh` records the
   launch commit and manifest hash in `<output_root>/scope_main/LAUNCH.json` on
   first launch, and **refuses to resume** if HEAD has moved or the manifest
   changed. `--allow-commit-drift` exists, logs loudly, and its use must be
   recorded — a run using it is no longer attributable to a single tree.
3. **The D-36 dirty-tree guard is never bypassed**, on the first launch or on
   any resume, and every trajectory carries its `source_hashes` map.

**Do not commit to this repository while the run is in flight.** Commit results
after Phase 1 completes.

## 8. Explicitly not to be done

Tuning any prompt, temperature, tool list, context limit or answer parser in
response to observed accuracy. Re-running an arm because its numbers
disappointed. Adding a third solver, a second verifier, or a fourth tier.
Pooling the arms. Reporting the better arm as the result. Moving the −0.15
capability bar, the 0.5 AUROC bar, or the §7 denominator guard. Promoting H2 or
H3 to primary. Reading the gate's n=24 numbers as evidence about H1.

---

*No `scope_main` trajectory exists at the time of writing. This file is a
precommitment, and is the authority against which any later claim from this
study is checked.*
