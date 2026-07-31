"""Trajectory instrumentation for a pinned Biomni ``A1`` agent.

Everything here is an *adapter*: LangChain callbacks, instance-level method
wrapping and module-attribute patching inside the already-imported
``biomni.agent.a1`` namespace. No upstream file is modified.

Three observable layers are captured:

1. **LLM calls** - via a ``BaseCallbackHandler`` attached to ``agent.llm``.
   Token counts come from the endpoint's ``usage`` block, not from any
   hidden-reasoning field.
2. **Code execution** - by patching ``biomni.agent.a1.run_with_timeout``, which
   is the single choke point through which the graph's ``execute`` node runs
   Python / R / bash.
3. **Biomni tool calls** - Biomni tools are plain Python functions invoked
   *inside* generated code, so the observable signal is the set of
   ``biomni.tool.*`` imports and calls parsed out of each ``<execute>`` block
   (upstream's own ``parse_tool_calls_with_modules`` is reused).

Concurrency note: ``biomni.tool.support_tools.run_python_repl`` executes into a
module-global namespace, so exactly one trajectory may run per process. The
dispatcher enforces this by running each trajectory in its own subprocess.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

from biomni_uncertainty.events import EventLogger

_TOOL_CALL_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")


def _arg_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass
class TrajectoryStats:
    """Running counters that become the run record's trajectory statistics."""

    llm_call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    token_usage_available: bool = False
    model_time_seconds: float = 0.0
    tool_time_seconds: float = 0.0
    code_execution_count: int = 0
    tool_call_count: int = 0
    failed_tool_call_count: int = 0
    parse_error_count: int = 0
    exception_count: int = 0
    retry_count: int = 0
    retrieval_count: int = 0
    finish_reasons: list[str] = field(default_factory=list)
    tool_call_names: list[str] = field(default_factory=list)
    tool_call_signatures: list[str] = field(default_factory=list)
    code_block_hashes: list[str] = field(default_factory=list)
    generated_chars: int = 0

    # -- derived ---------------------------------------------------------
    @property
    def unique_tool_count(self) -> int:
        return len(set(self.tool_call_names))

    @property
    def repeated_tool_call_count(self) -> int:
        """Tool invocations whose (name, arg-signature) was already seen."""
        seen: set[str] = set()
        n = 0
        for sig in self.tool_call_signatures:
            if sig in seen:
                n += 1
            else:
                seen.add(sig)
        return n

    @property
    def repeated_tool_call_fraction(self) -> float | None:
        if not self.tool_call_signatures:
            return None
        return self.repeated_tool_call_count / len(self.tool_call_signatures)

    @property
    def failed_tool_call_fraction(self) -> float | None:
        if not self.code_execution_count:
            return None
        return self.failed_tool_call_count / self.code_execution_count

    def to_dict(self) -> dict:
        return {
            "llm_call_count": self.llm_call_count,
            "total_input_tokens": self.total_input_tokens if self.token_usage_available else None,
            "total_output_tokens": self.total_output_tokens if self.token_usage_available else None,
            "total_tokens": self.total_tokens if self.token_usage_available else None,
            "token_usage_available": self.token_usage_available,
            "model_time_seconds": round(self.model_time_seconds, 3),
            "tool_time_seconds": round(self.tool_time_seconds, 3),
            "code_execution_count": self.code_execution_count,
            "tool_call_count": self.tool_call_count,
            "unique_tool_count": self.unique_tool_count,
            "failed_tool_call_count": self.failed_tool_call_count,
            "failed_tool_call_fraction": self.failed_tool_call_fraction,
            "repeated_tool_call_count": self.repeated_tool_call_count,
            "repeated_tool_call_fraction": self.repeated_tool_call_fraction,
            "retry_count": self.retry_count,
            "parse_error_count": self.parse_error_count,
            "exception_count": self.exception_count,
            "retrieval_count": self.retrieval_count,
            "generated_chars": self.generated_chars,
            "finish_reasons": self.finish_reasons,
        }


# --------------------------------------------------------------------------
# LangChain callback
# --------------------------------------------------------------------------


def make_llm_callback(logger: EventLogger, stats: TrajectoryStats):
    """Build a LangChain callback handler recording LLM request telemetry."""
    from langchain_core.callbacks.base import BaseCallbackHandler

    class _Handler(BaseCallbackHandler):
        raise_error = False

        def __init__(self) -> None:
            self._starts: dict[str, float] = {}

        # LangChain passes run_id as a UUID kwarg for every callback.
        @staticmethod
        def _rid(kwargs: dict) -> str:
            return str(kwargs.get("run_id", "unknown"))

        def on_chat_model_start(self, serialized, messages, **kwargs):  # noqa: ANN001
            self._on_start(kwargs, n_messages=sum(len(m) for m in messages))

        def on_llm_start(self, serialized, prompts, **kwargs):  # noqa: ANN001
            self._on_start(kwargs, n_messages=len(prompts))

        def _on_start(self, kwargs: dict, n_messages: int) -> None:
            rid = self._rid(kwargs)
            self._starts[rid] = time.perf_counter()
            params = kwargs.get("invocation_params") or {}
            logger.emit(
                "llm_request_start",
                request_id=rid,
                n_messages=n_messages,
                model=params.get("model") or params.get("model_name"),
                sampling_params={
                    k: params.get(k)
                    for k in ("temperature", "top_p", "max_tokens", "seed", "stop", "n")
                    if params.get(k) is not None
                },
            )

        def on_llm_end(self, response, **kwargs):  # noqa: ANN001
            rid = self._rid(kwargs)
            latency = time.perf_counter() - self._starts.pop(rid, time.perf_counter())
            stats.llm_call_count += 1
            stats.model_time_seconds += latency

            usage = _extract_usage(response)
            finish_reason, model_id, resp_id = _extract_meta(response)
            if usage:
                stats.token_usage_available = True
                stats.total_input_tokens += int(usage.get("input_tokens") or 0)
                stats.total_output_tokens += int(usage.get("output_tokens") or 0)
                stats.total_tokens += int(usage.get("total_tokens") or 0)
            try:
                stats.generated_chars += sum(len(g.text or "") for gen in response.generations for g in gen)
            except Exception:  # noqa: BLE001 - generation shape varies by provider
                pass
            if finish_reason:
                stats.finish_reasons.append(finish_reason)

            logger.emit(
                "llm_request_end",
                duration_seconds=latency,
                request_id=rid,
                usage=usage,
                usage_available=bool(usage),
                finish_reason=finish_reason,
                model=model_id,
                response_id=resp_id,
            )

        def on_llm_error(self, error, **kwargs):  # noqa: ANN001
            rid = self._rid(kwargs)
            latency = time.perf_counter() - self._starts.pop(rid, time.perf_counter())
            stats.exception_count += 1
            logger.emit(
                "exception",
                duration_seconds=latency,
                where="llm",
                request_id=rid,
                exception_class=type(error).__name__,
                message=str(error)[:2000],
            )

    return _Handler()


def _extract_usage(response: Any) -> dict | None:
    """Pull token usage from a LangChain LLMResult, tolerating provider shapes."""
    out = response.llm_output or {}
    for key in ("token_usage", "usage"):
        u = out.get(key)
        if isinstance(u, dict) and u:
            return {
                "input_tokens": u.get("prompt_tokens", u.get("input_tokens")),
                "output_tokens": u.get("completion_tokens", u.get("output_tokens")),
                "total_tokens": u.get("total_tokens"),
            }
    try:
        msg = response.generations[0][0].message
        u = getattr(msg, "usage_metadata", None)
        if isinstance(u, dict) and u:
            return {
                "input_tokens": u.get("input_tokens"),
                "output_tokens": u.get("output_tokens"),
                "total_tokens": u.get("total_tokens"),
            }
    except (AttributeError, IndexError):
        pass
    return None


def _extract_meta(response: Any) -> tuple[str | None, str | None, str | None]:
    finish_reason = model_id = resp_id = None
    out = response.llm_output or {}
    model_id = out.get("model_name") or out.get("model")
    resp_id = out.get("id")
    try:
        gen = response.generations[0][0]
        info = getattr(gen, "generation_info", None) or {}
        finish_reason = info.get("finish_reason")
        meta = getattr(getattr(gen, "message", None), "response_metadata", None) or {}
        finish_reason = finish_reason or meta.get("finish_reason")
        model_id = model_id or meta.get("model_name")
        resp_id = resp_id or meta.get("id")
    except (AttributeError, IndexError):
        pass
    return finish_reason, model_id, resp_id


# --------------------------------------------------------------------------
# Agent instrumentation
# --------------------------------------------------------------------------


class AgentInstrumentation:
    """Attach/detach instrumentation to a live ``A1`` instance."""

    def __init__(self, agent: Any, logger: EventLogger, stats: TrajectoryStats, *, stdout_limit: int = 4000):
        self.agent = agent
        self.logger = logger
        self.stats = stats
        self.stdout_limit = stdout_limit
        self._restore: list[tuple[Any, str, Any]] = []
        self._step = 0

    # -- public ----------------------------------------------------------
    def attach(self) -> None:
        self._attach_llm_callback()
        self._patch_execution()
        self._patch_retrieval()

    def detach(self) -> None:
        for obj, name, original in reversed(self._restore):
            setattr(obj, name, original)
        self._restore.clear()

    def __enter__(self) -> AgentInstrumentation:
        self.attach()
        return self

    def __exit__(self, *exc) -> None:
        self.detach()

    # -- internals -------------------------------------------------------
    def _swap(self, obj: Any, name: str, new: Any) -> None:
        self._restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, new)

    def _attach_llm_callback(self) -> None:
        handler = make_llm_callback(self.logger, self.stats)
        llm = self.agent.llm
        existing = list(getattr(llm, "callbacks", None) or [])
        self._restore.append((llm, "callbacks", getattr(llm, "callbacks", None)))
        llm.callbacks = existing + [handler]

    def _patch_execution(self) -> None:
        """Wrap the single choke point through which the graph executes code."""
        import biomni.agent.a1 as a1mod

        original = a1mod.run_with_timeout
        inst = self

        def wrapped(func, args, timeout=600):  # noqa: ANN001 - upstream signature
            code = args[0] if args else ""
            lang = _classify_code(getattr(func, "__name__", ""), code)
            inst._step += 1
            step = inst._step
            tools = inst._record_tool_calls(code, step)
            code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
            inst.stats.code_block_hashes.append(code_hash)
            inst.stats.code_execution_count += 1

            inst.logger.emit(
                "code_execution_start",
                step_index=step,
                language=lang,
                code_hash=code_hash,
                code_chars=len(code),
                code_excerpt=code[: inst.stdout_limit],
                tools_detected=tools,
                timeout_seconds=timeout,
            )
            t0 = time.perf_counter()
            status = "ok"
            error_text = None
            result = None
            try:
                result = original(func, args, timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - any executor failure must be recorded
                status = "exception"
                error_text = f"{type(exc).__name__}: {exc}"
                inst.stats.exception_count += 1
                inst.logger.emit(
                    "exception",
                    step_index=step,
                    where="code_execution",
                    exception_class=type(exc).__name__,
                    message=str(exc)[:2000],
                    traceback=traceback.format_exc()[-4000:],
                )
                raise
            finally:
                dt = time.perf_counter() - t0
                inst.stats.tool_time_seconds += dt
                text = result if isinstance(result, str) else ("" if result is None else str(result))
                if status == "ok":
                    status, error_text = _classify_execution_result(text, timeout)
                if status != "ok":
                    inst.stats.failed_tool_call_count += 1
                inst.logger.emit(
                    "code_execution_end",
                    step_index=step,
                    duration_seconds=dt,
                    language=lang,
                    code_hash=code_hash,
                    status=status,
                    error=error_text,
                    output_bytes=len(text.encode("utf-8", "ignore")),
                    stdout_excerpt=text[: inst.stdout_limit],
                    stdout_tail=text[-inst.stdout_limit :] if len(text) > inst.stdout_limit else None,
                )
                for name in tools:
                    inst.logger.emit(
                        "tool_call_end",
                        step_index=step,
                        tool_name=name,
                        status=status,
                        duration_seconds=dt,
                    )
            return result

        self._swap(a1mod, "run_with_timeout", wrapped)

    def _record_tool_calls(self, code: str, step: int) -> list[str]:
        """Detect Biomni tool usage in a generated code block."""
        names: list[str] = []
        try:
            from biomni.utils import parse_tool_calls_with_modules

            for item in parse_tool_calls_with_modules(code) or []:
                names.append(item[0] if isinstance(item, (tuple, list)) else str(item))
        except Exception:  # noqa: BLE001 - upstream parser is best-effort
            pass
        if not names:
            # Fall back to functions imported from a biomni.tool.* module.
            imported = set(re.findall(r"from\s+biomni\.tool\.[\w.]+\s+import\s+([^\n]+)", code))
            wanted = {n.strip() for chunk in imported for n in chunk.replace("(", "").replace(")", "").split(",")}
            wanted = {w.split(" as ")[0].strip() for w in wanted if w.strip()}
            called = set(_TOOL_CALL_RE.findall(code))
            names = sorted(wanted & called)

        for name in names:
            # Argument signature: the literal call text, hashed. Enough to tell a
            # genuine repeat from a re-parameterised retry without logging data.
            m = re.search(re.escape(name) + r"\s*\((.*?)\)", code, re.DOTALL)
            arg_text = (m.group(1) if m else "")[:2000]
            sig = f"{name}:{_arg_hash(arg_text)}"
            self.stats.tool_call_names.append(name)
            self.stats.tool_call_signatures.append(sig)
            self.stats.tool_call_count += 1
            self.logger.emit(
                "tool_call_start",
                step_index=step,
                tool_name=name,
                argument_hash=_arg_hash(arg_text),
                argument_excerpt=arg_text[:500],
                is_repeat=sig in set(self.stats.tool_call_signatures[:-1]),
            )
        return names

    def _patch_retrieval(self) -> None:
        retriever = getattr(self.agent, "retriever", None)
        if retriever is None or not hasattr(retriever, "prompt_based_retrieval"):
            return
        original = retriever.prompt_based_retrieval
        inst = self

        def wrapped(query, resources, llm=None, **kw):  # noqa: ANN001 - upstream signature
            inst.stats.retrieval_count += 1
            inst.logger.emit(
                "retrieval_start",
                n_tools=len(resources.get("tools", [])),
                n_data_lake=len(resources.get("data_lake", [])),
                n_libraries=len(resources.get("libraries", [])),
                llm_is_agent_llm=llm is inst.agent.llm,
            )
            t0 = time.perf_counter()
            try:
                out = original(query, resources, llm=llm, **kw)
            except Exception as exc:  # noqa: BLE001
                inst.stats.exception_count += 1
                inst.logger.emit(
                    "exception",
                    where="retrieval",
                    duration_seconds=time.perf_counter() - t0,
                    exception_class=type(exc).__name__,
                    message=str(exc)[:2000],
                )
                raise
            inst.logger.emit(
                "retrieval_end",
                duration_seconds=time.perf_counter() - t0,
                selected={k: len(v) for k, v in (out or {}).items()},
            )
            return out

        self._swap(retriever, "prompt_based_retrieval", wrapped)


def _classify_code(func_name: str, code: str) -> str:
    if "bash" in func_name:
        return "bash"
    if func_name.endswith("run_r_code"):
        return "r"
    if code.strip().startswith(("#!R", "# R code", "# R script")):
        return "r"
    if code.strip().startswith(("#!BASH", "# Bash script", "#!CLI")):
        return "bash"
    return "python"


_ERROR_PREFIXES = ("Error: ", "Traceback (most recent call last)")


def _classify_execution_result(text: str, timeout: int) -> tuple[str, str | None]:
    """Classify a code-execution result string.

    ``run_python_repl`` swallows exceptions and returns ``"Error: ..."``; the
    timeout helper returns a timeout sentinel. Both are agent-observable
    failures, so both are counted.
    """
    stripped = (text or "").strip()
    if not stripped:
        return "ok_empty_output", None
    low = stripped.lower()
    if "timed out" in low or "timeout" in low[:200] and str(timeout) in stripped:
        return "tool_timeout", stripped[:500]
    for prefix in _ERROR_PREFIXES:
        if stripped.startswith(prefix):
            return "error", stripped[:500]
    if re.search(r"^\s*\w*(Error|Exception):", stripped, re.MULTILINE):
        return "error", stripped[:500]
    return "ok", None


def analyze_messages(messages: list[Any]) -> dict:
    """Post-hoc, reliably-available counters over the final message list.

    Only counts things that are unambiguous in the transcript. Plan-revision
    counting is deliberately *not* attempted: Biomni has no plan object, and
    keyword heuristics were not validated, so it is reported as unavailable.
    """
    n_ai = n_human = n_observation = 0
    n_execute = n_solution = 0
    n_parse_error_messages = 0
    for m in messages or []:
        content = getattr(m, "content", "") or ""
        cls = type(m).__name__
        if cls == "AIMessage":
            n_ai += 1
            if content.startswith("<observation>"):
                n_observation += 1
            if "<execute>" in content:
                n_execute += 1
            if "<solution>" in content:
                n_solution += 1
        elif cls == "HumanMessage":
            n_human += 1
            if "There are no tags" in content or "must include thinking process" in content:
                n_parse_error_messages += 1
    return {
        "message_count": len(messages or []),
        "ai_message_count": n_ai,
        "human_message_count": n_human,
        "observation_count": n_observation,
        "execute_block_count": n_execute,
        "solution_block_count": n_solution,
        "parse_error_message_count": n_parse_error_messages,
        "visible_plan_step_count": n_ai - n_observation,
        "plan_revision_count": None,  # unavailable: no reliable observable signal
    }
