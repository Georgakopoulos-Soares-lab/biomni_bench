# Prerequisites for a scientifically valid constructed-verification experiment

**Written:** 2026-08-10, immediately after the Track-C diagnostic
(`reports/track_c_diversity_diagnostic.md`, D-30). **Status: design note only.
Nothing here is implemented.** No GPU work, no prospective manifest, no
benchmark expansion.

## Why this note exists

`reports/track_c_diversity_diagnostic.md` §11 concluded that resampling does not
produce independent verification and named five things a real `VERIFY` action
would need. That conclusion is only trustworthy if the *measurement* it rests on
is trustworthy. Three of the diagnostic's headline numbers are downstream of
known-broken measurement infrastructure:

* the 35.7%-zero-tool-call and evidence-channel-error numbers are measured
  against an environment already flagged in Phase 0 as missing the full E1
  install (`reports/phase0_environment.md` §157);
* the "retrieval content is unmeasurable" limitation (§3, §10 of the
  diagnostic) means no result in this project has ever been checked against
  *what evidence was actually retrieved*, only against counts;
* the unresolved 15.5% residual trajectory failure rate (D-27, D-29) means a
  material fraction of any future sample will be infrastructure noise, not
  signal, exactly as it was for Controller v1's abstention rule
  (`reports/post_phase2b_assessment.md` §4.1).

Building `VERIFY` on top of any of these would not be testing whether
independent verification helps — it would be testing whether the environment
got fixed. **These are scientific prerequisites for a valid experiment, not
general infrastructure cleanup**, for the same reason the context-overflow
repair in Phase 1.5 was not cleanup: an experiment that runs on a broken
measurement channel produces a result about the channel, not about the
hypothesis (`reports/research_north_star.md`, "the failure mode to watch").

None of the five items below is optional if the goal is a defensible causal
claim about `VERIFY` vs `RESAMPLE`. They are ordered by dependency, not by
effort.

---

## 1. Repair the literature/evidence channel

**What's broken, precisely.** From the diagnostic: 1,395 tool calls, 30.0%
error overall, concentrated in exactly the tools a `VERIFY` action would need —
`query_pubmed` 68.9%, `advanced_web_search_claude` 77.0%, `query_scholar`
80.0%. Root causes are import failures (`No module named 'pymed'`,
`No module named 'anthropic'`, `cannot import name 'advanced_web_search_claude'`)
— missing dependencies, not tool-design or query-formulation problems.
Structured databases (Ensembl, ClinVar, GWAS Catalog, Monarch, OpenTargets) are
already healthy at 6–11% error and do not need this work.

**Why it gates everything else.** A `VERIFY` action is defined by seeking
independent evidence. If the channel that would carry that evidence fails 7 in
10 times, any comparison between `VERIFY` and `RESAMPLE` measures which one
degrades more gracefully under tool failure, not which one verifies better.

**What "done" looks like.** The specific missing imports installed or the
affected tools substituted; the same per-tool error-rate table from the
diagnostic (`tc_tool_failure_by_tool.csv`) re-run and showing single-digit error
rates on the literature tools, matching the structured-database tools already
achieve. This does not require the full E1 environment — Phase 0 measured that
as >10 h and >30 GB for a broader repair than this narrow one needs; the
imports failing here are a handful of specific packages, not the whole
environment.

---

## 2. Instrument retrieval identity and content, not just counts

**What's missing, precisely.** `retrieval_end` events record only
`{"tools": N, "data_lake": N, "libraries": N, "know_how": N}` — counts. No event
anywhere records *which* tools, *which* data-lake entries, or *what content* was
retrieved. `diversity.py`'s evidence-level metric is therefore built from
tool-call arguments (what was *asked for*) and never from retrieval results
(what was *found*) — a real gap stated in the diagnostic's own limitations
(§10.2).

**Why it gates the experiment, not just the metric.** The entire scientific
claim of a `VERIFY` action is that it obtains evidence independent of what a
`RESAMPLE` trajectory already had. Without logging *which* evidence each
trajectory actually used, "independent evidence" cannot be verified — only
asserted. A future report claiming "VERIFY used different evidence than the
disagreeing trajectories" would be unfalsifiable exactly the way "the
controller never saw a future trajectory" was unfalsifiable before the
hash-chained decision log existed (`controller.py`'s own rationale). The
principle is the same one that produced that log: a claim about isolation must
be checkable from artifacts, not asserted.

**What "done" looks like.** Retrieval events extended to record retrieved item
identities (tool names, data-lake source IDs, or a content hash per retrieved
document) — not necessarily full content, which may be large, but a stable
identifier sufficient to compute overlap between two trajectories' evidence
sets. A regression test analogous to the leakage tests in `test_policy.py`
confirming the identifiers are actually populated, not silently empty.

---

## 3. Reduce residual trajectory failure below the halt threshold

**What's broken, precisely.** 15.5% of Phase-2B trajectories (93/600) hit the
Arm-2 circuit breaker (`budget_terminated_consecutive_runaway`), above the
pre-registered 15% threshold in `reports/phase2_protocol.md` §11. This is not
new — it is the halt condition D-27's gate bug hid — and it has been left
unrepaired by explicit decision (D-29, D-30) pending exactly this design phase.

**Why it gates the experiment.** §4 of the diagnostic separated failure (stratum
A, 15 of 150 instances) from substantive disagreement (stratum B, 53 of 150)
precisely because conflating them was what made Controller v1's abstention rule
look like an uncertainty rule when it was mostly a failure detector
(`reports/post_phase2b_assessment.md` §4.1: 15 of 29 abstentions had ≤1 usable
trajectory). A `VERIFY`-vs-`RESAMPLE` comparison run at 15%+ residual failure
risks the identical confound: any measured difference could be "VERIFY handles
dead trajectories differently" rather than "VERIFY handles disagreement
differently." The comparison needs a clean stratum-B population to be
interpretable.

**What "done" looks like.** The residual failure rate, recomputed by
`scripts/phase2b_verify.py`'s corrected gate (already exercised end-to-end,
D-29 §0) on a fresh sample, at or below 15% — ideally materially below it, since
15% is a halt threshold, not a target. Given `rare_disease_diagnosis` alone
accounts for 33.0% of Phase 2B's failures against 12.0% for the other nine
tasks pooled, this may be addressable by task-level guard tuning rather than a
repeat of the full Arm 1/2/3 ablation — but that is a decision for
implementation, not for this note.

---

## 4. Validate that the repairs do not change behavior on previously-healthy controls

**Why this is a prerequisite and not a nice-to-have.** Phase 1.5's own history
is the cautionary example: the Arm 3 repair (all guards, including a hard token
cap) eliminated the target failure but **collapsed reward to 0.000 on two
control strata that were fine at baseline**
(`context_overflow_forensics.md` §10, `PROJECT_STATUS.md` "Ablation verdict").
Arm 2 was selected specifically because it passed a control bar that Arm 3
failed. Any of items 1–3 above could have the same failure shape: fixing the
literature channel could change tool-selection behavior on tasks where it
already worked; new retrieval logging could add latency or truncation pressure
that interacts with the token budget guards; failure-rate tuning could suppress
genuine signal along with genuine noise.

**What "done" looks like**, mirroring the Arm-2/Arm-3 control-stratum method
that is already validated in this project: a small paired re-run (order of
Phase 1.5's 6–24 trajectories, not a new large sample) on instances that were
**healthy under the current environment** — high coverage, low failure rate,
matching Phase 1/2A/2B reward — comparing before/after the repairs on reward,
coverage, and mean cost. The decision rule is the one already used and
documented: accept the repair only if it does not regress the control stratum,
exactly as Arm 2 was preferred over Arm 3 for that reason. This is a **CPU-adjacent,
small-scale check**, not a new benchmark.

---

## 5. Define RESAMPLE vs VERIFY operationally, before any trajectory is generated under either label

**Why this must be settled on paper first.** `reports/phase2_protocol.md` §2.1
already states the current controller's action space excludes `VERIFY` and
`REPAIR`, and `CLAUDE.md`'s scientific integrity rules explicitly forbid
conflating "infrastructure retry, workflow repair, independent verification and
scientific self-correction" — treating them as interchangeable was flagged as a
standing risk before Track C even started. The diagnostic's own recommendation
depends on a sharp distinction: `RESAMPLE` is "run the same prompt again, let
temperature vary the trajectory"; `VERIFY` is "run a trajectory whose *plan* is
different by construction." Without an operational definition fixed in advance,
any future implementation could silently blur back into resampling — which is
the exact failure mode this diagnostic just spent its budget ruling out as
useless (§5–6 of the diagnostic: disagreeing trajectories have statistically
indistinguishable plans from agreeing ones).

**What "done" looks like**, as a specification to write, not code to run:

* An explicit, checkable criterion for what makes a trajectory's plan "different
  by construction" — e.g., a distinct required methodology, a distinct required
  evidence source, or an explicit critique-of-the-leading-answer framing —
  stated precisely enough that `pairwise_diversity`'s existing plan-Jaccard
  metric could, in principle, be used to *verify after the fact* that a `VERIFY`
  trajectory's plan differed materially from the trajectories it is checking.
  This reuses `src/biomni_uncertainty/diversity.py` as an audit tool for the
  next experiment, the same way the hash-chained decision log became an audit
  tool for shadow isolation.
* A statement of what `VERIFY` may and may not see — mirroring
  `TrajectoryView`'s `FORBIDDEN_VIEW_FIELDS` barrier — so a `VERIFY` trajectory
  cannot trivially reproduce the plan it is meant to check by reading it.
* A pre-committed rule for what counts as "the plan was genuinely different"
  being satisfied or violated, so that a future report is not the first place
  this gets decided.

---

## What this note is not

* Not an implementation plan. No code, config, or manifest is proposed here.
* Not a benchmark design. Item 4's control check is a small paired re-run on
  existing instance pools, not a new sampling exercise.
* Not a green light. Completing items 1–5 makes a constructed-verification
  experiment *possible to run validly* — it does not itself decide whether that
  experiment should be run, which per D-29 also requires a committed tree and a
  residual failure rate under threshold at launch time, and per the north star's
  five questions (`reports/research_north_star.md`) should be re-asked once
  these prerequisites are actually in hand rather than assumed.

## Next action

None started. This note is presented for review alongside
`reports/track_c_diversity_diagnostic.md`. Awaiting direction on which,
if any, of items 1–5 to begin.
