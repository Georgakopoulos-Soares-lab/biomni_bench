"""Execute exactly one instrumented Biomni trajectory in an isolated directory.

Isolation contract (one process, one trajectory):

* ``biomni.tool.support_tools.run_python_repl`` execs into a module-global
  namespace, so two trajectories in one process would share variables. The
  dispatcher therefore runs each trajectory in its own subprocess and this
  module refuses to run twice in the same interpreter.
* The process ``cwd`` is moved into ``<run_dir>/artifacts`` so any file the
  agent writes lands inside its own run directory.
* The Biomni data lake is shared and treated as read-only.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from biomni_uncertainty.canonicalization import parse_final_response
from biomni_uncertainty.confidence import confidence_instruction
from biomni_uncertainty.config import Config
from biomni_uncertainty.events import EventLogger, Redactor
from biomni_uncertainty.instrumentation import AgentInstrumentation, TrajectoryStats, analyze_messages
from biomni_uncertainty.provenance import git_info, gpu_info, slurm_info, write_json_atomic
from biomni_uncertainty.sampling import (
    COMPLETE_MARKER,
    CONDITION_INSTRUMENTED,
    FAILED_MARKER,
    RunSpec,
    write_marker,
)

_ALREADY_RAN = False

FAILURE_CLASSES = (
    "model_server_failure",
    "model_timeout",
    "tool_timeout",
    "external_resource_failure",
    "dependency_failure",
    "agent_parse_failure",
    "confidence_parse_failure",
    "benchmark_parse_failure",
    "evaluator_failure",
    "unknown_failure",
)


# --------------------------------------------------------------------------
# Local-endpoint configuration and validation
# --------------------------------------------------------------------------


@dataclass
class EndpointCheck:
    """Result of validating that every LLM path points at the local endpoint."""

    endpoint: str
    served_models: list[str]
    reachable: bool
    seed_supported: bool | None
    components: dict[str, dict]
    external_provider_keys_present: list[str]
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "endpoint": self.endpoint,
            "served_models": self.served_models,
            "reachable": self.reachable,
            "seed_supported": self.seed_supported,
            "components": self.components,
            "external_provider_keys_present": self.external_provider_keys_present,
            "error": self.error,
        }


EXTERNAL_PROVIDER_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_OPENAI_API_KEY",
)


def probe_endpoint(endpoint: str, model: str, timeout: int = 30) -> EndpointCheck:
    """Check ``/v1/models`` and probe whether the server accepts a ``seed``."""
    import requests

    base = endpoint.rstrip("/")
    served: list[str] = []
    reachable = False
    error = None
    try:
        r = requests.get(f"{base}/models", timeout=timeout)
        r.raise_for_status()
        served = [m["id"] for m in r.json().get("data", [])]
        reachable = True
    except Exception as exc:  # noqa: BLE001 - any transport error means unreachable
        error = repr(exc)

    seed_supported: bool | None = None
    if reachable:
        seed_supported = _probe_seed(base, served[0] if served else model, timeout)

    return EndpointCheck(
        endpoint=base,
        served_models=served,
        reachable=reachable,
        seed_supported=seed_supported,
        components={},
        external_provider_keys_present=[k for k in EXTERNAL_PROVIDER_KEYS if os.environ.get(k)],
        error=error,
    )


def _probe_seed(base: str, model: str, timeout: int) -> bool | None:
    """Does the endpoint honour ``seed``? Two identical seeded requests at
    temperature 1.0 should produce identical text if it does.

    Returns ``None`` when the probe itself failed - we never guess.
    """
    import requests

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Name three organelles, comma separated."}],
        "max_tokens": 32,
        "temperature": 1.0,
        "seed": 12345,
    }
    try:
        a = requests.post(f"{base}/chat/completions", json=payload, timeout=timeout)
        if a.status_code >= 400:
            return False
        b = requests.post(f"{base}/chat/completions", json=payload, timeout=timeout)
        if b.status_code >= 400:
            return False
        ta = a.json()["choices"][0]["message"]["content"]
        tb = b.json()["choices"][0]["message"]["content"]
        return ta == tb
    except Exception:  # noqa: BLE001
        return None


def configure_local_only(cfg: Config, endpoint: str, api_key: str = "EMPTY") -> None:
    """Point *every* Biomni LLM path at the local endpoint.

    Setting the model on the ``A1`` constructor alone is not enough: Biomni's
    ``default_config`` is consulted by ``get_llm`` for any component that builds
    its own client. We set both.
    """
    from biomni.config import default_config

    default_config.llm = cfg.model.identifier
    default_config.source = cfg.model.source
    default_config.base_url = endpoint
    default_config.api_key = api_key
    default_config.temperature = cfg.model.temperature
    default_config.timeout_seconds = cfg.execution.tool_timeout_seconds
    default_config.path = cfg.execution.data_path
    default_config.use_tool_retriever = cfg.execution.use_tool_retriever


def describe_llm_components(agent: Any) -> dict[str, dict]:
    """Effective model/provider/endpoint for each LLM-using subcomponent."""
    from biomni.config import default_config

    def describe(llm: Any) -> dict:
        if llm is None:
            return {"present": False}
        client = getattr(llm, "client", None)
        base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None)
        if base_url is None and client is not None:
            base_url = str(getattr(getattr(client, "_client", None), "base_url", None))
        return {
            "present": True,
            "class": type(llm).__name__,
            "model": getattr(llm, "model_name", None) or getattr(llm, "model", None),
            "base_url": str(base_url) if base_url else None,
            "temperature": getattr(llm, "temperature", None),
            "max_tokens": getattr(llm, "max_tokens", None),
            "seed": getattr(llm, "seed", None),
            "stop": getattr(llm, "stop", None),
        }

    out = {
        "primary_agent": describe(getattr(agent, "llm", None)),
        "biomni_default_config": {
            "llm": default_config.llm,
            "source": default_config.source,
            "base_url": default_config.base_url,
            "temperature": default_config.temperature,
        },
    }
    retriever = getattr(agent, "retriever", None)
    out["tool_retriever"] = {
        "present": retriever is not None,
        "class": type(retriever).__name__ if retriever is not None else None,
        # ToolRetriever.prompt_based_retrieval is always called by A1 with
        # llm=self.llm, so it shares the primary agent's client.
        "uses_agent_llm": retriever is not None,
    }
    out["database_query_helper"] = {
        "note": "Biomni database tools issue LLM calls through get_llm(config=default_config); "
        "the default_config entry above is therefore the effective configuration.",
    }
    out["secondary_critic_agent"] = {
        "enabled": bool(getattr(agent, "self_critic", False)),
        "uses_agent_llm": True,
    }
    return out


# --------------------------------------------------------------------------
# Agent construction
# --------------------------------------------------------------------------


def build_agent(cfg: Config, spec: RunSpec, endpoint: str, api_key: str = "EMPTY") -> Any:
    """Construct an ``A1`` bound to the local endpoint, with confidence elicitation.

    The confidence instruction is appended to the *system* prompt rather than to
    the benchmark prompt, so the task prompt handed to the agent is byte-identical
    between conditions A and B. Because ``A1.go`` regenerates the system prompt
    after tool retrieval, we wrap ``_generate_system_prompt`` so the suffix
    survives every regeneration.
    """
    from biomni.agent import A1

    configure_local_only(cfg, endpoint, api_key)
    agent = A1(
        path=cfg.execution.data_path,
        llm=cfg.model.identifier,
        source=cfg.model.source,
        base_url=endpoint,
        api_key=api_key,
        use_tool_retriever=cfg.execution.use_tool_retriever,
        timeout_seconds=cfg.execution.tool_timeout_seconds,
    )

    llm = agent.llm
    if hasattr(llm, "max_tokens"):
        llm.max_tokens = cfg.model.max_tokens
    if hasattr(llm, "temperature"):
        llm.temperature = cfg.model.temperature
    if spec.requested_seed is not None and hasattr(llm, "seed"):
        llm.seed = spec.requested_seed
    if hasattr(llm, "request_timeout"):
        llm.request_timeout = cfg.model.request_timeout_seconds

    if spec.condition == CONDITION_INSTRUMENTED and spec.confidence_mode != "none":
        suffix = confidence_instruction(cfg.confidence.open_delimiter, cfg.confidence.close_delimiter)
        original = agent._generate_system_prompt

        def with_confidence(*args, **kwargs):
            return original(*args, **kwargs) + suffix

        agent._generate_system_prompt = with_confidence
        agent.system_prompt = agent.system_prompt + suffix
    return agent


# --------------------------------------------------------------------------
# Failure classification
# --------------------------------------------------------------------------


def classify_exception(exc: BaseException, stats: TrajectoryStats) -> str:
    name = type(exc).__name__
    text = f"{name}: {exc}".lower()
    if name in ("APITimeoutError", "Timeout", "ReadTimeout", "ReadTimeoutError") or "timed out" in text:
        return "model_timeout"
    if name in ("APIConnectionError", "ConnectionError", "InternalServerError", "APIStatusError", "APIError"):
        return "model_server_failure"
    if "connection" in text and ("refused" in text or "reset" in text or "aborted" in text):
        return "model_server_failure"
    if name in ("RateLimitError",):
        return "model_server_failure"
    if name in ("ModuleNotFoundError", "ImportError"):
        return "dependency_failure"
    if name in ("HTTPError", "SSLError", "URLError") or "name or service not known" in text:
        return "external_resource_failure"
    if name == "GraphRecursionError" or "recursion limit" in text:
        return "agent_parse_failure"
    return "unknown_failure"


def classify_timeout(stats: TrajectoryStats, last_event_type: str | None) -> str:
    if last_event_type in ("code_execution_start", "tool_call_start"):
        return "tool_timeout"
    if last_event_type == "llm_request_start":
        return "model_timeout"
    return "unknown_failure"


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


@contextmanager
def _tee_streams(stdout_path: Path, stderr_path: Path):
    """Redirect this process's stdout/stderr into per-run log files."""
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    out_f = open(stdout_path, "a", encoding="utf-8", buffering=1)
    err_f = open(stderr_path, "a", encoding="utf-8", buffering=1)
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out_f, err_f
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        out_f.close()
        err_f.close()


def run_trajectory(
    cfg: Config,
    spec: RunSpec,
    endpoint: str,
    *,
    api_key: str = "EMPTY",
    project_repo: str | None = None,
    biomni_repo: str | None = None,
    endpoint_check: EndpointCheck | None = None,
) -> dict:
    """Run one trajectory and write every artifact into ``spec.run_dir``.

    Returns the run record (also persisted as ``metadata.json``).
    """
    global _ALREADY_RAN
    if _ALREADY_RAN:
        raise RuntimeError(
            "run_trajectory called twice in one interpreter. Biomni's Python REPL uses a "
            "module-global namespace; run each trajectory in its own process."
        )
    _ALREADY_RAN = True

    run_dir = Path(spec.run_dir)
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    for stale in (COMPLETE_MARKER, FAILED_MARKER):
        (run_dir / stale).unlink(missing_ok=True)

    redactor = Redactor(tuple(cfg.logging.redact_patterns), max_chars=cfg.logging.max_event_payload_chars)
    logger = EventLogger(spec.run_id, run_dir / "events.jsonl", redactor=redactor)

    record: dict[str, Any] = {
        # identity
        "experiment_id": spec.experiment_id,
        "run_id": spec.run_id,
        "condition": spec.condition,
        "task_name": spec.task_name,
        "global_instance_id": spec.global_instance_id,
        "task_instance_id": spec.task_instance_id,
        "trajectory_index": spec.trajectory_index,
        "split": spec.split,
        # configuration
        "requested_seed": spec.requested_seed,
        "seed_supported": endpoint_check.seed_supported if endpoint_check else None,
        "model": spec.model,
        "model_revision": spec.model_revision,
        "endpoint": endpoint,
        "temperature": spec.temperature,
        "max_tokens": spec.max_tokens,
        "confidence_mode": spec.confidence_mode,
        "timeout_seconds": spec.timeout_seconds,
        "prompt_hash": spec.prompt_hash,
        # provenance
        "hostname": socket.gethostname(),
        "slurm": slurm_info(),
        "gpu": gpu_info(),
        "biomni_git": git_info(biomni_repo),
        "project_git": git_info(project_repo),
        "config_hash": cfg.hash(),
        "config_snapshot": cfg.snapshot(),
        "started_at": time.time(),
        "ended_at": None,
        "wall_time_seconds": None,
        "completed": False,
        "failure_class": None,
        "error": None,
    }
    write_json_atomic(run_dir / "config.json", cfg.snapshot())

    stats = TrajectoryStats()
    logger.emit(
        "agent_start",
        condition=spec.condition,
        task_name=spec.task_name,
        task_instance_id=spec.task_instance_id,
        trajectory_index=spec.trajectory_index,
        prompt_hash=spec.prompt_hash,
        prompt_chars=len(spec.prompt),
        requested_seed=spec.requested_seed,
        endpoint=endpoint,
    )

    t0 = time.perf_counter()
    raw_response = ""
    agent = None
    cwd = os.getcwd()
    last_event_type: str | None = None

    try:
        with _tee_streams(run_dir / "stdout.log", run_dir / "stderr.log"):
            os.chdir(artifacts)  # isolate any files the agent writes
            agent = build_agent(cfg, spec, endpoint, api_key)
            record["llm_components"] = describe_llm_components(agent)
            write_json_atomic(run_dir / "llm_components.json", record["llm_components"])
            (run_dir / "system_prompt.txt").write_text(
                redactor.text(getattr(agent, "system_prompt", "")), encoding="utf-8"
            )

            with AgentInstrumentation(agent, logger, stats, stdout_limit=cfg.logging.stdout_limit):
                deadline = t0 + spec.timeout_seconds
                _log, raw_response = agent.go(spec.prompt)
                if time.perf_counter() > deadline:
                    record["exceeded_soft_deadline"] = True
        record["completed"] = True
    except BaseException as exc:  # noqa: BLE001 - every failure mode must be preserved
        os.chdir(cwd)
        stats.exception_count += 1
        failure_class = (
            classify_timeout(stats, last_event_type)
            if isinstance(exc, TimeoutError)
            else classify_exception(exc, stats)
        )
        record["failure_class"] = failure_class
        record["error"] = redactor.text(f"{type(exc).__name__}: {exc}")
        record["traceback"] = redactor.text(traceback.format_exc()[-8000:])
        logger.emit(
            "exception",
            where="run_trajectory",
            exception_class=type(exc).__name__,
            message=str(exc)[:2000],
            failure_class=failure_class,
        )
    finally:
        os.chdir(cwd)

    wall = time.perf_counter() - t0
    record["ended_at"] = time.time()
    record["wall_time_seconds"] = round(wall, 3)

    # ---- transcript + answer parsing -----------------------------------
    messages = []
    if agent is not None:
        state = getattr(agent, "_conversation_state", None) or {}
        messages = state.get("messages", []) if isinstance(state, dict) else []
        try:
            (run_dir / "transcript.json").write_text(
                json.dumps(
                    [
                        {"type": type(m).__name__, "content": redactor.text(getattr(m, "content", "") or "")}
                        for m in messages
                    ],
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - transcript is diagnostic
            record.setdefault("warnings", []).append(f"transcript_write_failed: {exc!r}")

    raw_response = raw_response or ""
    (run_dir / "final_response.txt").write_text(raw_response, encoding="utf-8")

    parsed = parse_final_response(
        spec.task_name,
        raw_response,
        spec.prompt,
        confidence_requested=(spec.confidence_mode != "none"),
        open_delim=cfg.confidence.open_delimiter,
        close_delim=cfg.confidence.close_delimiter,
    )
    write_json_atomic(run_dir / "parsed_answer.json", parsed)

    conf = parsed["confidence"]
    logger.emit(
        "final_answer",
        solution_block_status=parsed["solution_block_status"],
        parse_status=parsed["parsed"]["status"],
        canonical=parsed["parsed"]["canonical"],
    )
    logger.emit(
        "confidence_extracted",
        status=conf["status"],
        confidence_0_100=conf["confidence_0_100"],
        n_blocks=conf["n_blocks"],
    )

    msg_stats = analyze_messages(messages)
    record["trajectory_stats"] = {**stats.to_dict(), **msg_stats}
    record["final_response_raw_chars"] = len(raw_response)
    record["solution_block_status"] = parsed["solution_block_status"]
    record["final_answer_parsed"] = parsed["parsed"]["raw"]
    record["answer_canonical"] = parsed["parsed"]["canonical"]
    record["answer_parse_status"] = parsed["parsed"]["status"]
    record["answer_cluster_key"] = parsed["parsed"]["cluster_key"]
    record["final_confidence"] = conf["confidence"]
    record["final_confidence_0_100"] = conf["confidence_0_100"]
    record["confidence_parse_status"] = conf["status"]

    # A completed trajectory whose answer could not be parsed is a substantive
    # agent failure, not an infrastructure failure: it stays `completed` and
    # scores 0, but the failure class records what happened.
    if record["completed"] and parsed["parsed"]["status"] != "ok":
        record["failure_class"] = "agent_parse_failure"
    if (
        record["completed"]
        and spec.confidence_mode != "none"
        and conf["status"] not in ("ok", "multiple_blocks")
        and record["failure_class"] is None
    ):
        record["failure_class"] = "confidence_parse_failure"

    logger.emit(
        "agent_end",
        duration_seconds=wall,
        completed=record["completed"],
        failure_class=record["failure_class"],
        **stats.to_dict(),
    )

    write_json_atomic(run_dir / "metadata.json", record)
    marker_payload = {
        "run_id": spec.run_id,
        "completed": record["completed"],
        "failure_class": record["failure_class"],
        "ended_at": record["ended_at"],
        "wall_time_seconds": record["wall_time_seconds"],
    }
    write_marker(run_dir, COMPLETE_MARKER if record["completed"] else FAILED_MARKER, marker_payload)
    return record
