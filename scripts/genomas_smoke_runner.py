#!/usr/bin/env python3
"""Run exactly one native GenoMAS task through a local OpenAI-compatible server.

GenoMAS retains its upstream role graph, prompts, tools, retries, and execution
logic.  The sole adaptation is its LLM transport: the upstream Ollama client is
replaced at process start by a local vLLM OpenAI-compatible client.  This avoids
changing the pinned source and allows the existing local Qwen model to be used.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from biomni_uncertainty.adapters.genomas import normalize_condition_arg  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--trait", required=True)
    parser.add_argument("--condition", default=None,
                        help="Condition name (e.g. Age, Gender). Omit, or pass 'None', for the unconditioned task.")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--max-time", type=float, default=420)
    args = parser.parse_args()
    args.condition = normalize_condition_arg(args.condition)
    os.chdir(args.source)
    sys.path.insert(0, str(args.source))
    import main as genomas_main
    from openai import AsyncOpenAI
    from utils.llm import LLMClient, ModelConfig

    class LocalVLLMClient(LLMClient):
        def _initialize_client(self) -> None:
            self.client = AsyncOpenAI(api_key="EMPTY", base_url=args.endpoint.rstrip("/") + "/v1")

        async def generate_completion(self, messages: list[dict[str, str]]) -> dict[str, Any]:
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_name, messages=messages, temperature=0.7, max_tokens=2048,
                )
                usage = response.usage
                return self._format_response(
                    response.choices[0].message.content or "",
                    int(usage.prompt_tokens or 0) if usage else 0,
                    int(usage.completion_tokens or 0) if usage else 0,
                    response.model_dump(),
                )
            except Exception as exc:  # preserve upstream failure representation
                return self.handle_exception(exc)

    def local_client(role_args: Any, logger: Any = None) -> LocalVLLMClient:
        config = ModelConfig(model_name=args.model, provider="local", max_retries=3,
                             timeout_per_retry=30.0, timeout_per_message=90.0)
        return LocalVLLMClient(config, logger)

    # ``main`` otherwise loads the full benchmark.  Restricting only the task
    # iterator is the admission harness boundary; GenoMAS itself is unchanged.
    genomas_main.get_llm_client = local_client
    genomas_main.get_question_pairs = lambda _path: [(args.trait, args.condition)]
    sys.argv = ["main.py", "--version", args.version, "--model", args.model,
                "--data-root", args.data_root, "--quick-test", "--max-time", str(args.max_time)]
    asyncio.run(genomas_main.main())


if __name__ == "__main__":
    main()
