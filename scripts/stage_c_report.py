#!/usr/bin/env python3
"""Stage C — the §9 reporting analyses, written before any outcome exists.

`stage_c_analyze.py` computes the pre-specified verdict and nothing else. This
script computes everything `reports/stage_c_preregistration.md` §9 requires
*around* that verdict, and is deliberately a separate file so the order of
reporting matches the order of commitment: the verdict is reported first, and
these are reported after it, as secondary and explanatory.

Committed before any BiomniEval1 comparison was scored, for the same reason
the verdict script was: an analysis written after seeing an outcome is an
analysis chosen to fit it.

Everything here is **descriptive**. Nothing in this file can produce,
overturn, or soften a verdict.

Usage
-----
    python scripts/stage_c_report.py --out <dir> --cell c1
"""

from __future__ import annotations

import argparse
import json
import random
from itertools import permutations
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
import sys  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
import stage_c_analyze as sca  # noqa: E402

#: A.5b moved the phase2b denominators. §9 requires official and
#: audit-corrected headroom side by side wherever headroom is quoted.
AUDIT_CORRECTED = {
    "official": {"no_correct": 45, "no_correct_rate": 0.300, "oracle_at_4": 0.700, "selection_headroom": 0.093},
    "audit_corrected": {"no_correct": 42, "no_correct_rate": 0.280, "oracle_at_4": 0.720, "selection_headroom": 0.113},
    "note": (
        "A.5b's singled_out fraction is reported as the band 20%-51% per D-42, not as a point. "
        "These figures are for the 150-instance phase2b population; the frozen 78's floor "
        "(0.4103) and ceiling (0.6026) are unaffected."
    ),
}


# ---------------------------------------------------------------------------
# A.2 capture / harm decomposition
# ---------------------------------------------------------------------------


def capture_harm(df: pd.DataFrame) -> dict:
    """`Delta = (capture - harm)/n`, reconciling exactly, as A.2 requires.

    capture = plurality wrong and selector correct
    harm    = plurality correct and selector wrong or unresolved
    """
    plur = df.plurality_reward_descriptive.to_numpy()
    sel = df.selector_reward.to_numpy()
    capture = int(((plur == 0) & (sel == 1)).sum())
    harm_mask = (plur == 1) & (sel == 0)
    harm = int(harm_mask.sum())
    sub = df[harm_mask]
    breakdown = {
        "unresolved_tie": int(sub.unresolved_tie.sum()),
        "wrong_in_menu": int((~sub.unresolved_tie & (sub.oracle_over_candidates == 1)).sum()),
        "unreachable": int((sub.oracle_over_candidates == 0).sum()),
    }
    n = len(df)
    return {
        "n": n,
        "capture": capture,
        "harm": harm,
        "harm_breakdown": breakdown,
        "delta_from_decomposition": round((capture - harm) / n, 6),
        "interface_share_of_harm": round(breakdown["unresolved_tie"] / harm, 4) if harm else None,
    }


# ---------------------------------------------------------------------------
# ranking quality
# ---------------------------------------------------------------------------


def ranking_auroc(sel_records: list[dict], rewards: dict) -> dict:
    """AUROC of the verifier's mean preference for holding a correct answer.

    Computed over candidates, clustered by instance: the resampling unit is
    the instance, never the individual candidate (north-star constraint).
    """
    groups = []
    for s in sel_records:
        key = (s["pool"], s["task_name"], int(s["task_instance_id"]))
        for ans, score in zip(s["candidate_answers"], s["mean_preference"], strict=True):
            r = rewards.get((*key, str(ans)))
            if r is None:
                continue
            groups.append((key, score, r))
    scores = np.array([g[1] for g in groups])
    labels = np.array([g[2] for g in groups])
    if labels.min() == labels.max():
        return {"auroc": None, "note": "degenerate: all candidates share one label"}
    order = scores.argsort()
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    # average ranks for ties
    for v in np.unique(scores):
        m = scores == v
        ranks[m] = ranks[m].mean()
    n1 = int(labels.sum())
    n0 = len(labels) - n1
    auroc = (ranks[labels == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    return {"auroc": round(float(auroc), 4), "n_candidates": len(labels), "n_correct": n1}


def intransitivity(sel_records: list[dict]) -> dict:
    """Fraction of instances whose pairwise preferences contain a cycle.

    **Only defined for N >= 3.** A verifier producing cyclic preferences over
    three candidates is guessing, and that is measurable without any reward.
    The denominator is reported explicitly because it is small (19 of 78 on
    the frozen population) and the rate must never be quoted against 78.
    """
    eligible = [s for s in sel_records if s["n_candidates"] >= 3]
    cyclic = 0
    for s in eligible:
        n = s["n_candidates"]
        beats = {(a, b): s["pairwise"][f"{a}>{b}"]["p_a_beats_b"] > 0.5 for a, b in permutations(range(n), 2)}
        found = False
        for a in range(n):
            for b in range(n):
                for c in range(n):
                    if len({a, b, c}) == 3 and beats[(a, b)] and beats[(b, c)] and beats[(c, a)]:
                        found = True
        cyclic += int(found)
    return {
        "n_eligible": len(eligible),
        "n_total_instances": len(sel_records),
        "n_cyclic": cyclic,
        "intransitivity_rate": round(cyclic / len(eligible), 4) if eligible else None,
        "note": "defined only for instances with >=3 unique candidates; never quote against n=78",
    }


# ---------------------------------------------------------------------------
# margin-conditional accuracy and risk-coverage
# ---------------------------------------------------------------------------


def risk_coverage(df: pd.DataFrame) -> dict:
    """Accuracy as a function of coverage, ranking by the verifier's margin.

    The margin is the selection signal: abstain on the smallest margins first.
    A.3 showed this project's selectivity belonged to plain agreement counting,
    so this curve is reported against that benchmark rather than alone.
    """
    d = df.sort_values("margin", ascending=False).reset_index(drop=True)
    rows = []
    for frac in (0.1, 0.25, 0.5, 0.75, 1.0):
        k = max(1, int(round(frac * len(d))))
        head = d.head(k)
        rows.append(
            {
                "coverage": round(k / len(d), 4),
                "n": k,
                "accuracy": round(float(head.selector_reward.mean()), 4),
                "min_margin": round(float(head.margin.min()), 6),
            }
        )
    # AURC over the reported grid, trapezoidal in (coverage, risk)
    cov = [r["coverage"] for r in rows]
    risk = [1 - r["accuracy"] for r in rows]
    aurc = float(np.trapezoid(risk, cov)) if len(cov) > 1 else None
    return {"curve": rows, "aurc": round(aurc, 4) if aurc is not None else None}


def margin_conditional(df: pd.DataFrame) -> dict:
    q = df.margin.quantile([0.25, 0.5, 0.75]).to_dict()
    bins = [("q1_lowest", df[df.margin <= q[0.25]]), ("q4_highest", df[df.margin >= q[0.75]])]
    return {
        name: {"n": len(b), "accuracy": round(float(b.selector_reward.mean()), 4) if len(b) else None}
        for name, b in bins
    }


# ---------------------------------------------------------------------------
# PPT secondary - a re-aggregation of cached scores, zero extra compute
# ---------------------------------------------------------------------------


def ppt_secondary(sel_records: list[dict], rewards: dict, seed: int = 0) -> dict:
    """The published Probabilistic Pivot Tournament over the same scores.

    Round-robin scores every directed pair, so a PPT run is a strict subset of
    what is already cached: this is a re-aggregation, not new sampling, and not
    a second shot at the endpoint (stop rule §7.4 - reported as mechanism
    analysis, never substituted into the decision rule).
    """
    rng = random.Random(seed)
    total = 0.0
    for s in sel_records:
        n = s["n_candidates"]
        key = (s["pool"], s["task_name"], int(s["task_instance_id"]))
        p = {(a, b): s["pairwise"][f"{a}>{b}"]["p_a_beats_b"] for a, b in permutations(range(n), 2)}
        w = [0.0] * n
        c = [0] * n
        perm = list(range(n))
        rng.shuffle(perm)
        ring = [(perm[t], perm[(t + 1) % n]) for t in range(n)] if n > 1 else []
        for a, b in ring:
            w[a] += p[(a, b)]
            c[a] += 1
            w[b] += 1 - p[(a, b)]
            c[b] += 1
        order = sorted(range(n), key=lambda i: (-(w[i] / c[i] if c[i] else 0.0), i))
        pivots = order[: min(2, n)]
        pairs = [(i, q) for i in range(n) if i not in pivots for q in pivots]
        pairs += [(pivots[i], pivots[j]) for i in range(len(pivots)) for j in range(i + 1, len(pivots))]
        for a, b in pairs:
            w[a] += p[(a, b)]
            c[a] += 1
            w[b] += 1 - p[(a, b)]
            c[b] += 1
        best = max(range(n), key=lambda i: (w[i] / c[i] if c[i] else 0.0, -i))
        total += rewards.get((*key, str(s["candidate_answers"][best])), 0.0)
    mean = total / len(sel_records)
    return {
        "ppt_mean_reward": round(mean, 4),
        "delta_vs_floor": round(mean - sca.PLURALITY_FLOOR, 4),
        "status": "secondary mechanism analysis; never substituted into the decision rule",
    }


# ---------------------------------------------------------------------------
# cost, counted in tokens and GPU-seconds
# ---------------------------------------------------------------------------


def cost(meta: dict) -> dict:
    """§9: a larger verifier is not free because it produced no trajectory.

    Compare tokens and GPU time, not trajectory counts.
    """
    return {
        "comparisons": meta.get("comparisons"),
        "directed_pairs": meta.get("directed_pairs"),
        "generation_calls": meta.get("comparisons"),
        "prefill_calls": (meta.get("comparisons") or 0) * 2,
        "note": (
            "Wall-clock and GPU-seconds are read from the Slurm accounting record for the "
            "verdict job, not estimated here. New Biomni trajectories generated by Stage C: 0."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cell", required=True, choices=["c1", "c2"])
    args = ap.parse_args()
    out = Path(args.out)

    tables = REPO / "reports" / "tables" / "stage_c"
    per_instance = tables / f"stage_c_per_instance_{args.cell}.csv"
    if not per_instance.exists():
        raise SystemExit(f"{per_instance} not found - run stage_c_analyze.py first, and report its verdict first")
    df = pd.read_csv(per_instance)
    sel = [json.loads(x) for x in (out / f"selections_{args.cell}.jsonl").read_text().splitlines() if x.strip()]
    meta = json.loads((out / f"score_metadata_{args.cell}.json").read_text())
    rewards = sca._reward_lookup()

    report = {
        "cell": args.cell,
        "status": "SECONDARY / EXPLANATORY - reported after the pre-specified verdict, never in place of it",
        "capture_harm": capture_harm(df),
        "gap_fraction_recovered": round(float(df.selector_reward.mean() - sca.PLURALITY_FLOOR) / sca.GAP, 4),
        "ranking_auroc": ranking_auroc(sel, rewards),
        "intransitivity": intransitivity(sel),
        "margin_conditional_accuracy": margin_conditional(df),
        "risk_coverage": risk_coverage(df),
        "task_heterogeneity": {
            t: {"n": int(g.shape[0]), "accuracy": round(float(g.selector_reward.mean()), 4)}
            for t, g in df.groupby("task_name")
        },
        "pool_heterogeneity": {
            p: {"n": int(g.shape[0]), "accuracy": round(float(g.selector_reward.mean()), 4)}
            for p, g in df.groupby("pool")
        },
        "ppt_secondary": ppt_secondary(sel, rewards),
        "cost": cost(meta),
        "headroom_official_vs_audit_corrected": AUDIT_CORRECTED,
        "capability_covariate": {
            "status": "PENDING - deferred for scheduling, not a finding",
            "consequence": "§9's conditioning on solve capability is reported as pending, not as satisfied",
            "rule": (
                "If a verifier model cannot operate the Biomni scaffold, the covariate is reported "
                "UNAVAILABLE for that cell with the failure mode stated, never as a capability estimate "
                "(preregistration ADDENDUM 1, A1.3)."
            ),
        },
    }
    path = tables / f"stage_c_report_{args.cell}.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
