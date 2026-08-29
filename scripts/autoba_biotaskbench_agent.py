#!/usr/bin/env python3
"""Run one native AutoBA trajectory against a bioTaskBench task workspace.

Invoked as bioTaskBench's ``--agent-cmd`` (env vars ``BIOTASKBENCH_TASK_JSON``,
``BIOTASKBENCH_TEST_DIR``, ``BIOTASKBENCH_WORKSPACE`` set by the harness).
AutoBA's own task format (a YAML ``data_list``/``goal_description``) differs
from bioTaskBench's task JSON, so this translates one into the other; it does
not touch bioTaskBench's harness/grader or AutoBA's own source.

Two narrow, documented, non-invasive adaptations to the pinned AutoBA source
(commit a9f8f1244faf8b33cf1154150d612acf5026a4d9), both applied by patching
already-constructed objects/imported names -- no AutoBA file is edited:

1. LLM transport: AutoBA's OpenAI-path client is instantiated inside
   ``Agent.__init__`` as ``OpenAI(api_key=...)`` (real OpenAI endpoint). The
   ``OpenAI`` name imported into ``src.agent`` is monkeypatched before
   construction to instead build a client pointed at the local vLLM
   OpenAI-compatible endpoint. ``model_engine="gpt-4"`` is passed at
   construction only to satisfy AutoBA's own engine-validity check (which
   otherwise calls ``exit()``); immediately after construction the instance's
   ``model_engine``/``gpt_model_engines`` are corrected to the real served
   model name, so the actual request sent to vLLM uses the right ``model``.
2. Execution environment: ``CodeExecutor.code_prefix`` hardcodes
   ``mamba activate abc_runtime`` -- no such environment exists on this node
   (no conda/mamba is even installed) and AutoBA does not expose this as a
   CLI flag. Patched, post-construction, to instead activate the existing
   pandas/numpy-capable venv already used elsewhere in this project, via the
   documented LD_LIBRARY_PATH fix for this cluster's python3.11 module.
2b. Shell invocation mode: ``CodeExecutor.execute`` hardcodes
   ``subprocess.Popen(['bash', '-i', '-e', ...])``. ``-i`` (interactive) has
   no effect other than making bash try to set up job control, which fails
   with no controlling TTY in any headless/automated harness --
   ``bash: cannot set terminal process group`` / ``Inappropriate ioctl for
   device`` / ``stty: ... Inappropriate ioctl for device``. That noise lands
   in stderr, which AutoBA's own executor-response step feeds back to the
   model as part of its self-assessment of whether the code succeeded; two
   independent K=1 trajectories observed the model misreading these benign
   warnings as a real failure and stalling in place for the full timeout
   despite generating a completely correct script both times. Patched by
   replacing ``CodeExecutor.execute`` (class-level, before construction)
   with an otherwise-identical copy that drops ``-i``. Nothing about
   AutoBA's prompts, planning, retry semantics, or code generation changes
   -- only a shell flag that exists purely for interactive TTY convenience
   AutoBA never needs when run non-interactively (as any automated
   evaluation, including AutoBA's own admission smoke, necessarily must).
3. Import-time stubs: ``src.agent``/``src.build_RAG_private`` unconditionally
   import Meta's ``llama`` package (which itself imports ``fairscale`` --
   no prebuilt wheel for this node's aarch64) and ``llama_index`` with two
   embedding extras, purely to support AutoBA's local-LLaMA and RAG code
   paths. We use neither (``rag=False``, and only the OpenAI/vLLM transport
   branch is ever reached), so these are stubbed in ``sys.modules`` before
   import rather than installed -- nothing stubbed is ever called.
4. Token accounting: AutoBA's own ``get_single_response`` discards
   ``response.usage`` from every call (no native token logging, unlike
   GenoMAS's ``utils/logger.py`` -- see reports/autoba_admission.md Sec 4).
   The client ``local_vllm_client`` constructs is wrapped, post-construction,
   to record each call's ``usage`` before returning it unchanged; the
   aggregate is flushed to ``<workspace>/token_usage.json`` when the
   trajectory ends, including on early termination by a campaign's
   early-completion poller (SIGTERM), via a handler installed in ``main()``.
   Nothing about which requests are sent or how responses are used changes.

Preserves: AutoBA's own prompts, agent/executor logic, tool flow, retries,
and task semantics. Nothing about AutoBA's reasoning or code generation is
changed -- only where its LLM calls and generated-code execution actually go.
"""
from __future__ import annotations

import functools
import json
import os
import signal
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from biomni_uncertainty.adapters.autoba import aggregate_token_usage  # noqa: E402

AUTOBA_ROOT = Path("/work/11034/atzanakak/biomni_bench/external_agents/AutoBA")
VLLM_ENDPOINT = os.environ.get("AUTOBA_VLLM_ENDPOINT", "http://127.0.0.1:8000")
SERVED_MODEL = os.environ.get("AUTOBA_MODEL", "Qwen3-Coder-30B-A3B-Instruct")
EXEC_ENV_PREFIX = [
    "export LD_LIBRARY_PATH=/opt/apps/gcc14/cuda12/python3/3.11.8/lib:$LD_LIBRARY_PATH",
    "source /scratch/11034/atzanakak/genomas_admission/venv/bin/activate",
]

# Per-call token usage, recorded by the wrapper `_wrap_client_with_token_accounting`
# installs below. AutoBA itself discards `response.usage` entirely (see module
# docstring, "Token accounting" in reports/autoba_admission.md Sec 4) -- this is
# the only place that ever sees it, so it must be captured here, not reconstructed
# after the fact from logs.
_TOKEN_CALLS: list[dict[str, int | None] | None] = []


def _wrap_client_with_token_accounting(client):  # noqa: ANN001, ANN201
    """Record every call's `response.usage` without changing its behavior.

    Wraps the already-constructed client's bound `chat.completions.create`
    method (an instance attribute override, the same monkeypatch style as
    every other adaptation in this file) so AutoBA's own call sites and
    control flow are completely unaffected. A call whose `usage` is absent
    (some serving configs omit it) is recorded as `None`, never fabricated
    as zero -- see `aggregate_token_usage`.
    """
    original_create = client.chat.completions.create

    @functools.wraps(original_create)
    def create_and_record(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        response = original_create(*args, **kwargs)
        usage = getattr(response, "usage", None)
        _TOKEN_CALLS.append(
            None
            if usage is None
            else {
                "input_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
        )
        return response

    client.chat.completions.create = create_and_record
    return client


def _write_token_usage(workspace: Path) -> None:
    (workspace / "token_usage.json").write_text(
        json.dumps(aggregate_token_usage(_TOKEN_CALLS), indent=2) + "\n", encoding="utf-8"
    )


def _stub_unused_heavy_imports() -> None:
    """Register fake modules for import chains this run never exercises.

    A plain ``types.ModuleType`` with a permissive ``__getattr__`` satisfies
    both ``import x`` and ``from x import y`` without needing to enumerate
    every name each caller happens to import.
    """
    def _permissive_module(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__getattr__ = lambda attr: MagicMock(name=f"{name}.{attr}")  # type: ignore[method-assign]
        return mod

    for name in (
        "fire",
        "llama",
        "llama_index",
        "llama_index.core",
        "llama_index.embeddings",
        "llama_index.embeddings.openai",
        "llama_index.embeddings.huggingface",
    ):
        sys.modules.setdefault(name, _permissive_module(name))


def _execute_without_interactive_tty(self, bash_code_path):  # noqa: ANN001
    """Verbatim copy of ``CodeExecutor.execute`` with ``-i`` dropped from argv.

    See module docstring, patch 2b. Only the ``subprocess.Popen`` argv list
    differs from AutoBA's own ``src/executor.py::CodeExecutor.execute``.
    """
    import subprocess

    self.bash_code_path = bash_code_path
    with open(self.bash_code_path) as input_file:
        bash_content = input_file.read()

    self.bash_code_path_execute = self.bash_code_path + ".execute.sh"
    with open(self.bash_code_path_execute, "w") as output_file:
        for code in self.code_prefix:
            output_file.write(code + "\n")
        output_file.write(bash_content)
        output_file.write("\n")
        for code in self.code_postfix:
            output_file.write(code + "\n")

    process = subprocess.Popen(["bash", "-e", self.bash_code_path_execute],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    stdout = []
    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        print(f"[stdout] {output.strip()}")
        stdout.append(f"[stdout] {output.strip()}")

    stderr = []
    for line in process.stderr.readlines():
        if "EnvironmentNameNotFound" in line or line == "\n":
            pass
        else:
            print(f"[stderr] {line}", end="")
            stderr.append(line)

    if len(stdout) > 10:
        stdout = stdout[-10:]
    if len(stderr) > 10:
        stderr = stderr[-10:]

    stdout = "\n".join(stdout)
    stderr = "\n".join(stderr)
    process.communicate()
    return stdout + "\n" + stderr


def main() -> None:
    task_json = Path(os.environ["BIOTASKBENCH_TASK_JSON"])
    workspace = Path(os.environ["BIOTASKBENCH_WORKSPACE"])
    task = json.loads(task_json.read_text(encoding="utf-8"))

    data_files = task.get("context", {}).get("data_files", [])
    data_description = task.get("context", {}).get("data_description", "")
    data_list = [f"{(workspace / f).resolve()}: {data_description}" for f in data_files]
    goal_description = task["prompt"]

    sys.path.insert(0, str(AUTOBA_ROOT))
    os.chdir(AUTOBA_ROOT)  # AutoBA references ./softwares_config, ./softwares_database as relative paths.
    _stub_unused_heavy_imports()

    import src.agent as autoba_agent_mod
    import src.executor as autoba_executor_mod
    from openai import OpenAI as RealOpenAI

    def local_vllm_client(api_key: str = "unused") -> RealOpenAI:  # noqa: ARG001
        client = RealOpenAI(api_key="EMPTY", base_url=VLLM_ENDPOINT.rstrip("/") + "/v1")
        return _wrap_client_with_token_accounting(client)  # token-accounting patch, see module docstring.

    autoba_agent_mod.OpenAI = local_vllm_client  # transport patch #1, see module docstring.
    autoba_executor_mod.CodeExecutor.execute = _execute_without_interactive_tty  # transport patch #2b.

    # A campaign's early-completion poller (see
    # biomni_uncertainty.adapters.autoba.run_with_early_completion) terminates
    # this process with SIGTERM once the scored artifact is stable. SIGTERM's
    # default action skips Python's `finally` blocks, which would silently
    # drop every token count observed so far -- flush them here first.
    def _flush_and_exit(signum, frame):  # noqa: ANN001, ARG001
        _write_token_usage(workspace)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _flush_and_exit)

    agent = autoba_agent_mod.Agent(
        initial_data_list=data_list,
        output_dir=str(workspace.resolve()),
        initial_goal_description=goal_description,
        model_engine="gpt-4",  # satisfies AutoBA's own validity check; corrected below.
        openai_api="EMPTY",
        execute=True,
        blacklist="java,perl,annovar",
        gui_mode=False,
        cpu=False,
        rag=False,
    )
    agent.model_engine = SERVED_MODEL
    agent.gpt_model_engines = [*agent.gpt_model_engines, SERVED_MODEL]
    agent.code_executor.code_prefix = list(EXEC_ENV_PREFIX)  # transport patch #2, see module docstring.

    try:
        agent.run()
    finally:
        _write_token_usage(workspace)


if __name__ == "__main__":
    main()
