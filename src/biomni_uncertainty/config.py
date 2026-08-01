"""Validated experiment configuration.

All experiment constants live in YAML under configs/. Nothing here hardcodes a
cluster account, partition, allocation or filesystem path: those come from a
separate cluster config (configs/cluster.example.yaml) or the CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    """Recursively expand ``${VAR}`` / ``${VAR:-default}`` in strings."""
    if isinstance(value, str):

        def _sub(m: re.Match) -> str:
            var, default = m.group(1), m.group(2)
            got = os.environ.get(var)
            if got is None:
                if default is None:
                    raise KeyError(
                        f"Config references environment variable ${{{var}}} which is not set "
                        f"and has no default. Set it (see .env.example) or edit the config."
                    )
                return default
            return got

        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExperimentCfg(_Base):
    name: str
    seed: int
    output_root: str

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", v):
            raise ValueError("experiment.name must be a filesystem-safe slug")
        return v


class BenchmarkCfg(_Base):
    dataset: str = "biomni/Eval1"
    parquet_uri: str = "hf://datasets/biomni/Eval1/biomni_eval1_dataset.parquet"
    local_parquet: str | None = None
    target_total_instances: int = 50
    per_task_target: int = 5
    preferred_split: str | None = "val"
    manifest_seed: int = 20260731
    exclude_tasks: list[str] = Field(default_factory=list)
    max_prompt_chars: int | None = None


class ModelCfg(_Base):
    identifier: str = "biomni/Biomni-R0-32B-Preview"
    revision: str | None = None
    source: str = "Custom"
    temperature: float = 0.7
    max_tokens: int = 8192
    request_timeout_seconds: int = 1800
    context_length: int = 40960
    dtype: str = "bfloat16"
    json_model_override_args: str | None = None
    request_seed_enabled: bool = True


class ConfidenceCfg(_Base):
    mode: Literal["none", "final_only", "per_step"] = "final_only"
    open_delimiter: str = "<BIOMNI_CONFIDENCE>"
    close_delimiter: str = "</BIOMNI_CONFIDENCE>"
    epsilon: float = 1e-3


class TrajectoriesCfg(_Base):
    instrumented_k: int = 4
    standard_k: int = 1
    seed_base: int = 1000


class RetryPolicyCfg(_Base):
    max_attempts: int = 2
    retryable_failure_classes: list[str] = Field(
        default_factory=lambda: [
            "model_server_failure",
            "model_timeout",
            "external_resource_failure",
        ]
    )
    backoff_seconds: float = 20.0


class ExecutionCfg(_Base):
    max_concurrency: int = 4
    run_timeout_seconds: int = 3600
    tool_timeout_seconds: int = 600
    scratch_root: str = "/tmp/biomni_unc_scratch"
    data_path: str = "./biomni_data_root"
    use_tool_retriever: bool = True
    retry_policy: RetryPolicyCfg = Field(default_factory=RetryPolicyCfg)


class LoggingCfg(_Base):
    stdout_limit: int = 4000
    stderr_limit: int = 4000
    max_event_payload_chars: int = 20000
    redact_patterns: list[str] = Field(
        default_factory=lambda: [
            r"(?i)\b(sk-[A-Za-z0-9_\-]{16,})",
            r"(?i)\b(hf_[A-Za-z0-9]{20,})",
            r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([^\s\"',]{8,})",
            r"(?i)(authorization\"?\s*[:=]\s*\"?)(bearer\s+)?([^\s\"',]{8,})",
            r"(?i)(token\"?\s*[:=]\s*\"?)([^\s\"',]{12,})",
            r"(?i)(secret\"?\s*[:=]\s*\"?)([^\s\"',]{8,})",
            r"(?i)(password\"?\s*[:=]\s*\"?)([^\s\"',]{4,})",
        ]
    )


class TrajectoryBudgetCfg(_Base):
    """Guards against the degeneration trapdoor measured in Phase 1.

    Defaults are the Phase-1.5 repair values, chosen from
    ``reports/context_overflow_forensics.md``: a 32,768-token hard input budget
    disturbs 0 of the 188 completed pilot trajectories while catching 60 of 62
    failures, and truncating runaway generations keeps 62 of 62 under the
    request ceiling. ``enabled: false`` reproduces the original Phase-1 behaviour
    exactly, which is what the ablation's control arm uses.
    """

    enabled: bool = False
    # Input-token budget. Reactive rather than predictive: measured against the
    # endpoint's own reported usage, self-calibrated per run.
    soft_input_tokens: int = 24576
    hard_input_tokens: int = 32768
    # A generation stopping on `length` without a complete block is degenerate;
    # keep this much of it for context and replace the rest with a correction.
    runaway_keep_tokens: int = 512
    # Terminate in a controlled state after this many consecutive runaways.
    # 0 disables termination (truncation still applies).
    max_consecutive_runaway: int = 3
    # Model-visible cap on one tool observation. The full output is always kept
    # on disk and in the event log.
    max_observation_tokens: int = 4000
    # Caps on the tool retriever's selection size. `None` leaves it uncapped.
    retrieval_max_tools: int | None = 40
    retrieval_max_data_lake: int | None = 20
    retrieval_max_libraries: int | None = 20

    @field_validator("hard_input_tokens")
    @classmethod
    def _hard_above_soft(cls, v: int, info) -> int:  # noqa: ANN001
        soft = info.data.get("soft_input_tokens", 0)
        if v and soft and v <= soft:
            raise ValueError("trajectory_budget.hard_input_tokens must exceed soft_input_tokens")
        return v


class AnalysisCfg(_Base):
    bootstrap_replicates: int = 2000
    bootstrap_seed: int = 20260731
    calibration_bins: int = 5
    primary_length_field: str = "total_output_tokens"
    binary_reward_threshold: float = 0.5
    srlm_epsilon: float = 1e-3


class Config(_Base):
    experiment: ExperimentCfg
    benchmark: BenchmarkCfg = Field(default_factory=BenchmarkCfg)
    model: ModelCfg = Field(default_factory=ModelCfg)
    confidence: ConfidenceCfg = Field(default_factory=ConfidenceCfg)
    trajectories: TrajectoriesCfg = Field(default_factory=TrajectoriesCfg)
    execution: ExecutionCfg = Field(default_factory=ExecutionCfg)
    logging: LoggingCfg = Field(default_factory=LoggingCfg)
    trajectory_budget: TrajectoryBudgetCfg = Field(default_factory=TrajectoryBudgetCfg)
    analysis: AnalysisCfg = Field(default_factory=AnalysisCfg)

    # ---- derived paths -------------------------------------------------
    @property
    def experiment_id(self) -> str:
        return self.experiment.name

    @property
    def output_dir(self) -> Path:
        return Path(self.experiment.output_root) / self.experiment_id

    @property
    def runs_dir(self) -> Path:
        return self.output_dir / "runs"

    @property
    def results_dir(self) -> Path:
        return self.output_dir / "results"

    def snapshot(self) -> dict:
        """Plain-dict snapshot for provenance records."""
        return json.loads(self.model_dump_json())

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_config(path: str | Path, overrides: dict | None = None) -> Config:
    """Load and validate a YAML config, expanding ``${ENV}`` references."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    raw = expand_env(raw)
    if overrides:
        for dotted, value in overrides.items():
            node = raw
            *parents, leaf = dotted.split(".")
            for p in parents:
                node = node.setdefault(p, {})
            node[leaf] = value
    return Config.model_validate(raw)


def load_cluster_config(path: str | Path) -> dict:
    """Cluster config is intentionally a plain dict: it is site-specific and
    consumed by shell launchers, not by the scientific pipeline."""
    raw = yaml.safe_load(Path(path).read_text())
    return expand_env(raw or {})


def unresolved_placeholders(cluster_cfg: dict, prefix: str = "") -> list[str]:
    """Return dotted keys whose value still looks like an unfilled placeholder."""
    out: list[str] = []
    for k, v in cluster_cfg.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.extend(unresolved_placeholders(v, prefix=f"{key}."))
        elif isinstance(v, str) and (
            v.strip() == "" or v.startswith("<") or "CHANGE_ME" in v or "REPLACE" in v or v.strip() in {"TODO", "null"}
        ):
            out.append(key)
        elif v is None:
            out.append(key)
    return out
