# Track-C Step 2 — candidate-adjudication pilot: NO-GO

**Written:** 2026-08-10. Step 2 of the "Next steps — live GPU node" plan.
Driver: `scripts/track_c_adjudication_pilot.py` (generation, committed
`cddf96c`) + `scripts/track_c_adjudication_analyze.py` (analysis, committed
`95cf660`). Acceptance rule frozen before any trajectory existed
(scratch, throwaway by design, quoted verbatim below — not committed, per
the project's own discipline for exploratory-tier decision files that
precede a result). Tests: `tests/test_track_c_adjudication_analyze.py` (11).
Tables: `reports/tables/track_c_step2/`.

> **Headline: NO-GO, pooled and decisive on one of two pools.** Handing the
> real, tool-enabled Biomni agent the existing disagreeing candidates and
> asking it to adjudicate between them — strictly more information and
> capability than a real VERIFY trajectory would ever have (D-32) — does not
> clear even a third of the available headroom over plain plurality voting.
> Because this arm is a deliberate upper bound on VERIFY, **this result
> licenses a NO-GO recommendation for VERIFY mode-A/evidence-based
> adjudication as a family**, not just for this specific pilot's framing.
> Step 4 (K=2 characterization) is **not indicated** by this result; per the
> standing instruction, the node is left idle rather than spending the
> reserved pool speculatively. Step 5 (VERIFY implementation) remains
> **gated** — this finding is offered as evidence for that decision, not as
> a substitute for the user's separate explicit approval.

---

## 1. Design (frozen before any trajectory, reproduced from the acceptance rule)

**Population.** All 78 `B_substantive_disagreement` instances across both
available pools: 53 from `phase2b`, 25 from `phase1_pooled`. Nothing held
out — every candidate answer comes from already-completed, frozen
trajectories. Exclusion list written before any pilot result
(`exclusion_list.json`, 78 instances) for future VERIFY manifests to assert
zero overlap against.

**Frozen floor and ceiling** (computed once, before any Arm-1/Arm-2 trajectory):

| | n | mean reward |
| --- | ---: | ---: |
| plurality floor | 78 | 0.4103 |
| oracle ceiling | 78 | 0.6026 |
| gap | 78 | 0.1923 |

**Two arms**, 3 samples/instance/arm, majority-resolved (≥2-of-3 agreement;
anything else scores as no answer):

* **Arm 1** — one-shot, no tools. Tests whether the correct answer is
  already latent in the candidates and merely mis-selected by voting.
* **Arm 2** — the real Biomni A1 agent, given an adjudication-framed prompt,
  free to use any tool. **The kill-shot arm**: it has strictly more
  information than a real `VerifyView`-constrained VERIFY trajectory
  (task prompt + one candidate only, D-32), so it upper-bounds what VERIFY
  could ever achieve. Its formal verdict is the one that governs Step 4/5.

**Decision rule** (paired, instance-clustered bootstrap, 10,000 replicates,
`Δ` = Arm-2 majority reward − plurality floor):

* **GO** if `Δ`'s 95% CI lower bound > 0.
* **NO-GO** if `Δ`'s 95% CI upper bound < gap/3 = 0.0641.
* **INCONCLUSIVE** otherwise.

## 2. What actually ran

**Arm 1** — 234/234 chat completions, complete. A pre-launch smoke test
caught a token-truncation bug (512 tokens truncated every sample mid-`<think>`
on a reasoning model that always thinks before answering) and fixed it
(2048 tokens, explicit `FINAL ANSWER:` tag) before the full run.

**Arm 2** — 234/234 trajectories attempted (dispatch fully drained: `planned=234,
pending_at_start=234, skipped=0, executed=234`). **190 succeeded, 44 failed**
(42 `budget_terminated_consecutive_runaway`, 2 `dependency_failure`) — an
17.9% degeneration-failure rate by this project's standard definition
(`failure_class` starting with `model_context_overflow`/`budget_terminated`),
the same order of magnitude as, though not directly comparable to, D-34's
28.1% [15.6%, 45.4%] residual-failure remeasurement on the original protocol.
Failed trajectories are legitimate terminal outcomes, not "still running" —
the completeness gate checks that every planned run has a terminal marker
(`run_present`), not that every run succeeded; a missing sample simply cannot
contribute to the 2-of-3 majority, exactly as the frozen rule intends.

## 3. Result

### 3.1 Primary verdict (pooled, n=78)

| | value |
| --- | --- |
| Arm-2 mean reward | 0.3333 |
| plurality floor | 0.4103 |
| Δ | **−0.0769**, 95% CI [−0.1923, 0.0385] |
| gap/3 (NO-GO bar) | 0.0641 |
| **verdict** | **NO-GO** (CI upper bound 0.0385 < 0.0641) |

Arm 2 does not merely fail to clear the bar — its point estimate is
*negative*, i.e. majority-resolved tool-enabled adjudication scores worse on
average than doing nothing but voting on the trajectories already in hand.

### 3.2 Arm 1, descriptive (not the gating arm, reported per protocol)

| | value |
| --- | --- |
| Arm-1 mean reward | 0.1923 |
| Δ vs. floor | −0.2179, 95% CI [−0.3333, −0.1026] — **NO-GO** |

A clean, decisively negative result: without tools, adjudication is *worse*
than voting, not merely no better. Read alongside Arm 2 (also negative but
closer to the floor), the ordering is exactly what the acceptance rule
anticipated it might be — recovery, if it existed at all, would require
active tool work rather than passive re-selection — except that even the
tool-enabled version does not recover anything.

### 3.3 Secondary cuts (pre-registered, none override the pooled verdict)

| population | n | Δ | 95% CI | verdict |
| --- | ---: | ---: | --- | --- |
| evidence-retrievable tasks | 40 | −0.0750 | [−0.2250, 0.0750] | INCONCLUSIVE |
| domain-judgment tasks | 38 | −0.0789 | [−0.2368, 0.0789] | INCONCLUSIVE |
| `phase2b` only | 53 | −0.0377 | [−0.1887, 0.1132] | INCONCLUSIVE |
| `phase1_pooled` only | 25 | **−0.1600** | **[−0.3200, −0.0400]** | **NO-GO** |

No secondary cut reverses the pooled verdict into a GO. `phase1_pooled`
alone is a second, independent NO-GO (its CI is entirely negative, not
merely inconclusive) — the pooled result is not being driven by one noisy
sub-population; it replicates in the smaller, independently-collected pool.
The two task-family cuts are individually underpowered (n=38-40, wide CIs)
but both point the same direction as the pooled estimate.

## 4. Why it fails — mechanism, from the same artifacts

Arm 2's low mean reward is **not** explained by confidently picking the
wrong candidate. It is explained by frequently **failing to produce a usable
answer at all**:

* **47.4% of instances (37/78) have no majority-resolved answer** — 28
  three-way (or off-menu-diluted) splits with no 2-of-3 agreement, plus 9
  instances where every sample failed outright. Both are scored 0 under the
  pre-registered accounting, exactly as a real VERIFY trajectory's failure
  would be.
* **46.2% of instances have at least one sample answer that is off-menu**
  — not one of the candidates the prompt explicitly required the agent to
  choose from. This generalizes a single case flagged during Arm 2's
  pre-launch smoke test (`crispr_delivery`/i0018, candidates `['c','f']`,
  the agent answered `'e'` in all 3 samples — genuinely `all_wrong`, so it
  did not corrupt scoring, but it was a visible instruction-compliance
  failure at the time and is now confirmed as a systematic pattern, not an
  isolated one). The agent does not reliably respect a hard constraint on
  its answer format even when given the full candidate list and explicit
  instructions to reproduce one verbatim.
* **17.9% degeneration-failure rate** (§2) removes entire samples from
  contention before majority resolution ever runs.
* **96.2% of instances have at least one sample with ≥1 "runaway"
  generation event** (a single over-length generation triggering truncation,
  the *soft* signal — distinct from the 17.9% *hard* failure rate, which
  requires 3 *consecutive* runaways to terminate a trajectory). This is a
  near-universal, mostly-survived phenomenon on this prompt shape, not
  something visible only in the tail; the adjudication preamble plus a full
  original task prompt evidently pushes this reasoning model into
  long-generation territory very routinely.
* **D-33 retrieval-provenance field coverage: 59.8%** of Arm-2 trajectories
  show at least one retrieval-provenance event in their event log — a
  presence-only check, not a structured audit, reported because it was
  near-free to compute; a majority of trajectories did engage the
  retrieval-provenance-instrumented path, so the low reward is not simply
  explained by "the agent never touched a tool."

None of these failure modes were mode-A specific (Step 1b already found
almost no mode-A instances in this population) — they are properties of
handing this model an adjudication task with tools at all, on this
population.

## 5. Interpretation and the decision this licenses

Arm 2 was designed with one specific, deliberate property: it has **strictly
more** information than any real VERIFY mode-A trajectory ever could (a real
`VerifyView` trajectory sees the task prompt and *one* candidate, not the
full disagreeing set; D-32). If the maximally-empowered version — every
candidate visible, explicit adjudication framing, full tool access — cannot
clear a third of the available headroom, a more-constrained real
implementation has no plausible path to clearing it either. This is not an
extrapolation past the data; it is the logical content of "strictly more
information," which is exactly why this pilot was designed as a kill-shot
test before committing to a full VERIFY implementation.

**This result is evidence, not the decision itself.** Step 5 (VERIFY
mode-A implementation) was never to be started without the user's separate,
explicit "yes" — that gate is unaffected by what this pilot found. What
changes is the evidence available to that decision: any future case for
building VERIFY mode-A now has to explain why a real, more-constrained
implementation would succeed where this idealized, upper-bound version did
not, on the same population, using the same model and tooling.

**Step 4 (K=2 characterization run) is not indicated.** The plan's condition
for Step 4 is "GO or INCONCLUSIVE-leaning-GO"; this result is a decisive
NO-GO at the primary/pooled level, replicated independently on
`phase1_pooled`. Per the standing instruction, the GPU node is left idle
rather than spending the reserved ~120-instance pool on a characterization
run whose premise (adjudication recovers meaningful headroom) this pilot
has just falsified.

## 6. Provenance

* Launched from a clean tree (D-36 guard, not bypassed).
* Throwaway experiment tree
  (`/scratch/11034/atzanakak/biomni_unc_runs/track_c_adjudication_pilot`),
  never written to `manifests/` or `configs/`, no experiment ID registered
  in PROJECT_STATUS's Active Experiment IDs table.
* Every trajectory carries `source_hashes` (D-36) and `project_git`/
  `biomni_git` provenance, same as every other trajectory in this project.
* Exclusion list (`exclusion_list.json`, 78 instances) written before any
  pilot result existed.
* Analysis script refuses to compute a verdict on a partial run (gates on
  every planned trajectory having a terminal marker, not on every trajectory
  succeeding) — verified against live partial data at 14-20/234 before the
  full run completed, and re-verified against the completed 234/234 run.

## 7. Reproduction

```
python scripts/track_c_adjudication_analyze.py \
    --candidates <dir>/candidates.jsonl \
    --arm1 <dir>/arm1_results.jsonl \
    --config <dir>/step2_adjudication_config.yaml \
    --out reports/tables/track_c_step2
```

Full per-trajectory and per-instance tables (including majority-resolution
detail, off-menu flags, and budget-degeneration fields) are written to
`reports/tables/track_c_step2/`.
