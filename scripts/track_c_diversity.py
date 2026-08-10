#!/usr/bin/env python
"""Track-C diagnostic: is disagreement between trajectories substantive?

CPU only, read-only, no GPU, no model calls, no prompt/temperature/tool change.
Reads the preserved Phase-2B traces and asks one question:

    When Biomni trajectories disagree, are they performing meaningfully
    different analyses, or following correlated reasoning/evidence/tool paths
    and producing noisy different final answers?

**The interpretation rule below was written before any outcome association was
computed**, so the label cannot be chosen to fit the result:

    Outcome A - USEFUL INDEPENDENCE EXISTS.
        More independent plans/tools/evidence materially increase the chance of
        correcting an earlier error: P(correct | high workflow distance from a
        wrong trajectory) exceeds P(correct | low distance) by >= 10 pp with a
        95% instance-clustered bootstrap CI excluding 0, AND correct-minority
        trajectories are further from the wrong plurality than the wrong
        plurality's members are from each other.
        => Track C should deliberately generate independent verification.

    Outcome B - CORRELATED UPSTREAM, NOISY DOWNSTREAM.
        Trajectories that disagree are no more distant in plan/tool/evidence
        space than trajectories that agree (difference < 0.05 in composite
        distance, or CI covering 0).
        => resampling is not producing independent verification; Track C must
        explicitly decorrelate.

    Outcome C - ALREADY DIVERSE, STILL WRONG TOGETHER.
        Disagreeing trajectories ARE substantially more distant (>= 0.05), but
        distance does not predict correction (Outcome-A test fails).
        => more diversity is not the answer; reframe toward external
        verification or stronger evidence/tools/models.

    Mixed outcomes are permitted and are reported as mixed rather than forced.

Usage:

    python scripts/track_c_diversity.py --config configs/phase2b.yaml --out <dir>
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.diversity import extract_trace, pairwise_diversity  # noqa: E402

BOOTSTRAP_SEED = 20260811  # a new stream; not Phase 2B's and not the v2 analysis's
BOOTSTRAP_REPS = 10000

#: Pre-registered thresholds for the rule in the module docstring.
CORRECTION_GAP_THRESHOLD = 0.10
DISTANCE_GAP_THRESHOLD = 0.05


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------


def load_traces(cfg, pooled: pd.DataFrame) -> pd.DataFrame:
    """One row per trajectory: outcome fields joined to structural trace fields."""
    rows = []
    for r in pooled.to_dict("records"):
        run_dir = Path(str(r["run_dir"]))
        meta = {
            "run_id": r["run_id"],
            "task_name": r["task_name"],
            "task_instance_id": r["task_instance_id"],
            "trajectory_index": r["trajectory_index"],
            "condition": r["condition"],
            "completed": r["completed"],
            "failure_class": r.get("failure_class"),
        }
        t = extract_trace(run_dir, meta)
        rows.append(
            {
                **meta,
                "reward": r.get("reward"),
                "answer_parse_status": r.get("answer_parse_status"),
                "cluster_key": r.get("answer_cluster_key"),
                "final_confidence": r.get("final_confidence"),
                "trace": t,
                "n_tool_calls": t.n_tool_calls,
                "n_failed_tool_calls": t.n_failed_tool_calls,
                "n_unique_tools": len(t.tool_set),
                "n_think_blocks": t.n_think_blocks,
                "n_code_blocks": len(t.code_hashes),
                "plan_len_tokens": len(t.plan_tokens),
                "query_len_tokens": len(t.query_tokens),
                "has_plan": t.has_plan,
                "has_tools": t.has_tools,
                "retrieval_tools": (t.retrieval_selected or {}).get("tools"),
            }
        )
    return pd.DataFrame(rows)


def usable(row) -> bool:
    """Same definition the controller uses: completed and parseable (D-11/D-18)."""
    return bool(row["completed"]) and str(row["answer_parse_status"]) == "ok" and bool(str(row["cluster_key"] or ""))


# --------------------------------------------------------------------------
# Instance-level classification: failure (A) vs substantive disagreement (B)
# --------------------------------------------------------------------------


def classify_instances(traces: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (task, tid), g in traces.groupby(["task_name", "task_instance_id"], sort=True):
        g = g.sort_values("trajectory_index")
        us = g[g.apply(usable, axis=1)]
        keys = list(us["cluster_key"])
        n_distinct = len(set(keys))
        counts = pd.Series(keys).value_counts() if keys else pd.Series(dtype=int)
        top = int(counts.iloc[0]) if len(counts) else 0
        rewards = dict(zip(us["cluster_key"], us["reward"], strict=False))
        plur_key = counts.index[0] if len(counts) else None
        any_correct = bool((us["reward"] > 0).any())
        plur_correct = bool(plur_key is not None and (rewards.get(plur_key) or 0) > 0)

        if len(us) < 2:
            evidence_state = "A_insufficient_evidence"
        elif n_distinct == 1:
            evidence_state = "unanimous"
        else:
            evidence_state = "B_substantive_disagreement"

        if not any_correct:
            outcome = "all_wrong"
        elif n_distinct == 1:
            outcome = "unanimous_correct"
        elif plur_correct:
            outcome = "correct_plurality"
        elif top > 1:
            outcome = "wrong_plurality_correct_minority"
        else:
            outcome = "tied_correct_minority"

        out.append(
            {
                "task_name": task,
                "task_instance_id": tid,
                "n_usable": len(us),
                "n_failed": int(len(g) - len(us)),
                "n_distinct_answers": n_distinct,
                "top_support": top,
                "evidence_state": evidence_state,
                "outcome": outcome,
                "any_correct": any_correct,
                "plurality_correct": plur_correct,
                "early_consensus": bool(
                    len(g) >= 2
                    and usable(g.iloc[0])
                    and usable(g.iloc[1])
                    and g.iloc[0]["cluster_key"] == g.iloc[1]["cluster_key"]
                ),
            }
        )
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# Pairwise table
# --------------------------------------------------------------------------


def build_cross_instance_control(traces: pd.DataFrame, seed: int = BOOTSTRAP_SEED, per_task: int = 400) -> pd.DataFrame:
    """Pairs of trajectories from **different instances of the same task**.

    Without this, a within-instance plan Jaccard of 0.5 is uninterpretable: it
    could mean "convergent on this question" or "this is just how much any two
    Biomni reasoning blocks overlap". This is the null - two trajectories that
    are answering *different questions* and therefore cannot be convergent on
    anything except style and task boilerplate.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for task, g in traces.groupby("task_name", sort=True):
        recs = g.to_dict("records")
        if len(recs) < 4:
            continue
        for _ in range(per_task):
            a, b = (recs[i] for i in rng.choice(len(recs), 2, replace=False))
            if a["task_instance_id"] == b["task_instance_id"]:
                continue
            d = pairwise_diversity(a["trace"], b["trace"])
            rows.append({"task_name": task, "task_instance_id": -1, "pair_kind": "cross_instance_control", **d})
    return pd.DataFrame(rows)


def build_pairs(traces: pd.DataFrame, inst: pd.DataFrame) -> pd.DataFrame:
    meta = inst.set_index(["task_name", "task_instance_id"]).to_dict("index")
    rows = []
    for (task, tid), g in traces.groupby(["task_name", "task_instance_id"], sort=True):
        g = g.sort_values("trajectory_index").to_dict("records")
        im = meta[(task, tid)]
        for a, b in itertools.combinations(g, 2):
            d = pairwise_diversity(a["trace"], b["trace"])
            both_usable = usable(a) and usable(b)
            rows.append(
                {
                    "task_name": task,
                    "task_instance_id": tid,
                    "run_a": a["run_id"],
                    "run_b": b["run_id"],
                    "idx_a": a["trajectory_index"],
                    "idx_b": b["trajectory_index"],
                    "both_usable": both_usable,
                    "same_answer": bool(both_usable and a["cluster_key"] == b["cluster_key"]),
                    "reward_a": a["reward"],
                    "reward_b": b["reward"],
                    "evidence_state": im["evidence_state"],
                    "outcome": im["outcome"],
                    "n_usable": im["n_usable"],
                    **d,
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Statistics: always clustered on the instance (D-13)
# --------------------------------------------------------------------------


def cluster_bootstrap_mean(df: pd.DataFrame, value: str, seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float, int]:
    """Mean of `value` with a 95% CI resampling INSTANCES, not rows."""
    d = df[["task_name", "task_instance_id", value]].dropna()
    if d.empty:
        return float("nan"), float("nan"), float("nan"), 0
    groups = [g[value].to_numpy() for _, g in d.groupby(["task_name", "task_instance_id"], sort=True)]
    rng = np.random.default_rng(seed)
    stats = np.empty(BOOTSTRAP_REPS)
    n = len(groups)
    for i in range(BOOTSTRAP_REPS):
        pick = rng.integers(0, n, n)
        stats[i] = np.concatenate([groups[j] for j in pick]).mean()
    obs = np.concatenate(groups).mean()
    return float(obs), float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5)), n


def cluster_bootstrap_diff(
    df: pd.DataFrame, value: str, mask_a: pd.Series, mask_b: pd.Series, seed: int = BOOTSTRAP_SEED
) -> dict:
    """Difference in means between two row subsets, resampling instances jointly."""
    d = df.assign(_a=mask_a, _b=mask_b).dropna(subset=[value])
    keys = sorted(set(map(tuple, d[["task_name", "task_instance_id"]].to_numpy())))
    # NOT dict(groupby): pandas exposes `keys` as an attribute, so dict() takes the
    # mapping path and raises "'list' object is not callable".
    by = {k: g for k, g in d.groupby(["task_name", "task_instance_id"], sort=True)}  # noqa: C416
    rng = np.random.default_rng(seed)
    out = np.full(BOOTSTRAP_REPS, np.nan)
    for i in range(BOOTSTRAP_REPS):
        pick = [keys[j] for j in rng.integers(0, len(keys), len(keys))]
        s = pd.concat([by[k] for k in pick])
        va, vb = s.loc[s._a, value], s.loc[s._b, value]
        if len(va) and len(vb):
            out[i] = va.mean() - vb.mean()
    obs_a, obs_b = d.loc[d._a, value], d.loc[d._b, value]
    return {
        "mean_a": float(obs_a.mean()) if len(obs_a) else float("nan"),
        "mean_b": float(obs_b.mean()) if len(obs_b) else float("nan"),
        "n_a": int(len(obs_a)),
        "n_b": int(len(obs_b)),
        "difference": float(obs_a.mean() - obs_b.mean()) if len(obs_a) and len(obs_b) else float("nan"),
        "ci_lo": float(np.nanpercentile(out, 2.5)),
        "ci_hi": float(np.nanpercentile(out, 97.5)),
        "n_instances": len(keys),
    }


# --------------------------------------------------------------------------
# The conditional analysis
# --------------------------------------------------------------------------


def correction_table(traces: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Ordered pairs (i wrong, j usable): does j hold the correct answer, as a
    function of how far j's workflow is from i's?

    Both directions of each unordered pair are emitted when both sides qualify,
    because "which came first" is an ordering artifact - the controller has no
    privileged order (D-21).
    """
    rows = []
    for r in pairs.to_dict("records"):
        if not r["both_usable"] or r["workflow_distance"] is None or pd.isna(r["workflow_distance"]):
            continue
        for wrong, other, rw_other in (
            (r["run_a"], r["run_b"], r["reward_b"]),
            (r["run_b"], r["run_a"], r["reward_a"]),
        ):
            rw_wrong = r["reward_a"] if wrong == r["run_a"] else r["reward_b"]
            if rw_wrong is None or pd.isna(rw_wrong) or rw_wrong > 0:
                continue  # the anchor must be WRONG
            rows.append(
                {
                    "task_name": r["task_name"],
                    "task_instance_id": r["task_instance_id"],
                    "wrong_run": wrong,
                    "other_run": other,
                    "corrects": int((rw_other or 0) > 0),
                    "workflow_distance": r["workflow_distance"],
                    "plan_jaccard": r["plan_jaccard"],
                    "tool_jaccard": r["tool_jaccard"],
                    "query_jaccard": r["query_jaccard"],
                    "tool_seq_similarity": r["tool_seq_similarity"],
                    "same_answer": r["same_answer"],
                    "outcome": r["outcome"],
                }
            )
    return pd.DataFrame(rows)


def minority_isolation(traces: pd.DataFrame, pairs: pd.DataFrame, inst: pd.DataFrame) -> pd.DataFrame:
    """In instances with a wrong plurality and a correct minority: is the correct
    trajectory further from the plurality than the plurality members are from
    each other? Paired within the instance, so instance difficulty cancels."""
    tgt = inst[inst.outcome == "wrong_plurality_correct_minority"]
    rows = []
    for _, im in tgt.iterrows():
        key = (im.task_name, im.task_instance_id)
        g = traces[(traces.task_name == key[0]) & (traces.task_instance_id == key[1])]
        us = g[g.apply(usable, axis=1)]
        counts = us["cluster_key"].value_counts()
        plur = counts.index[0]
        plur_runs = set(us[us.cluster_key == plur]["run_id"])
        correct_runs = set(us[(us.reward > 0)]["run_id"])
        p = pairs[(pairs.task_name == key[0]) & (pairs.task_instance_id == key[1]) & pairs.both_usable]
        within = p[p.run_a.isin(plur_runs) & p.run_b.isin(plur_runs)]["workflow_distance"].dropna()
        across = p[
            (p.run_a.isin(correct_runs) & p.run_b.isin(plur_runs))
            | (p.run_b.isin(correct_runs) & p.run_a.isin(plur_runs))
        ]["workflow_distance"].dropna()
        if len(within) and len(across):
            rows.append(
                {
                    "task_name": key[0],
                    "task_instance_id": key[1],
                    "within_plurality_distance": float(within.mean()),
                    "correct_to_plurality_distance": float(across.mean()),
                    "isolation": float(across.mean() - within.mean()),
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------


def tool_failure_breakdown(traces: pd.DataFrame, runs_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-tool call and error counts, plus the commonest execution errors.

    Track C's premise is that a VERIFY action would fetch *independent evidence*.
    Whether the evidence channel works at all is therefore a precondition, not a
    detail, so it is measured rather than assumed.
    """
    import collections

    calls: collections.Counter = collections.Counter()
    errs: collections.Counter = collections.Counter()
    msgs: collections.Counter = collections.Counter()
    for ev in runs_dir.glob("*/i*/*/t*/events.jsonl"):
        pending: dict = {}
        for line in ev.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue  # a truncated tail on a killed run: evidence, not an error
            p = e.get("payload") or {}
            if e.get("event_type") == "tool_call_start":
                pending[e.get("step_index")] = p.get("tool_name")
            elif e.get("event_type") == "tool_call_end":
                name = p.get("tool_name") or pending.get(e.get("step_index"))
                calls[name] += 1
                if str(p.get("status")) == "error":
                    errs[name] += 1
            elif e.get("event_type") == "code_execution_end" and str(p.get("status")) == "error":
                msgs[str(p.get("error") or "")[:80]] += 1
    tools = pd.DataFrame(
        [{"tool": k, "calls": v, "errors": errs[k], "error_rate": errs[k] / v} for k, v in calls.most_common()]
    )
    errors = pd.DataFrame([{"error": k, "n": v} for k, v in msgs.most_common(20)])
    return tools, errors


def figures(out: Path, by_bin: pd.DataFrame, cmpdf: pd.DataFrame, desc: pd.DataFrame) -> None:
    """Two figures, both answering a question asked in the report."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))

    ax[0].bar(range(len(by_bin)), by_bin.correction_rate, color="#4C72B0")
    base = by_bin.correction_rate.mean()
    ax[0].axhline(base, ls="--", c="crimson", label=f"overall {base:.3f}")
    ax[0].set_xticks(range(len(by_bin)))
    ax[0].set_xticklabels([str(x) for x in by_bin.distance_bin], rotation=20, ha="right", fontsize=8)
    ax[0].set_ylabel("P(other trajectory correct | anchor wrong)")
    ax[0].set_title("Does workflow independence predict correction?")
    ax[0].legend(fontsize=8)

    m = cmpdf.set_index("metric")
    keys = ["plan_jaccard", "tool_jaccard", "tool_seq_similarity", "query_jaccard"]
    x = range(len(keys))
    ax[1].bar([i - 0.2 for i in x], [m.loc[k, "same_answer"] for k in keys], 0.4, label="pairs that AGREE")
    ax[1].bar([i + 0.2 for i in x], [m.loc[k, "different_answer"] for k in keys], 0.4, label="pairs that DISAGREE")
    ctrl = desc[desc.subset.str.startswith("CONTROL")].set_index("metric")
    ax[1].plot(list(x), [ctrl.loc[k, "mean"] for k in keys], "k_", ms=26, label="control: different question")
    ax[1].set_xticks(list(x))
    ax[1].set_xticklabels([k.replace("_", "\n") for k in keys], fontsize=8)
    ax[1].set_ylabel("similarity")
    ax[1].set_title("Do disagreeing trajectories differ upstream?")
    ax[1].legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out / "tc_01_independence_and_correction.png", dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO / "configs/phase2b.yaml")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cfg = load_config(args.config)
    pooled = pd.read_csv(cfg.results_dir / "tables" / "p2b_pooled_trajectories.csv")
    print(f"loading {len(pooled)} traces ...")
    traces = load_traces(cfg, pooled)
    inst = classify_instances(traces)
    pairs = build_pairs(traces, inst)
    print(f"{len(inst)} instances, {len(pairs)} within-instance pairs\n")

    tables: dict[str, pd.DataFrame] = {}
    results: dict[str, object] = {}

    # -- 0. failure vs disagreement (section 4 of the brief) ---------------
    ev = inst.evidence_state.value_counts().rename_axis("evidence_state").reset_index(name="n_instances")
    tables["evidence_state"] = ev
    results["evidence_state"] = ev.set_index("evidence_state")["n_instances"].to_dict()
    print("== A (failure) vs B (substantive disagreement) ==")
    print(ev.to_string(index=False))

    outc = (
        inst.groupby(["evidence_state", "outcome"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["evidence_state", "n"])
    )
    tables["outcome_by_evidence_state"] = outc
    print("\n== outcome structure ==")
    print(outc.to_string(index=False))

    # -- 1. descriptive diversity ------------------------------------------
    desc = []
    for name, sub in (
        ("all pairs", pairs),
        ("both usable", pairs[pairs.both_usable]),
        (
            "B: substantive disagreement",
            pairs[(pairs.evidence_state == "B_substantive_disagreement") & pairs.both_usable],
        ),
        ("unanimous instances", pairs[(pairs.evidence_state == "unanimous") & pairs.both_usable]),
    ):
        for metric in (
            "workflow_distance",
            "plan_jaccard",
            "tool_jaccard",
            "tool_seq_similarity",
            "query_jaccard",
            "code_hash_jaccard",
        ):
            m, lo, hi, ni = cluster_bootstrap_mean(sub, metric)
            desc.append(
                {
                    "subset": name,
                    "metric": metric,
                    "mean": m,
                    "ci_lo": lo,
                    "ci_hi": hi,
                    "n_pairs": int(sub[metric].notna().sum()),
                    "n_instances": ni,
                }
            )
    ctrl = build_cross_instance_control(traces)
    for metric in (
        "workflow_distance",
        "plan_jaccard",
        "tool_jaccard",
        "tool_seq_similarity",
        "query_jaccard",
        "code_hash_jaccard",
    ):
        v = ctrl[metric].dropna()
        desc.append(
            {
                "subset": "CONTROL: different instance, same task",
                "metric": metric,
                "mean": float(v.mean()) if len(v) else float("nan"),
                "ci_lo": float(np.percentile(v, 2.5)) if len(v) else float("nan"),
                "ci_hi": float(np.percentile(v, 97.5)) if len(v) else float("nan"),
                "n_pairs": int(len(v)),
                "n_instances": -1,
            }
        )
    desc = pd.DataFrame(desc)
    tables["diversity_descriptives"] = desc
    tables["cross_instance_control"] = ctrl
    print("\n== diversity descriptives (instance-clustered 95% CI) ==")
    print(
        desc[desc.metric.isin(["workflow_distance", "plan_jaccard", "tool_jaccard"])].to_string(
            index=False, float_format=lambda v: f"{v: .3f}"
        )
    )

    # -- 2. do disagreeing pairs differ upstream? --------------------------
    bu = pairs[pairs.both_usable].copy()
    cmp_rows = []
    for metric in (
        "workflow_distance",
        "plan_jaccard",
        "tool_jaccard",
        "tool_seq_similarity",
        "query_jaccard",
        "code_hash_jaccard",
    ):
        r = cluster_bootstrap_diff(bu, metric, ~bu.same_answer, bu.same_answer)
        cmp_rows.append(
            {
                "metric": metric,
                "different_answer": r["mean_a"],
                "same_answer": r["mean_b"],
                "difference": r["difference"],
                "ci_lo": r["ci_lo"],
                "ci_hi": r["ci_hi"],
                "n_diff": r["n_a"],
                "n_same": r["n_b"],
            }
        )
    cmpdf = pd.DataFrame(cmp_rows)
    tables["disagree_vs_agree"] = cmpdf
    print("\n== do trajectories that DISAGREE differ upstream from those that AGREE? ==")
    print(cmpdf.to_string(index=False, float_format=lambda v: f"{v: .4f}"))

    # -- 3. the conditional: does distance predict correction? -------------
    corr = correction_table(traces, pairs)
    tables["correction_pairs"] = corr
    if len(corr):
        q = corr.workflow_distance.quantile([0.25, 0.5, 0.75]).to_list()
        corr["distance_bin"] = pd.cut(
            corr.workflow_distance, [-1, *q, 2], labels=["Q1 most similar", "Q2", "Q3", "Q4 most independent"]
        )
        by_bin = (
            corr.groupby("distance_bin", observed=True)
            .agg(
                n_pairs=("corrects", "size"),
                correction_rate=("corrects", "mean"),
                mean_distance=("workflow_distance", "mean"),
            )
            .reset_index()
        )
        tables["correction_by_distance"] = by_bin
        print("\n== P(the other trajectory is CORRECT | anchor trajectory is WRONG), by workflow distance ==")
        print(by_bin.to_string(index=False, float_format=lambda v: f"{v: .3f}"))

        hi_mask = corr.workflow_distance >= corr.workflow_distance.median()
        gap = cluster_bootstrap_diff(corr, "corrects", hi_mask, ~hi_mask)
        results["correction_gap_high_vs_low_distance"] = gap
        print(
            f"\n  high-distance minus low-distance correction rate: {gap['difference']:+.4f} "
            f"95% CI [{gap['ci_lo']:+.4f}, {gap['ci_hi']:+.4f}]  (n={gap['n_a']}/{gap['n_b']} pairs, "
            f"{gap['n_instances']} instances)"
        )

    # -- 4. is the correct minority more isolated? -------------------------
    mi = minority_isolation(traces, pairs, inst)
    tables["minority_isolation"] = mi
    if len(mi):
        m, lo, hi, ni = cluster_bootstrap_mean(mi.assign(task_name=mi.task_name), "isolation")
        results["minority_isolation"] = {"mean": m, "ci_lo": lo, "ci_hi": hi, "n_instances": int(len(mi))}
        print("\n== is a correct MINORITY further from the wrong plurality than the plurality is from itself? ==")
        print(
            f"  isolation (correct-to-plurality minus within-plurality distance): {m:+.4f} "
            f"95% CI [{lo:+.4f}, {hi:+.4f}]  n={len(mi)} instances"
        )

    # -- 5. early vs late consensus ----------------------------------------
    ec = inst[["task_name", "task_instance_id", "early_consensus", "outcome", "evidence_state"]]
    p2 = pairs.merge(ec, on=["task_name", "task_instance_id"])
    first_pair = p2[(p2.idx_a == 0) & (p2.idx_b == 1) & p2.both_usable]
    r = cluster_bootstrap_diff(first_pair, "workflow_distance", first_pair.early_consensus, ~first_pair.early_consensus)
    results["early_vs_late_consensus_first_pair_distance"] = r
    print("\n== workflow distance of the FIRST PAIR: early consensus vs not ==")
    print(
        f"  early-consensus pairs {r['mean_a']:.4f} (n={r['n_a']}) vs non-agreeing {r['mean_b']:.4f} (n={r['n_b']});"
        f" difference {r['difference']:+.4f} 95% CI [{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}]"
    )

    # -- 6. per-task, visible but not over-read ----------------------------
    bt = (
        pairs[pairs.both_usable]
        .groupby("task_name")
        .agg(
            n_pairs=("workflow_distance", "size"),
            workflow_distance=("workflow_distance", "mean"),
            plan_jaccard=("plan_jaccard", "mean"),
            tool_jaccard=("tool_jaccard", "mean"),
        )
        .reset_index()
    )
    tables["by_task"] = bt
    print("\n== per task (directional; cells are small) ==")
    print(bt.to_string(index=False, float_format=lambda v: f"{v: .3f}"))

    # -- 7. trajectory-level descriptives for the failure stratum ----------
    tl = traces.assign(usable=traces.apply(usable, axis=1))
    tstat = (
        tl.groupby("usable")
        .agg(
            n=("run_id", "size"),
            tool_calls=("n_tool_calls", "mean"),
            failed_tool_calls=("n_failed_tool_calls", "mean"),
            think_blocks=("n_think_blocks", "mean"),
            unique_tools=("n_unique_tools", "mean"),
            has_plan=("has_plan", "mean"),
            has_tools=("has_tools", "mean"),
        )
        .reset_index()
    )
    tables["trajectory_descriptives"] = tstat
    print("\n== trajectory-level, usable vs not ==")
    print(tstat.to_string(index=False, float_format=lambda v: f"{v: .3f}"))

    tool_fail = float(tl.n_failed_tool_calls.sum() / max(tl.n_tool_calls.sum(), 1))
    results["tool_call_error_rate"] = tool_fail
    print(f"\n  tool-call error rate across all trajectories: {tool_fail:.1%}")

    # -- 8. is the agent consulting evidence at all? -----------------------
    us = tl[tl.usable]
    ef = pd.DataFrame(
        [
            {
                "group": "zero tool calls",
                "n": int((us.n_tool_calls == 0).sum()),
                "accuracy": float(us[us.n_tool_calls == 0].reward.mean()),
            },
            {
                "group": ">=1 tool call",
                "n": int((us.n_tool_calls > 0).sum()),
                "accuracy": float(us[us.n_tool_calls > 0].reward.mean()),
            },
            {
                "group": ">=1 SUCCESSFUL tool call",
                "n": int(((us.n_tool_calls - us.n_failed_tool_calls) > 0).sum()),
                "accuracy": float(us[(us.n_tool_calls - us.n_failed_tool_calls) > 0].reward.mean()),
            },
        ]
    )
    tables["evidence_free_answering"] = ef
    results["fraction_zero_tool_calls"] = float((tl.n_tool_calls == 0).mean())
    print("\n== is the agent consulting evidence at all? (usable trajectories) ==")
    print(ef.to_string(index=False, float_format=lambda v: f"{v: .3f}"))
    print(
        f"  trajectories making NO tool call at all: {(tl.n_tool_calls == 0).sum()}/{len(tl)} = {(tl.n_tool_calls == 0).mean():.1%}"
    )

    # -- 9. are wrong pluralities more correlated than correct ones? -------
    same = pairs[pairs.both_usable & pairs.same_answer]
    plur = (
        same.groupby("outcome")
        .agg(
            n_pairs=("workflow_distance", "size"),
            workflow_distance=("workflow_distance", "mean"),
            plan_jaccard=("plan_jaccard", "mean"),
            tool_jaccard=("tool_jaccard", "mean"),
        )
        .reset_index()
    )
    tables["agreeing_pairs_by_outcome"] = plur
    print("\n== among pairs that AGREE: are wrong pluralities more correlated than correct ones? ==")
    print(plur.to_string(index=False, float_format=lambda v: f"{v: .3f}"))

    # -- 10. the evidence channel itself -----------------------------------
    tools_df, errors_df = tool_failure_breakdown(traces, cfg.runs_dir)
    tables["tool_failure_by_tool"] = tools_df
    tables["code_execution_errors"] = errors_df
    print("\n== the evidence channel: per-tool error rates ==")
    print(tools_df.head(12).to_string(index=False, float_format=lambda v: f"{v: .3f}"))

    try:
        figures(args.out, by_bin, cmpdf, desc)
        print("\nwrote figure tc_01_independence_and_correction.png")
    except Exception as exc:  # pragma: no cover - plotting is not load-bearing
        print(f"\n(figure skipped: {exc})")

    for name, df in tables.items():
        df.to_csv(args.out / f"tc_{name}.csv", index=False)
    traces.drop(columns=["trace"]).to_csv(args.out / "tc_trajectory_features.csv", index=False)
    inst.to_csv(args.out / "tc_instances.csv", index=False)
    pairs.to_csv(args.out / "tc_pairs.csv", index=False)
    (args.out / "track_c_diversity.json").write_text(json.dumps(results, indent=2, default=float))
    print(f"\nwrote {len(tables) + 3} tables to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
