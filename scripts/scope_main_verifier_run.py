#!/usr/bin/env python3
"""Phase 2 of the matched scope study — verifier scoring of both arms.

`reports/scope_study_preregistration.md` SS4: "the frozen Stage-C C1 verifier
... with the unchanged port, capsule allowlist, three biomedical criteria,
score granularity G=20, K=8 repeats, full round-robin and Bradley-Terry
aggregation fixed in `reports/stage_c_preregistration.md` SS3-5." This script
is the adapter that SS4 anticipates: "an adapter that changes which traces are
read and nothing about how they are scored."

**This is a NEW file, not an edit to `scripts/stage_c_run.py`.** That script
produced D-43's gating decision and CLAUDE.md forbids overwriting a script that
already has. Every piece of scoring logic below is imported unmodified from the
Stage-C modules:

* `stage_c_capsule.build_capsule` / `render_capsule` — the capsule format and
  its leakage barrier, byte-for-byte identical code path;
* `stage_c_verifier_port` — the SGLang constrained-decoding port and its
  self-test, unmodified;
* `reports/stage_c_criteria.md` — the three frozen criteria, read verbatim;
* the round-robin / Bradley-Terry scoring loop, copied from
  `stage_c_run.py::cmd_score` with exactly one generalization: Stage C's
  population always had >=2 candidates (it was built from
  `B_substantive_disagreement` instances by construction); the scope study's
  120 instances were not filtered that way, so an instance can have 0 or 1
  usable candidate. Those are handled here, structurally, rather than by
  relaxing anything the frozen scoring loop does for n>=2.

Handling instances with fewer than 2 usable candidates (frozen here, decided
before any verifier call for either arm):

* **0 usable candidates** (every trajectory failed to produce a parseable
  answer): the verifier has nothing to select between. Recorded with
  `n_candidates=0`, `selected_answer=None`. This instance is excluded from the
  verifier-selected mean in the same way a fixed-K selector scores it: a
  non-answer is a non-answer, and the downstream analysis script's Δ
  computation is over the same 120-instance population as the verifier-free
  half, so a None answer scores 0, not "missing".
* **exactly 1 usable candidate**: no comparison is possible or needed. The
  verifier trivially "selects" the sole candidate. `n_candidates=1`,
  `mean_preference=[1.0]`, no directed pairs, no LLM calls spent. This is the
  correct behaviour under the method, not a shortcut around it: a verifier
  scoring a set of size 1 against nothing must return that one member.
* **>=2 usable candidates**: full round-robin, C=3, K=8, exactly as Stage C.

Usage
-----
    python scripts/scope_main_verifier_run.py prep  --arm a --out <dir>
    python scripts/scope_main_verifier_run.py score --arm a --out <dir> \
        --base-url http://host:30010/v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from itertools import permutations
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "src"))

import stage_c_capsule as capsule_mod  # noqa: E402
import stage_c_verifier_port as port  # noqa: E402

CRITERIA_FILE = REPO / "reports" / "stage_c_criteria.md"
MANIFEST = REPO / "manifests" / "scope_main.jsonl"

#: Frozen scoring configuration, unchanged from stage_c_preregistration.md SS5.
N_EVALUATIONS = 8


def _load_prompts() -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for line in MANIFEST.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            out[(d["task_name"], int(d["task_instance_id"]))] = d["prompt"]
    return out


def _trajectory_table(arm: str) -> pd.DataFrame:
    """This arm's instrumented trajectories, ground truth already stripped.

    Ground truth is dropped immediately so the barrier is visible at this call
    site: this script never reads a reward, exactly as `stage_c_run.py` never
    did. `instrumented.csv` was produced by `cli aggregate` against
    `manifests/scope_main.groundtruth.jsonl`; the reward column exists only
    because the evaluator wrote it during aggregation, not because this script
    consults it.
    """
    path = Path(f"/scratch/11034/atzanakak/biomni_unc_runs/scope_main_{arm}/results/tables/instrumented.csv")
    df = pd.read_csv(path)
    return df.drop(columns=[c for c in ("reward", "strict_reward", "correct") if c in df.columns])


def cmd_prep(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    prompts = _load_prompts()
    traj = _trajectory_table(args.arm)

    manifest_entries = [json.loads(x) for x in MANIFEST.read_text().splitlines() if x.strip()]
    if len(manifest_entries) != 120:
        raise SystemExit(f"expected the frozen 120 scope-study instances, got {len(manifest_entries)}")

    records = []
    trivial = 0
    empty = 0
    for inst in manifest_entries:
        task_name = inst["task_name"]
        tid = int(inst["task_instance_id"])
        prompt = prompts[(task_name, tid)]
        rows = traj[
            (traj.task_name == task_name)
            & (traj.task_instance_id == tid)
            & (traj.answer_parse_status.astype(str) == "ok")
        ]
        unique_answers = sorted(rows.answer_canonical.astype(str).unique().tolist())

        caps = []
        for answer in unique_answers:
            holders = rows[rows.answer_canonical.astype(str) == answer]
            # Representative trace: lexicographically smallest run_id, exactly
            # as stage_c_run.py chooses it -- deterministic, independent of
            # arrival order, independent of how many trajectories agreed.
            rep = holders.sort_values("run_id").iloc[0]
            events = capsule_mod.read_events(rep.run_dir)
            cap = capsule_mod.build_capsule(
                task_name=task_name,
                task_prompt=prompt,
                committed_answer=answer,
                answer_parse_status="ok",
                events=events,
            )
            caps.append(
                {
                    "candidate_answer": answer,
                    "n_events": len(events),
                    "rendered": capsule_mod.render_capsule(cap),
                }
            )

        if len(caps) == 0:
            empty += 1
        elif len(caps) == 1:
            trivial += 1

        records.append(
            {
                "arm": args.arm,
                "task_name": task_name,
                "task_instance_id": tid,
                "global_instance_id": inst["global_instance_id"],
                "task_prompt": prompt,
                "capsules": caps,
            }
        )

    path = out / f"capsules_{args.arm}.jsonl"
    with open(path, "w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    sizes = [len(c["rendered"]) for r in records for c in r["capsules"]]
    scoreable = [r for r in records if len(r["capsules"]) >= 2]
    n_pairs = sum(len(r["capsules"]) * (len(r["capsules"]) - 1) for r in scoreable)
    summary = {
        "arm": args.arm,
        "n_instances": len(records),
        "n_capsules": len(sizes),
        "n_zero_candidate_instances": empty,
        "n_trivial_single_candidate_instances": trivial,
        "n_scoreable_instances_ge2_candidates": len(scoreable),
        "directed_pairs": n_pairs,
        "comparisons": n_pairs * 3 * N_EVALUATIONS,
        "capsule_chars": {
            "min": min(sizes) if sizes else None,
            "median": sorted(sizes)[len(sizes) // 2] if sizes else None,
            "max": max(sizes) if sizes else None,
        },
    }
    (out / f"prep_summary_{args.arm}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    out = Path(args.out)

    from biomni_uncertainty import provenance

    git = provenance.assert_clean_tree(REPO)
    launch = {
        "project_commit": git["commit"],
        "dirty": git["dirty"],
        "source_hashes": provenance.source_hashes(REPO),
        "reference_repo_commit": port.reference_commit(),
    }
    print(f"launch commit {git['commit']} (clean tree)")

    os.environ["OPENAI_BASE_URL"] = args.base_url
    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")

    error_log = out / f"comparison_errors_{args.arm}.jsonl"
    fgr = port.install(error_log=str(error_log))
    probe = port.self_test(args.base_url)
    (out / f"port_self_test_{args.arm}.json").write_text(json.dumps(probe, indent=2))
    print(json.dumps(probe, indent=2))
    if probe["ported_regex"] < port.MIN_ON_SCALE_MASS:
        print("ABORT: constraint not honoured on this endpoint")
        return 1

    sys.path.insert(0, port.DEFAULT_REF_REPO)
    from llm_verifier.prompts import load_prompts as load_criteria  # noqa: E402

    note, criteria = load_criteria(str(CRITERIA_FILE))
    criteria_ids = [c["id"] for c in criteria]
    print(f"criteria={criteria_ids}  K={N_EVALUATIONS}  ranking=full round-robin")

    records = [json.loads(x) for x in (out / f"capsules_{args.arm}.jsonl").read_text().splitlines() if x.strip()]

    tasks: dict[str, list[dict]] = {}
    needed: dict[str, list[tuple[int, int]]] = {}
    for r in records:
        name = f"{r['task_name']}::{r['task_instance_id']}"
        tasks[name] = [
            {"problem": r["task_prompt"], "trace": c["rendered"], "answer": c["candidate_answer"]}
            for c in r["capsules"]
        ]
        # Only instances with >=2 candidates need any comparison at all.
        needed[name] = list(permutations(range(len(tasks[name])), 2)) if len(tasks[name]) >= 2 else []

    total_pairs = sum(len(v) for v in needed.values())
    total = total_pairs * len(criteria_ids) * N_EVALUATIONS
    print(f"{total_pairs} directed pairs -> {total} comparisons")

    cache_file = str(out / f"cache_{args.arm}.json")
    scores = (
        fgr.score_directed_pairs(
            fgr.LazyClient(),
            {k: v for k, v in tasks.items() if needed[k]},
            {k: v for k, v in needed.items() if v},
            criteria,
            note,
            N_EVALUATIONS,
            args.max_workers,
            cache_file,
            progress=True,
        )
        if total_pairs
        else {}
    )

    selections = []
    for r in records:
        name = f"{r['task_name']}::{r['task_instance_id']}"
        n = len(tasks[name])
        if n == 0:
            selections.append(
                {
                    "arm": args.arm,
                    "task_name": r["task_name"],
                    "task_instance_id": r["task_instance_id"],
                    "global_instance_id": r["global_instance_id"],
                    "n_candidates": 0,
                    "candidate_answers": [],
                    "mean_preference": [],
                    "selected_index": None,
                    "selected_answer": None,
                    "unresolved_tie": False,
                    "margin": 0.0,
                    "trivial": False,
                    "pairwise": {},
                }
            )
            continue
        if n == 1:
            selections.append(
                {
                    "arm": args.arm,
                    "task_name": r["task_name"],
                    "task_instance_id": r["task_instance_id"],
                    "global_instance_id": r["global_instance_id"],
                    "n_candidates": 1,
                    "candidate_answers": [tasks[name][0]["answer"]],
                    "mean_preference": [1.0],
                    "selected_index": 0,
                    "selected_answer": tasks[name][0]["answer"],
                    "unresolved_tie": False,
                    "margin": 0.0,
                    "trivial": True,
                    "pairwise": {},
                }
            )
            continue

        w = [0.0] * n
        c = [0] * n
        pairwise = {}
        for a, b in needed[name]:
            ra, rb = fgr.directed_reward(scores, name, a, b, criteria_ids, N_EVALUATIONS)
            p = 1.0 / (1.0 + pow(2.718281828459045, -(ra - rb)))
            pairwise[f"{a}>{b}"] = {"R_a": ra, "R_b": rb, "p_a_beats_b": p}
            w[a] += p
            c[a] += 1
            w[b] += 1.0 - p
            c[b] += 1
        mean = [w[i] / c[i] if c[i] else 0.0 for i in range(n)]
        best = max(range(n), key=lambda i: (mean[i], -i))
        ties = [i for i in range(n) if mean[i] == mean[best]]
        ordered = sorted(mean, reverse=True)
        selections.append(
            {
                "arm": args.arm,
                "task_name": r["task_name"],
                "task_instance_id": r["task_instance_id"],
                "global_instance_id": r["global_instance_id"],
                "n_candidates": n,
                "candidate_answers": [t["answer"] for t in tasks[name]],
                "mean_preference": mean,
                "selected_index": best,
                "selected_answer": tasks[name][best]["answer"],
                "unresolved_tie": len(ties) > 1,
                "margin": (ordered[0] - ordered[1]) if n > 1 else 0.0,
                "trivial": False,
                "pairwise": pairwise,
            }
        )

    path = out / f"selections_{args.arm}.jsonl"
    with open(path, "w") as fh:
        for s in selections:
            fh.write(json.dumps(s) + "\n")

    n_err = sum(1 for _ in open(error_log)) if error_log.exists() else 0
    meta = {
        "arm": args.arm,
        "base_url": args.base_url,
        "served_model": port.served_model(args.base_url),
        "launch": launch,
        "criteria": criteria_ids,
        "n_evaluations": N_EVALUATIONS,
        "ranking": "full round-robin, both directions",
        "n_instances": len(selections),
        "n_scoreable_instances": sum(1 for s in selections if s["n_candidates"] >= 2),
        "n_trivial_instances": sum(1 for s in selections if s.get("trivial")),
        "n_zero_candidate_instances": sum(1 for s in selections if s["n_candidates"] == 0),
        "directed_pairs": total_pairs,
        "comparisons": total,
        "comparison_errors": n_err,
        "unresolved_ties": sum(1 for s in selections if s["unresolved_tie"]),
        "port_self_test": probe,
    }
    (out / f"score_metadata_{args.arm}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: v for k, v in meta.items() if k != "port_self_test"}, indent=2))
    print(f"\nselections written: {path}  (no reward has been read)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep", help="build trace capsules for one arm")
    p.add_argument("--arm", required=True, choices=["a", "b"])
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_prep)
    s = sub.add_parser("score", help="round-robin scoring for one arm")
    s.add_argument("--arm", required=True, choices=["a", "b"])
    s.add_argument("--out", required=True)
    s.add_argument("--base-url", required=True)
    s.add_argument("--max-workers", type=int, default=24)
    s.set_defaults(fn=cmd_score)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
