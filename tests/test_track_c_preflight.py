"""Tests for the Step-1 CPU preflight (`scripts/track_c_preflight.py`).

The load-bearing property is the stratum reconciliation itself: D-30's
`evidence_state` scheme (n_usable-based) and the "91 unanimous / 51 split /
45 no-correct" framing used elsewhere are DIFFERENT, non-nested
classifications of the same 150 instances, and conflating them is exactly the
inconsistency this preflight exists to resolve. These tests fix that logic
against small, hand-built pools rather than trusting the reconciliation on
real data alone.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location("track_c_preflight", SCRIPTS / "track_c_preflight.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["track_c_preflight"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


def row(task, iid, idx, answer, reward, *, completed=True, parse="ok"):
    return {
        "task_name": task,
        "task_instance_id": iid,
        "trajectory_index": idx,
        "run_id": f"{task}-i{iid}-t{idx}",
        "completed": completed,
        "answer_parse_status": parse,
        "answer_cluster_key": answer,
        "reward": reward,
        "failure_class": None if completed else "model_context_overflow",
    }


def pooled(rows):
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# instance_table: evidence_state classification
# --------------------------------------------------------------------------


def test_two_usable_agreeing_trajectories_are_unanimous(mod):
    df = mod.instance_table(pooled([row("t", 1, 0, "A", 1.0), row("t", 1, 1, "A", 1.0)]))
    assert df.iloc[0].evidence_state == "unanimous"
    assert df.iloc[0].distinct_usable == 1


def test_one_usable_trajectory_is_insufficient_evidence_not_unanimous(mod):
    """This is the exact reconciliation point: a single usable answer trivially
    has 'distinct_usable == 1', which the naive '91 unanimous' framing counts
    as unanimous - but evidence_state correctly puts it in stratum A, because
    unanimity requires at least two independent opinions to agree."""
    df = mod.instance_table(
        pooled([row("t", 1, 0, "A", 1.0), row("t", 1, 1, None, 0.0, completed=False, parse="unparseable")])
    )
    r = df.iloc[0]
    assert r.n_usable == 1
    assert r.distinct_usable == 1  # naive framing would call this "unanimous"
    assert r.evidence_state == "A_insufficient_evidence"  # correct framing does not


def test_two_usable_disagreeing_trajectories_are_substantive_disagreement(mod):
    df = mod.instance_table(pooled([row("t", 1, 0, "A", 1.0), row("t", 1, 1, "B", 0.0)]))
    assert df.iloc[0].evidence_state == "B_substantive_disagreement"


def test_zero_usable_trajectories_is_insufficient_evidence_with_zero_headroom(mod):
    df = mod.instance_table(pooled([row("t", 1, i, None, 0.0, completed=False, parse="unparseable") for i in range(4)]))
    r = df.iloc[0]
    assert r.n_usable == 0
    assert r.evidence_state == "A_insufficient_evidence"
    assert bool(r.no_correct_trajectory) is True
    assert r.headroom == 0.0


def test_headroom_is_zero_whenever_oracle_equals_plurality(mod):
    """Stratum A and unanimous instances have oracle == plurality by
    construction - all of Step 1a's 'headroom sits 100% in stratum B' claim
    rests on this being exactly zero, not merely small, for every such row."""
    df = mod.instance_table(
        pooled(
            [row("t", 1, 0, "A", 1.0), row("t", 1, 1, "A", 1.0)]  # unanimous, both correct
            + [row("u", 2, 0, "A", 0.0), row("u", 2, 1, "A", 0.0)]  # unanimous, both wrong
        )
    )
    assert (df.headroom == 0.0).all()


def test_headroom_is_positive_exactly_when_plurality_misses_a_better_candidate(mod):
    """A 2-of-2 wrong plurality with a correct minority present has real headroom."""
    df = mod.instance_table(
        pooled(
            [
                row("t", 1, 0, "wrong", 0.0),
                row("t", 1, 1, "wrong", 0.0),
                row("t", 1, 2, "right", 1.0),
            ]
        )
    )
    r = df.iloc[0]
    assert r.plurality_reward == 0.0  # "wrong" has support 2, wins the plurality
    assert r.oracle_reward == 1.0
    assert r.headroom == pytest.approx(1.0)
    assert r.evidence_state == "B_substantive_disagreement"


# --------------------------------------------------------------------------
# mode-A eligibility: fixed set, not derived from data
# --------------------------------------------------------------------------


def test_mode_a_eligible_tasks_is_exactly_lab_bench_seqqa(mod):
    """Fixed in the module docstring before any headroom number was computed;
    this pins the set so a future edit cannot silently widen or narrow it
    without the test failing."""
    assert mod.MODE_A_ELIGIBLE_TASKS == frozenset({"lab_bench_seqqa"})


def test_every_task_eligibility_has_a_written_justification(mod):
    """'Fix the classification criteria in writing before classifying' - every
    task named anywhere must have a stated reason, not a bare label."""
    all_tasks = {
        "crispr_delivery",
        "gwas_causal_gene_gwas_catalog",
        "gwas_causal_gene_opentargets",
        "gwas_causal_gene_pharmaprojects",
        "gwas_variant_prioritization",
        "lab_bench_dbqa",
        "lab_bench_seqqa",
        "patient_gene_detection",
        "rare_disease_diagnosis",
        "screen_gene_retrieval",
    }
    assert set(mod.TASK_ELIGIBILITY_NOTE) == all_tasks
    for t, note in mod.TASK_ELIGIBILITY_NOTE.items():
        assert len(note) > 20, f"{t} has no real justification"
        expect_eligible = t in mod.MODE_A_ELIGIBLE_TASKS
        assert ("not mode-A" not in note) == expect_eligible


def test_mode_a_eligible_flag_on_instance_table_matches_the_fixed_set(mod):
    df = mod.instance_table(
        pooled(
            [row("lab_bench_seqqa", 1, 0, "A", 1.0), row("lab_bench_seqqa", 1, 1, "A", 1.0)]
            + [row("crispr_delivery", 2, 0, "A", 1.0), row("crispr_delivery", 2, 1, "A", 1.0)]
        )
    )
    got = dict(zip(df.task_name, df.mode_a_eligible, strict=False))
    assert got == {"lab_bench_seqqa": True, "crispr_delivery": False}


# --------------------------------------------------------------------------
# cluster_bootstrap_mean: sane on trivial inputs
# --------------------------------------------------------------------------


def test_cluster_bootstrap_mean_on_constant_values_has_a_degenerate_ci(mod):
    import numpy as np

    m, lo, hi = mod.cluster_bootstrap_mean(np.array([1.0, 1.0, 1.0, 1.0]))
    assert m == pytest.approx(1.0)
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(1.0)


def test_cluster_bootstrap_mean_on_empty_input_does_not_raise(mod):
    import numpy as np

    m, lo, hi = mod.cluster_bootstrap_mean(np.array([]))
    assert m != m  # nan
