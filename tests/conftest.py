from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def base_config_dict(tmp_path) -> dict:
    return {
        "experiment": {"name": "test", "seed": 1, "output_root": str(tmp_path / "runs")},
        "benchmark": {
            "target_total_instances": 4,
            "per_task_target": 2,
            "manifest_seed": 20260731,
            "preferred_split": "val",
        },
        "trajectories": {"instrumented_k": 3, "standard_k": 1, "seed_base": 1000},
        "execution": {"data_path": str(tmp_path / "data")},
    }


@pytest.fixture
def cfg(base_config_dict):
    from biomni_uncertainty.config import Config

    return Config.model_validate(base_config_dict)
