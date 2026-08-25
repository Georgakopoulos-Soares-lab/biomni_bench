#!/usr/bin/env bash
# Frozen D-49 B.2 pilot.  Launch only after a genuine end-to-end smoke pass.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VISTA_ROOT="${VISTA_ROOT:-/scratch/11034/atzanakak/biomni_vista}"

export RUN_ID="${RUN_ID:-rl_harness_vista_frozen_pilot}"
export AGL_SERVER_PORT="${AGL_SERVER_PORT:-8182}"
export BIOMNI_RL_CONFIG_PATH="$ROOT/configs/rl_harness_pilot.yaml"
export RL_ROLLOUT_N=4
export RL_MAX_NUM_SEQS=4
export RL_TRAIN_BATCH_SIZE=16
export RL_TOTAL_STEPS=25
export RL_SAVE_FREQ=1
export RL_N_TASKS=200
# D-49 permits a standard rank 16--64; fix it before the first training run.
export RL_LORA_RANK=16

exec "$ROOT/scripts/rl_harness/run_vista_smoke.sh"
