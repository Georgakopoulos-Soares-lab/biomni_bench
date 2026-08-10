#!/usr/bin/env bash
# Launch a Phase-2B run, detached, resumable.
#
# Detached (setsid) so the run survives losing the shell, and resumable so it
# survives losing the allocation: re-running this exact command continues from
# the committed decision logs and the COMPLETE markers already on disk. Nothing
# is recomputed and no decision is revisited.
#
#   scripts/run_phase2b.sh <config> <manifest> [reserve_minutes]
#
# Requires an already-serving endpoint (see scripts/launch_node_servers.sh).
# BIOMNI_UNC_ENDPOINTS points at its endpoints.json.

set -euo pipefail

CONFIG="${1:?usage: run_phase2b.sh <config> <manifest> [reserve_minutes]}"
MANIFEST="${2:?usage: run_phase2b.sh <config> <manifest> [reserve_minutes]}"
RESERVE="${3:-25}"

: "${BIOMNI_UNC_OUTPUT_ROOT:?set BIOMNI_UNC_OUTPUT_ROOT}"
: "${BIOMNI_UNC_ENDPOINTS:?set BIOMNI_UNC_ENDPOINTS to the endpoints.json}"
AGENT_PYTHON="${BIOMNI_UNC_AGENT_PYTHON:-python}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="logs/phase2b_${STAMP}.log"

echo "config    : $CONFIG"
echo "manifest  : $MANIFEST"
echo "endpoints : $BIOMNI_UNC_ENDPOINTS"
echo "reserve   : ${RESERVE} min before SLURM_JOB_END_TIME"
echo "log       : $LOG"

# Refuse to start against an unverified manifest: a prospective run on a
# manifest that has drifted since freezing is not the pre-registered experiment.
"$AGENT_PYTHON" - "$MANIFEST" <<'PY'
import json, sys
sys.path.insert(0, "src")
from biomni_uncertainty.benchmark import ManifestEntry, manifest_hash
entries = [ManifestEntry(**json.loads(l)) for l in open(sys.argv[1]) if l.strip()]
print(f"manifest: {len(entries)} instances, hash {manifest_hash(entries)}")
PY

setsid nohup "$AGENT_PYTHON" scripts/phase2b_run.py \
    --config "$CONFIG" \
    --manifest "$MANIFEST" \
    --endpoints "$BIOMNI_UNC_ENDPOINTS" \
    --python "$AGENT_PYTHON" \
    --reserve-minutes "$RESERVE" \
    > "$LOG" 2>&1 &

echo "launched pid $! (detached)"
echo "follow with: tail -f $LOG"
echo "resume after a timeout by re-running this identical command."
