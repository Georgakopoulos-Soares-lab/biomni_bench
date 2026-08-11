#!/usr/bin/env python
"""Stage A - existing-data decomposition (A.1-A.4). CPU only, no GPU, no model calls.

Nothing here gates Stage C (`reports/stage_c_stop_rule.md`, frozen and committed
before this script computed a single number). Everything here is mechanism
analysis for the manuscript.

=========================================================================
INTERPRETATION RULES - FIXED BEFORE ANY NUMBER IN THIS FILE WAS COMPUTED
=========================================================================

**A.1 - did Arm 2 lack verification ability, or did 2-of-3 majority destroy a
real signal?** The frozen D-38 verdict used majority resolution and is NOT
re-litigated here. Alternative aggregations locate the mechanism and are read as:

* Random single Arm-2 sample and in-menu-conditional accuracy both at or below
  the plurality floor (0.4103) => the samples do not beat voting and the
  aggregation destroyed nothing; the absence of recoverable signal is real.
* Any alternative aggregation *materially above* the floor - paired
  instance-clustered bootstrap CI for (aggregation - floor) excluding zero -
  => the 2-of-3 rule destroyed real signal, reported as a limitation of the
  pilot's aggregation, NEVER as a reversal of its verdict.
* Oracle@3 over Arm 2's own answers bounds what *any* aggregation of these
  samples could reach. Oracle@3 at or below the floor closes the aggregation
  question entirely.

**A.2 - is the harm interface harm or judgment harm?** Harm classes fixed now,
before counting: `wrong_in_menu` is JUDGMENT harm (the selector considered the
candidates and chose a worse one); `off_menu`, `no_majority`,
`trajectory_failure` are INTERFACE harm (no usable choice was ever delivered).

* interface share of harm >= 50% => quantitatively supports D-39's retraction:
  an elicitation failure, not a demonstrated inability to judge.
* interface share < 25% => the failure is genuinely one of judgment, and D-39's
  retraction, though logically correct, has little quantitative content.
* 25-50% => mixed; report as mixed, do not round to either story.

`delta == (capture - harm) / n` must hold EXACTLY for every selector (rewards
are binary). Asserted by test, not by inspection.

**A.3 - is the selectivity the controller's, or the agreement signal's?**

* If fixed K=4 with an agreement threshold reaches the same accepted-case
  accuracy at matched coverage, the agreement signal contributed the
  selectivity and the controller contributed nothing: it is a
  selective-prediction result, not a controller result.
* Only if the controller strictly dominates agreement-thresholded fixed K=4 at
  matched coverage may selectivity be attributed to the controller itself.

**A.4 - do cheap trace features separate the correct minority?**

* Every feature's instance-clustered AUROC CI covering 0.5 => traces carry no
  separating signal, and a later verifier null is attributable to the traces
  rather than to the verifier.
* Any feature with a CI excluding 0.5 => a separating signal exists and a
  verifier null would be a verifier failure. Exploratory: these features were
  taken from what happens to be instrumented, not pre-registered individually.

    python scripts/stage_a_decomposition.py --out reports/tables/stage_a
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from biomni_uncertainty.analysis import paired_bootstrap_difference  # noqa: E402

BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260811001

#: Frozen in reports/stage_c_stop_rule.md and D-37's canonical table.
PLURALITY_FLOOR = 0.4103

STEP2 = REPO / "reports" / "tables" / "track_c_step2"
PREFLIGHT = Path("/scratch/11034/atzanakak/biomni_unc_runs/track_c_preflight/results")
PHASE2B = Path("/scratch/11034/atzanakak/biomni_unc_runs/phase2b/results/tables")

#: Harm taxonomy, fixed before counting (A.2 rule above).
JUDGMENT_HARM = ("wrong_in_menu",)
INTERFACE_HARM = ("off_menu", "no_majority", "trajectory_failure")

KEY = ["task_name", "task_instance_id"]


# --------------------------------------------------------------------------
# Cluster bootstrap over instances (D-13), vectorised.
#
# `analysis.grouped_bootstrap` rebuilds a DataFrame per replicate, which costs
# milliseconds x 10,000 x every feature and makes this script unrunnable. The
# resampling scheme here is identical - whole instances drawn with replacement -
# but a mean over trajectories reduces to (sum of group sums)/(sum of group
# counts), which is a pure array operation.
# --------------------------------------------------------------------------


def cluster_boot_mean(values_by_group: list[np.ndarray], *, seed=BOOTSTRAP_SEED, reps=BOOTSTRAP_REPLICATES) -> dict:
    sums = np.array([v.sum() for v in values_by_group], dtype=float)
    cnts = np.array([len(v) for v in values_by_group], dtype=float)
    if cnts.sum() == 0:
        return {"point": None, "ci_lo": None, "ci_hi": None, "n": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(reps, len(sums)))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return {
        "point": float(sums.sum() / cnts.sum()),
        "ci_lo": float(np.quantile(means, 0.025)),
        "ci_hi": float(np.quantile(means, 0.975)),
        "n": int(len(sums)),
    }


def _auroc(x: np.ndarray, y: np.ndarray) -> float | None:
    m = ~np.isnan(x)
    x, y = x[m], y[m]
    n1 = int(y.sum())
    n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return None
    order = np.argsort(x, kind="mergesort")
    sx = x[order]
    ranks = np.empty(len(x), dtype=float)
    i = 0
    while i < len(sx):
        j = i
        while j + 1 < len(sx) and sx[j + 1] == sx[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def cluster_boot_auroc(
    xy_by_group: list[tuple[np.ndarray, np.ndarray]], *, seed=BOOTSTRAP_SEED, reps=2_000, n_tests=1
) -> dict:
    """AUROC needs the concatenated vectors, so this cannot reduce to sums.
    2,000 replicates: enough for a 95% percentile interval, and it keeps the
    seven-feature sweep to seconds rather than minutes.

    `n_tests` adds a Bonferroni-adjusted interval alongside the nominal 95% one.
    A.4 sweeps seven features that were taken from whatever happens to be
    instrumented rather than pre-registered individually, so a nominal interval
    that just clears 0.5 on one of seven is exactly the result most likely to be
    multiplicity noise - reporting both makes that visible instead of arguable.
    """
    xs = [g[0] for g in xy_by_group]
    ys = [g[1] for g in xy_by_group]
    point = _auroc(np.concatenate(xs), np.concatenate(ys))
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(reps):
        idx = rng.integers(0, len(xs), size=len(xs))
        v = _auroc(np.concatenate([xs[i] for i in idx]), np.concatenate([ys[i] for i in idx]))
        if v is not None:
            stats.append(v)
    if not stats:
        return {"point": point, "ci_lo": None, "ci_hi": None, "n": len(xs)}
    a = 0.05 / n_tests
    return {
        "point": point,
        "ci_lo": float(np.quantile(stats, 0.025)),
        "ci_hi": float(np.quantile(stats, 0.975)),
        "bonf_ci_lo": float(np.quantile(stats, a / 2)),
        "bonf_ci_hi": float(np.quantile(stats, 1 - a / 2)),
        "n": len(xs),
    }


def _lit(x):
    if isinstance(x, list):
        return x
    if pd.isna(x):
        return []
    return ast.literal_eval(x)


def load_candidates() -> pd.DataFrame:
    recs = [json.loads(x) for x in (STEP2 / "candidates_slim.jsonl").read_text().splitlines() if x.strip()]
    return pd.DataFrame(recs)


def load_floor() -> pd.DataFrame:
    a = pd.read_csv(PREFLIGHT / "instance_table__phase2b.csv").assign(pool="phase2b")
    b = pd.read_csv(PREFLIGHT / "instance_table__phase1_pooled.csv").assign(pool="phase1_pooled")
    return pd.concat([a, b], ignore_index=True)


# ==========================================================================
# A.1
# ==========================================================================


def run_a1(out: Path) -> dict:
    traj = pd.read_csv(STEP2 / "arm2_per_trajectory.csv")
    inst = pd.read_csv(STEP2 / "arm2_per_instance.csv")
    cands = load_candidates()
    floor = load_floor()

    traj["task_instance_id"] = traj.task_instance_id.astype(int)
    traj["usable"] = traj.completed.fillna(False).astype(bool) & traj.answer_canonical.notna()
    menu = {(r.task_name, int(r.task_instance_id)): list(r.candidates) for r in cands.itertuples()}
    traj["in_menu"] = [
        (a in menu.get((t, i), [])) if pd.notna(a) else False
        for t, i, a in zip(traj.task_name, traj.task_instance_id, traj.answer_canonical, strict=True)
    ]
    traj["reward0"] = traj.reward.fillna(0.0)
    traj["ikey"] = list(zip(traj.task_name, traj.task_instance_id, strict=True))

    res: dict = {
        "n_trajectories": int(len(traj)),
        "n_instances": int(traj.ikey.nunique()),
        "n_usable_trajectories": int(traj.usable.sum()),
        "plurality_floor": PLURALITY_FLOOR,
    }

    # -- per-sample accuracies, cluster-bootstrapped over instances ---------
    def groups(frame):
        return [g.reward0.to_numpy(dtype=float) for _, g in frame.groupby("ikey")]

    res["per_sample_all"] = cluster_boot_mean(groups(traj))
    res["per_sample_usable_only"] = cluster_boot_mean(groups(traj[traj.usable]))
    res["per_sample_in_menu_only"] = cluster_boot_mean(groups(traj[traj.in_menu]))

    # -- one randomly-drawn sample per instance; bootstrap BOTH the draw and
    #    the instance resample, so the CI covers sampling and selection alike.
    by = [g.reward0.to_numpy(dtype=float) for _, g in traj.groupby("ikey")]
    width = max(len(v) for v in by)
    padded = np.zeros((len(by), width), dtype=float)
    counts = np.array([len(v) for v in by], dtype=int)
    for i, v in enumerate(by):
        padded[i, : len(v)] = v
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    inst_idx = rng.integers(0, len(by), size=(BOOTSTRAP_REPLICATES, len(by)))
    within = (rng.random((BOOTSTRAP_REPLICATES, len(by))) * counts[inst_idx]).astype(int)
    means = padded[inst_idx, within].mean(axis=1)
    res["random_single_sample"] = {
        "point": float(np.mean([v.mean() for v in by])),
        "ci_lo": float(np.quantile(means, 0.025)),
        "ci_hi": float(np.quantile(means, 0.975)),
        "n": len(by),
    }

    # -- alternative aggregations (MECHANISM ONLY) -------------------------
    fl = floor.set_index(KEY)
    rows = []
    for (task, tid), g in traj.groupby(KEY):
        g = g.sort_values("trajectory_index")
        u = g[g.usable]
        answers = list(u.answer_canonical)
        rew = {a: float(r) for a, r in zip(u.answer_canonical, u.reward0, strict=True)}
        plur = None
        if answers:
            c = Counter(answers)
            top = max(c.values())
            plur = next(a for a in answers if c[a] == top)  # earliest arrival breaks ties
        rows.append(
            {
                "task_name": task,
                "task_instance_id": int(tid),
                "plurality_floor": float(fl.loc[(task, int(tid))].plurality_reward),
                "agg_plurality_available": rew.get(plur, 0.0) if plur is not None else 0.0,
                "agg_oracle_at_3": float(u.reward0.max()) if len(u) else 0.0,
                "n_usable": int(len(u)),
                "n_in_menu": int(g.in_menu.sum()),
            }
        )
    agg = pd.DataFrame(rows)
    agg.to_csv(out / "a1_alternative_aggregations.csv", index=False)

    res["aggregations"] = {}
    for col in ("agg_plurality_available", "agg_oracle_at_3"):
        res["aggregations"][col] = {
            "mean": float(agg[col].mean()),
            "vs_floor": paired_bootstrap_difference(
                agg[col].to_numpy(dtype=float),
                agg.plurality_floor.to_numpy(dtype=float),
                replicates=BOOTSTRAP_REPLICATES,
                seed=BOOTSTRAP_SEED,
            ),
        }
    res["aggregations"]["floor_recomputed"] = float(agg.plurality_floor.mean())

    # -- off-menu: violation, or a correction of an incomplete menu? -------
    off = traj[traj.usable & ~traj.in_menu]
    res["off_menu"] = {
        "n_off_menu_trajectories": int(len(off)),
        "n_off_menu_and_correct": int((off.reward0 > 0).sum()),
        "note": (
            "an off-menu answer scoring 1.0 means the true answer was ABSENT from the "
            "candidate set - the agent corrected the menu rather than merely violating it"
        ),
    }

    # -- trace correlates --------------------------------------------------
    def split(mask, label):
        a, b = traj[mask], traj[~mask]
        return {
            f"{label}_accuracy": float(a.reward0.mean()) if len(a) else None,
            f"not_{label}_accuracy": float(b.reward0.mean()) if len(b) else None,
            f"n_{label}": int(len(a)),
            f"n_not_{label}": int(len(b)),
        }

    res["tool_engagement"] = split(traj.tool_call_count.fillna(0) > 0, "used_tools")
    res["runaway"] = split(traj.runaway_generations.fillna(0) > 0, "runaway")

    # -- five terminal categories, asserted to partition -------------------
    inst["task_instance_id"] = inst.task_instance_id.astype(int)
    per_inst = dict(traj.groupby(KEY).__iter__())
    cats = []
    for r in inst.itertuples():
        g = per_inst[(r.task_name, int(r.task_instance_id))]
        if int(g.usable.sum()) == 0:
            cats.append("all_failed")
        elif r.majority_status == "majority":
            cats.append("usable_correct" if float(r.reward) > 0 else "usable_wrong")
        elif int(g.in_menu.sum()) == 0:
            cats.append("off_menu")
        else:
            cats.append("unresolved_aggregation")
    inst["terminal_category"] = cats
    assert len(inst) == 78, "the stratum-B population is 78 instances"
    res["terminal_categories"] = inst.terminal_category.value_counts().to_dict()
    assert sum(res["terminal_categories"].values()) == len(inst)
    inst.to_csv(out / "a1_terminal_categories.csv", index=False)

    return res, traj, inst, agg


# ==========================================================================
# A.2
# ==========================================================================


def capture_harm(sel, base, classes=None) -> dict:
    """Decompose mean(sel) - mean(base) into capture and harm. Binary rewards,
    so the identity delta == (capture - harm)/n is exact."""
    sel = np.asarray(sel, dtype=float)
    base = np.asarray(base, dtype=float)
    n = len(sel)
    capture = int(((base == 0) & (sel == 1)).sum())
    harm = int(((base == 1) & (sel == 0)).sum())
    delta = float(sel.mean() - base.mean())
    out = {
        "n": n,
        "capture": capture,
        "harm": harm,
        "neutral_correct": int(((base == 1) & (sel == 1)).sum()),
        "neutral_wrong": int(((base == 0) & (sel == 0)).sum()),
        "delta": delta,
        "delta_from_counts": (capture - harm) / n,
        "reconciles": bool(abs(delta - (capture - harm) / n) < 1e-12),
    }
    if classes is not None:
        harmed = Counter(c for c, b, s in zip(classes, base, sel, strict=True) if b == 1 and s == 0)
        interface = sum(v for k, v in harmed.items() if k in INTERFACE_HARM)
        judgment = sum(v for k, v in harmed.items() if k in JUDGMENT_HARM)
        out["harm_classes"] = dict(harmed)
        out["interface_harm"] = interface
        out["judgment_harm"] = judgment
        out["interface_share_of_harm"] = (interface / harm) if harm else None
    return out


def run_a2(traj: pd.DataFrame, inst: pd.DataFrame, out: Path) -> dict:
    res = {}

    # -- selectors on the 78 stratum-B instances: Arm 1 and Arm 2 ----------
    floor = load_floor().set_index(KEY)
    arm1 = pd.read_csv(STEP2 / "arm1_per_instance.csv")
    arm1["task_instance_id"] = arm1.task_instance_id.astype(int)
    inst = inst.set_index(KEY)
    arm1 = arm1.set_index(KEY)
    order = list(inst.index)

    base78 = np.array([float(floor.loc[k].plurality_reward) for k in order])

    def harm_classes_for(idx, resolved_flag, in_menu_count, usable_count):
        cls = []
        for k in idx:
            if usable_count[k] == 0:
                cls.append("trajectory_failure")
            elif in_menu_count[k] == 0:
                cls.append("off_menu")
            elif not resolved_flag[k]:
                cls.append("no_majority")
            else:
                cls.append("wrong_in_menu")
        return cls

    per_inst = dict(traj.groupby(KEY).__iter__())
    usable_ct = {k: int(g.usable.sum()) for k, g in per_inst.items()}
    inmenu_ct = {k: int(g.in_menu.sum()) for k, g in per_inst.items()}

    arm2_sel = np.array([float(inst.loc[k].reward) for k in order])
    arm2_res = {k: inst.loc[k].majority_status == "majority" for k in order}
    res["arm2_vs_plurality"] = capture_harm(arm2_sel, base78, harm_classes_for(order, arm2_res, inmenu_ct, usable_ct))

    arm1_sel = np.array([float(arm1.loc[k].reward) for k in order])
    # Arm 1 has no agent trajectory, so "trajectory_failure" cannot apply; its
    # unresolved cases are all_missing (an API/extraction failure) or no_majority.
    arm1_cls = ["no_majority" if arm1.loc[k].majority_status != "majority" else "wrong_in_menu" for k in order]
    res["arm1_vs_plurality"] = capture_harm(arm1_sel, base78, arm1_cls)

    # -- plurality against itself: the identity control --------------------
    res["plurality_vs_plurality_identity_control"] = capture_harm(base78, base78)

    # -- controller v1 on the phase2b 150 ----------------------------------
    ro = pd.read_csv(PHASE2B / "p2b_realized_outcomes.csv")
    ctrl = ro[ro.policy == "mandatory_k2_online"].set_index(KEY).sort_index()
    k4 = ro[ro.policy == "fixed_k4"].set_index(KEY).sort_index()
    idx150 = list(ctrl.index)
    ctrl_sel = np.array([float(ctrl.loc[k].reward_abstain_zero) for k in idx150])
    k4_base = np.array([float(k4.loc[k].reward_abstain_zero) for k in idx150])
    ctrl_cls = ["no_majority" if ctrl.loc[k].action == "ABSTAIN" else "wrong_in_menu" for k in idx150]
    res["controller_v1_vs_fixed_k4"] = capture_harm(ctrl_sel, k4_base, ctrl_cls)

    # plurality baseline on phase2b == fixed_k4 plurality; also compare to K=2
    k2 = ro[ro.policy == "fixed_k2"].set_index(KEY).sort_index()
    res["controller_v1_vs_fixed_k2"] = capture_harm(
        ctrl_sel, np.array([float(k2.loc[k].reward_abstain_zero) for k in idx150]), ctrl_cls
    )

    pd.DataFrame(
        [{"selector": k, **{kk: vv for kk, vv in v.items() if not isinstance(vv, dict)}} for k, v in res.items()]
    ).to_csv(out / "a2_capture_harm.csv", index=False)
    return res


# ==========================================================================
# A.3
# ==========================================================================


def run_a3(out: Path) -> dict:
    """Risk-coverage at matched coverage. Abstention-as-zero is kept (the
    protocol mandated it) and this is added alongside, not instead."""
    ro = pd.read_csv(PHASE2B / "p2b_realized_outcomes.csv")
    res = {}

    ctrl = ro[ro.policy == "mandatory_k2_online"].copy()
    # The controller's own selectivity ordering is how early agreement arrived.
    ctrl_acc = ctrl[ctrl.action == "ACCEPT"].copy()
    curve_c = []
    for kmax in sorted(ctrl_acc.k_used.unique()):
        sub = ctrl_acc[ctrl_acc.k_used <= kmax]
        curve_c.append(
            {
                "threshold": f"k_used<={int(kmax)}",
                "coverage": len(sub) / len(ctrl),
                "accuracy": float(sub.reward.mean()),
                "n": len(sub),
            }
        )
    res["controller"] = curve_c

    # Fixed K=4, thresholded on agreement (support), the like-for-like signal.
    k4 = ro[ro.policy == "fixed_k4"].copy()
    curve_k = []
    for s in sorted(k4.support.unique(), reverse=True):
        sub = k4[k4.support >= s]
        curve_k.append(
            {
                "threshold": f"support>={int(s)}",
                "coverage": len(sub) / len(k4),
                "accuracy": float(sub.reward.mean()),
                "n": len(sub),
            }
        )
    res["fixed_k4_agreement_threshold"] = curve_k

    # Matched-coverage comparison: for each controller point, the accuracy an
    # agreement-thresholded fixed K=4 achieves at >= that coverage.
    matched = []
    for c in curve_c:
        feasible = [k for k in curve_k if k["coverage"] >= c["coverage"] - 1e-9]
        best = min(feasible, key=lambda k: k["coverage"]) if feasible else None
        matched.append(
            {
                "controller_threshold": c["threshold"],
                "coverage": c["coverage"],
                "controller_accuracy": c["accuracy"],
                "k4_threshold": best["threshold"] if best else None,
                "k4_coverage": best["coverage"] if best else None,
                "k4_accuracy": best["accuracy"] if best else None,
                "controller_minus_k4": (c["accuracy"] - best["accuracy"]) if best else None,
            }
        )
    res["matched_coverage"] = matched
    dominates = [m for m in matched if m["controller_minus_k4"] is not None and m["controller_minus_k4"] > 0]
    res["dominates_at_all_matched_points"] = len(dominates) == len(matched) and bool(matched)
    res["dominates_at_any_matched_point"] = len(dominates) > 0
    res["verdict_per_prefixed_rule"] = (
        "selectivity attributable to the CONTROLLER"
        if res["dominates_at_all_matched_points"]
        else "selectivity attributable to the AGREEMENT SIGNAL, not the controller"
    )

    # AURC (lower is better): risk = 1 - accuracy. The two curves span DIFFERENT
    # coverage domains - the controller cannot go below 0.433 coverage or above
    # 0.807 - so a raw AURC comparison would be apples to oranges and would
    # spuriously favour whichever curve happens to cover less of the hard tail.
    # Restrict to the overlap and say so.
    def aurc(curve, lo=None, hi=None):
        cs = sorted(curve, key=lambda r: r["coverage"])
        xs = [c["coverage"] for c in cs]
        ys = [1 - c["accuracy"] for c in cs]
        if lo is not None:
            grid = [x for x in xs if lo - 1e-9 <= x <= hi + 1e-9]
            if len(grid) < 2:
                return None
            ys = [np.interp(x, xs, ys) for x in grid]
            xs = grid
        return float(np.trapezoid(ys, xs))

    lo = max(min(c["coverage"] for c in curve_c), min(c["coverage"] for c in curve_k))
    hi = min(max(c["coverage"] for c in curve_c), max(c["coverage"] for c in curve_k))
    res["aurc_overlap_domain"] = {"coverage_lo": lo, "coverage_hi": hi}
    res["aurc_controller_overlap"] = aurc(curve_c, lo, hi)
    res["aurc_fixed_k4_agreement_overlap"] = aurc(curve_k, lo, hi)
    res["aurc_note"] = (
        "restricted to the overlapping coverage domain; full-domain AURCs are not comparable "
        "because the controller's reachable coverage range is a strict subset of fixed K=4's"
    )

    # Coverage achievable at fixed error limits.
    def coverage_at(curve, err):
        ok = [c for c in curve if (1 - c["accuracy"]) <= err]
        return max([c["coverage"] for c in ok], default=0.0)

    res["coverage_at_error_limit"] = {
        f"{int(e * 100)}%": {
            "controller": coverage_at(curve_c, e),
            "fixed_k4_agreement": coverage_at(curve_k, e),
        }
        for e in (0.05, 0.10, 0.20)
    }

    pd.DataFrame(matched).to_csv(out / "a3_matched_coverage.csv", index=False)
    pd.DataFrame(curve_c + curve_k).to_csv(out / "a3_risk_coverage_curves.csv", index=False)
    return res


# ==========================================================================
# A.4
# ==========================================================================


def run_a4(out: Path) -> dict:
    """Do cheap trace features separate the correct minority from the wrong
    plurality, on the disagreement instances? Trajectory-level, labelled by
    whether that trajectory holds the correct answer; AUROC with an
    instance-clustered bootstrap."""
    p2b = pd.read_csv(PHASE2B / "p2b_pooled_trajectories.csv")
    pre = pd.read_csv(PREFLIGHT / "instance_table__phase2b.csv")
    split_ids = set(
        map(
            tuple, pre[pre.evidence_state == "B_substantive_disagreement"][KEY].astype({"task_instance_id": int}).values
        )
    )
    p2b["task_instance_id"] = p2b.task_instance_id.astype(int)
    d = p2b[[tuple(x) in split_ids for x in p2b[KEY].values]].copy()
    d = d[d.completed.fillna(False) & d.answer_canonical.notna()]
    d["label"] = (d.reward.fillna(0) > 0).astype(int)
    d["ikey"] = list(zip(d.task_name, d.task_instance_id, strict=True))

    feats = {
        "tool_call_count": d.tool_call_count,
        "unique_tool_count": d.unique_tool_count,
        "code_execution_count": d.code_execution_count,
        "failed_tool_call_fraction": d.failed_tool_call_fraction,
        "total_output_tokens": d.total_output_tokens,
        "llm_call_count": d.llm_call_count,
        "final_confidence": d.final_confidence,
    }

    res = {
        "n_trajectories": int(len(d)),
        "n_instances": int(d.ikey.nunique()),
        "n_features_tested": len(feats),
        "features": {},
    }
    for name in feats:
        xy = [
            (g[name].to_numpy(dtype=float), g["label"].to_numpy())
            for _, g in d[["label", name, "ikey"]].groupby("ikey")
        ]
        res["features"][name] = cluster_boot_auroc(xy, n_tests=len(feats))

    def excludes_half(v, lo="ci_lo", hi="ci_hi"):
        return v[lo] is not None and (v[lo] > 0.5 or v[hi] < 0.5)

    sep = {k: v for k, v in res["features"].items() if excludes_half(v)}
    sep_bonf = {k: v for k, v in res["features"].items() if excludes_half(v, "bonf_ci_lo", "bonf_ci_hi")}
    res["features_separating_at_95pct"] = sorted(sep)
    res["features_separating_bonferroni"] = sorted(sep_bonf)
    res["margins_of_separating_features"] = {
        k: {"point": v["point"], "distance_of_ci_from_0.5": min(abs(v["ci_lo"] - 0.5), abs(v["ci_hi"] - 0.5))}
        for k, v in sep.items()
    }
    res["verdict_per_prefixed_rule"] = (
        "traces carry NO separating signal; a verifier null is attributable to the traces"
        if not sep
        else "a separating signal exists in the traces; a verifier null would be a verifier failure"
    )
    res["multiplicity_caveat"] = (
        f"POST HOC (added after seeing that exactly one of {len(feats)} features cleared the nominal bar, "
        "and therefore labelled post hoc rather than presented as pre-registered; the *exploratory* framing "
        "of this feature sweep was however fixed in advance in this module's docstring). "
        f"Nominal-95% hits: {sorted(sep)}. Bonferroni-adjusted hits: {sorted(sep_bonf)}. "
        "The pre-registered verdict string above is reported mechanically and is NOT restated to fit this "
        "check; read the two together."
    )
    pd.DataFrame([{"feature": k, **v} for k, v in res["features"].items()]).to_csv(
        out / "a4_trace_discriminability.csv", index=False
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    a1, traj, inst, _agg = run_a1(args.out)
    a2 = run_a2(traj, inst, args.out)
    a3 = run_a3(args.out)
    a4 = run_a4(args.out)

    report = {"A1_arm2_decomposition": a1, "A2_capture_harm": a2, "A3_risk_coverage": a3, "A4_trace_probe": a4}
    (args.out / "stage_a_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
