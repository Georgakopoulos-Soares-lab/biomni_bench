# The RESAMPLE / VERIFY specification

**Written:** 2026-08-10. **Status: specification only. Nothing here is
implemented.** No code changes, no config, no manifest, no GPU work. This
completes prerequisite item 5 of `reports/verify_prerequisites.md` (D-31), and
is a precondition for items 1–4, not a follow-on to them: the audit criteria in
§5 determine what the retrieval-provenance instrumentation in item 2 must
actually record.

## Why this has to be settled on paper before anything else

`reports/track_c_diversity_diagnostic.md` (D-30) found that ordinary resampling
does not produce independent verification: trajectories that disagree have
statistically indistinguishable plans from trajectories that agree (plan
Jaccard 0.546 vs 0.538, against a same-task-different-question control of
0.301). If a future `VERIFY` action is implemented without a precise,
mechanically checkable difference from `RESAMPLE`, it will silently collapse
back into resampling under the same pressure — an agent solving a task freely
gravitates to the same plan regardless of instruction, unless something
external constrains it. `CLAUDE.md`'s scientific integrity rules already name
this exact risk: infrastructure retry, workflow repair, independent
verification and scientific self-correction must never be conflated. This
document is the fix for that risk, written before any of it is built.

`REPAIR` (fixing a broken workflow rather than resampling around it) is named
in the original Phase-2 action space (`reports/phase2_protocol.md` §2.1,
`reports/phase2_report.md` §10.5) but is **out of scope for this note**, which
was scoped to VERIFY only. Keeping the two separate is itself part of the
discipline this document exists to enforce.

---

## 1. RESAMPLE — formal definition

**RESAMPLE is what every trajectory in Phase 1 through Phase 2B already is.**
This section exists only to state its properties precisely enough that VERIFY
can be defined as a departure from them.

| property | value |
| --- | --- |
| task | the original task instance, unmodified |
| required methodology | none — the agent is free to choose any plan |
| required evidence source | none — the agent is free to choose any tool, or none |
| starting state | the task prompt only; no other trajectory's output is visible |
| independence mechanism | temperature (0.7) and sampling noise only |
| output | a candidate answer with the same status as any other candidate |

**RESAMPLE's demonstrated behaviour** (D-30, the empirical floor any VERIFY
definition must beat): same-instance trajectory pairs — whether they end up
agreeing or not — land in a **plan-Jaccard band of 0.51–0.55** with
overlapping confidence intervals. Whatever independent variable separates
agreement from disagreement in this system, it is not visible in the opening
plan. That band is the reference distribution for §5.

---

## 2. VERIFY — formal definition

**VERIFY is a distinct trajectory type, triggered by a distinct controller
action, that starts from a specific candidate claim and is required to test it
through a different epistemic operation than producing it.**

A VERIFY trajectory must satisfy all five of the following. Any one violated
means the trajectory is not a VERIFY trajectory, whatever it is labelled —
this is a definition, not a request.

1. **It starts from a specific candidate claim, not from the bare task.** A
   VERIFY trajectory without a claim to check is a RESAMPLE trajectory that
   forgot its name.
2. **It is required to test that claim, not to re-solve the task.** Producing
   a fresh independent answer to the same prompt and comparing it to the
   candidate is *not* VERIFY — that is exactly the resampling-and-voting
   behaviour D-30 found useless. VERIFY's object is the claim, not the task.
3. **It must differ from the candidate's method by construction**, along at
   least one of: methodology, evidence source, or computational checking
   procedure (§4 defines this per mode). "By construction" means the
   difference is imposed by the harness before generation starts, not left to
   emerge from temperature. This is the direct answer to D-30's finding —
   since divergence does not occur on its own, it must be engineered.
4. **It must not see hidden ground truth.** Same rule as every policy in this
   project (`CLAUDE.md`, `TrajectoryView`/`FORBIDDEN_VIEW_FIELDS`).
5. **It must not simply copy the original trajectory's reasoning.** Enforced
   two ways: structurally, by never exposing that reasoning to VERIFY in the
   first place (§3); and empirically, by the post-hoc audit (§5), because
   structural prevention alone is not self-certifying — the same principle
   behind the hash-chained decision log existing on top of "the code does not
   pass forbidden fields."

### Where VERIFY sits in the controller's action space

`reports/phase2_protocol.md` §2.1 already reserves the slot. Extending
`policy.Decision.action` with a fourth value alongside `ACCEPT` / `CONTINUE` /
`ABSTAIN`:

```
VERIFY = "VERIFY"
```

A policy that returns `VERIFY` names **which candidate claim** to check and
**which mode** (§4) to use; the harness generates a VERIFY trajectory instead
of an ordinary next resample. This is a controller-design decision for a later
document, not decided here — this note only fixes what a VERIFY trajectory
*is* once one is requested.

---

## 3. What VERIFY may see: `VerifyView`

Modelled directly on `policy.TrajectoryView`, which already solved this
problem for what a *controller* may see. `VerifyView` solves it for what a
*verification trajectory* may see, and the two barriers are independent: a
VERIFY trajectory must satisfy both `FORBIDDEN_VIEW_FIELDS` (no ground truth)
and the narrower restriction below (no access to the reasoning it exists to
check).

### 3.1 Permitted fields

| field | why it is permitted |
| --- | --- |
| `task_name`, `task_instance_id` | needed to run the task at all |
| `task_prompt` | the original question — VERIFY answers the same question, differently |
| `candidate_answer` | the specific claim under test — required by definition item 1 |
| `verification_mode` | which of §4's modes is requested; assigned externally, never chosen by the trajectory itself |
| `claims_to_check` *(optional, mode-dependent)* | a structured decomposition of the candidate into specific checkable sub-claims, e.g. "the computed ORF start position", populated only when the controller has such structure available |
| `verify_run_id` | its own identity, for provenance — carries no information about the original |

### 3.2 Forbidden fields — explicit, not implied

Analogous to `FORBIDDEN_VIEW_FIELDS`, and enforced the same way: by a fixed
field list plus a test, not by convention.

```
FORBIDDEN_VERIFY_FIELDS = frozenset({
    # ground truth — identical bar to FORBIDDEN_VIEW_FIELDS
    "reward", "strict_reward", "correct",
    "evaluation_status", "evaluation_error",
    # the reasoning VERIFY exists to check independently of
    "original_transcript", "original_events", "original_plan_text",
    "original_tool_calls", "original_code_blocks",
    # anchoring / sycophancy risk
    "original_final_confidence",
    # information no single trajectory has online (D-21's own barrier)
    "other_trajectory_answers", "support_count", "agreement_fraction",
    "trajectory_index",
    # would let VERIFY silently re-derive the same trace via the filesystem
    "original_run_dir",
})
```

**Two entries need justification because they are stricter than
`TrajectoryView`'s bar, not just equal to it:**

* **`original_final_confidence` is forbidden even though it is not ground
  truth.** A VERIFY trajectory that sees "the candidate was 95% confident"
  before forming its own judgement is exposed to anchoring — the general
  finding that a stated confidence value shifts an independent evaluator's
  own estimate even when the evaluator "knows" it should ignore it. Since
  S4 (`final_confidence == 1.00`) is a live candidate signal
  (`reports/phase2_report.md` §6), letting VERIFY see it would let a future
  controller partly re-derive S4 through VERIFY's verdict rather than testing
  VERIFY on its own terms.
* **`original_transcript`/`original_plan_text`/`original_tool_calls` are
  forbidden**, which is stricter than merely "not required." This is
  definition item 5 enforced structurally: if VERIFY cannot see the original
  reasoning, it cannot copy it, and the audit in §5 becomes a check on the
  harness's plumbing rather than the trajectory's honesty.

**What is not on the forbidden list, and why:** the task prompt and the
candidate answer are visible, because a VERIFY trajectory that does not know
what it is checking cannot check anything. This is the necessary information
gap — VERIFY sees strictly less than `RESAMPLE`'s next trajectory would if
that trajectory had somehow been told a candidate existed, and strictly less
than the original trajectory saw of its own reasoning.

---

## 4. VERIFY modes

Three, matching the brief, kept deliberately minimal rather than grown into a
taxonomy — per `reports/research_north_star.md`'s standing constraint against
building machinery beyond what the evidence currently supports.

### Mode A — computational verification

**Definition.** Independently re-derive a specific intermediate or final
result from the task's raw inputs, without reference to the candidate's
stated value, and compare.

**Required behaviour**, checkable structurally:
1. at least one code execution that computes the checked quantity from inputs
   present in the task prompt (not from `candidate_answer`);
2. the derivation's verdict (`confirmed` / `refuted` / `inconclusive`) is
   produced by comparing the independently-derived value to
   `candidate_answer`, not the reverse.

**What this mode does not require.** The code need not differ from what the
original trajectory ran — mode A's claim is independence of *derivation*, not
novelty of *implementation*. `lab_bench_seqqa/i0027` (the diagnostic's case
study: four trajectories share a near-identical plan and disagree on a
deterministic ORF computation) is exactly mode A's target case: the useful
check is "does independently re-deriving this value from the sequence agree
with the candidate", not "does a differently-worded plan happen to agree."

### Mode B — evidence verification

**Definition.** Independently retrieve evidence relevant to the candidate
conclusion, from a source not already consulted by the candidate trajectory.

**Required behaviour:**
1. at least one successful tool call to a literature or database source;
2. the query issued is not required to differ lexically from the original
   (the same search term is a legitimate way to check a claim), but the
   **source or retrieved evidence identity** must — this is exactly why
   prerequisite item 2's retrieval-identity logging is required before mode B
   can be audited at all (§5.3).

**Precondition this mode inherits from `reports/verify_prerequisites.md`
item 1:** mode B is only meaningful once the evidence channel it depends on
has a reliability comparable to the structured-database tools already at
6–11% error. At the 68–80% error rates measured in D-30, a mode-B verdict of
`inconclusive` would be indistinguishable from a mode-B verdict blocked by
infrastructure failure — the identical confound D-30 §4 separated for
Controller v1's abstention rule, recurring one level up.

### Mode C — adversarial verification

**Definition.** Actively search for evidence or reasoning that would falsify
the candidate or support a specific alternative, rather than search neutrally
for support.

**Required behaviour:**
1. the verification prompt explicitly instructs the trajectory to seek
   disconfirming evidence or a specific named alternative, not to confirm;
2. the trajectory must produce a verdict on both directions it was asked to
   check: whether disconfirming evidence was found, and whether it changes
   the assessment.

**Relationship to mode B.** Mode C is mode B's query strategy inverted, not a
different evidence channel — it inherits the same evidence-channel precondition.

### What all three modes share, and what none of them may do

* All three require a `verdict ∈ {confirmed, refuted, inconclusive}` with a
  free-text `verdict_basis`.
* None of the three may return `confirmed` on the strength of *agreement
  alone*, i.e. "I got the same answer" is not by itself a valid basis for
  `confirmed` in any mode — that is a RESAMPLE outcome wearing a VERIFY label,
  and the audit in §5 is designed to catch exactly this failure.

---

## 5. The audit criterion

**Principle.** The audit does not decide *whether* a VERIFY trajectory was
generated under the right instructions — the harness already knows that. It
decides *whether the instruction was actually honoured*, computed entirely
from stored artifacts after the fact, exactly the way `DecisionLog.verify()`
checks the controller's hash chain rather than trusting that generation and
commitment happened in the right order.

**On thresholds.** The brief is explicit that success must not be defined by
an arbitrary lexical-Jaccard number unless the stored data justify it. The
data available (D-30) justify a *reference distribution*, not a fixed
constant: same-instance `RESAMPLE` pairs, regardless of whether they agree,
land in a measured band. The audit is therefore a **rejection test against
that band**, not a threshold pulled from nowhere.

### 5.1 The RESAMPLE reference band (the null hypothesis VERIFY must beat)

From `<output_root>/track_c/results/tc_diversity_descriptives.csv`, both-usable
within-instance pairs, instance-clustered 95% CI, n=566/258 pairs:

| metric | RESAMPLE band (mean [95% CI]) |
| --- | --- |
| plan Jaccard | 0.540 [0.515, 0.566] |
| tool-set Jaccard | 0.442 [0.380, 0.508] |
| tool-sequence similarity | 0.409 [0.358, 0.463] |
| query Jaccard | 0.328 [0.287, 0.372] |

This is computed over *both* agreeing and disagreeing RESAMPLE pairs, because
D-30's finding is precisely that agreement status does not move these numbers
— so the combined band is the correct null, not a cherry-picked half of it.

### 5.2 The structural audit (available today, no new instrumentation)

For a VERIFY trajectory checking candidate `c`, compute
`pairwise_diversity(verify_trace, c_trace)` from the existing
`src/biomni_uncertainty/diversity.py` — used here exactly as
`reports/verify_prerequisites.md` item 5 anticipated, as a post-hoc audit tool,
not a generation-time input.

**Pass condition, mode A:** at least one code execution present that derives
the checked quantity from task inputs (structural check, not a similarity
score — mode A's independence claim is about derivation, not wording, per §4).

**Pass condition, modes B and C:** `query_jaccard(verify, candidate)` **or**
`tool_seq_similarity(verify, candidate)` falls **below the RESAMPLE band's
lower 95% CI bound** (0.287 and 0.358 respectively) — i.e., the verification
trajectory's evidence-seeking is statistically distinguishable from an
ordinary resample of the same instance, not merely numerically lower.

**All modes, always:** `plan_jaccard(verify, candidate)` need not fall outside
the RESAMPLE band — VERIFY is checking the *same claim*, so some plan overlap
is expected and is not itself evidence of copying. What §3's structural
barrier already prevents (VERIFY cannot see the original plan) is the failure
mode a Jaccard check on the plan would otherwise have to catch. This is by
design: prevent the failure structurally where possible, audit it statistically
only where structural prevention is not available (evidence and tool choice,
which VERIFY necessarily generates fresh and could still converge on by habit
— exactly as §3 of the diagnostic showed tool choice is only weakly
question-specific to begin with).

### 5.3 The evidence-identity audit (blocked on prerequisite item 2)

**Cannot be computed with current instrumentation.** `retrieval_end` events
record counts only. Once item 2 lands, the audit gains its strongest and most
direct check:

**Pass condition, mode B:** the set of retrieved evidence identifiers (item
2's stable identifiers/hashes) shares **no more than a stated small fraction**
of members with the candidate trajectory's retrieved-evidence set. Unlike
§5.2's lexical checks, this is a direct measurement of the thing VERIFY claims
to provide — independent evidence — rather than a proxy for it, and it is the
reason item 2 is a prerequisite for VERIFY rather than a parallel
nice-to-have. No numeric threshold is fixed here; it must be calibrated from
the first batch of real retrieval-identity data the same way §5.1's band was
calibrated from real trace data, not chosen in advance of seeing any.

### 5.4 What a failed audit means

A VERIFY trajectory that fails its pass condition is **not silently
recategorized as RESAMPLE and not silently discarded.** It is logged as
`verify_audit_status: failed`, with the failing metric and value, and is
excluded from any claim that VERIFY produced independent evidence for that
instance — the same discipline `reward_abstain_zero` enforces for abstention:
a soft failure must never be allowed to inflate a headline number by
disappearing quietly.

---

## 6. What this document does not decide

* **Whether VERIFY beats RESAMPLE.** Nothing here is an efficacy claim. This
  is a specification of what counts as attempting VERIFY at all.
* **Controller wiring** — how a policy chooses to fire `VERIFY`, on which
  states, with what budget. A separate design, downstream of this one.
* **Mode-selection policy** — which of A/B/C to request for a given claim.
  Left open; the diagnostic's case studies suggest mode A for
  computational tasks (`lab_bench_seqqa`) and mode B/C for evidence-dependent
  ones (`gwas_causal_gene_*`, `rare_disease_diagnosis`), but that mapping is
  not fixed here.
* **The §5.3 numeric threshold**, deliberately left uncalibrated until
  prerequisite item 2 produces real data to calibrate it from.

---

## 7. Consequence for the remaining prerequisite items

This specification is now the requirements document for item 2's
instrumentation work: retrieval-identity logging must be sufficient to
compute §5.3's evidence-overlap audit, which requires stable identifiers *per
retrieved item*, not merely per tool call. That requirement is carried forward
into `reports/evidence_channel_repair.md` when item 2 is executed.

**Status: frozen for the purposes of proceeding to item 2.** Revisiting this
definition after seeing VERIFY trial data is permitted only as a labelled,
explicit revision — never a silent edit — per the same rule this project
applies to every other frozen protocol.
