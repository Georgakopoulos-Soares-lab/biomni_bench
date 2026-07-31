#!/usr/bin/env bash
# GPU smoke test WITHOUT Slurm: start replicas on the current node, wait for
# health, run the 6 smoke trajectories, aggregate and analyze.
#
#   scripts/run_smoke.sh [cluster.yaml] [experiment.yaml]
#
# Use this on an interactive GPU allocation. For a batch submission use
# slurm/smoke.sbatch instead.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_CONFIG="${1:-$HERE/configs/cluster.yaml}"
EXP_CONFIG="${2:-$HERE/configs/smoke.yaml}"
PY="${AGENT_PYTHON:-python}"
cd "$HERE"

read_cfg() { "$PY" -c "
import yaml
d = yaml.safe_load(open('$CLUSTER_CONFIG'))
for k in '$1'.split('.'):
    d = d[k]
print(d if d is not None else '')
"; }

MODEL_PATH="$(read_cfg paths.model_path)"
SERVER_PYTHON="$(read_cfg paths.server_python)"
AGENT_PYTHON_CFG="$(read_cfg paths.agent_python)"
OUTPUT_ROOT="$(read_cfg paths.output_root)"
DATA_LAKE_ROOT="$(read_cfg paths.data_lake_root)"
HF_HOME_CFG="$(read_cfg paths.hf_home)"
BIOMNI_SRC_CFG="$(read_cfg paths.biomni_src)"
LAYOUT="$(read_cfg serving.layout)"
BASE_PORT="$(read_cfg serving.base_port)"
MEM_FRACTION="$(read_cfg serving.mem_fraction_static)"
CONTEXT_LENGTH="$(read_cfg serving.context_length)"
DTYPE="$(read_cfg serving.dtype)"
OVERRIDE_ARGS="$(read_cfg serving.json_model_override_args)"
STARTUP_TIMEOUT="$(read_cfg serving.startup_timeout_seconds)"
POLL_INTERVAL="$(read_cfg serving.health_poll_interval_seconds)"
MAX_PER_ENDPOINT="$(read_cfg dispatch.max_concurrent_per_endpoint)"

export BIOMNI_SRC="$BIOMNI_SRC_CFG" BIOMNI_PATH="$DATA_LAKE_ROOT" HF_HOME="$HF_HOME_CFG"
export BIOMNI_UNC_OUTPUT_ROOT="$OUTPUT_ROOT" BIOMNI_CUSTOM_API_KEY="EMPTY"
unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GROQ_API_KEY AZURE_OPENAI_API_KEY || true

JOB_DIR="${OUTPUT_ROOT}/_job_smoke_$$"
ENDPOINTS_DIR="${JOB_DIR}/endpoints"
SERVER_LOG_DIR="${JOB_DIR}/server_logs"
mkdir -p "$ENDPOINTS_DIR" "$SERVER_LOG_DIR" logs

echo "== 1/6 starting model replicas on $(hostname -s) =="
bash "$HERE/scripts/launch_node_servers.sh" \
    --model "$MODEL_PATH" --endpoints-dir "$ENDPOINTS_DIR" --log-dir "$SERVER_LOG_DIR" \
    --base-port "$BASE_PORT" --layout "$LAYOUT" --mem-fraction "$MEM_FRACTION" \
    --context-length "$CONTEXT_LENGTH" --dtype "$DTYPE" \
    --server-python "$SERVER_PYTHON" --max-concurrent "$MAX_PER_ENDPOINT" \
    ${OVERRIDE_ARGS:+--override-args "$OVERRIDE_ARGS"} &
SERVERS_PID=$!
trap 'echo "[smoke] stopping servers"; kill -TERM "$SERVERS_PID" 2>/dev/null || true; wait "$SERVERS_PID" 2>/dev/null || true' EXIT INT TERM

echo "== 2/6 waiting for replicas to become healthy =="
"$PY" "$HERE/scripts/wait_for_server.py" --aggregate --endpoints-dir "$ENDPOINTS_DIR" \
    --expected-nodes 1 --output "${JOB_DIR}/endpoints.json" \
    --timeout "$STARTUP_TIMEOUT" --interval "$POLL_INTERVAL"

echo "== 3/6 freezing the smoke manifest =="
"$PY" -m biomni_uncertainty.cli prepare-manifest --config "$EXP_CONFIG" \
    --output manifests/smoke.jsonl
"$PY" -m biomni_uncertainty.cli expand-runs --config "$EXP_CONFIG" \
    --manifest manifests/smoke.jsonl --output manifests/smoke_runs.jsonl

echo "== 4/6 dispatching smoke trajectories =="
"$PY" -m biomni_uncertainty.cli dispatch --config "$EXP_CONFIG" \
    --run-manifest manifests/smoke_runs.jsonl \
    --endpoints "${JOB_DIR}/endpoints.json" \
    --python "${AGENT_PYTHON_CFG:-$PY}"

echo "== 5/6 aggregating =="
"$PY" -m biomni_uncertainty.cli aggregate --config "$EXP_CONFIG"

echo "== 6/6 analyzing (generates figures) =="
"$PY" -m biomni_uncertainty.cli analyze --config "$EXP_CONFIG"

echo
echo "smoke test finished. Server logs: $SERVER_LOG_DIR"
