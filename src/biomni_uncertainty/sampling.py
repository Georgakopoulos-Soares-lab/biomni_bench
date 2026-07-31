"""Expansion of a benchmark manifest into concrete run specifications.

Conditions:

* ``standard``     - Condition A. One unmodified Biomni trajectory per instance.
* ``instrumented`` - Condition B. K trajectories per instance with the final
  confidence request added. Same model, temperature, tools and limits.

Run IDs are deterministic: re-expanding the same manifest with the same config
yields byte-identical run specs, which is what makes resumption safe.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from biomni_uncertainty.benchmark import ManifestEntry
from biomni_uncertainty.config import Config

CONDITION_STANDARD = "standard"
CONDITION_INSTRUMENTED = "instrumented"


@dataclass(frozen=True)
class RunSpec:
    """Everything needed to execute exactly one trajectory."""

    experiment_id: str
    run_id: str
    condition: str
    task_name: str
    global_instance_id: int
    task_instance_id: int
    trajectory_index: int
    prompt: str
    prompt_hash: str
    split: str
    requested_seed: int | None
    confidence_mode: str
    model: str
    model_revision: str | None
    temperature: float
    max_tokens: int
    timeout_seconds: int
    run_dir: str

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> RunSpec:
        return RunSpec(**d)


def make_run_id(
    experiment_id: str,
    task_name: str,
    task_instance_id: int,
    condition: str,
    trajectory_index: int,
) -> str:
    """Stable, collision-resistant, human-readable run identifier."""
    key = f"{experiment_id}|{task_name}|{task_instance_id}|{condition}|{trajectory_index}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"{task_name}-i{task_instance_id:04d}-{condition[:4]}-t{trajectory_index}-{digest}"


def run_dir_for(cfg: Config, spec_like: dict) -> Path:
    return (
        cfg.runs_dir
        / spec_like["task_name"]
        / f"i{int(spec_like['task_instance_id']):04d}"
        / spec_like["condition"]
        / f"t{int(spec_like['trajectory_index'])}"
    )


def expand_runs(entries: list[ManifestEntry], cfg: Config) -> list[RunSpec]:
    """Expand a manifest into the full list of trajectories to execute."""
    specs: list[RunSpec] = []
    for e in entries:
        plan = [(CONDITION_STANDARD, i, "none") for i in range(cfg.trajectories.standard_k)] + [
            (CONDITION_INSTRUMENTED, i, cfg.confidence.mode) for i in range(cfg.trajectories.instrumented_k)
        ]
        for condition, idx, conf_mode in plan:
            run_id = make_run_id(cfg.experiment_id, e.task_name, e.task_instance_id, condition, idx)
            base = {
                "task_name": e.task_name,
                "task_instance_id": e.task_instance_id,
                "condition": condition,
                "trajectory_index": idx,
            }
            # Requested seeds are distinct per (condition, trajectory) so that a
            # seed-honouring endpoint yields independent samples. Whether the
            # endpoint actually honours them is verified at run time and stored
            # separately as `seed_supported`.
            seed = (
                cfg.trajectories.seed_base + (0 if condition == CONDITION_STANDARD else 100) + idx
                if cfg.model.request_seed_enabled
                else None
            )
            specs.append(
                RunSpec(
                    experiment_id=cfg.experiment_id,
                    run_id=run_id,
                    condition=condition,
                    task_name=e.task_name,
                    global_instance_id=e.global_instance_id,
                    task_instance_id=e.task_instance_id,
                    trajectory_index=idx,
                    prompt=e.prompt,
                    prompt_hash=e.prompt_hash,
                    split=e.split,
                    requested_seed=seed,
                    confidence_mode=conf_mode,
                    model=cfg.model.identifier,
                    model_revision=cfg.model.revision,
                    temperature=cfg.model.temperature,
                    max_tokens=cfg.model.max_tokens,
                    timeout_seconds=cfg.execution.run_timeout_seconds,
                    run_dir=str(run_dir_for(cfg, base)),
                )
            )
    specs.sort(key=lambda s: (s.task_name, s.task_instance_id, s.condition, s.trajectory_index))
    return specs


def write_run_manifest(specs: list[RunSpec], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for s in specs:
            fh.write(json.dumps(s.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return path


def read_run_manifest(path: str | Path) -> list[RunSpec]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(RunSpec.from_dict(json.loads(line)))
    return out


def run_manifest_hash(specs: list[RunSpec]) -> str:
    payload = sorted(json.dumps(s.to_dict(), sort_keys=True, separators=(",", ":")) for s in specs)
    return hashlib.sha256("\n".join(payload).encode()).hexdigest()


# --------------------------------------------------------------------------
# Completion markers / resumption
# --------------------------------------------------------------------------

COMPLETE_MARKER = "COMPLETE"
FAILED_MARKER = "FAILED"


def write_marker(run_dir: str | Path, name: str, payload: dict) -> Path:
    """Atomically write a completion marker (temp file + rename)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / name
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def run_status(run_dir: str | Path) -> str:
    """``complete`` | ``failed`` | ``pending``."""
    run_dir = Path(run_dir)
    if (run_dir / COMPLETE_MARKER).exists():
        return "complete"
    if (run_dir / FAILED_MARKER).exists():
        return "failed"
    return "pending"


def is_valid_complete(run_dir: str | Path) -> bool:
    """A COMPLETE marker is only trusted when its artifacts are actually present.

    Guards against a marker surviving an interrupted copy-back from node-local
    scratch, which would otherwise cause a run to be silently skipped.
    """
    run_dir = Path(run_dir)
    if not (run_dir / COMPLETE_MARKER).exists():
        return False
    required = ("metadata.json", "final_response.txt", "parsed_answer.json", "events.jsonl")
    if not all((run_dir / f).exists() for f in required):
        return False
    try:
        meta = json.loads((run_dir / "metadata.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return bool(meta.get("completed"))


def pending_specs(specs: list[RunSpec], *, retry_failed_classes: tuple[str, ...] = ()) -> list[RunSpec]:
    """Filter to runs that still need executing.

    Valid COMPLETE runs are skipped. FAILED runs are re-queued only when their
    recorded failure class is in ``retry_failed_classes`` - substantive agent
    failures are never silently retried.
    """
    out = []
    for s in specs:
        d = Path(s.run_dir)
        if is_valid_complete(d):
            continue
        if (d / FAILED_MARKER).exists():
            try:
                marker = json.loads((d / FAILED_MARKER).read_text())
            except (OSError, json.JSONDecodeError):
                marker = {}
            if marker.get("failure_class") not in retry_failed_classes:
                continue
        out.append(s)
    return out
