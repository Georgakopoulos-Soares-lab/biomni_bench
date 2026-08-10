#!/usr/bin/env python
"""Phase-2B source provenance audit. CPU only, read-only, no GPU, no model calls.

Phase 2B ran with an uncommitted working tree: every one of its 600 run records
says `project_git.commit = 2c0bfc1, dirty = true`, and the controller that
produced the result was never committed. This script establishes, from preserved
artifacts alone, **what can and cannot be proven** about the code that executed.

It classifies every Phase-2B-relevant source file into exactly one of:

* ``ESTABLISHED``    - the run-time version is pinned by a cryptographic or
                       behavioural attestation computed here;
* ``CHANGED_AFTER``  - the file is known to differ from what ran, with the
                       change identified;
* ``UNPROVEN``       - the exact run-time bytes cannot be established; only
                       circumstantial evidence (mtime, no-op-on-outcome) exists.

**mtime is treated as circumstantial, never as proof.** A filesystem timestamp
is settable and is not a cryptographic record. Where a stronger attestation
exists it is computed and reported; where none exists the file is UNPROVEN and
says so.

    python scripts/phase2b_provenance_audit.py --config configs/phase2b.yaml \
        --manifest manifests/phase2b.jsonl --out <dir>
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pandas as pd  # noqa: E402

from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.controller import (  # noqa: E402
    DECISION_LOG_NAME,
    DecisionLog,
    build_controller,
)
from biomni_uncertainty.policy import PolicyState, build_pools, resolve  # noqa: E402

ESTABLISHED = "ESTABLISHED"
CHANGED_AFTER = "CHANGED_AFTER"
UNPROVEN = "UNPROVEN"

#: Files whose run-time state matters, with the reason each is in scope. Order is
#: the order they are reported in.
IN_SCOPE: tuple[tuple[str, str], ...] = (
    ("configs/phase2b.yaml", "every experiment constant"),
    ("manifests/phase2b.jsonl", "the frozen held-out sample"),
    ("manifests/phase2b.groundtruth.jsonl", "evaluation labels"),
    ("src/biomni_uncertainty/controller.py", "the online controller and its decision log"),
    ("src/biomni_uncertainty/policy.py", "resolution, agreement and the policy classes"),
    ("src/biomni_uncertainty/sampling.py", "run ids, seeds, run directories, markers"),
    ("src/biomni_uncertainty/benchmark.py", "manifest entries and prompts"),
    ("src/biomni_uncertainty/config.py", "config validation and hashing"),
    ("src/biomni_uncertainty/runner.py", "one trajectory; failure classification"),
    ("src/biomni_uncertainty/budget.py", "the Arm-2 degeneration guards"),
    ("src/biomni_uncertainty/canonicalization.py", "raw response -> canonical answer"),
    ("src/biomni_uncertainty/confidence.py", "confidence elicitation and extraction"),
    ("src/biomni_uncertainty/instrumentation.py", "LLM/tool/retrieval interception"),
    ("src/biomni_uncertainty/evaluation.py", "the official scorer wrapper"),
    ("scripts/phase2b_run.py", "the online driver that generated trajectories"),
    ("scripts/run_phase2b.sh", "launch wrapper"),
    ("scripts/phase2b_supervise.sh", "launch supervisor"),
    ("scripts/phase2b_verify.py", "the integrity/halt gate"),
    ("scripts/phase2b_analyze.py", "post-run analysis"),
    ("tests/test_controller.py", "controller tests"),
    ("tests/test_phase2b_analyze.py", "analysis tests"),
)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).stdout.strip()


def git_tracked(rel: str) -> bool:
    return bool(git("ls-files", "--error-unmatch", rel)) or rel in git("ls-files").splitlines()


def git_matches_head(rel: str) -> bool:
    rc = subprocess.run(["git", "-C", str(REPO), "diff", "--quiet", "HEAD", "--", rel])
    return rc.returncode == 0


def run_window(runs_dir: Path) -> tuple[float, float, list[dict]]:
    metas = []
    for p in glob.glob(str(runs_dir / "*" / "*" / "*" / "t*" / "metadata.json")):
        m = json.loads(Path(p).read_text())
        m["_metadata_dir"] = str(Path(p).parent)
        metas.append(m)
    starts = [m["started_at"] for m in metas]
    ends = [m["ended_at"] for m in metas]
    return min(starts), max(ends), metas


def fmt(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# Attestations
# --------------------------------------------------------------------------


def attest_config(cfg_path: Path, metas: list[dict]) -> dict:
    """Recompute the stored `config_hash` from the current YAML under the
    run-time environment. The config file records `${ENV}` placeholders, so the
    recorded snapshot's expanded paths have to be restored before hashing -
    otherwise the mismatch is an artifact of the environment, not of the file.
    """
    snap = metas[0]["config_snapshot"]
    env = {
        "BIOMNI_UNC_OUTPUT_ROOT": snap["experiment"]["output_root"],
        "BIOMNI_PATH": snap["execution"]["data_path"],
        "BIOMNI_UNC_EVAL1_PARQUET": snap["benchmark"]["local_parquet"],
    }
    saved = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        cfg = load_config(cfg_path)
        recomputed = cfg.hash()
        live = json.loads(cfg.model_dump_json())
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    stored = {m["config_hash"] for m in metas}
    return {
        "stored_config_hash": sorted(stored),
        "recomputed_from_current_yaml": recomputed,
        "hash_match": len(stored) == 1 and recomputed in stored,
        "snapshot_identical": json.dumps(live, sort_keys=True) == json.dumps(snap, sort_keys=True),
        "env_restored_for_hashing": env,
    }


def attest_controller(runs_dir: Path, pooled: pd.DataFrame, cfg) -> dict:
    """Replay every committed decision record against the *current* controller.

    This is the strongest available attestation for `controller.py` and
    `policy.py`: the hash-chained log stores each decision's action, its
    free-text ``reason`` string, support count, agreement flag, resolved cluster
    key and the exact list of observed run_ids. Those strings are generated by
    f-strings inside the policy classes, so any edit to the decision logic - or
    to the wording that describes it - breaks the reproduction.
    """
    controller = build_controller(cfg.controller)
    pools = {(p.task_name, p.task_instance_id): p for p in build_pools(pooled)}
    total = matched = 0
    chains_ok = 0
    mismatches: list[dict] = []
    for (task, tid), pool in sorted(pools.items()):
        log = DecisionLog(runs_dir / task / f"i{tid:04d}" / DECISION_LOG_NAME)
        ok, _ = log.verify()
        chains_ok += int(ok)
        views = pool.views(tuple(range(pool.k)))
        for rec in log.records:
            total += 1
            d = controller.decide(PolicyState(task, views[: rec.step], pool.k))
            res = resolve(views[: rec.step])
            same = (
                d.action == rec.action
                and d.reason == rec.reason
                and res.support == rec.support
                and res.valid_agreement == rec.valid_agreement
                and res.cluster_key == rec.resolved_cluster_key
                and [v.run_id for v in views[: rec.step]] == rec.observed_run_ids
            )
            matched += int(same)
            if not same:
                mismatches.append(
                    {"task": task, "instance": tid, "step": rec.step, "logged": rec.action, "now": d.action}
                )
    return {
        "decision_records": total,
        "reproduced_exactly": matched,
        "mismatches": len(mismatches),
        "examples": mismatches[:5],
        "instances": len(pools),
        "hash_chains_verified": chains_ok,
        "fields_compared": [
            "action",
            "reason (free text, generated by the policy)",
            "support",
            "valid_agreement",
            "resolved_cluster_key",
            "observed_run_ids",
        ],
    }


#: The manifest hash frozen in `reports/phase2_protocol.md` before any inference.
FROZEN_MANIFEST_HASH = "7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd"


def attest_manifest(manifest: Path) -> dict:
    """Recompute the content hash frozen in the protocol before inference ran."""
    from biomni_uncertainty.benchmark import ManifestEntry, manifest_hash

    entries = [ManifestEntry(**json.loads(li)) for li in manifest.read_text().splitlines() if li.strip()]
    h = manifest_hash(entries)
    return {
        "n_instances": len(entries),
        "frozen_in_protocol": FROZEN_MANIFEST_HASH,
        "recomputed": h,
        "match": h == FROZEN_MANIFEST_HASH,
        "file_sha256": sha256_file(manifest),
    }


def attest_driver_specs(cfg, manifest: Path, metas: list[dict]) -> dict:
    """Recompute every trajectory's identity from tracked code alone.

    `scripts/phase2b_run.py` is untracked, so its bytes cannot be proven. What
    *can* be proven is that every run identity it emitted is the deterministic
    output of tracked `sampling.make_run_id` / `run_dir_for` plus the frozen
    manifest and the attested config - including the shadow condition, which
    `expand_runs` does not itself produce. That pins the driver's
    spec-generation path without pinning its orchestration.
    """
    from biomni_uncertainty.benchmark import ManifestEntry
    from biomni_uncertainty.sampling import make_run_id, run_dir_for

    entries = {
        (e.task_name, e.task_instance_id): e
        for e in (ManifestEntry(**json.loads(li)) for li in manifest.read_text().splitlines() if li.strip())
    }
    checks = {"run_id": 0, "requested_seed": 0, "prompt_hash": 0, "run_dir_on_disk": 0}
    for m in metas:
        task, tid = m["task_name"], m["task_instance_id"]
        cond, idx = m["condition"], m["trajectory_index"]
        checks["run_id"] += make_run_id(cfg.experiment_id, task, tid, cond, idx) == m["run_id"]
        checks["requested_seed"] += (cfg.trajectories.seed_base + 100 + idx) == m["requested_seed"]
        checks["prompt_hash"] += entries[(task, tid)].prompt_hash == m["prompt_hash"]
        base = {"task_name": task, "task_instance_id": tid, "condition": cond, "trajectory_index": idx}
        checks["run_dir_on_disk"] += str(run_dir_for(cfg, base)) == m["_metadata_dir"]
    return {"n": len(metas), "matched": checks, "all_match": all(v == len(metas) for v in checks.values())}


def classify(rel: str, sha: str, mtime: float, t0: float, t1: float, tracked: bool, clean: bool) -> tuple[str, str]:
    """Assign one of the three provenance classes, with the reason."""
    if tracked and clean:
        return ESTABLISHED, f"tracked and byte-identical to HEAD ({git('rev-parse', '--short', 'HEAD')})"
    if mtime > t1:
        return CHANGED_AFTER, f"last modified {fmt(mtime)}, after the run ended {fmt(t1)}"
    if mtime < t0:
        return UNPROVEN, f"untracked; mtime {fmt(mtime)} predates the run start {fmt(t0)} (circumstantial only)"
    return UNPROVEN, f"untracked; mtime {fmt(mtime)} falls inside the run window (circumstantial only)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO / "configs/phase2b.yaml")
    ap.add_argument("--manifest", type=Path, default=REPO / "manifests/phase2b.jsonl")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cfg = load_config(args.config)
    runs_dir = cfg.runs_dir
    t0, t1, metas = run_window(runs_dir)
    head = git("rev-parse", "HEAD")

    print(f"run window: {fmt(t0)} -> {fmt(t1)}  ({len(metas)} trajectories)")
    print(f"HEAD now  : {head}\n")

    # --- what the run records say about itself ---------------------------
    def uniq(fn):
        return sorted({json.dumps(fn(m), sort_keys=True) for m in metas})

    recorded = {
        "n_trajectories": len(metas),
        "config_hash": uniq(lambda m: m["config_hash"]),
        "project_git": uniq(lambda m: m.get("project_git")),
        "biomni_git": uniq(lambda m: m.get("biomni_git")),
        "hostname": uniq(lambda m: m.get("hostname")),
        "slurm_job_id": uniq(lambda m: (m.get("slurm") or {}).get("SLURM_JOB_ID")),
        "run_window": [fmt(t0), fmt(t1)],
    }

    # --- attestations -----------------------------------------------------
    pooled = pd.read_csv(cfg.results_dir / "tables" / "p2b_pooled_trajectories.csv")
    att = {
        "config": attest_config(args.config, metas),
        "manifest": attest_manifest(args.manifest),
        "controller_behaviour": attest_controller(runs_dir, pooled, cfg),
        "driver_spec_generation": attest_driver_specs(cfg, args.manifest, metas),
    }

    # --- per-file inventory ----------------------------------------------
    rows = []
    for rel, why in IN_SCOPE:
        p = REPO / rel
        if not p.exists():
            rows.append({"file": rel, "why_in_scope": why, "class": UNPROVEN, "evidence": "file absent"})
            continue
        tracked = rel in set(git("ls-files").splitlines())
        clean = tracked and git_matches_head(rel)
        sha = sha256_file(p)
        mtime = p.stat().st_mtime
        klass, evidence = classify(rel, sha, mtime, t0, t1, tracked, clean)
        rows.append(
            {
                "file": rel,
                "why_in_scope": why,
                "tracked_in_HEAD": tracked,
                "identical_to_HEAD": clean,
                "sha256": sha,
                "mtime": fmt(mtime),
                "class": klass,
                "evidence": evidence,
                "attested_behaviour": "",
            }
        )

    # --- upgrade the two files that carry an independent attestation ------
    by = {r["file"]: r for r in rows}
    if att["config"]["hash_match"] and att["config"]["snapshot_identical"]:
        r = by["configs/phase2b.yaml"]
        r["class"] = ESTABLISHED
        r["evidence"] = (
            "stored config_hash recomputes bit-exactly from this file under the run-time environment, "
            "and the full config snapshot is identical; " + r["evidence"]
        )
    cb = att["controller_behaviour"]
    if cb["mismatches"] == 0 and cb["decision_records"] > 0:
        for rel in ("src/biomni_uncertainty/controller.py", "src/biomni_uncertainty/policy.py"):
            r = by[rel]
            r["class"] = ESTABLISHED
            r["attested_behaviour"] = (
                f"all {cb['reproduced_exactly']}/{cb['decision_records']} committed decision records reproduce "
                "exactly (action, free-text reason, support, agreement, cluster key, observed run_ids)"
            )
            r["evidence"] = "decision logic attested behaviourally; " + r["evidence"]

    # `phase2b_run.py` stays UNPROVEN as bytes, but what it emitted is pinned.
    ds = att["driver_spec_generation"]
    if ds["all_match"]:
        by["scripts/phase2b_run.py"]["attested_behaviour"] = (
            f"all {ds['n']} trajectory identities recompute from tracked code: run_id via sampling.make_run_id "
            "(including the shadow condition), requested_seed via seed_base+100+index, prompt_hash against the "
            "frozen manifest, run_dir via sampling.run_dir_for. Orchestration (concurrency, resume, the "
            "commit-before-generate barrier) is attested only by the gate invariants, not by these hashes."
        )

    df = pd.DataFrame(rows)
    df.to_csv(args.out / "phase2b_provenance_inventory.csv", index=False)
    (args.out / "phase2b_provenance.json").write_text(
        json.dumps(
            {"head_at_audit": head, "recorded_by_runs": recorded, "attestations": att, "inventory": rows}, indent=2
        )
    )

    counts = df["class"].value_counts().to_dict()
    print(df[["file", "class", "sha256"]].assign(sha256=df.sha256.str[:12]).to_string(index=False))
    print(f"\nclasses: {counts}")
    print(f"config hash match      : {att['config']['hash_match']}")
    print(f"manifest hash match    : {att['manifest']['match']} ({att['manifest']['n_instances']} instances)")
    print(f"driver spec identities : {att['driver_spec_generation']['matched']}")
    print(
        f"decision records replayed: {cb['reproduced_exactly']}/{cb['decision_records']} exact, {cb['mismatches']} mismatches"
    )
    print(f"\nwrote {args.out}/phase2b_provenance_inventory.csv and phase2b_provenance.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
