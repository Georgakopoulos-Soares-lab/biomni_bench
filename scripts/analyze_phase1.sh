#!/usr/bin/env bash
# Run the frozen Phase-1 analysis and generate every figure and table.
#   scripts/analyze_phase1.sh configs/phase1.yaml
set -euo pipefail
CONFIG="${1:-configs/phase1.yaml}"
PY="${AGENT_PYTHON:-python}"
exec "$PY" -m biomni_uncertainty.cli analyze --config "$CONFIG" "${@:2}"
