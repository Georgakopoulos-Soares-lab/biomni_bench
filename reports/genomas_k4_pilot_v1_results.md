# GenoMAS K=4 pilot v1 — execution and results

Status: **COMPLETE**. All 12 preregistered tasks ran to completion (48/48
requested trajectories attempted, 42 completed, 6 failed and correctly
classified — never silently scored). This report is the preregistered
reliability analysis called for in
`reports/genomas_k4_pilot_v1_preregistration.md`. Nothing beyond this pilot
was started.

## Pre-flight verification (before any trajectory)

- New Slurm allocation confirmed: job `944566`, partition `gh`, node
  `c608-092`, 48h walltime (`2026-08-26T17:37:24` → `2026-08-28T17:37:24`).
- GPU confirmed clean: 1× GH200 120GB, 0 MiB used at allocation start.
- Host RAM confirmed: 212 GiB total, ~175 GiB available at start (some
  pre-existing swap usage noted, see Memory/OOM section).
- Frozen preregistration manifest re-verified byte-for-byte
  (`sha256sum` matched `71a9adab37c1489750b9e84210940c2a6de5fa804fa96d5c599eb76eb5df6399`
  recorded at preregistration time).
- Held-out reference bundle re-verified: 87/87 files, unchanged.
- GenoMAS worktree re-confirmed at the exact pinned commit
  `d6365a700794587b53958db3bf22bb1fb80c3451`, clean.
- vLLM relaunched **exactly** per the frozen launch command (same `CC=nvc++`
  and `libcudart.so` shim environment fixes as the fresh admission ladder;
  the flashinfer JIT cache on `/home1` was reused cleanly — same GH200
  `sm_90a` architecture as the node that built it). Confirmed healthy
  (`max_model_len: 32768`) before the first trajectory started.

No protocol parameter was changed from the frozen manifest. No trajectory
was retried.

## Execution timeline

Sequential, one task at a time, exactly as frozen. Total wall-clock:
**33.94 hours** (`2026-08-26T22:45:15Z` → `2026-08-28T08:41:41Z`), within
the preregistered 34–45 h estimate.

| # | Task | Elapsed | Exit |
| - | --- | ---: | --- |
| 1 | `Bile_Duct_Cancer` | 1h20m | 0 |
| 2 | `Angelman_Syndrome` | 0h51m | 0 |
| 3 | `Colon_and_Rectal_Cancer` | 1h53m | 0 |
| 4 | `Alopecia` | 2h54m | 0 |
| 5 | `Adrenocortical_Cancer` | 5h13m | 0 |
| 6 | `Allergies` | 4h48m | 0 |
| 7 | `Ocular_Melanomas::Age` | 1h21m | 0 |
| 8 | `Ankylosing_Spondylitis::Age` | 1h16m | 0 |
| 9 | `Lower_Grade_Glioma::Age` | 2h21m | 0 |
| 10 | `Aniridia::Age` | 1h57m | 0 |
| 11 | `Bladder_Cancer::Age` | 5h11m | 0 |
| 12 | `Alzheimers_Disease::Age` | 4h49m | 0 |

Every per-task campaign script exited 0 (the script itself never crashed;
individual trajectory failures within a task are handled and recorded, not
propagated as a campaign-level crash). The driver never needed to abort for
an unhealthy endpoint — vLLM stayed up for the entire 34 hours.

## Per-trajectory results

`official_reward` is `selection_metrics.average.accuracy / 100` from the
unchanged, pinned `GenoMAS/eval.py`. Rows with no reward were execution or
artifact-contract failures (see Failure analysis) — never scored as wrong.

| Task | k4_00 | k4_01 | k4_02 | k4_03 |
| --- | --- | --- | --- | --- |
| `Bile_Duct_Cancer` | **contract-fail** | 1.0 | 1.0 | 0.0 |
| `Angelman_Syndrome` | **contract-fail** | 1.0 | **contract-fail** | 1.0 |
| `Colon_and_Rectal_Cancer` | 0.0 | 0.0 | 0.0 | 0.0 |
| `Alopecia` | 0.0 | 1.0 | 0.0 | **OOM (SIGKILL)** |
| `Adrenocortical_Cancer` | 0.0 | 0.0 | 0.0 | 0.0 |
| `Allergies` | 0.0 | 0.0 | **crash (SIGSEGV)** | 0.0 |
| `Ocular_Melanomas::Age` | 1.0 | 1.0 | 1.0 | 1.0 |
| `Ankylosing_Spondylitis::Age` | 0.0 | **contract-fail** | 0.0 | 0.0 |
| `Lower_Grade_Glioma::Age` | 1.0 | 1.0 | 1.0 | 1.0 |
| `Aniridia::Age` | 1.0 | 0.0 | 0.0 | 0.0 |
| `Bladder_Cancer::Age` | 0.0 | 0.0 | 0.0 | 0.0 |
| `Alzheimers_Disease::Age` | 0.0 | 0.0 | 0.0 | 0.0 |

Two tasks (`Ocular_Melanomas::Age`, `Lower_Grade_Glioma::Age`) scored a
perfect 4/4. Four tasks with no failures at all still scored 0 on every one
of their 4 trajectories (`Colon_and_Rectal_Cancer`, `Adrenocortical_Cancer`,
`Bladder_Cancer::Age`, `Alzheimers_Disease::Age`); two more scored 0 on
every *evaluable* trajectory after excluding a failure
(`Ankylosing_Spondylitis::Age`, `Allergies`). The rest show genuine
within-task disagreement (see taxonomy below).

## Failure analysis (6 of 48 trajectories)

**4 artifact-contract failures** — the exact failure mode the artifact-
contract repair exists to catch:

- `Bile_Duct_Cancer` k4_00, `Angelman_Syndrome` k4_00: missing prediction
  artifact entirely (`cohort_info.json` never written for that trajectory).
- `Angelman_Syndrome` k4_02, `Ankylosing_Spondylitis::Age` k4_01: malformed
  artifact — `"expected cohort mapping, got scalar/string result for key
  'trait'"`, the same TCGA-no-match-branch pattern diagnosed in
  `reports/genomas_artifact_contract_diagnosis.md` recurring on fresh tasks,
  exactly as that report predicted it would.

All four were caught **before** scoring, correctly excluded from
`pass_at_1`/`oracle_at_k`/`plurality_accuracy`/agreement, and never produced
a fabricated reward. This is the repair working as designed, on real fresh
data, at a base rate of 4/48 ≈ 8.3%.

**2 agent-control failures** — both memory-related, both correctly
classified and excluded from correctness metrics, but with an honest,
mixed result on the `--max-memory-gb 150` mitigation added after the fresh
ladder's OOM:

- `Alopecia` k4_03: `runner_exit_-9` (`SIGKILL`). Cross-referenced against
  `dmesg` (kernel boot-time + monotonic counter → `2026-08-27 05:44:16 UTC`,
  matching this trajectory's end within `uptime`'s ~seconds-level precision):
  a **genuine kernel-level global OOM** still occurred —
  `oom-kill:constraint=CONSTRAINT_NONE,...,global_oom`, killing a `python`
  process at **143.6 GiB virtual / ~102 GiB resident** — i.e., *under* the
  150 GiB `RLIMIT_AS` ceiling. The cap never engaged because this process's
  own virtual-memory commitment stayed below it while the node's real,
  physical+swap capacity ran out first. `RLIMIT_AS` bounds a process's
  *virtual address space*, not its guaranteed backing by real memory — the
  two are only loosely related, and 150 GiB left too little margin under
  this node's actual available capacity (212 GiB total, reduced by
  pre-existing swap usage, buff/cache, and vLLM's own footprint).
- `Allergies` k4_02: `runner_exit_-11` (`SIGSEGV`), no matching `dmesg`
  entry. This is consistent with the cap *working* — the process's own
  allocation was refused once it hit the 150 GiB ceiling — but the specific
  failure mode was a segfault, not the clean Python `MemoryError` the
  mitigation was tested against
  (`test_memory_rlimit_preexec_fn_actually_bounds_the_child_address_space`
  confirmed the *ceiling* is enforced and a *pure-Python* allocation over it
  raises `MemoryError`; it did not — and could not, from user space — test
  every native allocator GenoMAS's dependency stack touches). Many C/C++
  memory allocators (numpy, pandas, and similar) don't universally check
  `mmap`/`brk` return values on failure; an `RLIMIT_AS`-triggered allocation
  failure inside one of those can crash the interpreter with a signal
  instead of surfacing a catchable Python exception. The safety property
  that mattered — this process died on its own, the shared vLLM server was
  never threatened, and the driver correctly moved on to the next task —
  held in both cases. **vLLM never went down at any point in this pilot.**

Both failures are correctly recorded as `agent_control_failure`, correctly
excluded from `pass_at_1`/`oracle_at_k`/`plurality_accuracy`/agreement
(verified below), and their artifacts/logs are preserved untouched.

**Recommendation for future campaigns** (not applied retroactively; this
pilot's results and protocol stand as run): lower `--max-memory-gb`
meaningfully further below total node RAM (e.g. ~90–100 GiB rather than
150 GiB) to leave real margin against physical exhaustion, not just virtual
address space; and/or add a lightweight external RSS-polling watchdog that
sends `SIGTERM` proactively, since `RLIMIT_AS` alone does not reliably
prevent every failure mode observed here.

## Pooled reliability analysis (preregistered primary definitions)

Computed with `biomni_uncertainty.reliability.evaluate_reliability` (the
post-audit version — primary agreement/plurality/consensus restricted to
completed trajectories) over all 48 pooled records. Full output:
`/scratch/11034/atzanakak/genomas_admission/genomas_k4_pilot_v1_20260826/pooled_reliability_report.json`.

| Metric | Primary (completed-only) | Legacy (all-runs) |
| --- | ---: | ---: |
| `pass_at_1` | 0.300 (n=10) | — (not computed under legacy) |
| `plurality_accuracy` | **0.417** (n=12) | 0.300 (n=10) |
| `oracle_at_k` (K=4) | 0.500 (n=12) | — |
| `agreement_plurality_fraction` | 0.299 (n=12) | 0.250 (n=12) |
| `selection_failure_rate` | 0.083 (n=12) | 0.100 (n=10) |
| `all_wrong_rate` | 0.500 (n=12) | — |
| `agreement_to_correctness_auroc` | 0.529 | — |
| `agreement_to_correctness_auprc` | 0.530 | — |
| `agreement_risk_coverage.aurc` | 0.639 | — |

**The audit fix visibly changes the answer on real data**, not just in unit
tests: `plurality_accuracy` is 0.417 under the corrected primary definition
vs. 0.300 under the legacy all-runs definition — a real execution/artifact
failure was distorting which trajectory "won" the plurality vote for at
least one task before this pass's fix, and would have understated apparent
plurality accuracy by 12 points had it gone uncorrected.

**Failure taxonomy** (completed-only agreement, this pass's second fix):

```
unstable_recoverable:   6
unstable_unrecoverable: 6
stable_correct:         0
stable_wrong:           0
```

**Zero of twelve tasks show unanimous agreement among their completed
trajectories.** Every task's K=4 (or K=2/3 after failures) completed runs
disagreed with each other at least once. This is a materially different,
higher-disagreement regime than this project's earlier Biomni-side findings
would suggest, on a panel deliberately chosen to be more structurally
diverse (more cohorts, both TCGA and GEO-only paths, both conditioned and
unconditioned tasks) than anything exercised in the admission ladder.
`agreement_to_correctness_auroc` at 0.529 (barely above chance) is
consistent with that — on this panel, self-consistency alone is a weak
correctness signal — but with only 12 task instances this is a wide,
uncertain estimate, not a confirmed replication or refutation of anything;
treat it as a hypothesis worth a larger follow-up panel, not a finding.

## Resource accounting

| | Total |
| --- | ---: |
| Trajectories requested | 48 |
| Trajectories completed | 42 |
| Trajectories failed (classified, excluded) | 6 (4 artifact-contract, 2 agent-control) |
| Input tokens | 51,279,922 |
| Output tokens | 2,246,828 |
| Measured runtime (sum, excludes the 2 unmeasured failures) | 118,124.26 s (32.81 h) |
| Wall-clock (sequential driver, start to finish) | 33.94 h |
| Paid API cost | $0.00 (local model) |

All `llm_input_tokens`/`llm_output_tokens`/`runtime_seconds` values are real
and nonzero for every completed trajectory (bookkeeping fix holds under a
full 12-task campaign, not just the fresh ladder's 5 rungs).

## Provenance

- Preregistration: `reports/genomas_k4_pilot_v1_preregistration.md`,
  manifest `genomas_k4_pilot_v1_20260826_preregistration_manifest.json`
  (unmodified since freeze, re-verified above).
- Per-task campaigns, records, native logs, scorer logs, worktrees:
  `/scratch/11034/atzanakak/genomas_admission/genomas_k4_pilot_v1_20260826/{01..12}_*_k4/`.
- Driver progress log (start/end timestamps, exit codes, every task):
  `/scratch/11034/atzanakak/genomas_admission/genomas_k4_pilot_v1_20260826/driver_progress.jsonl`.
- Pooled reliability report:
  `/scratch/11034/atzanakak/genomas_admission/genomas_k4_pilot_v1_20260826/pooled_reliability_report.json`.
- No code, test, or prior report was modified to produce this result — this
  is a pure read/analysis pass over the frozen campaign's output.
- GenoMAS source, `eval.py`, and the pinned commit were never touched.

## Stop

Pilot complete, analyzed, reported. **No OpenBioLLM, AutoBA, BioMaster, or
RL work was started.** No further GenoMAS experiment has been launched or
proposed in this pass — the next step (a larger confirmatory panel, an
investigation of the near-chance agreement→correctness AUROC, or a retuned
memory mitigation) is an open decision for the operator, not something
executed here.
