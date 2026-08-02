#!/usr/bin/env python
"""Compare the three repair-ablation arms and apply the pre-stated decision rule.

The rule, fixed in ``reports/context_overflow_forensics.md`` section 9 before any
arm ran: **accept the least invasive arm that greatly reduces degeneration
without materially harming reward or altering successful behaviour.** So the
control strata matter as much as the overflow-prone one - an arm that fixes the
failures by making the agent worse everywhere has not passed.

    python scripts/analyze_ablation.py --output-root <root> --strata manifests/ablation.strata.json
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

ARMS = ("abl_arm1", "abl_arm2", "abl_arm3")
ARM_LABEL = {
    "abl_arm1": "arm1 control (Phase-1 behaviour)",
    "abl_arm2": "arm2 bounding only",
    "abl_arm3": "arm3 bounding + budgets",
}
STRATUM_ORDER = ("overflow_prone", "same_family_control", "short_easy_control", "gwas_control")


def read_events(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                break
    return out


def load_arm(runs_root: Path) -> list[dict]:
    rows = []
    for d in sorted(runs_root.glob("*/i*/*/t*")):
        meta_path, failed_path = d / "metadata.json", d / "FAILED"
        # A run still in flight has neither marker. Counting it as a failure
        # would make every mid-dispatch look catastrophic, so skip it and let
        # the caller see a short run count instead.
        if not (d / "COMPLETE").exists() and not failed_path.exists():
            continue
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        failed = json.loads(failed_path.read_text()) if failed_path.exists() else {}
        calls, guards = [], defaultdict(int)
        if (d / "events.jsonl").exists():
            for e in read_events(d / "events.jsonl"):
                p = e.get("payload") or {}
                if e["event_type"] == "llm_request_end":
                    u = p.get("usage") or {}
                    calls.append((u.get("input_tokens"), u.get("output_tokens"), p.get("finish_reason")))
                elif e["event_type"] in (
                    "budget_warning",
                    "budget_terminated",
                    "runaway_truncated",
                    "observation_truncated",
                    "retrieval_capped",
                ):
                    guards[e["event_type"]] += 1
        parsed_path = d / "parsed_answer.json"
        parsed = json.loads(parsed_path.read_text()) if parsed_path.exists() else {}
        rows.append(
            {
                "task": d.parts[-4],
                "instance": int(d.parts[-3].lstrip("i")),
                "run_id": meta.get("run_id") or failed.get("run_id"),
                "completed": bool(meta.get("completed")),
                "failure_class": meta.get("failure_class") or failed.get("failure_class"),
                "wall": meta.get("wall_time_seconds") or failed.get("wall_time_seconds") or 0.0,
                "peak_input": max([c[0] for c in calls if c[0]], default=0),
                # Call 0 is the retrieval query, not part of the agent loop.
                "runaways": sum(1 for c in calls[1:] if c[2] == "length"),
                "n_calls": len(calls),
                "output_tokens": sum(c[1] or 0 for c in calls),
                "answer_status": (parsed.get("parsed") or {}).get("status"),
                # Reward is NOT in metadata.json - the runner never scores its own
                # trajectory (ground truth must stay out of the execution process).
                # It is computed later by `cli aggregate` against the official
                # evaluator and only lives in results/tables/trajectories.csv,
                # joined in by run_id below. Left None here as the "not yet
                # joined" sentinel.
                "reward": None,
                "guards": dict(guards),
            }
        )
    return rows


def load_rewards(results_root: Path) -> dict[str, float | None]:
    """run_id -> official reward, from the aggregated trajectories table.

    `cli aggregate` is the only code path that scores a trajectory (it is the
    one place ground truth and predictions are both in scope); this reads that
    output rather than re-deriving reward here.
    """
    path = results_root / "tables" / "trajectories.csv"
    if not path.exists():
        return {}
    out: dict[str, float | None] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            v = row.get("reward")
            out[row["run_id"]] = float(v) if v not in (None, "", "nan") else None
    return out


def fmt(x, spec=".3f"):
    return "n/a" if x is None else format(x, spec)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-root", required=True, type=Path)
    ap.add_argument("--strata", type=Path, default=Path("manifests/ablation.strata.json"))
    args = ap.parse_args()

    stratum_of = {(s["task_name"], s["task_instance_id"]): s["stratum"] for s in json.loads(args.strata.read_text())}

    data = {}
    for arm in ARMS:
        root = args.output_root / arm / "runs"
        data[arm] = load_arm(root) if root.exists() else []
        rewards = load_rewards(args.output_root / arm / "results")
        n_unmatched = 0
        for r in data[arm]:
            r["stratum"] = stratum_of.get((r["task"], r["instance"]), "unknown")
            if r["run_id"] in rewards:
                r["reward"] = rewards[r["run_id"]]
            elif r["completed"]:
                n_unmatched += 1
        if n_unmatched:
            print(
                f"  [warning] {ARM_LABEL[arm]}: {n_unmatched} completed run(s) have no reward "
                f"in results/tables/trajectories.csv - re-run `cli aggregate` for this arm]"
            )

    print("=" * 96)
    print("REPAIR ABLATION - 24 balanced instances x 3 arms")
    print("=" * 96)
    for arm in ARMS:
        print(f"  {ARM_LABEL[arm]:<38} runs on disk: {len(data[arm]):2d}/24")
    if any(len(data[a]) < 24 for a in ARMS):
        print("  [incomplete - numbers below are provisional]")

    print("\n1. PRIMARY OUTCOME - degeneration and completion")
    print("-" * 96)
    print(f"{'arm':<40}{'completed':>12}{'failed':>9}{'runs w/ runaway':>18}{'total runaways':>16}")
    for arm in ARMS:
        rs = data[arm]
        if not rs:
            continue
        comp = sum(1 for r in rs if r["completed"])
        anyr = sum(1 for r in rs if r["runaways"] > 0)
        print(
            f"{ARM_LABEL[arm]:<40}{comp:>7}/{len(rs):<4}{len(rs) - comp:>9}"
            f"{anyr:>13}/{len(rs):<4}{sum(r['runaways'] for r in rs):>16}"
        )

    print("\n2. CONTEXT USE")
    print("-" * 96)
    print(f"{'arm':<40}{'median peak':>14}{'max peak':>12}{'>32768':>10}{'median calls':>15}")
    for arm in ARMS:
        rs = data[arm]
        if not rs:
            continue
        peaks = [r["peak_input"] for r in rs]
        print(
            f"{ARM_LABEL[arm]:<40}{st.median(peaks):>14.0f}{max(peaks):>12}"
            f"{sum(1 for p in peaks if p > 32768):>10}{st.median([r['n_calls'] for r in rs]):>15.0f}"
        )

    print("\n3. THE DECISION - failure and reward BY STRATUM")
    print("-" * 96)
    print("   The controls are the test that matters: a repair that fixes the")
    print("   overflow-prone stratum by degrading the others has failed.\n")
    header = f"{'stratum':<24}" + "".join(f"{a.replace('abl_', ''):>24}" for a in ARMS)
    print(header)
    for metric, label in (("failed", "failed / n"), ("reward", "mean reward"), ("parsed", "answer parsed")):
        print(f"  -- {label}")
        for strat in STRATUM_ORDER:
            line = f"    {strat:<20}"
            for arm in ARMS:
                rs = [r for r in data[arm] if r["stratum"] == strat]
                if not rs:
                    line += f"{'-':>24}"
                    continue
                if metric == "failed":
                    line += f"{sum(1 for r in rs if not r['completed'])}/{len(rs):<21}"
                elif metric == "reward":
                    vals = [r["reward"] for r in rs if r["reward"] is not None]
                    line += f"{(st.mean(vals) if vals else float('nan')):>24.3f}"
                else:
                    line += f"{sum(1 for r in rs if r['answer_status'] == 'ok')}/{len(rs):<21}"
            print(line)

    print("\n4. COST")
    print("-" * 96)
    print(f"{'arm':<40}{'total wall (h)':>16}{'median wall (s)':>18}{'output tokens':>16}")
    for arm in ARMS:
        rs = data[arm]
        if not rs:
            continue
        print(
            f"{ARM_LABEL[arm]:<40}{sum(r['wall'] for r in rs) / 3600:>16.2f}"
            f"{st.median([r['wall'] for r in rs]):>18.0f}{sum(r['output_tokens'] for r in rs):>16}"
        )

    print("\n5. WHICH GUARDS ACTUALLY FIRED")
    print("-" * 96)
    for arm in ARMS:
        tot = defaultdict(int)
        for r in data[arm]:
            for k, v in r["guards"].items():
                tot[k] += v
        print(f"   {ARM_LABEL[arm]:<40}{dict(tot) or 'none'}")

    print("\n6. DECISION RULE")
    print("-" * 96)
    rule_lines = []
    if all(len(data[a]) == 24 for a in ARMS):
        base_fail = sum(1 for r in data["abl_arm1"] if not r["completed"])
        ctrl = [s for s in STRATUM_ORDER if s != "overflow_prone"]
        base_ctrl = [r["reward"] for r in data["abl_arm1"] if r["stratum"] in ctrl and r["reward"] is not None]
        for arm in ("abl_arm2", "abl_arm3"):
            fail = sum(1 for r in data[arm] if not r["completed"])
            arm_ctrl = [r["reward"] for r in data[arm] if r["stratum"] in ctrl and r["reward"] is not None]
            d_ctrl = (st.mean(arm_ctrl) - st.mean(base_ctrl)) if (arm_ctrl and base_ctrl) else float("nan")
            rule_lines.append(
                f"   {ARM_LABEL[arm]:<40} failures {fail}/24 (control {base_fail}/24), "
                f"control reward delta {d_ctrl:+.3f}"
            )
        print("\n".join(rule_lines))
        print("\n   Accept the LEAST INVASIVE arm that clears both bars.")
    else:
        print("   [pending - run all three arms first]")


if __name__ == "__main__":
    main()
