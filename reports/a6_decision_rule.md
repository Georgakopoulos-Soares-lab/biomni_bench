# A.6 — semantic discriminability probe: decision rule, frozen before any AUROC exists

**Written:** 2026-08-11T15:05Z. **Status: FROZEN.** No AUROC, and no feature
value of any kind, had been computed when this file was committed. The feature
family, the primary feature, and the multiplicity correction are all fixed
below, in advance — A.4's lesson was that a nominal hit died under a correction
applied *post hoc*, and that failure mode is closed here by declaring the
correction first.

---

## 1. What this probe is for

A.4 tested **structural** trace features (tool counts, token counts, call
counts) and found no usable separating signal. `singled_out` — the measure that
carried A.5b — is a **semantic** feature, and A.4 never covered that class. The
Stage C capsule format is frozen at Stage C's start and cannot be revisited, so
if a semantic feature discriminates it has to be known **now** or it can never
be exposed to the verifier at all.

Neither outcome gates Stage C's launch. Both are useful:

* **DISCRIMINATES** → the capsule exposes the feature, and the interpretation
  table gains a cell: *signal existed in the traces and the verifier failed to
  use it.*
* **NULL** → A.4's null strengthens materially, and a Stage C NO-GO becomes
  attributable to the traces **with positive evidence** rather than by
  elimination.

## 2. The leakage barrier — the load-bearing part

**A.5b's `singled_out` took ground truth as an input**: it measured whether a
trajectory discusses *the correct answer* preferentially. That construction is
valid for an audit, which is allowed to look at labels, and **invalid here**,
because a Stage C capsule is computed at inference time when no label exists.
It cannot be reused, and is not.

**Reformulation, entirely label-free:** for each usable trajectory, measure how
preferentially it discusses **its own committed answer** relative to the other
candidates present for that instance. The trajectory's committed answer and the
instance's candidate set are both available without ground truth.

**The label enters only at evaluation**, as the target of the AUROC, never as
an input to any feature.

Enforcement, not just intent:

* Feature extraction receives only `(trajectory text, committed answer,
  instance candidate set)`. It is never passed `reward`, `correct`,
  `strict_reward`, or the ground-truth answer.
* A test asserts that no ground-truth field is reachable from the
  feature-extraction path, in the spirit of `policy.FORBIDDEN_VIEW_FIELDS` and
  D-32's `FORBIDDEN_VERIFY_FIELDS`.
* Extraction and normalisation reuse A.5b's code **including both of its bug
  fixes** — the prose-vs-gene-list candidate regex, and the repeated-strip
  normaliser that sees `'BRCA1'.` as `BRCA1`.

## 3. Population

All **usable** trajectories on the frozen 78 stratum-B instances: 176 from
`phase2b` + 87 from `phase1_pooled` = **263 trajectories** across 78 instances.
"Usable" = completed with a parseable answer; it is a label-free property.
(Counted before this file was frozen; counting does not involve labels.)

Target: **discriminate correct from incorrect trajectories.** AUROC with an
**instance-clustered** bootstrap (D-13: instances are the resampling unit, never
trajectories).

## 4. The feature family — fixed now, in full

Four features. No feature may be added, removed, or redefined after this file is
committed.

| # | name | definition | label-free? |
| --- | --- | --- | --- |
| **P** | `own_answer_share` | mentions of the trajectory's **own committed answer** ÷ mentions of **any** candidate for that instance, in model-generated text | yes |
| S1 | `n_competing_candidates_discussed` | count of *other* instance candidates mentioned at least once (were alternatives considered at all) | yes |
| S2 | `hedging_near_answer` | count of hedging markers in the closing segment (final 20% of model text) | yes |
| S3 | `closing_concentration` | share of own-answer mentions falling in the closing segment (final 20%) | yes |

**Hedging marker list, fixed now** (case-insensitive, word-boundary matched, so
it cannot be tuned later): `may`, `might`, `possibly`, `perhaps`, `unclear`,
`uncertain`, `not certain`, `hard to say`, `difficult to determine`,
`insufficient`, `cannot determine`, `ambiguous`, `speculative`, `tentative`,
`appears to`, `seems to`, `likely` , `probably`, `suggests`.

**Model text** = AIMessage content with `<observation>` blocks stripped, exactly
as in A.5b, so tool and code output is never mistaken for the model's own
reasoning.

**Primary feature: `own_answer_share` (P).** Declared primary because it is the
direct label-free analogue of the measure that carried A.5b, and because it is
the feature a capsule could most cheaply expose. S1–S3 are secondary.

## 5. Multiplicity correction — fixed now

**Bonferroni across the whole declared family of 4.** Every feature is tested at
α = 0.05 / 4 = 0.0125, i.e. a **98.75% instance-clustered bootstrap interval**.
The nominal 95% interval is also reported, for transparency and to make any gap
between the two visible rather than arguable — but **the verdict keys on the
corrected interval only**.

## 6. Decision rule

Let *corrected CI* be the 98.75% instance-clustered bootstrap interval.

* **DISCRIMINATES** — the **primary** feature's corrected CI excludes 0.5 (in
  either direction; an inverse discriminator is still a discriminator, and its
  direction is reported). Stage C's capsule exposes `own_answer_share`.
* **DISCRIMINATES (secondary)** — the primary's corrected CI covers 0.5 but some
  secondary feature's corrected CI excludes it. Reported as a secondary finding,
  explicitly labelled as such; Stage C's capsule may expose that feature.
* **NULL** — no feature's corrected CI excludes 0.5.

**No feature may be promoted to primary after the fact**, and a nominal-only hit
(95% excludes 0.5, 98.75% does not) is reported as **multiplicity noise, not
signal** — the exact outcome A.4 produced and the reason this file exists.

## 7. Provenance

CPU only, no GPU, no model calls, no new instances. Reads only frozen artifacts.
Result reported in `reports/stage_a_decomposition.md` (A.6 section) and a new
`D-` entry; this file is not edited afterwards.
