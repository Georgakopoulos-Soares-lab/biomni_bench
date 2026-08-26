"""Non-invasive GenoMAS artifact-contract validation.

The pinned ``GenoMAS/eval.py`` (``evaluate_dataset_selection``) reads a
prediction ``cohort_info.json`` and calls ``.get(...)`` on every value under
the assumption that the file is a mapping from cohort id to a metadata dict
(the exact shape ``tools/preprocess.py::validate_and_save_cohort_info``
writes). This module checks only that shape before the native scorer runs;
it never scores an artifact and never mutates GenoMAS output. Correctness
still comes from the unchanged native evaluator.
"""
from __future__ import annotations

import json
import resource
from collections.abc import Callable
from pathlib import Path
from typing import Any


def normalize_condition_arg(value: str | None) -> str | None:
    """Map a CLI ``--condition`` value to the sentinel GenoMAS actually expects.

    ``environment.py``'s task loop does ``if condition`` (Python truthiness) to
    detect the unconditioned task, and ``eval.py`` does
    ``condition is None or condition.lower() in [..., 'none']``. A literal
    ``"None"`` string passed on a command line is truthy, so on the
    ``environment.py`` side it would be misread as a real condition (and, since
    it is not ``'Age'``/``'Gender'``, appended to the trait list as if it were a
    comorbidity to also process) instead of selecting the unconditioned task.
    """
    if value is None or value.strip().lower() == "none":
        return None
    return value


def memory_rlimit_preexec_fn(max_bytes: int) -> Callable[[], None]:
    """Build a ``subprocess.run(preexec_fn=...)`` capping the child's address space.

    A single GenoMAS trajectory has been observed to grow to >110 GiB resident
    within one long-running Python process (per-cohort clinical/genetic
    matrices accumulating across GEO/TCGA steps with no evidence of a Slurm or
    cgroup limit involved -- the node's own memory was genuinely exhausted;
    see reports/genomas_fresh_admission_ladder_20260826.md). Left unbounded,
    the kernel OOM killer's victim selection is global and indiscriminate: on
    a shared node it can just as easily pick the vLLM server as the runaway
    trajectory. This bounds only the child agent subprocess's own virtual
    address space (``RLIMIT_AS``) so a runaway trajectory hits its own clean,
    local `MemoryError`/allocation failure well before threatening anything
    else on the node. It never touches GenoMAS's own algorithm or code.
    """
    def _apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
    return _apply


def validate_cohort_info_contract(path: Path | str) -> dict[str, Any]:
    """Check that ``path`` is a cohort-id -> metadata-dict mapping.

    Returns ``{"artifact_contract_valid": bool, "artifact_contract_error": str | None}``.
    """
    path = Path(path)
    if not path.is_file():
        return {"artifact_contract_valid": False, "artifact_contract_error": f"missing prediction artifact: {path}"}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"artifact_contract_valid": False, "artifact_contract_error": f"unreadable prediction artifact: {exc}"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"artifact_contract_valid": False, "artifact_contract_error": f"invalid JSON: {exc}"}
    if not isinstance(data, dict):
        return {"artifact_contract_valid": False,
                "artifact_contract_error": f"expected a cohort-id -> metadata mapping, got {type(data).__name__} result"}
    for cohort_id, value in data.items():
        if not isinstance(value, dict):
            return {"artifact_contract_valid": False,
                    "artifact_contract_error": f"expected cohort mapping, got scalar/string result for key '{cohort_id}'"}
    return {"artifact_contract_valid": True, "artifact_contract_error": None}
