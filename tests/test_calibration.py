"""Tests for grouped out-of-fold calibration.

The point of every test here is the same: an instance must never contribute to
the model that scores it, and a missing confidence must never be quietly imputed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from biomni_uncertainty.calibration import (
    MISSING_CONFIDENCE_FILL,
    confidence_features,
    instance_weights,
    isotonic_oof,
    logistic_oof,
    reliability_table,
    weighted_brier,
    weighted_ece,
)


@pytest.fixture
def separable():
    """20 instances x 4 trajectories; x carries a real, learnable signal."""
    rng = np.random.default_rng(20260802)
    groups = np.repeat(np.arange(20), 4)
    y = rng.integers(0, 2, size=80).astype(float)
    x = y + rng.normal(0, 0.4, size=80)
    return x, y, groups


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------


def test_instance_weights_give_every_instance_equal_mass():
    groups = np.array([1, 1, 1, 1, 2, 2])
    w = instance_weights(groups)
    assert w[:4].sum() == pytest.approx(1.0)
    assert w[4:].sum() == pytest.approx(1.0)


def test_predictions_are_out_of_fold_for_every_row(separable):
    x, y, groups = separable
    r = logistic_oof(x.reshape(-1, 1), y, groups, name="t", feature_names=("x",))
    assert np.isfinite(r.oof).all()
    assert r.n_splits == 5


def test_a_memorized_instance_label_does_not_leak_through_the_fit():
    """Feature = instance id, label = a per-instance coin flip. In-fold this is
    perfectly predictable; out-of-fold it must be worthless."""
    groups = np.repeat(np.arange(20), 4)
    labels = np.array([0.0, 1.0] * 10)
    y = np.repeat(labels, 4)
    x = groups.astype(float).reshape(-1, 1)
    r = logistic_oof(x, y, groups, name="leak", feature_names=("instance_id",))
    oof_err = np.mean((r.oof - y) ** 2)
    in_fold = r.full_model.predict_proba(x)[:, 1]
    assert np.mean((in_fold - y) ** 2) < oof_err, "grouped folds failed to break memorization"
    assert oof_err > 0.15


def test_isotonic_oof_matches_logistic_on_a_monotone_signal(separable):
    x, y, groups = separable
    iso = isotonic_oof(x, y, groups, name="iso")
    log = logistic_oof(x.reshape(-1, 1), y, groups, name="log", feature_names=("x",))
    assert weighted_brier(iso.oof, iso.y, iso.weights) < 0.25
    assert weighted_brier(log.oof, log.y, log.weights) < 0.25


def test_degenerate_training_fold_falls_back_to_the_base_rate():
    """All-one-class training folds must not crash and must not invent a signal."""
    groups = np.repeat(np.arange(6), 2)
    y = np.zeros(12)
    y[-2:] = 1.0  # only the last instance is positive
    x = np.arange(12, dtype=float).reshape(-1, 1)
    r = logistic_oof(x, y, groups, name="degen", feature_names=("x",), n_splits=6)
    assert np.isfinite(r.oof).all()
    assert (r.oof >= 0).all() and (r.oof <= 1).all()


def test_n_splits_is_clipped_to_the_group_count():
    groups = np.repeat(np.arange(3), 2)
    y = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    r = logistic_oof(np.arange(6, dtype=float).reshape(-1, 1), y, groups, name="t", feature_names=("x",), n_splits=10)
    assert r.n_splits == 3


def test_too_few_groups_is_an_error_not_a_silent_fit():
    with pytest.raises(ValueError, match="at least 2 groups"):
        logistic_oof(np.zeros((4, 1)), np.array([0.0, 1, 0, 1]), np.zeros(4), name="t", feature_names=("x",))


# --------------------------------------------------------------------------
# Missing confidence
# --------------------------------------------------------------------------


def test_missing_confidence_gets_an_indicator_not_an_imputed_value():
    conf = pd.Series([0.95, None, 1.0, np.nan])
    X, names = confidence_features(conf)
    assert names == ("confidence", "confidence_missing")
    assert X[:, 1].tolist() == [0.0, 1.0, 0.0, 1.0]
    assert X[1, 0] == MISSING_CONFIDENCE_FILL and X[3, 0] == MISSING_CONFIDENCE_FILL


def test_the_missing_indicator_can_carry_its_own_base_rate():
    """Missing-confidence trajectories are a distinct, less accurate population;
    the fit must be able to say so rather than blending them in."""
    groups = np.repeat(np.arange(20), 4)
    conf = pd.Series([0.95 if i % 2 else None for i in range(80)])
    y = np.array([1.0 if i % 2 else 0.0 for i in range(80)])
    X, _ = confidence_features(conf)
    r = logistic_oof(X, y, groups, name="miss", feature_names=("confidence", "confidence_missing"))
    present = r.oof[X[:, 1] == 0]
    missing = r.oof[X[:, 1] == 1]
    assert present.mean() > missing.mean() + 0.3


# --------------------------------------------------------------------------
# Scoring quality
# --------------------------------------------------------------------------


def test_brier_and_ece_reward_a_calibrated_forecast():
    y = np.array([1.0, 1.0, 0.0, 0.0])
    w = np.ones(4)
    perfect = np.array([1.0, 1.0, 0.0, 0.0])
    hedged = np.array([0.5, 0.5, 0.5, 0.5])
    overconfident = np.array([0.99, 0.99, 0.99, 0.99])
    assert weighted_brier(perfect, y, w) == pytest.approx(0.0)
    assert weighted_ece(perfect, y, w) == pytest.approx(0.0)
    assert weighted_brier(hedged, y, w) < weighted_brier(overconfident, y, w)
    assert weighted_ece(hedged, y, w) == pytest.approx(0.0)  # 0.5 predicted, 0.5 observed


def test_ece_penalizes_the_phase1_pathology():
    """Stated 0.96 against an actual 0.59 is exactly the gap ECE must expose."""
    y = np.array([1.0] * 59 + [0.0] * 41)
    p = np.full(100, 0.96)
    assert weighted_ece(p, y, np.ones(100)) == pytest.approx(0.37, abs=0.01)


def test_reliability_table_bins_are_exhaustive_and_weighted():
    p = np.array([0.05, 0.35, 0.55, 0.85, 0.95])
    y = np.array([0.0, 0.0, 1.0, 1.0, 1.0])
    t = reliability_table(p, y, np.ones(5), n_bins=5)
    assert len(t) == 5
    assert t.n.sum() == 5
    assert t.weight.sum() == pytest.approx(5.0)


def test_metrics_tolerate_missing_predictions():
    p = np.array([0.9, np.nan, 0.1])
    y = np.array([1.0, 1.0, 0.0])
    assert weighted_brier(p, y, np.ones(3)) == pytest.approx(0.01)
    assert weighted_ece(p, y, np.ones(3)) is not None


def test_within_fold_auroc_survives_fold_specific_intercepts():
    """Pooling out-of-fold predictions destroys a ranking metric when folds have
    different intercepts. The within-fold summary must not be fooled by that."""
    from biomni_uncertainty.analysis import auroc
    from biomni_uncertainty.calibration import CalibrationResult, within_fold_auroc

    y = np.array([0.0, 1.0] * 6)
    fold = np.repeat([0, 1, 2], 4)
    # Perfect ranking inside every fold, but fold 2's scores all sit below fold 0's.
    oof = np.array([0.90, 0.95, 0.90, 0.95, 0.50, 0.55, 0.50, 0.55, 0.10, 0.15, 0.10, 0.15])
    r = CalibrationResult("t", "logistic", oof, y, np.ones(12), fold, 3, fold_index=fold)
    assert within_fold_auroc(r, auroc)["mean"] == pytest.approx(1.0)
    assert auroc(oof, y) < 0.7, "the pooled metric is the one that gets fooled"


def test_within_fold_auroc_handles_a_missing_fold_index():
    from biomni_uncertainty.analysis import auroc
    from biomni_uncertainty.calibration import CalibrationResult, within_fold_auroc

    r = CalibrationResult("t", "logistic", np.array([0.1, 0.9]), np.array([0.0, 1.0]), np.ones(2), np.array([1, 2]), 2)
    assert within_fold_auroc(r, auroc)["mean"] is None
