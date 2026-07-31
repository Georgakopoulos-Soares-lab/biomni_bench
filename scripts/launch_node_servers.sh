#!/usr/bin/env bash
# Launch every SGLang replica for ONE node and publish its endpoints.
#
# Layout selection (--layout auto):
#   GPU memory >= 70 GB  -> TP2, two replicas per 4-GPU node   (GPUs 0,1 and 2,3)
#   GPU memory <  70 GB  -> TP4, one replica per 4-GPU node
# Override with --layout tp2 | tp4.
#
# Endpoint publication avoids races: each node writes its OWN file
#   <endpoints-dir>/node_<hostname>.json
# and the coordinator (wait_for_server.py --aggregate) merges them into
# endpoints.json once every expected node has reported.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODEL=""; ENDPOINTS_DIR=""; LOG_DIR="./logs"; BASE_PORT="30000"
LAYOUT="auto"; MEM_FRACTION="0.85"; CONTEXT_LENGTH="40960"; DTYPE="bfloat16"
OVERRIDE_ARGS=""; SERVER_PYTHON="${SERVER_PYTHON:-python}"
GPUS_PER_NODE=""; MAX_CONCURRENT="1"

usage() { sed -n '2,12p' "$0"; exit 2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)           MODEL="$2"; shift 2 ;;
    --endpoints-dir)   ENDPOINTS_DIR="$2"; shift 2 ;;
    --log-dir)         LOG_DIR="$2"; shift 2 ;;
    --base-port)       BASE_PORT="$2"; shift 2 ;;
    --layout)          LAYOUT="$2"; shift 2 ;;
    --mem-fraction)    MEM_FRACTION="$2"; shift 2 ;;
    --context-length)  CONTEXT_LENGTH="$2"; shift 2 ;;
    --dtype)           DTYPE="$2"; shift 2 ;;
    --override-args)   OVERRIDE_ARGS="$2"; shift 2 ;;
    --server-python)   SERVER_PYTHON="$2"; shift 2 ;;
    --gpus-per-node)   GPUS_PER_NODE="$2"; shift 2 ;;
    --max-concurrent)  MAX_CONCURRENT="$2"; shift 2 ;;
    -h|--help)         usage ;;
    *) echo "unknown flag: $1" >&2; usage ;;
  esac
done

[[ -n "$MODEL" && -n "$ENDPOINTS_DIR" ]] || { echo "ERROR: --model and --endpoints-dir are required" >&2; usage; }

mkdir -p "$ENDPOINTS_DIR" "$LOG_DIR"
HOST="$(hostname -s)"
HOST_FQDN="$(hostname -f 2>/dev/null || hostname)"

# ---- inspect GPUs --------------------------------------------------------
mapfile -t GPU_MEM < <(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)
N_GPU="${GPUS_PER_NODE:-${#GPU_MEM[@]}}"
if (( N_GPU == 0 )); then echo "ERROR: no GPUs visible on $HOST" >&2; exit 1; fi
MIN_MEM_MIB="${GPU_MEM[0]}"
for m in "${GPU_MEM[@]:0:$N_GPU}"; do (( m < MIN_MEM_MIB )) && MIN_MEM_MIB="$m"; done
MIN_MEM_GB=$(( MIN_MEM_MIB / 1024 ))

echo "[launch_node_servers] host=$HOST gpus=$N_GPU min_gpu_mem=${MIN_MEM_GB}GB layout=$LAYOUT"

if [[ "$LAYOUT" == "auto" ]]; then
  if (( MIN_MEM_GB >= 70 )); then LAYOUT="tp2"; else LAYOUT="tp4"; fi
  echo "[launch_node_servers] auto-selected layout=$LAYOUT"
fi

case "$LAYOUT" in
  tp2) TP=2 ;;
  tp4) TP=4 ;;
  *) echo "ERROR: unknown layout '$LAYOUT' (expected auto|tp2|tp4)" >&2; exit 2 ;;
esac

N_REPLICAS=$(( N_GPU / TP ))
if (( N_REPLICAS < 1 )); then
  echo "ERROR: layout $LAYOUT needs $TP GPUs but only $N_GPU are visible" >&2; exit 1
fi
echo "[launch_node_servers] starting $N_REPLICAS replica(s) with tp=$TP"

# ---- launch --------------------------------------------------------------
PIDS=(); PORTS=(); LABELS=()
for (( r=0; r<N_REPLICAS; r++ )); do
  first=$(( r * TP ))
  gpu_list="$first"
  for (( g=1; g<TP; g++ )); do gpu_list="${gpu_list},$(( first + g ))"; done
  port=$(( BASE_PORT + r ))
  label="${HOST}_r${r}"

  "$HERE/launch_sglang_server.sh" \
      --model "$MODEL" --port "$port" --gpus "$gpu_list" --tp "$TP" \
      --log-dir "$LOG_DIR" --mem-fraction "$MEM_FRACTION" \
      --context-length "$CONTEXT_LENGTH" --dtype "$DTYPE" \
      --server-python "$SERVER_PYTHON" --label "$label" \
      ${OVERRIDE_ARGS:+--override-args "$OVERRIDE_ARGS"} &
  PIDS+=("$!"); PORTS+=("$port"); LABELS+=("$label")
  echo "[launch_node_servers] replica $r: gpus=$gpu_list port=$port pid=$! label=$label"
done

# Shut every replica down cleanly when this script exits, however it exits.
cleanup() {
  echo "[launch_node_servers] shutting down replicas on $HOST"
  for pid in "${PIDS[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  sleep 10
  for pid in "${PIDS[@]}"; do kill -KILL "$pid" 2>/dev/null || true; done
  rm -f "${ENDPOINTS_DIR}/node_${HOST}.json"
}
trap cleanup EXIT INT TERM

# ---- publish this node's endpoints atomically ----------------------------
NODE_FILE="${ENDPOINTS_DIR}/node_${HOST}.json"
{
  printf '{"host": "%s", "layout": "%s", "tp": %d, "gpus_per_node": %d, "endpoints": [' \
         "$HOST_FQDN" "$LAYOUT" "$TP" "$N_GPU"
  for (( r=0; r<N_REPLICAS; r++ )); do
    (( r > 0 )) && printf ', '
    printf '{"url": "http://%s:%s/v1", "label": "%s", "max_concurrent": %s}' \
           "$HOST_FQDN" "${PORTS[$r]}" "${LABELS[$r]}" "$MAX_CONCURRENT"
  done
  printf ']}\n'
} > "${NODE_FILE}.tmp"
mv -f "${NODE_FILE}.tmp" "$NODE_FILE"   # atomic rename: readers never see a partial file
echo "[launch_node_servers] published $NODE_FILE"

# Stay alive so the trap runs when the allocation ends or the coordinator stops us.
wait
