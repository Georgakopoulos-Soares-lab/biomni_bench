#!/usr/bin/env bash
# Submit the Phase-1 pilot, building the sbatch command from configs/cluster.yaml
# so that no account, partition or allocation is hardcoded in the repository.
#
#   scripts/run_phase1.sh [cluster.yaml] [experiment.yaml] [--dry-run]
#
# Refuses to submit while any cluster placeholder is unresolved, or while the
# frozen run manifest is missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_CONFIG="${1:-$HERE/configs/cluster.yaml}"
EXP_CONFIG="${2:-$HERE/configs/phase1.yaml}"
DRY_RUN=""
[[ "${3:-}" == "--dry-run" ]] && DRY_RUN="1"

PY="${AGENT_PYTHON:-python}"
cd "$HERE"

[[ -f "$CLUSTER_CONFIG" ]] || {
  echo "ERROR: $CLUSTER_CONFIG not found. Copy configs/cluster.example.yaml and fill it in." >&2
  exit 2
}

echo "== validating cluster config =="
"$PY" -m biomni_uncertainty.cli check-cluster --cluster-config "$CLUSTER_CONFIG"

read_cfg() { "$PY" -c "
import yaml
d = yaml.safe_load(open('$CLUSTER_CONFIG'))
for k in '$1'.split('.'):
    d = d[k]
print(d if d is not None else '')
"; }

ACCOUNT="$(read_cfg slurm.account)"
PARTITION="$(read_cfg slurm.partition)"
QOS="$(read_cfg slurm.qos)"
WALLTIME="$(read_cfg slurm.wall_time)"
NODES="$(read_cfg slurm.nodes)"
GPUS_PER_NODE="$(read_cfg slurm.gpus_per_node)"
CPUS_PER_TASK="$(read_cfg slurm.cpus_per_task)"
MEMORY="$(read_cfg slurm.memory)"
JOB_NAME="$(read_cfg slurm.job_name)"

EXP_NAME="$("$PY" -c "
from biomni_uncertainty.config import load_config
print(load_config('$EXP_CONFIG').experiment_id)")"
RUN_MANIFEST="manifests/${EXP_NAME}_runs.jsonl"

[[ -f "$RUN_MANIFEST" ]] || {
  echo "ERROR: $RUN_MANIFEST not found. Freeze the protocol first:" >&2
  echo "  python -m biomni_uncertainty.cli prepare-manifest --config $EXP_CONFIG" >&2
  echo "  python -m biomni_uncertainty.cli expand-runs --config $EXP_CONFIG --manifest manifests/${EXP_NAME}.jsonl" >&2
  exit 2
}
N_RUNS="$(wc -l < "$RUN_MANIFEST")"

CMD=(sbatch
  --account="$ACCOUNT"
  --partition="$PARTITION"
  --nodes="$NODES"
  --gres=gpu:"$GPUS_PER_NODE"
  --cpus-per-task="$CPUS_PER_TASK"
  --time="$WALLTIME"
  --job-name="$JOB_NAME"
)
[[ -n "$QOS" ]] && CMD+=(--qos="$QOS")
[[ -n "$MEMORY" && "$MEMORY" != "0" ]] && CMD+=(--mem="$MEMORY")
CMD+=("$HERE/slurm/phase1_two_nodes.sbatch" "$CLUSTER_CONFIG" "$EXP_CONFIG")

echo
echo "== planned submission =="
echo "experiment    : $EXP_NAME"
echo "run manifest  : $RUN_MANIFEST ($N_RUNS runs)"
echo "nodes x gpus  : $NODES x $GPUS_PER_NODE"
echo "wall time     : $WALLTIME"
echo "command       : ${CMD[*]}"
echo

if [[ -n "$DRY_RUN" ]]; then
  echo "[dry-run] not submitting"
  exit 0
fi

mkdir -p logs
exec "${CMD[@]}"
