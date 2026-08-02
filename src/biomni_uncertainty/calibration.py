"""Grouped out-of-fold calibration for Phase-2 reliability signals.

Everything here exists to turn a raw signal into a *probability that the answer
is correct*, without ever letting a fold see its own instance.

Two rules are structural rather than conventional:

* **The grouping unit is the task instance.** An instance contributes up to K
  trajectories and up to 11 answer subsets; they are not independent draws.
  ``GroupKFold`` on the instance is the only splitter used.
* **Every prediction consumed by a policy is out-of-fold.** ``*_oof`` returns one
  prediction per row, produced by the fold model that did not see that row's
  instance. The full-data model is fitted too, but only for reporting
  coefficients — it is never used to score the rows it was fitted on.

Sample weights normalize each instance's contribution to 1, so an instance with
four trajectories does not outvote one with four subsets of a different size.

Raw verbalized confidence is never used as a probability anywhere in Phase 2;
it enters only as a feature to these estimators (north star: "confidence *ranks*
but does not *calibrate*").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

# A confidence value stands in for "missing" alongside an explicit indicator, so
# the fit never silently imputes. The value is irrelevant to the fitted model as
# long as it is constant, because the indicator absorbs it.
MISSING_CONFIDENCE_FILL = 0.0


@dataclass(frozen=True)
class CalibrationResult:
    """Out-of-fold predictions plus the reporting-only full-data model."""

    name: str
    method: str
    oof: np.ndarray
    y: np.ndarray
    weights: np.ndarray
    groups: np.ndarray
    n_splits: int
    #: Which fold produced each row's prediction. Needed because pooling
    #: predictions across folds is *not* safe for a ranking metric - see
    #: :func:`within_fold_auroc`.
    fold_index: np.ndarray | None = None
    full_model: object = field(repr=False, default=None)
    feature_names: tuple[str, ...] = ()

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"group": self.groups, "y": self.y, "weight": self.weights, "p_oof": self.oof, "fold": self.fold_index}
        )


def _grouped_folds(groups: np.ndarray, n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Deterministic grouped folds; ``n_splits`` is clipped to the group count."""
    uniq = np.unique(groups)
    k = int(min(n_splits, len(uniq)))
    if k < 2:
        raise ValueError(f"need at least 2 groups to cross-validate, got {len(uniq)}")
    return list(GroupKFold(n_splits=k).split(np.zeros(len(groups)), groups=groups))


def instance_weights(groups: np.ndarray) -> np.ndarray:
    """Weights that give every instance a total mass of 1."""
    s = pd.Series(groups)
    return (1.0 / s.map(s.value_counts())).to_numpy(dtype=float)


def logistic_oof(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    *,
    name: str,
    feature_names: tuple[str, ...],
    n_splits: int = 5,
    C: float = 1.0,
    weights: np.ndarray | None = None,
) -> CalibrationResult:
    """L2-regularized logistic calibration with grouped out-of-fold predictions.

    With two features this is Platt scaling; with a handful it is the small
    regularized model the brief permits as a *secondary* estimator. It is never
    allowed to grow beyond a handful — 50 instances cannot support more.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    groups = np.asarray(groups)
    w = instance_weights(groups) if weights is None else np.asarray(weights, dtype=float)

    oof = np.full(len(y), np.nan, dtype=float)
    fold_index = np.full(len(y), -1, dtype=int)
    folds = _grouped_folds(groups, n_splits)
    for fi, (tr, te) in enumerate(folds):
        fold_index[te] = fi
        if len(np.unique(y[tr])) < 2:
            # A degenerate training fold cannot produce a calibrated model. The
            # base rate is the honest fallback, and it is recorded as such by
            # leaving the fold's coefficients out of the reported model.
            oof[te] = float(np.average(y[tr], weights=w[tr]))
            continue
        m = LogisticRegression(C=C, max_iter=2000)
        m.fit(X[tr], y[tr], sample_weight=w[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]

    full = None
    if len(np.unique(y)) >= 2:
        full = LogisticRegression(C=C, max_iter=2000).fit(X, y, sample_weight=w)
    return CalibrationResult(name, "logistic", oof, y, w, groups, len(folds), fold_index, full, feature_names)


def isotonic_oof(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    *,
    name: str,
    n_splits: int = 5,
    weights: np.ndarray | None = None,
) -> CalibrationResult:
    """Isotonic calibration, grouped out-of-fold. **Exploratory only.**

    With 50 instances and seven distinct confidence values this is close to a
    lookup table and is reported for comparison, never used by a primary policy.
    """
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float)
    groups = np.asarray(groups)
    w = instance_weights(groups) if weights is None else np.asarray(weights, dtype=float)

    oof = np.full(len(y), np.nan, dtype=float)
    fold_index = np.full(len(y), -1, dtype=int)
    folds = _grouped_folds(groups, n_splits)
    for fi, (tr, te) in enumerate(folds):
        fold_index[te] = fi
        if len(np.unique(y[tr])) < 2 or len(np.unique(x[tr])) < 2:
            oof[te] = float(np.average(y[tr], weights=w[tr]))
            continue
        m = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        m.fit(x[tr], y[tr], sample_weight=w[tr])
        oof[te] = m.predict(x[te])

    full = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(x, y, sample_weight=w)
    return CalibrationResult(name, "isotonic", oof, y, w, groups, len(folds), fold_index, full, ("x",))


def confidence_features(confidence: pd.Series) -> tuple[np.ndarray, tuple[str, ...]]:
    """Platt design matrix for verbalized confidence with explicit missingness.

    Missing confidence is a *signal*, not a gap to impute: in the pooled pool it
    is 27% of trajectories and those trajectories are 37% correct against 53%
    for the rest. The indicator lets the fit give them their own intercept.
    """
    c = pd.to_numeric(confidence, errors="coerce")
    missing = c.isna().to_numpy(dtype=float)
    filled = c.fillna(MISSING_CONFIDENCE_FILL).to_numpy(dtype=float)
    return np.column_stack([filled, missing]), ("confidence", "confidence_missing")


# --------------------------------------------------------------------------
# Scoring quality
# --------------------------------------------------------------------------


def within_fold_auroc(result: CalibrationResult, auroc_fn) -> dict:
    """Discrimination measured **inside each fold**, then averaged.

    Pooling out-of-fold predictions and computing one AUROC over the pool is
    wrong for a ranking metric: each fold's model has its own intercept, so
    predictions from different folds are not on a common scale and the pooled
    ranking mixes them. The pooled value can collapse toward 0.5 while every
    fold individually discriminates well - which is exactly what happens to the
    K=1 confidence calibrator here. Both numbers are reported; this one is the
    honest estimate of discrimination, the pooled one belongs with calibration
    metrics (Brier, ECE), which *are* scale-referenced and pool correctly.
    """
    if result.fold_index is None:
        return {"mean": None, "min": None, "max": None, "n_folds": 0}
    vals = []
    for f in sorted(set(result.fold_index.tolist())):
        m = result.fold_index == f
        a = auroc_fn(result.oof[m], result.y[m])
        if a is not None:
            vals.append(float(a))
    if not vals:
        return {"mean": None, "min": None, "max": None, "n_folds": 0}
    return {
        "mean": float(np.mean(vals)),
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
        "n_folds": len(vals),
    }


def weighted_brier(p: np.ndarray, y: np.ndarray, w: np.ndarray) -> float | None:
    m = ~(np.isnan(p) | np.isnan(y))
    if not m.any():
        return None
    return float(np.average((p[m] - y[m]) ** 2, weights=w[m]))


def weighted_ece(p: np.ndarray, y: np.ndarray, w: np.ndarray, *, n_bins: int = 5) -> float | None:
    """Equal-width expected calibration error over the weighted sample."""
    m = ~(np.isnan(p) | np.isnan(y))
    if not m.any():
        return None
    p, y, w = p[m], y[m], w[m]
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    total = w.sum()
    err = 0.0
    for b in range(n_bins):
        sel = idx == b
        if not sel.any():
            continue
        mass = w[sel].sum()
        err += (mass / total) * abs(np.average(p[sel], weights=w[sel]) - np.average(y[sel], weights=w[sel]))
    return float(err)


def reliability_table(p: np.ndarray, y: np.ndarray, w: np.ndarray, *, n_bins: int = 5) -> pd.DataFrame:
    m = ~(np.isnan(p) | np.isnan(y))
    p, y, w = p[m], y[m], w[m]
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        sel = idx == b
        rows.append(
            {
                "bin_lo": edges[b],
                "bin_hi": edges[b + 1],
                "n": int(sel.sum()),
                "weight": float(w[sel].sum()),
                "mean_predicted": float(np.average(p[sel], weights=w[sel])) if sel.any() else math.nan,
                "observed_accuracy": float(np.average(y[sel], weights=w[sel])) if sel.any() else math.nan,
            }
        )
    return pd.DataFrame(rows)
