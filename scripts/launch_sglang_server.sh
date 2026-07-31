#!/usr/bin/env bash
# Launch ONE SGLang replica bound to an explicit set of CUDA devices.
#
# Usage:
#   launch_sglang_server.sh --model PATH --port N --gpus 0,1 --log-dir DIR [options]
#
# Everything site-specific arrives as a flag; nothing is hardcoded.
set -euo pipefail

MODEL=""; PORT=""; GPUS=""; LOG_DIR="./logs"; TP=""
MEM_FRACTION="0.85"; CONTEXT_LENGTH="40960"; DTYPE="bfloat16"
TRUST_REMOTE_CODE="1"; OVERRIDE_ARGS=""; SERVER_PYTHON="${SERVER_PYTHON:-python}"
LABEL=""

usage() { sed -n '2,10p' "$0"; exit 2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)            MODEL="$2"; shift 2 ;;
    --port)             PORT="$2"; shift 2 ;;
    --gpus)             GPUS="$2"; shift 2 ;;
    --tp)               TP="$2"; shift 2 ;;
    --log-dir)          LOG_DIR="$2"; shift 2 ;;
    --mem-fraction)     MEM_FRACTION="$2"; shift 2 ;;
    --context-length)   CONTEXT_LENGTH="$2"; shift 2 ;;
    --dtype)            DTYPE="$2"; shift 2 ;;
    --override-args)    OVERRIDE_ARGS="$2"; shift 2 ;;
    --server-python)    SERVER_PYTHON="$2"; shift 2 ;;
    --label)            LABEL="$2"; shift 2 ;;
    --no-trust-remote-code) TRUST_REMOTE_CODE="0"; shift ;;
    -h|--help)          usage ;;
    *) echo "unknown flag: $1" >&2; usage ;;
  esac
done

[[ -n "$MODEL" && -n "$PORT" && -n "$GPUS" ]] || { echo "ERROR: --model, --port and --gpus are required" >&2; usage; }

# Tensor parallelism defaults to the number of GPUs bound to this replica.
if [[ -z "$TP" ]]; then TP="$(awk -F',' '{print NF}' <<< "$GPUS")"; fi
LABEL="${LABEL:-p${PORT}}"

mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/sglang_${LABEL}.log"

# Biomni-R0-32B-Preview ships FP32 weights (131 GB on disk). Without an explicit
# --dtype, SGLang follows config.json's torch_dtype ("float32") and needs ~131 GB
# of VRAM for weights alone. bfloat16 is the intended serving dtype.
ARGS=(
  -m sglang.launch_server
  --model-path "$MODEL"
  --host 0.0.0.0
  --port "$PORT"
  --tp "$TP"
  --dtype "$DTYPE"
  --mem-fraction-static "$MEM_FRACTION"
  --context-length "$CONTEXT_LENGTH"
)
[[ "$TRUST_REMOTE_CODE" == "1" ]] && ARGS+=(--trust-remote-code)
# Only set when the operator explicitly asks for context extension: it changes an
# experimental parameter and may degrade short-trajectory performance.
[[ -n "$OVERRIDE_ARGS" ]] && ARGS+=(--json-model-override-args "$OVERRIDE_ARGS")

echo "[launch_sglang_server] label=$LABEL gpus=$GPUS tp=$TP port=$PORT dtype=$DTYPE ctx=$CONTEXT_LENGTH"
echo "[launch_sglang_server] log=$LOG_FILE"
echo "[launch_sglang_server] cmd: $SERVER_PYTHON ${ARGS[*]}"

export CUDA_VISIBLE_DEVICES="$GPUS"
exec "$SERVER_PYTHON" "${ARGS[@]}" >>"$LOG_FILE" 2>&1
