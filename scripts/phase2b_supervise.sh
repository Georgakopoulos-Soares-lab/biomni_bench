#!/usr/bin/env bash
# Unattended Phase-2B supervisor: wait for the smoke, check the gates, launch.
#
# Exists so the smoke -> verify -> launch sequence survives losing the terminal,
# the SSH connection, or the operator's machine. Everything it starts is
# setsid'd and re-parented to init.
#
# It implements DEV-2 exactly as approved: the full run launches ONLY if every
# fatal gate in reports/phase2_protocol.md §10 passes, as judged by
# scripts/phase2b_verify.py. A gate failure blocks the launch and leaves a
# report; it never "proceeds anyway".
#
# Status is written to logs/phase2b_STATUS so progress is legible without
# reading any log:
#   WAITING_FOR_SMOKE -> VERIFYING -> {BLOCKED_GATES_FAILED | FULL_RUN_LAUNCHED}
#
#   scripts/phase2b_supervise.sh

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

export BIOMNI_UNC_OUTPUT_ROOT="${BIOMNI_UNC_OUTPUT_ROOT:-/scratch/11034/atzanakak/biomni_unc_runs}"
export BIOMNI_UNC_EVAL1_PARQUET="${BIOMNI_UNC_EVAL1_PARQUET:-/scratch/11034/atzanakak/biomni_eval1_dataset.parquet}"
export BIOMNI_PATH="${BIOMNI_PATH:-/scratch/11034/atzanakak/biomni_data_root}"
export BIOMNI_UNC_SCRATCH="${BIOMNI_UNC_SCRATCH:-/tmp/biomni_unc_scratch}"

PY="${BIOMNI_UNC_AGENT_PYTHON:-/scratch/11034/atzanakak/envs/biomni_unc/bin/python}"
ENDPOINTS="${BIOMNI_UNC_ENDPOINTS:-$BIOMNI_UNC_OUTPUT_ROOT/endpoints_phase2b.json}"
RESERVE="${PHASE2B_RESERVE_MINUTES:-25}"

STATUS=logs/phase2b_STATUS
say() { echo "[$(date '+%F %T')] $*" | tee -a logs/phase2b_supervisor.log; }
set_status() { echo "$1" > "$STATUS"; say "STATUS -> $1"; }

say "supervisor pid $$ starting; endpoints=$ENDPOINTS reserve=${RESERVE}min"

# ---------------------------------------------------------------- 1. smoke
# Wait on the driver's own completion artifact, not on pgrep: a -f pattern also
# matches any shell whose command line happens to contain it (e.g. a snapshot
# script that sources this file's own invocation), which silently turns "wait
# for the smoke" into "wait forever". If the summary is already there (a prior
# smoke run already finished), this returns immediately.
SMOKE_SUMMARY="$BIOMNI_UNC_OUTPUT_ROOT/phase2b_smoke/phase2b_run_summary.json"
set_status WAITING_FOR_SMOKE
say "waiting for $SMOKE_SUMMARY"
WAITED=0
while [ ! -f "$SMOKE_SUMMARY" ]; do
    sleep 30
    WAITED=$((WAITED + 30))
    if [ "$WAITED" -ge 7200 ]; then
        set_status BLOCKED_SMOKE_TIMEOUT
        say "FATAL: smoke did not finish within 2h; not launching."
        exit 1
    fi
done
say "smoke finished: $(tr -d '\n' < "$SMOKE_SUMMARY" | cut -c1-400)"

# ---------------------------------------------------------------- 2. gates
set_status VERIFYING
"$PY" scripts/phase2b_verify.py \
    --config configs/phase2b_smoke.yaml \
    --manifest manifests/phase2b_smoke.jsonl \
    --smoke > logs/phase2b_smoke_gates.log 2>&1
GATE_RC=$?
say "gate verification exit code $GATE_RC"
tail -30 logs/phase2b_smoke_gates.log | tee -a logs/phase2b_supervisor.log

if [ "$GATE_RC" -ne 0 ]; then
    set_status BLOCKED_GATES_FAILED
    say "FATAL GATE(S) FAILED - the full run was NOT launched. See logs/phase2b_smoke_gates.log"
    exit 1
fi

# ------------------------------------------------------------- 3. full run
say "all fatal gates passed; launching the frozen prospective run"
"$PY" - <<'PY' 2>&1 | tee -a logs/phase2b_supervisor.log
import json, sys
sys.path.insert(0, "src")
from biomni_uncertainty.benchmark import ManifestEntry, manifest_hash
e = [ManifestEntry(**json.loads(l)) for l in open("manifests/phase2b.jsonl") if l.strip()]
h = manifest_hash(e)
expected = "7cb5da3ac345a4a3274c0c33845cdbf886fcea75867985121511e5dcfa1fb2cd"
print(f"manifest {len(e)} instances hash {h}")
sys.exit(0 if h == expected else 1)
PY
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
    set_status BLOCKED_MANIFEST_HASH_MISMATCH
    say "FATAL: manifests/phase2b.jsonl no longer matches its pre-registered hash. Not launching."
    exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
FULL_LOG="logs/phase2b_full_${STAMP}.log"
setsid nohup "$PY" scripts/phase2b_run.py \
    --config configs/phase2b.yaml \
    --manifest manifests/phase2b.jsonl \
    --endpoints "$ENDPOINTS" \
    --python "$PY" \
    --reserve-minutes "$RESERVE" \
    > "$FULL_LOG" 2>&1 < /dev/null &

say "full run launched, pid $!, log $FULL_LOG"
set_status FULL_RUN_LAUNCHED
echo "$FULL_LOG" > logs/phase2b_full_logpath
say "supervisor done. Resume after an allocation timeout with:"
say "  scripts/run_phase2b.sh configs/phase2b.yaml manifests/phase2b.jsonl ${RESERVE}"
exit 0
