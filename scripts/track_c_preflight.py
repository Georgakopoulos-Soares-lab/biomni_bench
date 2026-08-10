#!/usr/bin/env python
"""Track-C CPU-only preflight — Step 1 of the "Next steps, live GPU node" plan.

Three checks, in order. All decision rules are stated here, before any number
below them is computed, so the criteria cannot be adjusted to fit an outcome.
No GPU, no model calls, no held-out instance touched.

## 1a. Reconcile the stratum partition (accounting, no decision rule)

D-30's Track-C diagnostic and the post-Phase-2B / Controller-v2 assessments
(D-28) have each quoted a partition of the 150 `phase2b` instances - "82
unanimous / 53 substantive disagreement / 15 insufficient evidence" versus "91
unanimous / 51 split / 45 no-correct-trajectory" - without stating that these
are TWO DIFFERENT, non-nested classifications of the same instances. This
section recomputes both directly from `p2b_pooled_trajectories.csv` and
cross-tabulates them so every later step cites one canonical table instead of
either framing in isolation.

## 1b. Verifiability x headroom crossing

**Premise under test.** VERIFY assumes checking is cheaper than solving. That
asymmetry plausibly holds for deterministic computational claims and plausibly
does not hold for inferential claims, where checking is about as hard as
answering.

**Mode-A eligibility criterion, fixed before classification:** an instance is
mode-A-eligible if and only if the quantity being asked for is COMPUTABLE from
raw data given verbatim in the task prompt itself, with no external database,
literature, or domain-knowledge lookup required. This is evaluated at the TASK
level from one representative prompt per task (BiomniEval1's prompts are
template-generated per task, so a single template determines eligibility for
every instance of that task) and is reported per task, not tuned per instance,
specifically so eligibility cannot be adjusted case by case to fit a headroom
result.

**Decision rule, fixed before computing the headroom fraction:**
- >= 40% of recoverable headroom on mode-A-eligible instances -> mode A is
  the pilot's primary arm.
- 15-40% -> pilot runs, but stratified, and mode A cannot carry a prospective
  run alone.
- < 15% -> the computational-verification route is not where the headroom is;
  state that plainly.

## 1c. Degeneration x stratum

**Question.** Are `consecutive_runaway`-prone instances concentrated in the
no-correct-trajectory bucket (screening loses little) or the split/
minority-held bucket (screening would destroy the target population)?
Reported as a contingency table with instance-clustered bootstrap CIs, on
`phase2b` and replicated on `phase1_pooled`. No numeric accept/reject
threshold is pre-specified here because the two readings the brief describes
are directional, not a single pass/fail number; the table and its CIs are the
deliverable.

    python scripts/track_c_preflight.py --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from biomni_uncertainty.policy import build_pools, resolve  # noqa: E402

BOOTSTRAP_SEED = 20260811001
BOOTSTRAP_REPS = 10000

#: Fixed BEFORE classification (see module docstring 1b). One representative
#: prompt per task was read to make this call; `screen_gene_retrieval` was the
#: one case that could plausibly have gone the other way (it sounds
#: data-driven - "strongest perturbation effect" - but the prompt supplies no
#: perturbation data, only a research description and a candidate gene list,
#: so it requires external screen-literature knowledge like every other
#: non-lab_bench_seqqa task, not a raw-input computation).
MODE_A_ELIGIBLE_TASKS = frozenset({"lab_bench_seqqa"})

TASK_ELIGIBILITY_NOTE = {
    "lab_bench_seqqa": "mode-A: the raw DNA/protein sequence is given verbatim in the prompt; "
    "the asked-for quantity (an ORF translation, a position, a primer) is a pure computation over it.",
    "crispr_delivery": "not mode-A: selecting a delivery method requires domain knowledge about the "
    "cell type, not a computation over prompt data.",
    "gwas_causal_gene_gwas_catalog": "not mode-A: causal-gene likelihood requires external GWAS-database "
    "evidence; the locus gene list alone does not determine which gene is causal.",
    "gwas_causal_gene_opentargets": "not mode-A: same as gwas_catalog - requires external evidence.",
    "gwas_causal_gene_pharmaprojects": "not mode-A: same - requires external evidence.",
    "gwas_variant_prioritization": "not mode-A: variant prioritization requires external fine-mapping/"
    "eQTL evidence, not computation over the variant ID list alone.",
    "lab_bench_dbqa": "not mode-A: the question is explicitly phrased as a lookup against a named "
    "external database (e.g. 'according to miRDB v6.0'); no data to compute from is in the prompt.",
    "patient_gene_detection": "not mode-A: causal-gene identification from phenotype terms requires "
    "external phenotype-gene association knowledge (e.g. Monarch/ClinVar), not raw computation.",
    "rare_disease_diagnosis": "not mode-A: diagnostic reasoning from phenotype+candidate genes requires "
    "clinical knowledge, not raw computation.",
    "screen_gene_retrieval": "not mode-A, resolved from the full prompt: no perturbation data is "
    "supplied - the prompt gives only a research description and a candidate gene list - so answering "
    "requires external screen/literature knowledge, exactly like the other non-seqqa tasks.",
}


# --------------------------------------------------------------------------
# Shared: build the per-instance table with both classification schemes
# --------------------------------------------------------------------------


def instance_table(pooled: pd.DataFrame) -> pd.DataFrame:
    pools = build_pools(pooled)
    rows = []
    for pool in pools:
        v = pool.views(tuple(range(pool.k)))
        n_usable = sum(1 for x in v if x.usable)
        distinct_usable = len({x.cluster_key for x in v if x.usable})
        r_full = resolve(v)
        oracle = max(pool.rewards.values())
        plurality_reward = pool.reward_of(r_full.cluster_key, r_full.members)
        any_correct_usable = any(pool.rewards[x.run_id] > 0 for x in v if x.usable)

        if n_usable < 2:
            evidence_state = "A_insufficient_evidence"
        elif distinct_usable == 1:
            evidence_state = "unanimous"
        else:
            evidence_state = "B_substantive_disagreement"

        rows.append(
            {
                "task_name": pool.task_name,
                "task_instance_id": pool.task_instance_id,
                "k": pool.k,
                "n_usable": n_usable,
                "distinct_usable": distinct_usable,
                "evidence_state": evidence_state,
                "no_correct_trajectory": oracle == 0,
                "any_correct_usable": any_correct_usable,
                "oracle_reward": oracle,
                "plurality_reward": plurality_reward,
                "headroom": oracle - plurality_reward,
                "mode_a_eligible": pool.task_name in MODE_A_ELIGIBLE_TASKS,
            }
        )
    return pd.DataFrame(rows)


def cluster_bootstrap_mean(values: np.ndarray, seed: int = BOOTSTRAP_SEED, reps: int = BOOTSTRAP_REPS):
    if len(values) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(reps, len(values)))
    stat = values[idx].mean(axis=1)
    return float(values.mean()), float(np.percentile(stat, 2.5)), float(np.percentile(stat, 97.5))


# --------------------------------------------------------------------------
# 1a
# --------------------------------------------------------------------------


def step_1a(df: pd.DataFrame, out: Path, label: str) -> dict:
    print(f"\n{'=' * 70}\n1a. STRATUM RECONCILIATION ({label})\n{'=' * 70}")

    ev = df.evidence_state.value_counts()
    print("\nevidence_state (n_usable-based; Track-C's D-30 partition):")
    print(ev.to_string())

    du = df.distinct_usable.value_counts().sort_index()
    print("\ndistinct_usable count (the '91 unanimous' framing checks against distinct_usable==1):")
    print(du.to_string())

    cross = pd.crosstab(df.evidence_state, df.distinct_usable)
    print("\nCROSS-TAB evidence_state x distinct_usable (the reconciliation):")
    print(cross.to_string())

    noc = pd.crosstab(df.evidence_state, df.no_correct_trajectory)
    print("\nCROSS-TAB evidence_state x no_correct_trajectory (the orthogonal, outcome-based axis):")
    print(noc.to_string())
    print(f"\ntotal no_correct_trajectory (oracle4==0): {int(df.no_correct_trajectory.sum())}/{len(df)}")

    # -- the canonical outcome table, both axes together --------------------
    def outcome(r):
        if not r.any_correct_usable:
            return "all_wrong"
        if r.evidence_state == "unanimous":
            return "unanimous_correct"
        if r.evidence_state == "A_insufficient_evidence":
            return "single_usable_correct"
        # B_substantive_disagreement, at least one usable trajectory correct
        if r.plurality_reward > 0:
            return "correct_plurality"
        return "wrong_plurality_or_tied_correct_minority"

    df = df.assign(outcome=df.apply(outcome, axis=1))
    canon = (
        df.groupby(["evidence_state", "outcome"])
        .agg(
            n=("task_instance_id", "size"),
            mean_oracle=("oracle_reward", "mean"),
            mean_plurality=("plurality_reward", "mean"),
        )
        .reset_index()
    )
    print("\nCANONICAL evidence_state x outcome table (cite this, not either framing alone):")
    print(canon.to_string(index=False))

    # -- headroom arithmetic: per-stratum and as an overall reward ceiling --
    b = df[df.evidence_state == "B_substantive_disagreement"]
    b_headroom_mean, b_lo, b_hi = cluster_bootstrap_mean(b.headroom.to_numpy())
    overall_headroom_mean, o_lo, o_hi = cluster_bootstrap_mean(df.headroom.to_numpy())
    print(
        f"\nheadroom (oracle - plurality) on stratum B only : {b_headroom_mean:.4f} [{b_lo:.4f},{b_hi:.4f}]  n={len(b)}"
    )
    print(
        f"headroom (oracle - plurality) overall            : {overall_headroom_mean:.4f} [{o_lo:.4f},{o_hi:.4f}]  n={len(df)}"
    )
    print(
        f"stratum-B headroom AS A SHARE OF overall reward ceiling: "
        f"{b.headroom.sum() / len(df):.4f} of {overall_headroom_mean:.4f} total "
        f"({b.headroom.sum() / df.headroom.sum():.1%} of all headroom sits in stratum B)"
    )

    canon.to_csv(out / f"1a_canonical_table__{label}.csv", index=False)
    cross.to_csv(out / f"1a_crosstab_evidence_x_distinct__{label}.csv")
    return {
        "evidence_state_counts": ev.to_dict(),
        "no_correct_trajectory_total": int(df.no_correct_trajectory.sum()),
        "stratum_b_headroom_mean": b_headroom_mean,
        "stratum_b_headroom_ci": [b_lo, b_hi],
        "overall_headroom_mean": overall_headroom_mean,
        "overall_headroom_ci": [o_lo, o_hi],
        "stratum_b_share_of_total_headroom": float(b.headroom.sum() / df.headroom.sum()) if df.headroom.sum() else None,
    }


# --------------------------------------------------------------------------
# 1b
# --------------------------------------------------------------------------


def step_1b(df: pd.DataFrame, out: Path, label: str) -> dict:
    print(f"\n{'=' * 70}\n1b. VERIFIABILITY x HEADROOM CROSSING ({label})\n{'=' * 70}")

    print("\nmode-A eligibility, fixed before classification (module docstring):")
    for t in sorted(df.task_name.unique()):
        elig = "ELIGIBLE" if t in MODE_A_ELIGIBLE_TASKS else "not eligible"
        print(f"  {t:35s} {elig:14s} {TASK_ELIGIBILITY_NOTE.get(t, '')}")

    b = df[df.evidence_state == "B_substantive_disagreement"].copy()
    total_headroom = b.headroom.sum()
    a_headroom = b[b.mode_a_eligible].headroom.sum()
    frac = a_headroom / total_headroom if total_headroom else float("nan")

    by_task = (
        b.groupby(["task_name", "mode_a_eligible"])
        .agg(n=("task_instance_id", "size"), headroom_sum=("headroom", "sum"), headroom_mean=("headroom", "mean"))
        .reset_index()
        .sort_values("headroom_sum", ascending=False)
    )
    print("\nheadroom by task, stratum B only (the population any VERIFY route addresses):")
    print(by_task.to_string(index=False))

    print(f"\nTOTAL stratum-B headroom            : {total_headroom:.4f} (sum of oracle-plurality gaps)")
    print(f"stratum-B headroom on mode-A tasks  : {a_headroom:.4f}")
    print(f"FRACTION OF HEADROOM THAT IS MODE-A-ELIGIBLE: {frac:.1%}")

    if frac >= 0.40:
        verdict = "GO: mode A is the pilot's primary arm (>=40% of headroom is mode-A-eligible)."
    elif frac >= 0.15:
        verdict = "STRATIFY: pilot runs, but mode A cannot carry a prospective run alone (15-40%)."
    else:
        verdict = "NOT-WHERE-THE-HEADROOM-IS: the computational-verification route is not primary (<15%)."
    print(f"\nDECISION (rule fixed in the module docstring before this number was computed): {verdict}")

    # secondary: also report as a share of ALL headroom (not just stratum B),
    # since some headroom sits in "unanimous but wrong" / stratum-A instances
    # that stratum B alone does not capture.
    all_headroom = df.headroom.sum()
    a_headroom_all = df[df.mode_a_eligible].headroom.sum()
    print(
        f"\n(secondary, all strata) mode-A share of ALL headroom: "
        f"{a_headroom_all / all_headroom:.1%} of {all_headroom:.4f} total"
    )

    by_task.to_csv(out / f"1b_headroom_by_task__{label}.csv", index=False)
    return {
        "mode_a_tasks": sorted(MODE_A_ELIGIBLE_TASKS),
        "stratum_b_total_headroom": float(total_headroom),
        "stratum_b_mode_a_headroom": float(a_headroom),
        "fraction_mode_a_of_stratum_b_headroom": float(frac),
        "verdict": verdict,
    }


# --------------------------------------------------------------------------
# 1c
# --------------------------------------------------------------------------


def step_1c(pooled: pd.DataFrame, df: pd.DataFrame, out: Path, label: str) -> dict:
    print(f"\n{'=' * 70}\n1c. DEGENERATION x STRATUM ({label})\n{'=' * 70}")

    bad_prefix = (
        pooled.failure_class.fillna("").astype(str).str.startswith(("model_context_overflow", "budget_terminated"))
    )
    traj_bad = pooled.assign(bad=bad_prefix)[["task_name", "task_instance_id", "bad"]]
    inst_bad = traj_bad.groupby(["task_name", "task_instance_id"]).bad.agg(["sum", "size"]).reset_index()
    inst_bad = inst_bad.rename(columns={"sum": "n_degenerate", "size": "k"})
    merged = df.merge(inst_bad, on=["task_name", "task_instance_id"])
    merged["any_degenerate"] = merged.n_degenerate > 0

    bucket = np.where(
        merged.no_correct_trajectory,
        "no_correct_trajectory",
        np.where(merged.evidence_state == "B_substantive_disagreement", "split_B", "other_has_correct"),
    )
    merged["bucket"] = bucket

    table = pd.crosstab(merged.bucket, merged.any_degenerate)
    print("\ncontingency: bucket x any_degenerate_trajectory")
    print(table.to_string())

    rates = merged.groupby("bucket").any_degenerate.agg(["mean", "sum", "size"]).reset_index()
    rows_with_ci = []
    for r in rates.to_dict("records"):
        sub = merged[merged.bucket == r["bucket"]].any_degenerate.to_numpy().astype(float)
        m, lo, hi = cluster_bootstrap_mean(sub)
        rows_with_ci.append(
            {
                "bucket": r["bucket"],
                "n": int(r["size"]),
                "n_degenerate_instances": int(r["sum"]),
                "rate": m,
                "ci_lo": lo,
                "ci_hi": hi,
            }
        )
    rate_df = pd.DataFrame(rows_with_ci)
    print("\ndegeneration rate by bucket, instance-clustered 95% CI:")
    print(rate_df.to_string(index=False))

    no_correct_rate = (
        rate_df.set_index("bucket").loc["no_correct_trajectory", "rate"]
        if "no_correct_trajectory" in rate_df.bucket.values
        else float("nan")
    )
    split_rate = (
        rate_df.set_index("bucket").loc["split_B", "rate"] if "split_B" in rate_df.bucket.values else float("nan")
    )
    if split_rate > no_correct_rate:
        reading = "CONCENTRATED IN SPLIT: pre-screening would remove instances from the target population - avoid or loudly caveate screening."
    else:
        reading = "CONCENTRATED IN NO-CORRECT-TRAJECTORY: screening removes instances with nothing to learn - the bias objection is largely dissolved."
    print(f"\nREADING: {reading}")

    table.to_csv(out / f"1c_contingency__{label}.csv")
    rate_df.to_csv(out / f"1c_rates__{label}.csv", index=False)
    return {
        "rates_by_bucket": rate_df.to_dict("records"),
        "reading": reading,
    }


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    for label, path in (
        ("phase2b", "/scratch/11034/atzanakak/biomni_unc_runs/phase2b/results/tables/p2b_pooled_trajectories.csv"),
        ("phase1_pooled", "/scratch/11034/atzanakak/biomni_unc_runs/phase1_pooled/results/tables/trajectories.csv"),
    ):
        pooled = pd.read_csv(path)
        if "condition" in pooled.columns:
            pooled = pooled[pooled.condition.isin(["instrumented", "shadow"])]
        df = instance_table(pooled)
        df.to_csv(args.out / f"instance_table__{label}.csv", index=False)

        r1a = step_1a(df, args.out, label)
        r1b = step_1b(df, args.out, label) if label == "phase2b" else None  # primary pool only
        r1c = step_1c(pooled, df, args.out, label)
        results[label] = {"1a": r1a, "1b": r1b, "1c": r1c}

    (args.out / "track_c_preflight.json").write_text(json.dumps(results, indent=2, default=float))
    print(f"\nwrote results to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
