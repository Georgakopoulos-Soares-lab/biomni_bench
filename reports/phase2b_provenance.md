# Phase-2B source provenance — what can and cannot be proven

**Written:** 2026-08-10, after the post-Phase-2B review found that Phase 2B ran
from an uncommitted working tree. **Audit script:**
`scripts/phase2b_provenance_audit.py` (CPU only, read-only, ~30 s). **Tests:**
`tests/test_phase2b_provenance_audit.py` (8). Machine-readable output:
`<output_root>/phase2b_provenance/phase2b_provenance_inventory.csv` and
`phase2b_provenance.json`.

> **The failure, stated plainly.** Phase 2B is a pre-registered prospective
> experiment. All 600 of its run records say
> `project_git.commit = 2c0bfc18…, dirty = true`, and the file that implements
> the controller — `src/biomni_uncertainty/controller.py` — was **never
> committed**. The exact source tree that executed was therefore not captured by
> version control at run time, and **no commit in this repository can be
> honestly described as "the Phase-2B execution commit."** This document does
> not repair that. It establishes what the preserved artifacts do and do not
> prove, and records the rest as an unresolved limitation.

> **What is not in doubt.** The Phase-2B *result* reproduces exactly from the
> stored run artifacts — H1, H2, coverage, the selective table, matched compute,
> S4 and the sensitivity analysis were all recomputed by an independent script
> in the post-Phase-2B review, and the frozen controller re-simulated offline
> matches the online decision log on **0/150** instances. The provenance gap is
> about *auditability of the source*, not about the validity of the numbers.

---

## 1. The run window, and what the runs say about themselves

Derived from all 600 `metadata.json` files, not from a log line.

| fact | value | distinct values across 600 trajectories |
| --- | --- | ---: |
| first trajectory start | 2026-08-09 18:33:29 | — |
| last trajectory end | 2026-08-10 03:03:59 | — |
| `config_hash` | `ee5f8cd36bf6df89…` | **1** |
| `project_git` | commit `2c0bfc18…`, branch `master`, **dirty `true`** | **1** |
| `biomni_git` | commit `400c1f36…`, **dirty `false`** | **1** |
| hostname | `c561-007.stampede3.tacc.utexas.edu` | **1** |
| Slurm job | `3388121` | **1** |

The run is internally uniform: one config, one project state, one dependency
state, one node, one job. Nothing was swapped mid-run.

**The pinned dependency is fully attested.** `biomni_src` is still at
`400c1f366b96a35ca253e13c9b06c5076af41d65` with a clean working tree, and every
run recorded `dirty = false` for it. Biomni itself is not part of this problem.

---

## 2. Classification

Every Phase-2B-relevant file falls into exactly one class. **A filesystem
timestamp is treated as circumstantial and never as proof** — mtime is settable
and is not a cryptographic record. Where a stronger attestation exists it was
computed; where none exists the file is `UNPROVEN` and says so.
`tests/test_phase2b_provenance_audit.py` asserts that mtime alone can never
promote a file to `ESTABLISHED`.

### 2.1 `ESTABLISHED` — run-time version pinned (14 files)

| file | how it is pinned |
| --- | --- |
| **`configs/phase2b.yaml`** | **Cryptographic.** The stored `config_hash` `ee5f8cd3…` recomputes **bit-exactly** from the current file, and the full stored `config_snapshot` is **identical** to the live parse. |
| **`manifests/phase2b.jsonl`** | **Cryptographic.** `manifest_hash` recomputes to `7cb5da3ac345…`, the value frozen in `reports/phase2_protocol.md` before any inference ran. 150 instances. |
| `manifests/phase2b.groundtruth.jsonl` | tracked and byte-identical to `HEAD` |
| **`src/biomni_uncertainty/controller.py`** | **Behavioural.** See §3. |
| **`src/biomni_uncertainty/policy.py`** | **Behavioural** (§3) *and* tracked, byte-identical to `HEAD` |
| `sampling.py`, `benchmark.py`, `config.py`, `runner.py`, `budget.py`, `canonicalization.py`, `confidence.py`, `instrumentation.py`, `evaluation.py` | tracked and byte-identical to `HEAD` (`2c0bfc18…`), which is the commit every run recorded |

**On the config-hash check.** A naive recomputation *fails*, because
`configs/phase2b.yaml` stores `${ENV}` placeholders and the run expanded three of
them (`BIOMNI_UNC_OUTPUT_ROOT`, `BIOMNI_PATH`, `BIOMNI_UNC_EVAL1_PARQUET`). The
audit restores those three values from the stored snapshot before hashing. The
mismatch was an artifact of the environment, not of the file — and it is recorded
here because anyone re-running this check without the restoration will see a
false alarm.

### 2.2 `CHANGED_AFTER` — known to differ from what ran (3 files)

| file | change | does it affect the result? |
| --- | --- | --- |
| **`scripts/phase2b_verify.py`** | The **D-27 gate fix**, applied 2026-08-10 04:36:14, after the run ended 03:03:59. The version that gated the smoke test and the launch had the exact-string-match bug and reported 0.0%. | **No** — it is a monitoring tool, not part of trajectory generation or scoring. It is the reason a real halt condition was not caught in time (D-27), which is already on the record. |
| `scripts/phase2b_analyze.py` | last modified 04:41:49, after the run | **No** — post-run analysis only. Note the ordering: the stored result tables were written 04:42:31–32, *after* that edit, so the current file is the one that produced them. Independently reproduced in the post-Phase-2B review regardless. |
| `tests/test_phase2b_analyze.py` | 04:41:49 — this is when the D-27 regression test was added | **No** — test code. |

### 2.3 `UNPROVEN` — exact run-time bytes cannot be established (4 files)

| file | circumstantial evidence | what *is* attested |
| --- | --- | --- |
| **`scripts/phase2b_run.py`** | untracked; mtime 2026-08-02 11:29:14, a week before the run and unchanged since | **Its output is pinned** — see §4. Its *orchestration* is not. |
| `scripts/run_phase2b.sh` | untracked; mtime 2026-08-02 11:35:25 | nothing beyond the recorded endpoint/experiment id |
| `scripts/phase2b_supervise.sh` | untracked; mtime **2026-08-09 18:29:03**, four minutes before the run started | nothing; see §5 |
| `tests/test_controller.py` | untracked; mtime 2026-08-02 11:34:26 | nothing — test code, no bearing on the result |

---

## 3. Behavioural attestation of the controller

This is the strongest evidence available for the two files that actually decide
anything, and it is stronger than an mtime.

The hash-chained decision log stores, for every step of every instance: the
action, the **free-text `reason` string**, the support count, the agreement flag,
the resolved cluster key, and the exact ordered list of observed `run_id`s. Those
reason strings are f-strings generated inside `MandatoryK2.decide` and
`Abstaining.decide` — any edit to the decision logic, or even to the wording that
describes it, breaks the reproduction.

| check | result |
| --- | ---: |
| decision records in the committed logs | **434** |
| reproduced **exactly** by the current `controller.py` + `policy.py` | **434 / 434** |
| mismatches | **0** |
| hash chains verified end to end | **150 / 150** |

**Interpretation, stated carefully.** This proves the current files are
*behaviourally identical* to what ran, across every state the run actually
visited — 434 decisions covering all four stopping depths and both terminal
actions. It does **not** prove byte identity, and it says nothing about code
paths the run never entered. It is an attestation of behaviour on the observed
domain, and that is how it should be cited.

---

## 4. What is pinned about the untracked driver

`scripts/phase2b_run.py` cannot be proven byte-for-byte. What *can* be proven is
that every trajectory identity it emitted is the deterministic output of tracked
code plus the attested config and frozen manifest:

| recomputed from tracked code | matched |
| --- | ---: |
| `run_id` via `sampling.make_run_id` — **including the `shadow` condition, which `expand_runs` does not itself produce** | **600 / 600** |
| `requested_seed` = `seed_base(2000) + 100 + trajectory_index` | **600 / 600** |
| `prompt_hash` against the frozen manifest | **600 / 600** |
| `run_dir` via `sampling.run_dir_for`, against the actual on-disk location | **600 / 600** |

So the driver's **spec-generation path is attested**. Its **orchestration** —
concurrency, resume, and the commit-before-generate barrier that makes the
shadow-isolation argument work — is attested only indirectly, by the gate
invariants computed from artifacts: 150/150 instances have `consumed + shadow ==
4` with `consumed == depth`, all 166 shadow start timestamps post-date their
instance's terminal decision, and every step 1..depth has exactly one decision.
Those are strong invariants, but they are properties of the *output*, not of the
source.

---

## 5. An open observation about the launch path

Recorded because it bears on DEV-2/D-27's account of a *compressed auto-launch*,
and because the artifacts do not quite match it:

* `logs/phase2b_supervisor.log` ends at **2026-08-02 12:10:41** with
  `STATUS -> WAITING_FOR_SMOKE`, and `logs/phase2b_STATUS` still reads
  `WAITING_FOR_SMOKE`.
* The smoke test completed **2026-08-02 12:32**.
* The full run started **2026-08-09 18:33** — seven days later — with
  `scripts/phase2b_supervise.sh` last modified at **18:29:03** that day.

The supervisor process that logged on 2026-08-02 therefore did not launch the
full run, and the supervise script was edited immediately before the launch that
did happen. **This is an observation about the artifacts, not a correction to
D-27**, whose substantive point stands either way: the residual-failure gate
reported a false PASS, nothing blocked on it, and no test had exercised its
failure path. Whether the launch was automatic or hand-issued does not change
that. It is logged here so that a future reader is not misled by the word
"auto-launch" into thinking a supervisor decision is recoverable from the logs —
it is not.

---

## 6. The recovery snapshot commit

The working tree was committed as a **post-hoc provenance recovery snapshot**.

**What that commit is:** the current state of the repository, including the
files that were untracked during Phase 2B and the files that changed after it,
so that they exist in version control from this point forward and this document
can name their hashes.

**What that commit is NOT:** it is **not** the Phase-2B execution commit, and no
artifact may describe it as such. Every Phase-2B run record correctly says
`project_git.commit = 2c0bfc18…, dirty = true`; that record is accurate and is
not rewritten. The snapshot commit post-dates the run by hours and contains
files (`phase2b_verify.py`'s gate fix, `phase2b_analyze.py`, the post-Phase-2B
review, the Controller-v2 offline analysis) that did not exist in their current
form when the run executed.

No frozen artifact was modified: not the manifest, not the config, not a run
directory, not a decision log, not a result table, not a report of record. Git
history was not rewritten.

---

## 7. Limitations

1. **Byte-level provenance of four files is permanently unrecoverable.** No
   amount of later analysis can restore what was never recorded. §3 and §4
   substitute behavioural attestation where the artifacts allow it and say
   "unproven" where they do not.
2. **Behavioural attestation covers only the observed domain.** 434 decisions
   across 150 instances is a large domain, but a code path the run never entered
   is not covered.
3. **mtime evidence is circumstantial throughout** and is reported as such.
4. **The gate that ran is gone.** The buggy `phase2b_verify.py` was overwritten
   in place rather than superseded by a commit, so the exact code that produced
   the false PASS cannot be exhibited — only its documented behaviour (D-27) and
   the fix.
5. **This audit does not address the second blocker.** The residual trajectory
   failure rate remains **15.5%** (93/600), above the pre-registered 15% halt
   threshold, and is **deliberately not repaired here**.

---

## 8. Consequences for any future prospective run

Non-negotiable, and to be written into the next protocol:

1. **Commit before launch, and record the commit in the protocol.** A run whose
   `project_git.dirty` is `true` is not auditable, whatever else is preserved.
2. **Refuse to launch on a dirty tree.** The launcher should check
   `project_git.dirty` and exit non-zero, exactly as the halt gate now does — a
   gate that is not exercised is not a gate.
3. **Hash the source into the run record.** A `sha256` of every file the run
   imports, written into `metadata.json` at start, makes this entire audit a
   single equality check instead of a forensic exercise.
4. **Never overwrite a tool that produced a gating decision.** Fix forward in a
   commit so the version that made the decision remains exhibitable.

---

## 9. Reproduction

```bash
BIOMNI_UNC_OUTPUT_ROOT=<output_root> \
python scripts/phase2b_provenance_audit.py \
    --config configs/phase2b.yaml \
    --manifest manifests/phase2b.jsonl \
    --out <output_root>/phase2b_provenance
```

CPU only, read-only, no GPU, no model calls. Writes only under
`phase2b_provenance/`.
