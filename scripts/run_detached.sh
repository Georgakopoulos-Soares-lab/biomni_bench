#!/usr/bin/env bash
# Run a full experiment detached from the terminal, on an interactive allocation
# whose model replicas are ALREADY running.
#
#   scripts/run_detached.sh <cluster.yaml> <experiment.yaml> <endpoints.json> [concurrency]
#
# Intended to be started with setsid+nohup so it survives the login session:
#
#   setsid nohup scripts/run_detached.sh configs/cluster.yaml configs/phase1.yaml \
#          "$JOB_DIR/endpoints.json" 4 > "$JOB_DIR/supervisor.log" 2>&1 < /dev/null &
#
# It dispatches (resuming any completed runs), then aggregates and analyzes.
# Every stage is safe to re-run: the dispatcher skips valid COMPLETE runs, and
# aggregation/analysis are pure functions of what is on disk. If the allocation
# ends mid-flight, re-running this script continues from where it stopped.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_CONFIG="${1:?usage: run_detached.sh <cluster.yaml> <experiment.yaml> <endpoints.json> [concurrency]}"
EXP_CONFIG="${2:?usage: run_detached.sh <cluster.yaml> <experiment.yaml> <endpoints.json> [concurrency]}"
ENDPOINTS="${3:?usage: run_detached.sh <cluster.yaml> <experiment.yaml> <endpoints.json> [concurrency]}"
CONCURRENCY="${4:-}"

cd "$HERE"

read_cfg() { "${AGENT_PYTHON:-python}" -c "
import yaml
d = yaml.safe_load(open('$CLUSTER_CONFIG'))
for k in '$1'.split('.'):
    d = d[k]
print(d if d is not None else '')
"; }

export AGENT_PYTHON="${AGENT_PYTHON:-python}"
PY="$AGENT_PYTHON"

export BIOMNI_SRC="$(read_cfg paths.biomni_src)"
export BIOMNI_PATH="$(read_cfg paths.data_lake_root)"
export HF_HOME="$(read_cfg paths.hf_home)"
export BIOMNI_UNC_OUTPUT_ROOT="$(read_cfg paths.output_root)"
export BIOMNI_UNC_SCRATCH="$(read_cfg paths.node_scratch)"
export BIOMNI_CUSTOM_API_KEY="EMPTY"
# Phase 1 must never reach a paid provider.
unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GROQ_API_KEY AZURE_OPENAI_API_KEY || true

EXP_NAME="$("$PY" -c "
from biomni_uncertainty.config import load_config
print(load_config('$EXP_CONFIG').experiment_id)")"
RUN_MANIFEST="manifests/${EXP_NAME}_runs.jsonl"

if [[ ! -f "$RUN_MANIFEST" ]]; then
  echo "FATAL: $RUN_MANIFEST not found. Freeze the protocol first." >&2
  exit 2
fi

echo "=================================================================="
echo "detached run   : $EXP_NAME"
echo "started        : $(date -Is)"
echo "host           : $(hostname -s)   pid=$$"
echo "run manifest   : $RUN_MANIFEST ($(wc -l < "$RUN_MANIFEST") runs)"
echo "endpoints      : $ENDPOINTS"
echo "concurrency    : ${CONCURRENCY:-<config default>}"
echo "output root    : $BIOMNI_UNC_OUTPUT_ROOT"
echo "=================================================================="

CONC_ARGS=()
if [[ -n "$CONCURRENCY" ]]; then
  CONC_ARGS=(--max-concurrent-per-endpoint "$CONCURRENCY"
             --set "execution.max_concurrency=$CONCURRENCY")
fi

echo "== dispatch =="
"$PY" -m biomni_uncertainty.cli dispatch \
    --config "$EXP_CONFIG" \
    --run-manifest "$RUN_MANIFEST" \
    --endpoints "$ENDPOINTS" \
    --python "$PY" \
    "${CONC_ARGS[@]}"
DISPATCH_RC=$?
echo "dispatch exit code: $DISPATCH_RC"

# Aggregation and analysis run even after a partial dispatch: a partial result
# set is still worth inspecting, and missing runs show up as findings.
echo "== aggregate =="
"$PY" -m biomni_uncertainty.cli aggregate --config "$EXP_CONFIG"

echo "== analyze =="
"$PY" -m biomni_uncertainty.cli analyze --config "$EXP_CONFIG"

echo "== status =="
"$PY" -m biomni_uncertainty.cli status --config "$EXP_CONFIG"

echo "finished: $(date -Is)"
exit "$DISPATCH_RC"
