"""Assign pending trajectories to healthy model replicas and run them.

Each trajectory runs in its own subprocess (``cli run-one``) because Biomni's
Python REPL uses a module-global namespace. Concurrency is bounded per endpoint,
so by default exactly one active agent trajectory occupies each replica.

Trajectories are not purely model-bound - they also wait on code execution, file
I/O and external biomedical databases - so ``max_concurrency`` may exceed the
number of replicas. That is a configuration choice, not an assumption baked in.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from biomni_uncertainty.config import Config
from biomni_uncertainty.runner import probe_endpoint
from biomni_uncertainty.sampling import FAILED_MARKER, RunSpec, pending_specs


@dataclass
class Endpoint:
    url: str
    label: str
    max_concurrent: int = 1
    healthy: bool = True
    seed_supported: bool | None = None
    served_models: list[str] = field(default_factory=list)


def load_endpoints(path: str | Path) -> list[Endpoint]:
    """Read the endpoints.json written by the node launchers."""
    data = json.loads(Path(path).read_text())
    raw = data["endpoints"] if isinstance(data, dict) and "endpoints" in data else data
    out = []
    for i, e in enumerate(raw):
        if isinstance(e, str):
            out.append(Endpoint(url=e, label=f"replica{i}"))
        else:
            out.append(
                Endpoint(
                    url=e["url"],
                    label=e.get("label", f"replica{i}"),
                    max_concurrent=int(e.get("max_concurrent", 1)),
                )
            )
    return out


def check_endpoints(endpoints: list[Endpoint], model: str, timeout: int = 30) -> list[Endpoint]:
    """Probe every endpoint; mark unhealthy ones and record seed support."""
    for ep in endpoints:
        chk = probe_endpoint(ep.url, model, timeout=timeout)
        ep.healthy = chk.reachable
        ep.seed_supported = chk.seed_supported
        ep.served_models = chk.served_models
    return endpoints


@dataclass
class DispatchResult:
    run_id: str
    returncode: int
    duration_seconds: float
    endpoint: str
    attempt: int
    failure_class: str | None = None


def _read_failure_class(run_dir: str) -> str | None:
    p = Path(run_dir) / FAILED_MARKER
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("failure_class")
    except (OSError, json.JSONDecodeError):
        return None


def _run_one_subprocess(
    spec: RunSpec,
    endpoint: Endpoint,
    config_path: str,
    *,
    timeout: int,
    env_extra: dict[str, str] | None = None,
    python: str | None = None,
) -> DispatchResult:
    run_dir = Path(spec.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_path = run_dir / "run_spec.json"
    spec_path.write_text(json.dumps(spec.to_dict(), indent=2, sort_keys=True))

    cmd = [
        python or sys.executable,
        "-m",
        "biomni_uncertainty.cli",
        "run-one",
        "--run-spec",
        str(spec_path),
        "--endpoint",
        endpoint.url,
        "--config",
        config_path,
    ]
    env = dict(os.environ)
    env.update(env_extra or {})
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, env=env, timeout=timeout, capture_output=True, text=True)
        rc = proc.returncode
        if rc != 0:
            (run_dir / "dispatch_stderr.log").write_text((proc.stderr or "")[-20000:], encoding="utf-8")
    except subprocess.TimeoutExpired:
        rc = 124
        (run_dir / "dispatch_stderr.log").write_text(
            f"Subprocess exceeded the dispatcher wall-clock timeout of {timeout}s and was killed.",
            encoding="utf-8",
        )
        # The child never got to write a marker; record one so the failure is preserved.
        from biomni_uncertainty.sampling import write_marker

        write_marker(
            run_dir,
            FAILED_MARKER,
            {
                "run_id": spec.run_id,
                "completed": False,
                "failure_class": "model_timeout",
                "note": "killed by dispatcher wall-clock timeout",
            },
        )
    dt = time.perf_counter() - t0
    return DispatchResult(spec.run_id, rc, dt, endpoint.url, attempt=1, failure_class=_read_failure_class(str(run_dir)))


def dispatch(
    specs: list[RunSpec],
    endpoints: list[Endpoint],
    cfg: Config,
    config_path: str,
    *,
    resume: bool = True,
    progress_every: int = 1,
    env_extra: dict[str, str] | None = None,
    python: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run every pending trajectory across the healthy endpoints."""
    healthy = [e for e in endpoints if e.healthy]
    if not healthy:
        raise RuntimeError("No healthy endpoints. Refusing to start the dispatcher.")

    retryable = tuple(cfg.execution.retry_policy.retryable_failure_classes)
    todo = pending_specs(specs, retry_failed_classes=retryable) if resume else list(specs)
    skipped = len(specs) - len(todo)

    print(f"[dispatch] planned={len(specs)} pending={len(todo)} skipped(complete/non-retryable)={skipped}", flush=True)
    print(f"[dispatch] endpoints={[e.url for e in healthy]}", flush=True)
    if dry_run:
        return {
            "dry_run": True,
            "planned": len(specs),
            "pending": len(todo),
            "skipped": skipped,
            "endpoints": [e.url for e in healthy],
        }

    # One slot per allowed concurrent trajectory on each replica, capped globally.
    slots: queue.Queue[Endpoint] = queue.Queue()
    for ep in healthy:
        for _ in range(max(1, ep.max_concurrent)):
            slots.put(ep)
    global_sem = threading.Semaphore(max(1, cfg.execution.max_concurrency))

    results: list[DispatchResult] = []
    lock = threading.Lock()
    counter = {"done": 0}
    started = time.time()
    attempts: dict[str, int] = {}

    def work(spec: RunSpec) -> None:
        with global_sem:
            ep = slots.get()
            try:
                attempt = attempts.get(spec.run_id, 0) + 1
                attempts[spec.run_id] = attempt
                res = _run_one_subprocess(
                    spec,
                    ep,
                    config_path,
                    timeout=cfg.execution.run_timeout_seconds + 300,
                    env_extra=env_extra,
                    python=python,
                )
                res = DispatchResult(
                    res.run_id, res.returncode, res.duration_seconds, res.endpoint, attempt, res.failure_class
                )
                # Retry only clearly transient infrastructure failures, and never
                # hide the original failure: both attempts are recorded.
                if res.failure_class in retryable and attempt < cfg.execution.retry_policy.max_attempts:
                    with lock:
                        results.append(res)
                    time.sleep(cfg.execution.retry_policy.backoff_seconds)
                    slots.put(ep)
                    return work(spec)
            finally:
                try:
                    slots.put_nowait(ep)
                except queue.Full:  # pragma: no cover - queue is unbounded
                    pass
            with lock:
                results.append(res)
                counter["done"] += 1
                done = counter["done"]
            if done % progress_every == 0:
                elapsed = time.time() - started
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (len(todo) - done) / rate if rate > 0 else float("nan")
                print(
                    f"[dispatch] {done}/{len(todo)} done | rc={res.returncode} "
                    f"fail={res.failure_class or '-'} | {res.duration_seconds:.0f}s | "
                    f"eta≈{remaining / 60:.1f} min",
                    flush=True,
                )

    threads = []
    for spec in todo:
        t = threading.Thread(target=work, args=(spec,), daemon=True)
        t.start()
        threads.append(t)
        # Bound live threads so a large manifest does not spawn thousands at once.
        while sum(1 for x in threads if x.is_alive()) >= max(1, cfg.execution.max_concurrency) * 2:
            time.sleep(0.2)
    for t in threads:
        t.join()

    ok = sum(1 for r in results if r.returncode == 0)
    summary = {
        "planned": len(specs),
        "pending_at_start": len(todo),
        "skipped": skipped,
        "executed": len(results),
        "subprocess_ok": ok,
        "subprocess_failed": len(results) - ok,
        "elapsed_seconds": round(time.time() - started, 1),
        "failure_class_counts": _counts([r.failure_class for r in results]),
        "endpoints": [e.url for e in healthy],
    }
    print("[dispatch] " + json.dumps(summary), flush=True)
    return summary


def _counts(values: list[Any]) -> dict:
    out: dict[str, int] = {}
    for v in values:
        k = v or "none"
        out[k] = out.get(k, 0) + 1
    return out
