#!/usr/bin/env python3
"""Stage C — the frozen verdict run.

Builds one trace capsule per unique candidate answer on the frozen 78
`B_substantive_disagreement` instances, scores every directed pair with the
ported LLM-as-a-Verifier fine-grained reward, and records the selected
candidate per instance.

**No new solver trajectories. Zero held-out instances consumed.** Every
candidate comes from already-completed, frozen trajectories.

Frozen by `reports/stage_c_preregistration.md` and
`reports/stage_c_stop_rule.md` (Amendments 1 and 2):

* population: the 78, unchanged;
* ranking: **full round-robin, both directions** — 244 directed pairs — not
  the pivot tournament; PPT is a zero-cost re-aggregation of these same
  cached scores and is computed by the analysis script, not here;
* C = 3 biomedical criteria, K = 8 repeated evaluations, granularity 20;
* rewards are never read here: this script writes selections, and the
  analysis script alone joins them to rewards.

This script does **not** compute a verdict and does **not** read ground truth.
That separation is deliberate — it makes it impossible to see an outcome while
the run is still in progress.

Usage
-----
    python scripts/stage_c_run.py prep  --out <dir>
    python scripts/stage_c_run.py score --out <dir> --cell c1 \
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
import stage_c_population  # noqa: E402
import stage_c_verifier_port as port  # noqa: E402

CRITERIA_FILE = REPO / "reports" / "stage_c_criteria.md"

#: Frozen scoring configuration (preregistration §5).
N_EVALUATIONS = 8
CANDIDATES = REPO / "reports" / "tables" / "track_c_step2" / "candidates_slim.jsonl"


def _load_prompts() -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for name in ("phase2b.jsonl", "phase1.jsonl"):
        path = REPO / "manifests" / name
        for line in path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                out[(d["task_name"], int(d["task_instance_id"]))] = d["prompt"]
    return out


def _trajectory_table() -> pd.DataFrame:
    """The frozen population's trajectory rows, minus ground truth.

    Pool filtering (`phase2b` unfiltered, `phase1_pooled` instrumented-only,
    reproducing exactly what `track_c_adjudication_pilot.py` used to build the
    frozen 78) lives in `stage_c_population.py`, the single source both this
    script and `stage_c_analyze.py` read from — they diverged once when the
    filter was duplicated, dropping a reward row for a shadow-held candidate,
    and that is why it now lives in exactly one place.

    Ground truth is dropped here, immediately, so the barrier is visible at
    this call site: this script never reads a reward.
    """
    df = stage_c_population.raw_trajectory_table()
    return df.drop(columns=[c for c in ("reward", "strict_reward", "correct") if c in df.columns])


def cmd_prep(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    prompts = _load_prompts()
    traj = _trajectory_table()
    instances = [json.loads(x) for x in CANDIDATES.read_text().splitlines() if x.strip()]
    if len(instances) != 78:
        raise SystemExit(f"expected the frozen 78 instances, got {len(instances)}")

    records = []
    for inst in instances:
        key = (inst["task_name"], int(inst["task_instance_id"]))
        prompt = prompts[key]
        rows = traj[
            (traj.pool == inst["pool"])
            & (traj.task_name == inst["task_name"])
            & (traj.task_instance_id == int(inst["task_instance_id"]))
        ]
        caps = []
        for answer in inst["candidates"]:
            holders = rows[rows.answer_canonical.astype(str) == str(answer)]
            if holders.empty:
                raise SystemExit(f"no trajectory holds candidate {answer!r} for {key}")
            # Representative trace: lexicographically smallest run_id, so the
            # choice cannot depend on arrival order or on how many agreed.
            rep = holders.sort_values("run_id").iloc[0]
            events = capsule_mod.read_events(rep.run_dir)
            cap = capsule_mod.build_capsule(
                task_name=inst["task_name"],
                task_prompt=prompt,
                committed_answer=str(answer),
                answer_parse_status=str(rep.answer_parse_status),
                events=events,
            )
            caps.append(
                {
                    "candidate_answer": str(answer),
                    "n_events": len(events),
                    "rendered": capsule_mod.render_capsule(cap),
                }
            )
        records.append(
            {
                "pool": inst["pool"],
                "task_name": inst["task_name"],
                "task_instance_id": int(inst["task_instance_id"]),
                "global_instance_id": inst["global_instance_id"],
                "task_prompt": prompt,
                "capsules": caps,
            }
        )

    path = out / "capsules.jsonl"
    with open(path, "w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    sizes = [len(c["rendered"]) for r in records for c in r["capsules"]]
    n_pairs = sum(len(r["capsules"]) * (len(r["capsules"]) - 1) for r in records)
    summary = {
        "n_instances": len(records),
        "n_capsules": len(sizes),
        "directed_pairs": n_pairs,
        "comparisons": n_pairs * 3 * N_EVALUATIONS,
        "capsule_chars": {
            "min": min(sizes),
            "median": sorted(sizes)[len(sizes) // 2],
            "max": max(sizes),
        },
    }
    (out / "prep_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    out = Path(args.out)

    # Stop rule §9: clean tree at launch, D-36 guard, never bypassed; model ids
    # and revision hashes recorded; source hashes so a D-29-style audit is one
    # equality check. There is deliberately no --allow-dirty here: this is a
    # confirmatory run, and D-36 reserves that flag for throwaway work.
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

    error_log = out / f"comparison_errors_{args.cell}.jsonl"
    fgr = port.install(error_log=str(error_log))
    probe = port.self_test(args.base_url)
    (out / f"port_self_test_{args.cell}.json").write_text(json.dumps(probe, indent=2))
    print(json.dumps(probe, indent=2))
    if probe["ported_regex"] < port.MIN_ON_SCALE_MASS:
        print("ABORT: constraint not honoured on this endpoint")
        return 1

    sys.path.insert(0, port.DEFAULT_REF_REPO)
    from llm_verifier.prompts import load_prompts as load_criteria  # noqa: E402

    note, criteria = load_criteria(str(CRITERIA_FILE))
    criteria_ids = [c["id"] for c in criteria]
    print(f"criteria={criteria_ids}  K={N_EVALUATIONS}  ranking=full round-robin")

    records = [json.loads(x) for x in (out / "capsules.jsonl").read_text().splitlines() if x.strip()]

    # Full round-robin: every ordered pair, so slot bias cancels exactly
    # rather than in expectation over a random ring.
    tasks: dict[str, list[dict]] = {}
    needed: dict[str, list[tuple[int, int]]] = {}
    for r in records:
        name = f"{r['pool']}::{r['task_name']}::{r['task_instance_id']}"
        tasks[name] = [
            {"problem": r["task_prompt"], "trace": c["rendered"], "answer": c["candidate_answer"]}
            for c in r["capsules"]
        ]
        needed[name] = list(permutations(range(len(tasks[name])), 2))

    total = sum(len(v) for v in needed.values()) * len(criteria_ids) * N_EVALUATIONS
    print(f"{sum(len(v) for v in needed.values())} directed pairs -> {total} comparisons")

    cache_file = str(out / f"cache_{args.cell}.json")
    scores = fgr.score_directed_pairs(
        fgr.LazyClient(),
        tasks,
        needed,
        criteria,
        note,
        N_EVALUATIONS,
        args.max_workers,
        cache_file,
        progress=True,
    )

    # Bradley-Terry soft wins, exactly as the reference aggregates them.
    selections = []
    for r in records:
        name = f"{r['pool']}::{r['task_name']}::{r['task_instance_id']}"
        n = len(tasks[name])
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
                "pool": r["pool"],
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
                "pairwise": pairwise,
            }
        )

    path = out / f"selections_{args.cell}.jsonl"
    with open(path, "w") as fh:
        for s in selections:
            fh.write(json.dumps(s) + "\n")

    n_err = sum(1 for _ in open(error_log)) if error_log.exists() else 0
    meta = {
        "cell": args.cell,
        "base_url": args.base_url,
        "served_model": port.served_model(args.base_url),
        "launch": launch,
        "criteria": criteria_ids,
        "n_evaluations": N_EVALUATIONS,
        "ranking": "full round-robin, both directions",
        "n_instances": len(selections),
        "directed_pairs": sum(len(v) for v in needed.values()),
        "comparisons": total,
        "comparison_errors": n_err,
        "unresolved_ties": sum(1 for s in selections if s["unresolved_tie"]),
        "port_self_test": probe,
    }
    (out / f"score_metadata_{args.cell}.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: v for k, v in meta.items() if k != "port_self_test"}, indent=2))
    print(f"\nselections written: {path}  (no reward has been read)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep", help="build trace capsules")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_prep)
    s = sub.add_parser("score", help="round-robin scoring for one cell")
    s.add_argument("--out", required=True)
    s.add_argument("--cell", required=True, choices=["c1", "c2"])
    s.add_argument("--base-url", required=True)
    s.add_argument("--max-workers", type=int, default=24)
    s.set_defaults(fn=cmd_score)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
