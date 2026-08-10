#!/usr/bin/env python
"""Phase 2B - drive the online reliability controller over the held-out sample.

Unlike Phase 1, trajectories for one instance are **not** independent: the
controller decides after each one whether to buy another. So this driver
sequences *within* an instance and parallelises *across* instances.

Per instance:

    trajectory 1 -> decide+commit -> [trajectory 2 -> decide+commit -> ...]
    -> terminal decision committed -> remaining trajectories run as SHADOWS

Shadows are evaluation-only. They exist so fixed-K and oracle baselines pair on
the same instances, and they are generated **strictly after** the terminal
decision is durable on disk, so they cannot have influenced it (D-23). Shadows
live under their own `shadow/` condition subtree, which keeps them in a separate
tree while leaving `collect_run_records` unchanged.

Resumption is the decision log. Every committed decision is authoritative and is
re-used, never recomputed, so a run killed by a Slurm timeout resumes exactly
where it stopped rather than diverging. Use `--reserve-minutes` so the driver
stops *starting* new trajectories before the allocation ends and leaves clean
state behind.

    python scripts/phase2b_run.py \
        --config configs/phase2b.yaml \
        --manifest manifests/phase2b.jsonl \
        --endpoints <endpoints.json> \
        --reserve-minutes 25
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biomni_uncertainty.aggregation import collect_run_records  # noqa: E402
from biomni_uncertainty.benchmark import ManifestEntry  # noqa: E402
from biomni_uncertainty.config import Config, load_config  # noqa: E402
from biomni_uncertainty.controller import (  # noqa: E402
    ABSTAIN,
    ACCEPT,
    CONDITION_CONSUMED,
    CONDITION_SHADOW,
    CONTINUE,
    DECISION_LOG_NAME,
    DecisionLog,
    build_controller,
    decide_step,
)
from biomni_uncertainty.dispatcher import (  # noqa: E402
    _run_one_subprocess,
    check_endpoints,
    load_endpoints,
)
from biomni_uncertainty.policy import view_from_row  # noqa: E402
from biomni_uncertainty.provenance import write_json_atomic  # noqa: E402
from biomni_uncertainty.sampling import RunSpec, is_valid_complete, make_run_id, run_dir_for  # noqa: E402


class Deadline:
    """Wall-clock guard so an allocation boundary leaves resumable state.

    The driver refuses to *start* a trajectory it does not expect to finish. A
    trajectory killed mid-flight is recoverable (it re-runs on resume), but not
    starting it is cheaper and leaves the run directory clean.
    """

    def __init__(self, stop_at: float | None, per_run_seconds: int):
        self.stop_at = stop_at
        self.per_run_seconds = per_run_seconds
        self.tripped = threading.Event()

    def may_start(self) -> bool:
        if self.stop_at is None:
            return True
        if time.time() + self.per_run_seconds > self.stop_at:
            self.tripped.set()
            return False
        return True

    @property
    def remaining_h(self) -> float:
        return float("inf") if self.stop_at is None else (self.stop_at - time.time()) / 3600.0


def spec_for(cfg: Config, entry: ManifestEntry, idx: int, condition: str) -> RunSpec:
    """One trajectory's spec. Seeds differ per index so a seed-honouring endpoint
    yields independent samples; the condition only decides where it is written."""
    base = {
        "task_name": entry.task_name,
        "task_instance_id": entry.task_instance_id,
        "condition": condition,
        "trajectory_index": idx,
    }
    seed = cfg.trajectories.seed_base + 100 + idx if cfg.model.request_seed_enabled else None
    return RunSpec(
        experiment_id=cfg.experiment_id,
        run_id=make_run_id(cfg.experiment_id, entry.task_name, entry.task_instance_id, condition, idx),
        condition=condition,
        task_name=entry.task_name,
        global_instance_id=entry.global_instance_id,
        task_instance_id=entry.task_instance_id,
        trajectory_index=idx,
        prompt=entry.prompt,
        prompt_hash=entry.prompt_hash,
        split=entry.split,
        requested_seed=seed,
        confidence_mode=cfg.confidence.mode,
        model=cfg.model.identifier,
        model_revision=cfg.model.revision,
        temperature=cfg.model.temperature,
        max_tokens=cfg.model.max_tokens,
        timeout_seconds=cfg.execution.run_timeout_seconds,
        run_dir=str(run_dir_for(cfg, base)),
    )


def ensure_trajectory(spec: RunSpec, endpoint, config_path: str, cfg: Config, deadline: Deadline, python: str | None):
    """Run one trajectory unless it is already validly complete.

    Returns ``"reused"``, ``"ran"``, or ``"deadline"``. Infrastructure failures
    are retried per the config; agent-side outcomes are never retried, because
    they are exactly what the controller's failure override exists to observe.
    """
    if is_valid_complete(spec.run_dir):
        return "reused"
    if not deadline.may_start():
        return "deadline"

    retryable = tuple(cfg.execution.retry_policy.retryable_failure_classes)
    for attempt in range(1, cfg.execution.retry_policy.max_attempts + 1):
        res = _run_one_subprocess(
            spec,
            endpoint,
            config_path,
            timeout=cfg.execution.run_timeout_seconds + 300,
            python=python,
        )
        if res.failure_class in retryable and attempt < cfg.execution.retry_policy.max_attempts:
            time.sleep(cfg.execution.retry_policy.backoff_seconds)
            continue
        break
    return "ran"


def views_for(specs: list[RunSpec]) -> list:
    """Build the controller's view of the trajectories observed so far.

    Goes through `collect_run_records`, which is the same parsing the analysis
    uses and which reads **no ground truth** - rewards are attached later, by a
    separate step the controller never touches.
    """
    df = collect_run_records(specs)
    df = df.set_index("run_id").loc[[s.run_id for s in specs]].reset_index()
    return [view_from_row(row, position=i + 1) for i, row in enumerate(df.to_dict("records"))]


def drive_instance(
    entry: ManifestEntry, cfg: Config, config_path: str, endpoint, deadline: Deadline, python: str | None
) -> dict:
    """Sequence one instance: generate, decide, commit, repeat; then shadows."""
    controller = build_controller(cfg.controller)
    max_k = cfg.controller.max_trajectories
    inst_dir = cfg.runs_dir / entry.task_name / f"i{entry.task_instance_id:04d}"
    log = DecisionLog(inst_dir / DECISION_LOG_NAME)

    consumed: list[RunSpec] = []
    depth = 0
    action = None
    for k in range(1, max_k + 1):
        spec = spec_for(cfg, entry, k - 1, CONDITION_CONSUMED)
        state = ensure_trajectory(spec, endpoint, config_path, cfg, deadline, python)
        if state == "deadline":
            return {
                "task_name": entry.task_name,
                "task_instance_id": entry.task_instance_id,
                "status": "deadline",
                "depth": depth,
            }
        consumed.append(spec)
        depth = k

        decision, _record, reused = decide_step(
            controller,
            log,
            task_name=entry.task_name,
            task_instance_id=entry.task_instance_id,
            views=views_for(consumed),
            max_k=max_k,
        )
        action = decision.action
        if action != CONTINUE:
            break

    # Only now, with the terminal decision durable on disk, may the shadows run.
    shadows_ran = 0
    if cfg.controller.generate_shadows:
        for idx in range(depth, max_k):
            spec = spec_for(cfg, entry, idx, CONDITION_SHADOW)
            state = ensure_trajectory(spec, endpoint, config_path, cfg, deadline, python)
            if state == "deadline":
                return {
                    "task_name": entry.task_name,
                    "task_instance_id": entry.task_instance_id,
                    "status": "deadline_in_shadows",
                    "depth": depth,
                    "action": action,
                    "shadows_ran": shadows_ran,
                }
            shadows_ran += 1

    ok, why = log.verify()
    return {
        "task_name": entry.task_name,
        "task_instance_id": entry.task_instance_id,
        "status": "done",
        "depth": depth,
        "action": action,
        "shadows_ran": shadows_ran,
        "chain_ok": ok,
        "chain_reason": why,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--endpoints", required=True, type=Path)
    ap.add_argument("--python", default=None, help="interpreter for the agent subprocess")
    ap.add_argument("--limit", type=int, default=None, help="cap instances (smoke test)")
    ap.add_argument(
        "--reserve-minutes",
        type=float,
        default=0.0,
        help="stop starting trajectories this long before SLURM_JOB_END_TIME",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="override the D-29 clean-tree guard; logs a prominent warning into metadata.json "
        "instead of refusing to start. Never use for a confirmatory prospective run.",
    )
    args = ap.parse_args()

    from biomni_uncertainty.provenance import DirtyTreeError, assert_clean_tree

    project_repo = Path(__file__).resolve().parents[1]
    try:
        assert_clean_tree(project_repo, allow_dirty=args.allow_dirty)
    except DirtyTreeError as exc:
        raise SystemExit(f"REFUSING TO LAUNCH: {exc}") from exc

    cfg = load_config(args.config)
    if not cfg.controller.enabled:
        raise SystemExit("controller.enabled is false; refusing to run a prospective experiment without a controller")

    entries = [ManifestEntry(**json.loads(line)) for line in args.manifest.read_text().splitlines() if line.strip()]
    if args.limit:
        entries = entries[: args.limit]

    endpoints = check_endpoints(load_endpoints(args.endpoints), cfg.model.identifier)
    healthy = [e for e in endpoints if e.healthy]
    if not healthy:
        raise SystemExit("no healthy endpoint; refusing to start")

    stop_at = None
    if args.reserve_minutes > 0:
        import os

        end = os.environ.get("SLURM_JOB_END_TIME")
        if end:
            stop_at = float(end) - args.reserve_minutes * 60
    deadline = Deadline(stop_at, cfg.execution.run_timeout_seconds)

    print(f"[phase2b] instances={len(entries)} endpoints={[e.url for e in healthy]}", flush=True)
    print(f"[phase2b] controller={cfg.controller.model_dump()}", flush=True)
    if stop_at:
        print(
            f"[phase2b] deadline in {deadline.remaining_h:.2f} h (reserving {args.reserve_minutes:.0f} min)", flush=True
        )
    if args.dry_run:
        print("[phase2b] --dry-run: nothing executed")
        return 0

    cfg.runs_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    lock = threading.Lock()
    sem = threading.Semaphore(max(1, cfg.execution.max_concurrency))
    started = time.time()

    def work(entry: ManifestEntry) -> None:
        with sem:
            ep = healthy[hash((entry.task_name, entry.task_instance_id)) % len(healthy)]
            try:
                r = drive_instance(entry, cfg, str(args.config), ep, deadline, args.python)
            except Exception as exc:  # keep one bad instance from killing the run
                r = {
                    "task_name": entry.task_name,
                    "task_instance_id": entry.task_instance_id,
                    "status": "error",
                    "error": repr(exc),
                }
            with lock:
                results.append(r)
                n = len(results)
            el = time.time() - started
            print(
                f"[phase2b] {n}/{len(entries)} {r['task_name']}/i{r['task_instance_id']:04d} "
                f"{r['status']} depth={r.get('depth')} action={r.get('action')} "
                f"| {el / 60:.1f} min elapsed",
                flush=True,
            )

    threads = []
    for e in entries:
        if deadline.tripped.is_set():
            break
        t = threading.Thread(target=work, args=(e,), daemon=True)
        t.start()
        threads.append(t)
        while sum(1 for x in threads if x.is_alive()) >= max(1, cfg.execution.max_concurrency) * 2:
            time.sleep(0.5)
    for t in threads:
        t.join()

    done = [r for r in results if r["status"] == "done"]
    summary = {
        "experiment": cfg.experiment_id,
        "instances_planned": len(entries),
        "instances_done": len(done),
        "instances_stopped_at_deadline": sum(1 for r in results if str(r["status"]).startswith("deadline")),
        "instances_errored": sum(1 for r in results if r["status"] == "error"),
        "elapsed_seconds": round(time.time() - started, 1),
        "deadline_tripped": deadline.tripped.is_set(),
        "mean_depth": round(sum(r["depth"] for r in done) / len(done), 3) if done else None,
        "action_counts": {a: sum(1 for r in done if r.get("action") == a) for a in (ACCEPT, ABSTAIN, CONTINUE)},
        "depth_counts": {k: sum(1 for r in done if r["depth"] == k) for k in (1, 2, 3, 4)},
        "chain_failures": [r for r in done if not r.get("chain_ok", True)],
        "endpoints": [e.url for e in healthy],
    }
    write_json_atomic(cfg.output_dir / "phase2b_run_summary.json", summary)
    write_json_atomic(cfg.output_dir / "phase2b_instance_results.json", results)
    print("[phase2b] " + json.dumps(summary), flush=True)
    if summary["deadline_tripped"]:
        print(
            "[phase2b] DEADLINE REACHED - state is clean and resumable; re-run the same command to continue.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
