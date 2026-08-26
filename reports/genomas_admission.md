# GenoMAS admission record — K=1 smoke

Date: 2026-08-25. This record covers one declared smoke task only; no K=4
experiment was launched.

## Pinned sources and inputs

- GenoMAS source: `d6365a700794587b53958db3bf22bb1fb80c3451`, detached clean
  worktree at `/scratch/11034/atzanakak/genomas_admission/GenoMAS_run`.
- GenoTEX source: `Liu-Hy/GenoTEX@9d50c9020256e8c943e02b6c0ad843017cd76cf8`.
- Raw agent input: the exact `input/**` tree, 1,889 files and 41,546,154,010
  bytes. SHA-256 verification compared every local file against the upstream
  Hugging Face LFS digest: 1,889 observed, zero mismatches, `verified: true`.
- Input manifest SHA-256:
  `925bf60ec8b61d74d28a87efc488aaf367d90164521ec65176f778ef504759cc`.
- Input verification SHA-256:
  `8fbc66a67fa92c50ea4158159c438dc8bb94dfea77406719346482f8ca878d2c`.
- Held-out scorer reference: only
  `output/preprocess/Alcohol_Flush_Reaction/**` (three files, 7,765 bytes),
  stored separately at `/scratch/11034/atzanakak/genomas_admission/genotex_references`.
  It was never mounted in the agent worktree. Its SHA-256 manifest is
  `44fbd5a4569d17d1bad0cb3bcd4050be8307ffa6a4b923c014fbdd6b2c83f401`.

The full input manifest and verification record are at:

- `/scratch/11034/atzanakak/genomas_admission/provenance/genotex_input_manifest.json`
- `/scratch/11034/atzanakak/genomas_admission/provenance/genotex_input_verification.json`

## Local runtime

- Serving: vLLM 0.27.1 on the allocated GH200, bound only to `127.0.0.1:8000`.
- Model: existing local `Qwen3-Coder-30B-A3B-Instruct`, BF16, served model
  name `Qwen3-Coder-30B-A3B-Instruct`; 16 safetensors files have a SHA-256
  manifest at `/scratch/11034/atzanakak/genomas_admission/provenance/qwen3_coder_safetensors.sha256`
  (manifest SHA-256 `5ddcc304930ae6cf1ba3c41bb6d2a6104ab8cf8a08fd1279953439f40ac39e47`).
- The source was not modified. `scripts/genomas_smoke_runner.py` changes only
  LLM transport (upstream Ollama client to the local OpenAI-compatible vLLM
  endpoint) and task iteration (one declared pair); GenoMAS prompts, agents,
  tools, retries, and execution flow remain native.
- vLLM was run in eager mode after the node's default `nvc` compiler rejected
  a Triton flag. The startup also required the existing venv `ninja` on PATH
  and the installed CUDA 12.5 runtime path. These are serving-environment
  fixes, not model or benchmark changes.

## Executed smoke and native score

- Task boundary: `Alcohol_Flush_Reaction` conditioned on `Age`; quick-test;
  K=1 only; maximum task time 420 seconds.
- Successful run ID: `genomas_k1_admission_20260825_retry1`.
- Runtime: 290.12 s. Local-model accounting: 119,230 input tokens and 6,162
  output tokens. No paid or external model endpoint was used.
- Native artifacts: `/scratch/11034/atzanakak/genomas_admission/GenoMAS_run/output/genomas_k1_admission_20260825_retry1`.
- Native selector scorer was run on just this pair with the held-out reference:
  selection accuracy 100.0; filtering accuracy 100.0. Precision, recall, and
  F1 are 0.0 because the single reference and prediction both classify
  `GSE133228` as unavailable, leaving no positive class.
- Score JSON SHA-256:
  `2aad714ba7afa305bad00ba29c0bb323f0fd56863ce4d0aa579c748a70277cbb`.

The K=1 score is an admission/smoke result, not a claim of full-benchmark
performance. K=4 remains gated pending approval.
