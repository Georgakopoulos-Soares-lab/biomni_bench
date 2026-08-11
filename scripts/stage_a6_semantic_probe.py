#!/usr/bin/env python
"""A.6 - semantic discriminability probe on the frozen 78. CPU only, no GPU.

Decision rule: `reports/a6_decision_rule.md`, frozen and committed (`2051a7f`)
BEFORE any AUROC or any feature value existed. The feature family, the primary
feature and the multiplicity correction are all fixed there and are copied here
as constants; changing any of them is a protocol violation, and
`tests/test_stage_a6.py` pins them.

WHY THIS EXISTS: A.4 tested *structural* features (counts of tools, tokens,
calls) and found nothing usable. `singled_out`, the measure that carried A.5b,
is *semantic*, and A.4 never covered that class. Stage C's capsule format is
frozen at its start, so a semantic discriminator has to be found now or it can
never be exposed to the verifier.

=========================================================================
THE LEAKAGE BARRIER - the load-bearing part of this file
=========================================================================

A.5b's `singled_out` measured whether a trajectory preferentially discusses
**the correct answer**. That takes ground truth as an INPUT. It is legitimate
for an audit and illegitimate here, because a Stage C capsule is computed at
inference time when no label exists.

Reformulated label-free: how preferentially does a trajectory discuss **its own
committed answer** relative to the other candidates for that instance? Both
inputs are available without ground truth.

Enforced structurally, not by intention:

* `extract_features()` takes exactly `(model_text, own_answer, candidates)`.
  It has no other parameters, so a label cannot be threaded into it.
* `FORBIDDEN_FEATURE_INPUTS` names the fields that must never reach it, in the
  spirit of `policy.FORBIDDEN_VIEW_FIELDS` and D-32's `FORBIDDEN_VERIFY_FIELDS`.
* `build_feature_frame()` drops every forbidden column BEFORE features are
  computed and re-attaches the label only afterwards, as the AUROC target.
* Tests assert both: that the forbidden fields are unreachable from the
  extraction path, and that feature values are unchanged when the labels are
  permuted.

    python scripts/stage_a6_semantic_probe.py --out reports/tables/stage_a
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

STEP2 = REPO / "reports" / "tables" / "track_c_step2"
PHASE2B = Path("/scratch/11034/atzanakak/biomni_unc_runs/phase2b/results/tables")
PHASE1 = Path("/scratch/11034/atzanakak/biomni_unc_runs/phase1_pooled/results/tables")

BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_SEED = 20260811001

#: Copied verbatim from reports/a6_decision_rule.md section 4-5. Pinned by test.
PRIMARY_FEATURE = "own_answer_share"
SECONDARY_FEATURES = ("n_competing_candidates_discussed", "hedging_near_answer", "closing_concentration")
FEATURE_FAMILY = (PRIMARY_FEATURE, *SECONDARY_FEATURES)
FAMILY_SIZE = len(FEATURE_FAMILY)  # Bonferroni denominator, fixed in advance
ALPHA_CORRECTED = 0.05 / FAMILY_SIZE  # 0.0125 -> 98.75% interval
CLOSING_FRACTION = 0.20  # "closing segment" = final 20% of model text

#: Fixed in the frozen rule so it cannot be tuned after seeing results.
HEDGING_MARKERS = (
    "may",
    "might",
    "possibly",
    "perhaps",
    "unclear",
    "uncertain",
    "not certain",
    "hard to say",
    "difficult to determine",
    "insufficient",
    "cannot determine",
    "ambiguous",
    "speculative",
    "tentative",
    "appears to",
    "seems to",
    "likely",
    "probably",
    "suggests",
)

#: Must never reach feature extraction. The A.6 analogue of FORBIDDEN_VIEW_FIELDS.
FORBIDDEN_FEATURE_INPUTS = frozenset(
    {"reward", "strict_reward", "correct", "ground_truth", "answer", "evaluation_status"}
)


def _load_triage():
    """Reuse A.5b's extraction and normalisation - INCLUDING both bug fixes (the
    prose-vs-gene-list candidate regex and the repeated-strip normaliser)."""
    spec = importlib.util.spec_from_file_location("stage_a_label_triage", REPO / "scripts" / "stage_a_label_triage.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stage_a_label_triage"] = mod
    spec.loader.exec_module(mod)
    return mod


TRIAGE = _load_triage()


# --------------------------------------------------------------------------
# Feature extraction - label-free by construction
# --------------------------------------------------------------------------


def extract_features(model_text: str, own_answer: str, candidates: list[str]) -> dict:
    """The ONLY feature entry point. Three inputs, none of them a label.

    `own_answer` is what this trajectory committed - knowable at inference time.
    `candidates` is the instance's candidate set - knowable at inference time.
    Ground truth appears nowhere.
    """
    others = [c for c in candidates if not TRIAGE.normalised_equal(c, own_answer)]
    own = TRIAGE.count_mentions(model_text, own_answer)
    other_counts = [TRIAGE.count_mentions(model_text, c) for c in others]
    total = own + sum(other_counts)

    cut = int(len(model_text) * (1 - CLOSING_FRACTION))
    closing = model_text[cut:]
    own_closing = TRIAGE.count_mentions(closing, own_answer)

    hedges = sum(len(re.findall(rf"(?<![A-Za-z]){re.escape(m)}(?![A-Za-z])", closing, re.I)) for m in HEDGING_MARKERS)

    return {
        "own_answer_share": (own / total) if total else np.nan,
        "n_competing_candidates_discussed": float(sum(1 for c in other_counts if c > 0)),
        "hedging_near_answer": float(hedges),
        "closing_concentration": (own_closing / own) if own else np.nan,
    }


def model_text_for(run_dir: str) -> str:
    p = Path(run_dir) / "transcript.json"
    if not p.exists():
        return ""
    try:
        msgs = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    out = []
    for m in msgs:
        if m.get("type") != "AIMessage":
            continue  # never the prompt: the candidate list lives there
        out.append(TRIAGE.OBS_RE.sub(" ", str(m.get("content") or "")))
    return "\n".join(out)


def build_feature_frame(traj: pd.DataFrame, menus: dict) -> pd.DataFrame:
    """Compute features with every forbidden column dropped first, then
    re-attach the label afterwards purely as the AUROC target."""
    labels = (traj["reward"].fillna(0) > 0).astype(int).to_numpy()
    safe = traj.drop(columns=[c for c in traj.columns if c in FORBIDDEN_FEATURE_INPUTS])
    assert not (set(safe.columns) & FORBIDDEN_FEATURE_INPUTS), "a forbidden field survived the drop"

    rows = []
    for r in safe.itertuples():
        key = (r.pool, r.task_name, int(r.task_instance_id))
        feats = extract_features(model_text_for(r.run_dir), r.answer_canonical, menus.get(key, []))
        rows.append({"pool": r.pool, "task_name": r.task_name, "task_instance_id": int(r.task_instance_id), **feats})
    out = pd.DataFrame(rows)
    out["label"] = labels  # the label enters HERE and nowhere earlier
    out["ikey"] = list(zip(out.pool, out.task_name, out.task_instance_id, strict=True))
    return out


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


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


def clustered_auroc(df: pd.DataFrame, feature: str) -> dict:
    groups = [
        (g[feature].to_numpy(dtype=float), g["label"].to_numpy())
        for _, g in df[[feature, "label", "ikey"]].groupby("ikey")
    ]
    xs = [g[0] for g in groups]
    ys = [g[1] for g in groups]
    point = _auroc(np.concatenate(xs), np.concatenate(ys))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    stats = []
    for _ in range(BOOTSTRAP_REPLICATES):
        idx = rng.integers(0, len(xs), size=len(xs))
        v = _auroc(np.concatenate([xs[i] for i in idx]), np.concatenate([ys[i] for i in idx]))
        if v is not None:
            stats.append(v)
    if not stats:
        return {"point": point, "n_instances": len(xs)}
    a = ALPHA_CORRECTED
    return {
        "point": point,
        "ci95_lo": float(np.quantile(stats, 0.025)),
        "ci95_hi": float(np.quantile(stats, 0.975)),
        "corrected_lo": float(np.quantile(stats, a / 2)),
        "corrected_hi": float(np.quantile(stats, 1 - a / 2)),
        "n_instances": len(xs),
    }


def excludes_half(r, lo="corrected_lo", hi="corrected_hi") -> bool:
    return r.get(lo) is not None and (r[lo] > 0.5 or r[hi] < 0.5)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cands = [json.loads(x) for x in (STEP2 / "candidates_slim.jsonl").read_text().splitlines() if x.strip()]
    keys = {(c["pool"], c["task_name"], int(c["task_instance_id"])) for c in cands}
    menus = {(c["pool"], c["task_name"], int(c["task_instance_id"])): list(c["candidates"]) for c in cands}

    p2 = pd.read_csv(PHASE2B / "p2b_pooled_trajectories.csv").assign(pool="phase2b")
    p1 = pd.read_csv(PHASE1 / "trajectories.csv")
    p1 = p1[p1.condition == "instrumented"].assign(pool="phase1_pooled")
    traj = pd.concat([p2, p1], ignore_index=True)
    traj["task_instance_id"] = traj.task_instance_id.astype(int)
    traj = traj[[(r.pool, r.task_name, int(r.task_instance_id)) in keys for r in traj.itertuples()]]
    traj = traj[traj.completed.fillna(False).astype(bool) & traj.answer_canonical.notna()]

    feats = build_feature_frame(traj, menus)
    feats.to_csv(args.out / "a6_features.csv", index=False)

    results = {f: clustered_auroc(feats, f) for f in FEATURE_FAMILY}

    primary_hit = excludes_half(results[PRIMARY_FEATURE])
    secondary_hits = [f for f in SECONDARY_FEATURES if excludes_half(results[f])]
    nominal_only = [
        f for f in FEATURE_FAMILY if excludes_half(results[f], "ci95_lo", "ci95_hi") and not excludes_half(results[f])
    ]

    if primary_hit:
        verdict = "DISCRIMINATES"
    elif secondary_hits:
        verdict = "DISCRIMINATES (secondary)"
    else:
        verdict = "NULL"

    report = {
        "population": {
            "n_trajectories": int(len(feats)),
            "n_instances": int(feats.ikey.nunique()),
            "n_correct": int(feats.label.sum()),
            "n_incorrect": int((1 - feats.label).sum()),
        },
        "frozen_rule": {
            "primary": PRIMARY_FEATURE,
            "family": list(FEATURE_FAMILY),
            "family_size": FAMILY_SIZE,
            "alpha_corrected": ALPHA_CORRECTED,
            "source": "reports/a6_decision_rule.md (committed 2051a7f, before any feature value existed)",
        },
        "features": results,
        "verdict": verdict,
        "primary_hit": primary_hit,
        "secondary_hits": secondary_hits,
        "nominal_only_hits_reported_as_multiplicity_noise": nominal_only,
        "consequence": (
            "Stage C's capsule exposes the discriminating feature"
            if verdict != "NULL"
            else "A.4's null strengthens; a Stage C NO-GO is attributable to the traces with positive evidence"
        ),
    }
    (args.out / "a6_semantic_probe.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
