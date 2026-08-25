#!/usr/bin/env bash
# One-GH200 engineering smoke. Invoke this script through setsid/nohup; it
# owns only the Agent Lightning server/controller child PIDs it starts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VISTA_ROOT="${VISTA_ROOT:-/scratch/11034/atzanakak/biomni_vista}"
RL_PY="${RL_PY:-$VISTA_ROOT/envs/rl_harness312/bin/python}"
MODEL="${BIOMNI_RL_MODEL:-biomni/Biomni-R0-32B-Preview}"
PORT="${AGL_SERVER_PORT:-8181}"
KEY="${AGL_KEY:-biomni-vista}"
RUN_ID="${RUN_ID:-rl_harness_vista_smoke}"
LOG_DIR="$VISTA_ROOT/logs/$RUN_ID"

mkdir -p "$LOG_DIR" "$VISTA_ROOT/outputs/$RUN_ID" "$VISTA_ROOT/checkpoints/$RUN_ID" "$VISTA_ROOT/ray"
export PYTHONPATH="$ROOT/scripts/rl_harness:${PYTHONPATH:-}"
export HF_HOME="$VISTA_ROOT/hf_cache"
export RAY_TMPDIR="$VISTA_ROOT/ray"
export BIOMNI_PATH="$VISTA_ROOT/biomni_data_root"
export BIOMNI_UNC_OUTPUT_ROOT="$VISTA_ROOT/outputs"
export BIOMNI_UNC_SCRATCH="$VISTA_ROOT/tmp"
export BIOMNI_RL_PROJECT_ROOT="$ROOT"
export BIOMNI_RL_PYTHON="$VISTA_ROOT/envs/biomni_unc/bin/python"
export BIOMNI_RL_CONFIG_PATH="$ROOT/configs/rl_harness_smoke.yaml"
export BIOMNI_RL_OUTPUT_ROOT="$VISTA_ROOT/outputs"
export BIOMNI_RL_EXPERIMENT_ID="$RUN_ID"
export BIOMNI_RL_PROVENANCE_LOG="$VISTA_ROOT/outputs/$RUN_ID/provenance.jsonl"
export BIOMNI_RL_TIMEOUT_SECONDS="3720"
export BIOMNI_RL_MAX_TOKENS="2048"
export BIOMNI_RL_TEMPERATURE="0.7"
export BIOMNI_RL_MODEL="$MODEL"

server_pid=""
controller_pid=""
cleanup() {
    [[ -n "$controller_pid" ]] && kill "$controller_pid" 2>/dev/null || true
    [[ -n "$server_pid" ]] && kill "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$RL_PY" -m agentlightning.server \
    "port=$PORT" "key=$KEY" "default_proxy.model_name=$MODEL" \
    >"$LOG_DIR/agl-server.log" 2>&1 &
server_pid=$!
for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null && break
    sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null

"$RL_PY" -m agentlightning.controller \
    runner_type=local "agl_server.url=http://127.0.0.1:$PORT" "agl_server.key=$KEY" \
    local_runner.maximum_size=2 local_runner.poll_interval=1 \
    >"$LOG_DIR/agl-controller.log" 2>&1 &
controller_pid=$!

"$RL_PY" "$ROOT/scripts/rl_harness/rl_harness_v1_launcher.py" \
    --experiment-id "$RUN_ID" \
    --model-path "$MODEL" \
    --checkpoint-dir "$VISTA_ROOT/checkpoints/$RUN_ID" \
    --groundtruth "$ROOT/manifests/phase1.groundtruth.jsonl" \
    --groundtruth "$ROOT/manifests/phase2b.groundtruth.jsonl" \
    --agl-base-url "http://127.0.0.1:$PORT" --agl-key "$KEY" \
    --n-gpus 1 --tp 1 --rollout-n 2 --train-batch-size 1 --micro-batch-size 1 \
    --lora-rank 8 --gpu-mem-util 0.82 --total-steps 1 --save-freq 1 --n-tasks 1
