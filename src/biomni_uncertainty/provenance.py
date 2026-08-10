"""Provenance and environment capture.

Distinguishes a *requested* seed from *confirmed* deterministic behaviour: we
never claim reproducibility the stack does not provide.

## The D-29 process gap this module closes

Phase 2B ran from an uncommitted tree (`project_git.dirty = True` on all 600
runs) and its controller was never committed, so no commit could later be
cited as the execution commit (`reports/phase2b_provenance.md`). Two things
close that gap going forward: :func:`assert_clean_tree`, which every launch
entrypoint calls *before* any trajectory starts, and :func:`source_hashes`,
recorded into every trajectory's `metadata.json` so a future audit is one
equality check instead of the forensic reconstruction D-29 had to do.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

SECRET_ENV_HINT = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


class DirtyTreeError(RuntimeError):
    """Raised when a launch entrypoint refuses to start from an uncommitted tree."""


def _run(cmd: list[str], timeout: int = 30) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def git_info(repo: str | Path | None) -> dict:
    """Commit, dirty flag and describe for a git working tree."""
    info: dict[str, Any] = {"path": str(repo) if repo else None, "commit": None, "dirty": None, "branch": None}
    if not repo or not Path(repo).exists():
        return info
    repo = str(repo)
    commit = _run(["git", "-C", repo, "rev-parse", "HEAD"])
    if commit is None:
        return info
    info["commit"] = commit
    info["branch"] = _run(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"])
    status = _run(["git", "-C", repo, "status", "--porcelain"])
    info["dirty"] = bool(status)
    return info


def assert_clean_tree(repo: str | Path, *, allow_dirty: bool = False, log_path: str | Path | None = None) -> dict:
    """Refuse to proceed if ``repo`` has uncommitted changes.

    Every launch entrypoint calls this before generating a single trajectory.
    Raises :class:`DirtyTreeError` (callers turn that into a non-zero exit) unless
    ``allow_dirty`` is explicitly set, in which case the caller gets the info
    dict back but a prominent warning is written to stderr and, if given, to
    ``log_path`` and returned in the dict under ``"warning"`` so it lands in
    `metadata.json` rather than only scrolling past in a terminal.
    """
    info = git_info(repo)
    if not info["dirty"]:
        return info
    warning = (
        f"DIRTY TREE at launch: {repo} has uncommitted changes (commit {info['commit']}). "
        "Per D-29, a prospective run's execution commit must be reconstructable from git "
        "history. Commit before launching, or pass --allow-dirty to override with a logged "
        "warning (never for a confirmatory prospective run)."
    )
    if allow_dirty:
        print(f"WARNING: {warning}", file=sys.stderr)
        if log_path:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"WARNING: {warning}\n")
        info["warning"] = warning
        return info
    raise DirtyTreeError(warning)


def source_hashes(
    root: str | Path, *, globs: tuple[str, ...] = ("src/biomni_uncertainty/*.py", "scripts/*.py")
) -> dict:
    """SHA-256 of every file matched by ``globs`` under ``root``, keyed by relative path.

    Recorded into every trajectory's `metadata.json` under `source_hashes` so a
    future D-29-style audit is one equality check against the current tree
    instead of the file-by-file forensic reconstruction that D-29 required.
    Deliberately covers `scripts/*.py` (every driver, not just the one that
    happened to launch this trajectory) rather than trying to identify which
    entrypoint was used from inside a subprocess that does not reliably know.
    """
    root = Path(root)
    out: dict[str, str] = {}
    for pattern in globs:
        for p in sorted(root.glob(pattern)):
            if not p.is_file():
                continue
            h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            out[str(p.relative_to(root))] = h
    return out


def gpu_info() -> dict:
    """GPU model/memory and the CUDA_VISIBLE_DEVICES assignment for this process."""
    info: dict[str, Any] = {
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "devices": [],
        "driver_version": None,
        "cuda_version": None,
    }
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.used,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if out:
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                info["devices"].append(
                    {
                        "index": int(parts[0]),
                        "name": parts[1],
                        "memory_total_mib": int(parts[2]),
                        "memory_used_mib": int(parts[3]),
                    }
                )
                info["driver_version"] = parts[4]
    smi = _run(["nvidia-smi"])
    if smi:
        import re

        m = re.search(r"CUDA Version:\s*([0-9.]+)", smi)
        if m:
            info["cuda_version"] = m.group(1)
    return info


def slurm_info() -> dict:
    keys = (
        "SLURM_JOB_ID",
        "SLURM_JOBID",
        "SLURM_ARRAY_JOB_ID",
        "SLURM_ARRAY_TASK_ID",
        "SLURM_JOB_PARTITION",
        "SLURM_JOB_NUM_NODES",
        "SLURM_NODELIST",
        "SLURM_PROCID",
        "SLURMD_NODENAME",
    )
    return {k: os.environ.get(k) for k in keys if os.environ.get(k) is not None}


def package_versions(
    names: tuple[str, ...] = (
        "biomni",
        "langchain",
        "langchain_openai",
        "langgraph",
        "openai",
        "pandas",
        "numpy",
        "sglang",
        "torch",
        "transformers",
    ),
) -> dict:
    from importlib import metadata

    out: dict[str, str | None] = {}
    for n in names:
        try:
            out[n] = metadata.version(n.replace("_", "-"))
        except metadata.PackageNotFoundError:
            try:
                out[n] = metadata.version(n)
            except metadata.PackageNotFoundError:
                out[n] = None
    return out


def pip_freeze() -> list[str]:
    out = _run([sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"], timeout=180)
    return out.splitlines() if out else []


def cli_tool_versions(
    tools: tuple[str, ...] = (
        "python",
        "R",
        "Rscript",
        "samtools",
        "bcftools",
        "bedtools",
        "blastn",
        "muscle",
        "plink",
        "gcc",
    ),
) -> dict:
    """Presence/version of the system bioinformatics tools Biomni code may shell out to."""
    out: dict[str, str | None] = {}
    for t in tools:
        which = _run(["bash", "-lc", f"command -v {t}"])
        if not which:
            out[t] = None
            continue
        ver = _run(["bash", "-lc", f"{t} --version 2>&1 | head -1"]) or "present"
        out[t] = f"{which} | {ver}"
    return out


def environment_manifest(
    *,
    project_repo: str | Path | None = None,
    biomni_repo: str | Path | None = None,
    include_pip_freeze: bool = True,
    include_cli_tools: bool = True,
) -> dict:
    """Full environment manifest for reports/phase0_environment.md and each experiment."""
    man: dict[str, Any] = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
        "virtual_env": os.environ.get("VIRTUAL_ENV"),
        "packages": package_versions(),
        "gpu": gpu_info(),
        "slurm": slurm_info(),
        "project_git": git_info(project_repo),
        "biomni_git": git_info(biomni_repo),
    }
    if include_pip_freeze:
        man["pip_freeze"] = pip_freeze()
    if include_cli_tools:
        man["cli_tools"] = cli_tool_versions()
    return man


def redacted_env_names() -> list[str]:
    """Names (never values) of environment variables that look secret-bearing."""
    return sorted(k for k in os.environ if any(h in k.upper() for h in SECRET_ENV_HINT))


def write_json_atomic(path: str | Path, obj: Any) -> Path:
    """Write JSON via a temp file + rename so readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, default=str, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path
