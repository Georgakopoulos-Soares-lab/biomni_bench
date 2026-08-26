# GenoMAS artifact-contract diagnosis — post-K=4 repair

Date: 2026-08-25. This report is derived **after** the frozen K=4 campaign
(`reports/genomas_k4_reliability_failure.md`, campaign directory
`/scratch/11034/atzanakak/genomas_admission/k4_reliability_v1_20260825`,
manifest SHA-256 `1968c56a2e907fc5e6efc396e3eca7fc5f14604afdaf0e7410244a8c6855cc63`).
That campaign and its four worktrees remain untouched and frozen; nothing in
this report edits it. No new agent trajectory, paid API call, or K=1/K=4
GenoMAS run was executed while producing this report — it is inspection and
code repair only.

## Root cause

**Possibility B — GenoMAS generated a malformed output**, with a specific,
fully reproduced mechanism, in all four trajectories.

The pinned evaluator (`GenoMAS/eval.py::evaluate_dataset_selection`, lines
79–98) loads `preprocess/<trait>/cohort_info.json` and treats it as a mapping
from cohort id to a metadata dict:

```python
for cohort_id in set(ref_trait_info.keys()).union(set(pred_trait_info.keys())):
    ref_available = ref_trait_info.get(cohort_id, {}).get('is_available', False)
    pred_available = pred_trait_info.get(cohort_id, {}).get('is_available', False)
```

The *only* code path in the pinned source that ever writes this file is
`tools/preprocess.py::validate_and_save_cohort_info`, which always
read-merges-writes `{cohort: {...9-key schema...}}` — including the
legitimate "not usable" terminal state (`is_gene_available`/`is_trait_available
= False` when no match exists). That native terminal state is a valid, fully
scoreable dict entry; it is not what broke.

What broke is upstream of that function. GenoMAS's TCGA action-unit prompt
(`prompts/action_units/base/tcga_action_units.json`, first action unit, step
1) instructs the agent:

> "If no suitable directory is found, skip this trait and mark the task as
> completed."

— but never tells the agent to record that state via
`validate_and_save_cohort_info`, unlike the *later* action unit (step 6),
which explicitly says: "save relevant information about the linked cohort
data using the `validate_and_save_cohort_info` function from the library."
The early-exit branch has no such instruction. In K=1 the sampled completion
for that branch chose to `raise ValueError(...)` (harmless: no file write).
In all four K=4 trajectories the sampled completion instead improvised its
own ad hoc JSON object and wrote it directly with `open(json_path, 'w')` +
`json.dump(...)`, bypassing the shared writer entirely. Each trajectory
invented a different schema:

| Run | `code/TCGA.py` behavior | `cohort_info.json` written |
| --- | --- | --- |
| k4_00 | no-match early exit | `{"trait": ..., "status": "no_matching_directory", "message": ...}` |
| k4_01 | no-match early exit | `{"trait": ..., "selected_cohort": null, "data_available": false, "message": ...}` |
| k4_02 | naive substring match, ad hoc dump | `{"trait": ..., "cohort": ..., "clinical_file": ..., "clinical_shape": [...], ...}` |
| k4_03 | column-content match, ad hoc dump, **then** a correct call | ad hoc keys **and** a valid nested `"TCGA_Bladder_Cancer_(BLCA)"` entry, merged together |

None of these four objects satisfy `.get(...)` uniformly across their
top-level values, which is exactly why the evaluator raised
`AttributeError: 'str' object has no attribute 'get'` on all four (caught per
task at `eval.py` line 153, which is why the whole evaluator process
completed but emitted zero `selection_metrics`).

**k4_00 additionally shows destructive overwrite, not just malformed output.**
Filesystem mtimes inside the frozen worktree show the GEO
(`GSE133228.py`) step ran first and correctly called
`validate_and_save_cohort_info`, producing a valid `{"GSE133228": {...}}`
mapping (write completes at run-relative t≈477s). The TCGA step then ran
*after* it (t≈547–557s) and its generated code used a truncating
`open(json_path, 'w')` rather than the shared writer's read-merge-write, so
the ad hoc scalar object **replaced** the already-valid GEO entry rather than
merging beside it. k4_03 shows the same clobbering mechanism, but only
partially — its later `validate_and_save_cohort_info(cohort="TCGA_Bladder_
Cancer_(BLCA)", ...)` call read the file *after* the ad hoc TCGA write had
already landed, so it correctly appended a valid nested entry, but the
earlier ad hoc top-level keys (`trait`, `status`, `cohort`, `clinical_file`,
`clinical_columns`) were never cleared and still poison the top level. k4_01
and k4_02's own GEO scripts appear to have errored out (their generated code
ends mid-computation, before reaching their `validate_and_save_cohort_info`
call) and never wrote a competing entry, so their file only ever held the ad
hoc TCGA object.

Ruled out:
- **A (wrong artifact selected):** the controller/reliability adapter reads
  the correct, only `cohort_info.json` the agent wrote. There is no second,
  correct artifact elsewhere that was missed.
- **C (legitimate scorer-unsupported terminal state):** GenoMAS *does* define
  a valid, scoreable terminal state for "no usable cohort" — the
  `is_usable=False` dict entry `validate_and_save_cohort_info` writes when
  `is_final=False`. The agent simply did not reliably reach that code path in
  the no-match branch; the terminal state the evaluator can't read is not one
  GenoMAS's own tooling would have produced if invoked correctly.
- **D (evaluator/version mismatch):** the same pinned `eval.py` and the same
  `cohort_info.json` schema were in force for both K=1 and K=4. K=1 never
  exercised the failure because its sampled TCGA completion raised an
  exception instead of writing anything.

## K=1 vs K=4 comparison

- **K=1** (`Alcohol_Flush_Reaction::Age`, successful): `code/TCGA.py` raised
  `ValueError("No matching TCGA cohort found...")` on the no-match branch and
  wrote nothing. `code/GSE133228.py` then ran to completion and called
  `validate_and_save_cohort_info`, producing:
  `{"GSE133228": {"is_usable": false, "is_gene_available": false, "is_trait_available": false, "is_available": false, "is_biased": null, "has_age": null, "has_gender": null, "sample_size": null, "note": null}}`
  — a valid, scoreable mapping (native selection accuracy 100.0, as recorded
  in `reports/genomas_admission.md`).
- **K=4** (same task, four trajectories): every trajectory's TCGA no-match (or
  false-positive-match) branch wrote raw, differently-shaped JSON directly,
  and in k4_00/k4_03 this overwrote or polluted an already-valid GEO entry.

The difference is not the evaluator, the benchmark, or the adapter — it is
which of two plausible agent behaviors the sampled completion took on an
under-specified prompt branch. That variance across otherwise-identical
retries (same task, same source, same model) is itself a reliability-relevant
observation, but it is an execution/output-contract signal, not a scored
outcome, and per `reports/genomas_k4_reliability_failure.md` it must not be
read as one.

## Code changes

- `src/biomni_uncertainty/adapters/genomas.py` (new): `validate_cohort_info_contract(path)`.
  Checks the file exists, parses as JSON, is a top-level dict, and that every
  value is itself a dict (the exact shape `eval.py`'s `.get(...)` calls
  require). Returns `artifact_contract_valid` / `artifact_contract_error`.
  Never scores, never mutates GenoMAS output, never touches `eval.py`. Also
  adds `normalize_condition_arg(value)`, which maps a CLI `--condition` of
  `None`/omitted/`"none"` (any case) to a real Python `None` — see the
  unconditioned-task bug below.
- `scripts/genomas_smoke_runner.py`, `scripts/genomas_score_smoke.py`:
  `--condition` is now optional and normalized through
  `normalize_condition_arg` before it reaches GenoMAS's `get_question_pairs`
  override, instead of always being a required, possibly-misleading string.
- `scripts/run_genomas_k4_reliability.py`:
  - Calls the validator on `cohort_info.json` before/alongside invoking the
    unchanged native scorer (the scorer call itself is untouched — the
    validator supplements, never replaces it).
  - Records four explicit layers per trajectory: `agent_execution_success`
    (subprocess exit code), `artifact_contract_valid` /
    `artifact_contract_error`, `native_scorer_success` (reward extracted),
    and `official_reward` (task correctness). `failure_class` now
    distinguishes `artifact_contract_failure` from `native_scorer_failure`
    instead of collapsing both into one bucket.
  - Fixed the token/runtime bookkeeping bug (see below): reads GenoMAS's own
    `output/log_<run_id>.txt` (written by `utils/logger.py`) instead of the
    controller's captured subprocess stdout, which never contained the
    "Total Input/Output Tokens" / "Total Duration" lines.
- `src/biomni_uncertainty/reliability.py`: added `_failure_layers(df)`,
  surfaced as `failure_accounting.failure_layers`. It buckets each requested
  run into the first layer it failed at
  (`execution_failure` → `artifact_contract_failure` → `native_scorer_failure`
  → `scored`) using the adapter-reported booleans above, and returns `None`
  (not a guess) when an adapter reports none of them. A missing score is
  still never conflated with a score of zero: the existing taxonomy fix from
  the in-progress schema work (uncommitted before this pass) already ensures
  an instance with no evaluable trajectory gets no `stable_correct` /
  `stable_wrong` / `unstable_*` label, and the new layer breakdown does not
  change that.

None of these changes touch `GenoMAS/eval.py`, GenoMAS prompts, or GenoMAS
agent/tool code. The pinned source at
`d6365a700794587b53958db3bf22bb1fb80c3451` is unmodified.

## Controller bookkeeping bug (§14)

The frozen campaign's `reliability_report.json` and `records.jsonl` all show
zero-valued `llm_input_tokens` / `llm_output_tokens` / `runtime_seconds`, even
though native per-trajectory logs plainly contain real accounting. Cause:
`token_and_runtime()` parsed `logs/<run_id>.log` — the controller's own
captured subprocess stdout/stderr — but GenoMAS's `Logger` (`utils/logger.py`)
writes its "Total Duration" / "Total Input Tokens" / "Total Output Tokens"
lines to its **own** file, `<worktree>/output/log_<run_id>.txt`
(`main.py:32`), which the controller never read. Confirmed by grepping that
file directly for all four frozen runs — the values match the totals already
reported by hand in this handoff (235,077 / 8,253 / 395.62s for k4_00, etc.).
Fixed by reading `output/log_<run_id>.txt` first, falling back to the
captured subprocess log only if that file is absent. **The frozen
`reliability_report.json` and `records.jsonl` are not retroactively edited**;
the native per-run log totals already recorded in
`reports/genomas_k4_reliability_failure.md` remain the authoritative record
for that campaign.

## Tests

Added `tests/test_adapters_genomas.py` (synthetic/copied artifacts only, never
the frozen campaign files):
- valid cohort mapping (the exact K1 admission shape) → accepted;
- malformed scalar artifact (the exact k4_00 shape) → rejected, reason names
  the offending key;
- mixed ad hoc-keys-plus-valid-entry artifact (the exact k4_03 shape) →
  rejected;
- missing artifact → rejected;
- invalid JSON → rejected;
- empty dict (a legitimate, vacuously valid no-match mapping) → accepted,
  distinguishing a genuine empty-map terminal state from a malformed one;
- `normalize_condition_arg` maps `None`/`"None"`/`"none"`/`"  NONE  "` to
  `None` and passes real condition names (`Age`, `Gender`, a comorbidity
  trait name) through unchanged.

Extended `tests/test_reliability.py`:
- `failure_layers` is `None` when an adapter reports none of the three layer
  columns (never fabricated);
- `failure_layers` correctly separates an execution failure, an
  artifact-contract failure, a native-scorer failure, and a scored run into
  four distinct buckets, and confirms the artifact-contract failure does not
  leak into `failure_taxonomy` (which requires an evaluable reward).

`pytest -q` (excluding two pre-existing, environment-only failures in
`tests/test_budget.py` / `tests/test_mock_end_to_end.py` — missing `biomni`
and `langchain_openai` packages in the smoke venv used to run this suite,
unrelated to this change): all tests pass, including the new ones.
`ruff check src tests scripts`: passes with no warnings.

## Provenance

- Modified: `src/biomni_uncertainty/reliability.py`.
- Added: `src/biomni_uncertainty/adapters/genomas.py`,
  `tests/test_adapters_genomas.py`.
- Extended: `tests/test_reliability.py`, `scripts/run_genomas_k4_reliability.py`,
  `scripts/genomas_smoke_runner.py`, `scripts/genomas_score_smoke.py`.
- This report: `reports/genomas_artifact_contract_diagnosis.md`.
- No commit has been made; the working tree still also carries the
  pre-existing uncommitted reliability-schema work (AUPRC/risk-coverage
  metrics, `failure_class`/`by_failure_class` breakdown) from before this
  diagnosis pass, plus the untracked GenoMAS admission scripts/config/reports
  from the admission and K=4 campaign. Nothing frozen was altered:
  `k4_reliability_v1_20260825/**`, `reports/genomas_admission.md`, and
  `reports/genomas_k4_reliability_failure.md` are untouched.

## Fresh admission proposal

Do not reuse `Alcohol_Flush_Reaction` (used in both the K=1 admission smoke
and the K=4 engineering panel). Selection rule, applied mechanically to the
132 admitted, verified GenoTEX traits in `metadata/task_info.json` (sorted
alphabetically) and the verified local `TCGA`/`GEO` input trees — no gold
outcomes consulted:

1. First trait alphabetically that has a matching local TCGA cohort
   directory, unconditioned: **`Acute_Myeloid_Leukemia :: (none)`**. Exercises
   the TCGA-available path with single-cohort selection.
2. Same trait, `Age`-conditioned: **`Acute_Myeloid_Leukemia :: Age`**.
   Exercises the two-step trait+condition cohort-pair selection with TCGA
   available (different result cardinality than #1).
3. First trait alphabetically with **no** matching local TCGA cohort
   directory, unconditioned: **`Age-Related_Macular_Degeneration :: (none)`**.
   Forces the pure-GEO path the K=4 panel's TCGA no-match branch was
   supposed to exercise safely.
4. Same GEO-only trait, `Gender`-conditioned (a condition untested by the
   K=1/K=4 panel, which only used `Age`): **`Age-Related_Macular_Degeneration
   :: Gender`**.

Proposed ladder per the operator's admission protocol (§16): task #1 as a
single fresh K=1 smoke first, gated on the new artifact-contract validator
reporting `artifact_contract_valid: true` and the unchanged native scorer
returning a real `selection_metrics.average.accuracy`; then #2–#4 each as a
K=1; then a small K=2 on task #1; only then propose a new preregistered
held-out K=4 campaign under a new campaign name (never reusing
`k4_reliability_v1_20260825`).

## Go / No-Go

```text
GO: GenoMAS integration repaired; ready for fresh admission smoke.
```

The repair is narrow (one new adapter-side validator module, explicit
4-layer classification in the campaign controller and the shared reliability
schema, a controller log-source bug fix) and touches no GenoMAS source,
prompts, or the pinned evaluator. It does not itself guarantee the next
fresh trajectory will produce a valid artifact — that remains a property of
the sampled agent completion, which is exactly the variance under study — but
the suite can now (a) tell a valid native score apart from an
artifact-contract failure before the scorer crashes, and (b) will correctly
record real token/runtime accounting instead of zeros.

Exact command for the next fresh K=1 smoke (task #1 above), **not executed**:

```bash
cd /work/11034/atzanakak/biomni_bench/biomni-uncertainty
python scripts/run_genomas_k4_reliability.py \
  --campaign-root /scratch/11034/atzanakak/genomas_admission/genomas_fresh_k1_aml_20260826 \
  --source /scratch/11034/atzanakak/genomas_admission/GenoMAS_run \
  --data-root /scratch/11034/atzanakak/genomas_admission/genotex_data/input \
  --reference-root /scratch/11034/atzanakak/genomas_admission/genotex_references \
  --endpoint http://127.0.0.1:8000 \
  --model Qwen3-Coder-30B-A3B-Instruct \
  --trait Acute_Myeloid_Leukemia --condition None \
  --k 1 \
  --source-commit d6365a700794587b53958db3bf22bb1fb80c3451 \
  --benchmark-revision 9d50c9020256e8c943e02b6c0ad843017cd76cf8
```

This requires a running local vLLM endpoint on an allocated GPU and a new
`--campaign-root`; it must not be run without explicit approval.

**Unconditioned-task plumbing fixed as part of this pass.** The K=1/K=4 panel
only ever exercised `condition="Age"`, so the unconditioned `(trait, None)`
path was never exercised end to end. Auditing it surfaced a real bug: all
three GenoMAS-facing scripts required `--condition` and passed it straight
through as a string, and GenoMAS's own `environment.py::run` detects the
unconditioned task with `if condition` (Python truthiness) — a literal
`--condition None` is a non-empty, truthy *string*, so it would have been
misread as a real condition and, since it is not `'Age'`/`'Gender'`, appended
to the trait list as a comorbidity to also process (`environment.py:250,254`).
Fixed by making `--condition` optional in `run_genomas_k4_reliability.py`,
`genomas_smoke_runner.py`, and `genomas_score_smoke.py`, and adding
`biomni_uncertainty.adapters.genomas.normalize_condition_arg` (unit tested)
to map `None`/omitted/`"none"` (any case) to a real Python `None` before it
ever reaches the task tuple; the `--condition` flag is now omitted entirely
from the child-process command lines rather than passed as the string
`"None"`. The command above is written the correct way — omitting
`--condition` — as a result.
