#!/usr/bin/env bash
# Phase-1 pilot on N GPU nodes.
#
# All #SBATCH directives that are site-specific are intentionally LEFT OUT of this
# file and supplied on the command line, so no institution, allocation or
# partition is baked into the repository:
#
#   sbatch --account=$ACCOUNT --partition=$PARTITION --qos=$QOS \
#          --nodes=$NODES --gres=gpu:$GPUS_PER_NODE --time=$WALLTIME \
#          --job-name=biomni-unc-phase1 \
#          slurm/phase1_two_nodes.sbatch configs/cluster.yaml configs/phase1.yaml
#
# scripts/run_phase1.sh generates this command from configs/cluster.yaml.
#SBATCH --output=logs/slurm-%j.out
#SBATCH --error=logs/slurm-%j.err

set -euo pipefail

CLUSTER_CONFIG="${1:?usage: phase1_two_nodes.sbatch <cluster.yaml> <experiment.yaml>}"
EXP_CONFIG="${2:?usage: phase1_two_nodes.sbatch <cluster.yaml> <experiment.yaml>}"

# ---- read the cluster config (yq-free: a tiny python reader) --------------
read_cfg() { "$AGENT_PYTHON_BOOTSTRAP" -c "
import sys, yaml
d = yaml.safe_load(open('$CLUSTER_CONFIG'))
for k in '$1'.split('.'):
    d = d[k]
print(d if d is not None else '')
"; }

AGENT_PYTHON_BOOTSTRAP="${AGENT_PYTHON_BOOTSTRAP:-python3}"

PROJECT_ROOT="$(read_cfg paths.project_root)"
BIOMNI_SRC="$(read_cfg paths.biomni_src)"
DATA_LAKE_ROOT="$(read_cfg paths.data_lake_root)"
NODE_SCRATCH="$(read_cfg paths.node_scratch)"
MODEL_PATH="$(read_cfg paths.model_path)"
HF_HOME_CFG="$(read_cfg paths.hf_home)"
AGENT_PYTHON="$(read_cfg paths.agent_python)"
SERVER_PYTHON="$(read_cfg paths.server_python)"
OUTPUT_ROOT="$(read_cfg paths.output_root)"

LAYOUT="$(read_cfg serving.layout)"
BASE_PORT="$(read_cfg serving.base_port)"
MEM_FRACTION="$(read_cfg serving.mem_fraction_static)"
CONTEXT_LENGTH="$(read_cfg serving.context_length)"
DTYPE="$(read_cfg serving.dtype)"
OVERRIDE_ARGS="$(read_cfg serving.json_model_override_args)"
STARTUP_TIMEOUT="$(read_cfg serving.startup_timeout_seconds)"
POLL_INTERVAL="$(read_cfg serving.health_poll_interval_seconds)"
MAX_PER_ENDPOINT="$(read_cfg dispatch.max_concurrent_per_endpoint)"

cd "$PROJECT_ROOT"

export BIOMNI_SRC BIOMNI_PATH="$DATA_LAKE_ROOT" HF_HOME="$HF_HOME_CFG"
export BIOMNI_UNC_OUTPUT_ROOT="$OUTPUT_ROOT"
export BIOMNI_UNC_SCRATCH="$NODE_SCRATCH"
export BIOMNI_CUSTOM_API_KEY="EMPTY"
export PYTHONPATH="$PROJECT_ROOT/src:${PYTHONPATH:-}"
# Phase 1 must never reach a paid provider. Unset any inherited provider keys.
unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GROQ_API_KEY AZURE_OPENAI_API_KEY || true

JOB_DIR="${OUTPUT_ROOT}/_job_${SLURM_JOB_ID:-local}"
ENDPOINTS_DIR="${JOB_DIR}/endpoints"
SERVER_LOG_DIR="${JOB_DIR}/server_logs"
mkdir -p "$ENDPOINTS_DIR" "$SERVER_LOG_DIR" logs

N_NODES="${SLURM_JOB_NUM_NODES:-1}"
echo "=================================================================="
echo "Phase-1 pilot | job=${SLURM_JOB_ID:-local} nodes=$N_NODES"
echo "cluster config : $CLUSTER_CONFIG"
echo "experiment cfg : $EXP_CONFIG"
echo "endpoints dir  : $ENDPOINTS_DIR"
echo "server logs    : $SERVER_LOG_DIR   (preserved after the job)"
echo "=================================================================="

# ---- 1. start replicas on every allocated node ---------------------------
srun --nodes="$N_NODES" --ntasks="$N_NODES" --ntasks-per-node=1 --gres=gpu:"${SLURM_GPUS_ON_NODE:-4}" \
     bash "$PROJECT_ROOT/scripts/launch_node_servers.sh" \
       --model "$MODEL_PATH" \
       --endpoints-dir "$ENDPOINTS_DIR" \
       --log-dir "$SERVER_LOG_DIR" \
       --base-port "$BASE_PORT" \
       --layout "$LAYOUT" \
       --mem-fraction "$MEM_FRACTION" \
       --context-length "$CONTEXT_LENGTH" \
       --dtype "$DTYPE" \
       --server-python "$SERVER_PYTHON" \
       --max-concurrent "$MAX_PER_ENDPOINT" \
       ${OVERRIDE_ARGS:+--override-args "$OVERRIDE_ARGS"} &
SERVERS_PID=$!

shutdown_servers() {
  echo "[phase1] stopping model servers"
  kill -TERM "$SERVERS_PID" 2>/dev/null || true
  wait "$SERVERS_PID" 2>/dev/null || true
}
trap shutdown_servers EXIT INT TERM

# ---- 2. wait for every replica, then aggregate endpoints.json ------------
if ! "$AGENT_PYTHON" "$PROJECT_ROOT/scripts/wait_for_server.py" \
        --aggregate --endpoints-dir "$ENDPOINTS_DIR" \
        --expected-nodes "$N_NODES" \
        --output "${JOB_DIR}/endpoints.json" \
        --timeout "$STARTUP_TIMEOUT" --interval "$POLL_INTERVAL"; then
  echo "[phase1] FATAL: model servers never became ready. Not starting the dispatcher." >&2
  exit 1
fi

# ---- 3. record provenance -------------------------------------------------
"$AGENT_PYTHON" -m biomni_uncertainty.cli inspect-env \
    --output "${JOB_DIR}/environment_manifest.json" > "${JOB_DIR}/inspect_env.txt" || true

# ---- 4. dispatch ----------------------------------------------------------
EXP_NAME="$("$AGENT_PYTHON" -c "
from biomni_uncertainty.config import load_config
print(load_config('$EXP_CONFIG').experiment_id)")"

"$AGENT_PYTHON" -m biomni_uncertainty.cli dispatch \
    --config "$EXP_CONFIG" \
    --run-manifest "manifests/${EXP_NAME}_runs.jsonl" \
    --endpoints "${JOB_DIR}/endpoints.json" \
    --python "$AGENT_PYTHON"
DISPATCH_RC=$?

# ---- 5. aggregate + analyze (safe to re-run after a resume) ---------------
"$AGENT_PYTHON" -m biomni_uncertainty.cli aggregate --config "$EXP_CONFIG" || true
"$AGENT_PYTHON" -m biomni_uncertainty.cli status --config "$EXP_CONFIG" || true

echo "[phase1] dispatch exit code: $DISPATCH_RC"
echo "[phase1] server logs preserved under $SERVER_LOG_DIR"
exit "$DISPATCH_RC"
