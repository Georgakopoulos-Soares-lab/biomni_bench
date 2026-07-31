from __future__ import annotations

import json

import pandas as pd

from biomni_uncertainty.benchmark import (
    build_manifest,
    dataset_fingerprint,
    manifest_hash,
    read_manifest,
    write_manifest,
)
from biomni_uncertainty.sampling import (
    expand_runs,
    make_run_id,
    read_run_manifest,
    run_manifest_hash,
    write_run_manifest,
)


def fake_df(per_task: dict[str, int], split: str = "val") -> pd.DataFrame:
    rows = []
    gid = 0
    for task, n in per_task.items():
        for i in range(n):
            rows.append(
                {
                    "instance_id": gid,
                    "task_instance_id": i,
                    "prompt": f"{task} prompt {i} " + "x" * (i * 3),
                    "task_name": task,
                    "split": split,
                    "answer": f"ANS{i}",
                }
            )
            gid += 1
    return pd.DataFrame(rows)


DF = fake_df({"task_a": 20, "task_b": 20, "task_c": 3})


def build(**kw):
    params = {
        "per_task_target": 5,
        "target_total_instances": 15,
        "manifest_seed": 20260731,
        "preferred_split": "val",
    }
    params.update(kw)
    return build_manifest(DF, **params)


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_manifest_is_deterministic():
    a, _ = build()
    b, _ = build()
    assert [e.to_dict() for e in a] == [e.to_dict() for e in b]
    assert manifest_hash(a) == manifest_hash(b)


def test_manifest_hash_is_order_independent():
    a, _ = build()
    b = list(reversed(a))
    assert manifest_hash(a) == manifest_hash(b)


def test_different_seed_gives_different_selection():
    a, _ = build()
    b, _ = build(manifest_seed=999)
    assert manifest_hash(a) != manifest_hash(b)


def test_task_order_does_not_affect_per_task_selection():
    """A task's chosen instances must not depend on other tasks in the frame."""
    # target == 5+5+3 so no redistribution top-up perturbs the comparison.
    full, _ = build(target_total_instances=13)
    only_a, _ = build_manifest(
        DF[DF.task_name == "task_a"],
        per_task_target=5,
        target_total_instances=5,
        manifest_seed=20260731,
        preferred_split="val",
    )
    got_full = sorted(e.task_instance_id for e in full if e.task_name == "task_a")
    got_alone = sorted(e.task_instance_id for e in only_a)
    assert got_full == got_alone


# --------------------------------------------------------------------------
# Balance and redistribution
# --------------------------------------------------------------------------


def test_balanced_per_task_target():
    # target == 5+5+3, so the per-task target is met exactly with no top-up.
    entries, report = build(target_total_instances=13)
    assert report["counts_by_task"] == {"task_a": 5, "task_b": 5, "task_c": 3}
    assert report["short_tasks"] == {"task_c": 3}  # only 3 available
    assert report["redistributed"] == {}
    assert len(entries) == 13


def test_shortfall_is_redistributed_to_other_tasks():
    entries, report = build()
    # 5+5+3 = 13 < 15 -> two more drawn from tasks that still have instances.
    assert len(entries) == 15
    assert report["final_total"] == 15
    assert sum(report["redistributed"].values()) == 2
    assert "task_c" not in report["redistributed"]


def test_exhausted_benchmark_is_reported_not_silently_short():
    small = fake_df({"t": 3})
    entries, report = build_manifest(
        small, per_task_target=5, target_total_instances=10, manifest_seed=1, preferred_split="val"
    )
    assert len(entries) == 3
    assert any("exhausted" in e["reason"] for e in report["exclusions"])


# --------------------------------------------------------------------------
# Split handling
# --------------------------------------------------------------------------


def test_single_split_release_is_recorded_as_no_held_out_split():
    _, report = build()
    assert report["available_splits"] == ["val"]
    assert report["split_used"] == "val"
    assert report["held_out_split_available"] is False


def test_missing_preferred_split_falls_back_and_records_it():
    df = fake_df({"t": 10}, split="train")
    _, report = build_manifest(df, per_task_target=5, target_total_instances=5, manifest_seed=1, preferred_split="val")
    assert report["split_used"] == "ALL"
    assert any("not present" in e["reason"] for e in report["exclusions"])


# --------------------------------------------------------------------------
# Exclusions
# --------------------------------------------------------------------------


def test_task_exclusion_recorded():
    _, report = build(exclude_tasks=["task_c"])
    assert "task_c" not in report["counts_by_task"]
    assert any("task_c" in e["reason"] for e in report["exclusions"])


def test_prompt_length_exclusion_recorded():
    _, report = build(max_prompt_chars=25)
    assert any("longer than" in e["reason"] for e in report["exclusions"])


def test_report_contains_prompt_length_summary_and_fingerprint():
    _, report = build()
    s = report["prompt_length_chars"]
    assert set(s) == {"min", "p25", "median", "p75", "max", "mean"}
    assert s["min"] <= s["median"] <= s["max"]
    assert len(report["dataset_fingerprint"]) == 64


def test_dataset_fingerprint_changes_with_content():
    other = DF.copy()
    other.loc[0, "answer"] = "CHANGED"
    assert dataset_fingerprint(DF) != dataset_fingerprint(other)


# --------------------------------------------------------------------------
# Ground-truth separation
# --------------------------------------------------------------------------


def test_ground_truth_written_to_a_separate_file_and_never_in_the_manifest(tmp_path):
    entries, _ = build()
    mpath, gpath = write_manifest(entries, DF, tmp_path / "m.jsonl")
    assert mpath != gpath

    text = mpath.read_text()
    for line in text.splitlines():
        rec = json.loads(line)
        assert "answer" not in rec
    assert "ANS" not in text  # no ground-truth value leaked into the agent file

    gt = [json.loads(x) for x in gpath.read_text().splitlines()]
    assert len(gt) == len(entries)
    assert all("answer" in r for r in gt)


def test_manifest_round_trips(tmp_path):
    entries, _ = build()
    mpath, _ = write_manifest(entries, DF, tmp_path / "m.jsonl")
    assert [e.to_dict() for e in read_manifest(mpath)] == [e.to_dict() for e in entries]


# --------------------------------------------------------------------------
# Run expansion
# --------------------------------------------------------------------------


def test_run_id_is_stable_and_unique(cfg):
    a = make_run_id("exp", "task_a", 3, "instrumented", 2)
    assert a == make_run_id("exp", "task_a", 3, "instrumented", 2)
    others = {
        make_run_id("exp", "task_a", 3, "instrumented", 1),
        make_run_id("exp", "task_a", 4, "instrumented", 2),
        make_run_id("exp", "task_b", 3, "instrumented", 2),
        make_run_id("exp", "task_a", 3, "standard", 2),
        make_run_id("exp2", "task_a", 3, "instrumented", 2),
    }
    assert a not in others
    assert len(others) == 5


def test_expand_runs_creates_k_plus_standard_per_instance(cfg):
    entries, _ = build_manifest(
        fake_df({"t": 4}), per_task_target=4, target_total_instances=4, manifest_seed=1, preferred_split="val"
    )
    specs = expand_runs(entries, cfg)
    assert len(specs) == 4 * (cfg.trajectories.instrumented_k + cfg.trajectories.standard_k)
    per = {}
    for s in specs:
        per.setdefault((s.task_instance_id, s.condition), 0)
        per[(s.task_instance_id, s.condition)] += 1
    assert all(per[(i, "instrumented")] == cfg.trajectories.instrumented_k for i in range(4))
    assert all(per[(i, "standard")] == cfg.trajectories.standard_k for i in range(4))


def test_expand_runs_is_deterministic_and_isolates_run_dirs(cfg):
    entries, _ = build_manifest(
        fake_df({"t": 3}), per_task_target=3, target_total_instances=3, manifest_seed=1, preferred_split="val"
    )
    a = expand_runs(entries, cfg)
    b = expand_runs(entries, cfg)
    assert [s.to_dict() for s in a] == [s.to_dict() for s in b]
    assert run_manifest_hash(a) == run_manifest_hash(b)
    dirs = [s.run_dir for s in a]
    assert len(dirs) == len(set(dirs)), "two runs share a working directory"


def test_standard_condition_has_confidence_mode_none(cfg):
    entries, _ = build_manifest(
        fake_df({"t": 2}), per_task_target=2, target_total_instances=2, manifest_seed=1, preferred_split="val"
    )
    specs = expand_runs(entries, cfg)
    assert all(s.confidence_mode == "none" for s in specs if s.condition == "standard")
    assert all(s.confidence_mode == "final_only" for s in specs if s.condition == "instrumented")


def test_seeds_are_distinct_across_trajectories_and_conditions(cfg):
    entries, _ = build_manifest(
        fake_df({"t": 1}), per_task_target=1, target_total_instances=1, manifest_seed=1, preferred_split="val"
    )
    specs = expand_runs(entries, cfg)
    seeds = [s.requested_seed for s in specs]
    assert len(set(seeds)) == len(seeds)


def test_prompt_is_identical_between_conditions(cfg):
    entries, _ = build_manifest(
        fake_df({"t": 1}), per_task_target=1, target_total_instances=1, manifest_seed=1, preferred_split="val"
    )
    specs = expand_runs(entries, cfg)
    assert len({s.prompt for s in specs}) == 1
    assert len({s.prompt_hash for s in specs}) == 1


def test_run_manifest_round_trips(tmp_path, cfg):
    entries, _ = build_manifest(
        fake_df({"t": 2}), per_task_target=2, target_total_instances=2, manifest_seed=1, preferred_split="val"
    )
    specs = expand_runs(entries, cfg)
    p = write_run_manifest(specs, tmp_path / "runs.jsonl")
    assert [s.to_dict() for s in read_run_manifest(p)] == [s.to_dict() for s in specs]
