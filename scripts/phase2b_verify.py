#!/usr/bin/env python
"""Phase 2B - verify the protocol's integrity gates against a completed run.

Implements `reports/phase2_protocol.md` §10 (smoke pass conditions) and the
run-level halt conditions of §11. Every check is computed from artifacts on
disk, never from a claim in a log line.

The two that matter most are SHADOW ISOLATION and CHAIN INTEGRITY: if either
fails, the run is not prospective evidence and must not be analysed as if it
were.

    python scripts/phase2b_verify.py --config configs/phase2b_smoke.yaml \
        --manifest manifests/phase2b_smoke.jsonl [--smoke]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from biomni_uncertainty.benchmark import ManifestEntry  # noqa: E402
from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.controller import (  # noqa: E402
    ABSTAIN,
    ACCEPT,
    CONDITION_CONSUMED,
    CONDITION_SHADOW,
    CONTINUE,
    DECISION_LOG_NAME,
    DecisionLog,
)
from biomni_uncertainty.policy import FORBIDDEN_VIEW_FIELDS, TrajectoryView  # noqa: E402

MAX_OVERFLOW_FRACTION = 0.15  # §11 halt condition
MAX_MISSING_INSTANCE_FRACTION = 0.10


class Gates:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def check(self, name: str, ok: bool, detail: str, *, fatal: bool = True) -> bool:
        self.rows.append({"gate": name, "pass": bool(ok), "fatal": fatal, "detail": detail})
        return bool(ok)

    @property
    def failed_fatal(self) -> list[dict]:
        return [r for r in self.rows if not r["pass"] and r["fatal"]]

    def report(self) -> int:
        width = max(len(r["gate"]) for r in self.rows)
        for r in self.rows:
            mark = "PASS" if r["pass"] else ("FAIL" if r["fatal"] else "warn")
            print(f"  [{mark}] {r['gate']:<{width}}  {r['detail']}")
        print()
        if self.failed_fatal:
            print(f"VERDICT: BLOCKED - {len(self.failed_fatal)} fatal gate(s) failed.")
            return 1
        print("VERDICT: ALL GATES PASS.")
        return 0


def load_run(run_dir: Path) -> dict | None:
    meta = run_dir / "metadata.json"
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--smoke", action="store_true", help="also apply the smoke-specific coverage gates")
    args = ap.parse_args()

    cfg = load_config(args.config)
    entries = [ManifestEntry(**json.loads(li)) for li in args.manifest.read_text().splitlines() if li.strip()]
    max_k = cfg.controller.max_trajectories
    g = Gates()

    print(f"Phase-2B verification: {cfg.experiment_id}, {len(entries)} instances, K={max_k}")
    print(f"runs: {cfg.runs_dir}\n")

    inst: list[dict] = []
    for e in entries:
        d = cfg.runs_dir / e.task_name / f"i{e.task_instance_id:04d}"
        log = DecisionLog(d / DECISION_LOG_NAME)
        ok_chain, why = log.verify()
        term = log.terminal()
        depth = term.step if term else log.n_steps
        consumed, shadows = [], []
        for idx in range(max_k):
            for cond, bucket in ((CONDITION_CONSUMED, consumed), (CONDITION_SHADOW, shadows)):
                m = load_run(d / cond / f"t{idx}")
                if m is not None:
                    bucket.append({"idx": idx, "meta": m})
        inst.append(
            {
                "task_name": e.task_name,
                "task_instance_id": e.task_instance_id,
                "n_steps": log.n_steps,
                "depth": depth,
                "action": term.action if term else None,
                "chain_ok": ok_chain,
                "chain_why": why,
                "terminal_decided_at": term.decided_at if term else None,
                "consumed": consumed,
                "shadows": shadows,
                "records": log.records,
            }
        )

    finished = [i for i in inst if i["action"] in (ACCEPT, ABSTAIN)]

    # -- 1. every instance ran and terminated ------------------------------
    g.check(
        "instances terminated",
        len(finished) == len(entries),
        f"{len(finished)}/{len(entries)} reached ACCEPT or ABSTAIN",
        fatal=args.smoke,
    )
    missing = [i for i in inst if i["n_steps"] == 0]
    g.check(
        "instances started",
        len(missing) <= MAX_MISSING_INSTANCE_FRACTION * len(entries),
        f"{len(missing)} instance(s) produced no decision at all (halt above {MAX_MISSING_INSTANCE_FRACTION:.0%})",
    )

    # -- 2. a decision at every step, none skipped -------------------------
    bad_steps = [
        f"{i['task_name']}/i{i['task_instance_id']:04d} steps={[r.step for r in i['records']]}"
        for i in finished
        if [r.step for r in i["records"]] != list(range(1, i["depth"] + 1))
    ]
    g.check("decision at every step", not bad_steps, bad_steps[:3] or "every step 1..depth has exactly one decision")

    # -- 3. hash chain -----------------------------------------------------
    broken = [f"{i['task_name']}/i{i['task_instance_id']:04d}: {i['chain_why']}" for i in inst if not i["chain_ok"]]
    g.check("decision chain intact", not broken, broken[:3] or f"all {len(inst)} chains verify end to end")

    # -- 4. shadow isolation -----------------------------------------------
    violations = []
    for i in finished:
        t = i["terminal_decided_at"]
        for s in i["shadows"]:
            started = s["meta"].get("started_at")
            if started is not None and t is not None and started < t:
                violations.append(
                    f"{i['task_name']}/i{i['task_instance_id']:04d} shadow t{s['idx']} "
                    f"started {t - started:.1f}s BEFORE the terminal decision"
                )
    g.check(
        "shadow isolation",
        not violations,
        violations[:3]
        or f"every shadow started after its instance's terminal decision ({sum(len(i['shadows']) for i in finished)} shadows)",
    )

    # -- 5. leakage --------------------------------------------------------
    view_fields = set(TrajectoryView.__dataclass_fields__)
    g.check(
        "controller view has no label field",
        not (view_fields & FORBIDDEN_VIEW_FIELDS),
        f"{len(view_fields)} fields, none in the forbidden set",
    )
    logged = {k for i in inst for r in i["records"] for k in r.payload()}
    g.check(
        "decision log has no label field",
        not (logged & FORBIDDEN_VIEW_FIELDS),
        f"logged keys: {sorted(logged - {'observed_run_ids'})[:6]}...",
    )

    # -- 6. stopping behaviour --------------------------------------------
    depths = [i["depth"] for i in finished]
    dist = {k: depths.count(k) for k in range(1, max_k + 1)}
    g.check("never stops at K=1", dist.get(1, 0) == 0, f"depth distribution {dist}")
    if args.smoke:
        g.check(
            "stopping is exercised",
            dist.get(2, 0) >= 1 and (dist.get(3, 0) + dist.get(4, 0)) >= 1,
            f"at least one early stop and one continuation: {dist}",
            fatal=False,
        )

    # -- 7. failure override ----------------------------------------------
    fo = []
    for i in finished:
        for r in i["records"]:
            if "failure override" in r.reason and r.action != CONTINUE:
                fo.append(f"{i['task_name']}/i{i['task_instance_id']:04d} step {r.step}")
    g.check("failure override always continues", not fo, fo[:3] or "no failure was ever accepted")

    # -- 8. cost accounting ------------------------------------------------
    bad_cost = [
        f"{i['task_name']}/i{i['task_instance_id']:04d}: {len(i['consumed'])}+{len(i['shadows'])}"
        for i in finished
        if len(i["consumed"]) + len(i["shadows"]) != max_k or len(i["consumed"]) != i["depth"]
    ]
    g.check(
        "consumed + shadow == K",
        not bad_cost,
        bad_cost[:3] or f"every finished instance has exactly {max_k} trajectories, consumed == depth",
    )

    # -- 9. failure rate (§11 halt condition) ------------------------------
    # Bug fixed 2026-08-10: this used to require an EXACT match against
    # "budget_terminated", but the runner records the fuller
    # "budget_terminated_consecutive_runaway" (see budget.py / D-17 lineage),
    # so the check silently matched nothing and reported 0% on the full
    # phase2b run when the true rate was 93/600 = 15.5% - a halt condition that
    # tripped and went unnoticed until the offline analysis. Caught because the
    # smoke test had 0/24 failures and never exercised this path. Reports the
    # incident: reports/phase2_protocol.md DEV-4, DECISIONS.md D-26.
    all_meta = [s["meta"] for i in inst for s in i["consumed"] + i["shadows"]]
    n = len(all_meta)
    overflow = sum(
        1
        for m in all_meta
        if str(m.get("failure_class") or "").startswith(("model_context_overflow", "budget_terminated"))
    )
    g.check(
        "residual failure rate",
        n == 0 or overflow / n <= MAX_OVERFLOW_FRACTION,
        f"{overflow}/{n} = {(overflow / n if n else 0):.1%} overflow/degeneration (halt above {MAX_OVERFLOW_FRACTION:.0%})",
    )

    # -- summary -----------------------------------------------------------
    print("Per-instance:")
    for i in inst:
        print(
            f"  {i['task_name']}/i{i['task_instance_id']:04d}  depth={i['depth']} "
            f"action={i['action']} consumed={len(i['consumed'])} shadows={len(i['shadows'])} chain={'ok' if i['chain_ok'] else 'BROKEN'}"
        )
    print()
    if finished:
        print(
            f"mean depth {sum(depths) / len(depths):.2f}  actions {pd.Series([i['action'] for i in finished]).value_counts().to_dict()}\n"
        )

    rc = g.report()
    out = cfg.output_dir / "phase2b_gates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"experiment": cfg.experiment_id, "gates": g.rows}, indent=2))
    print(f"\nwrote {out}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
