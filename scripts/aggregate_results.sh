#!/usr/bin/env bash
# Collect per-run records into Parquet/CSV analysis tables.
#   scripts/aggregate_results.sh configs/phase1.yaml
set -euo pipefail
CONFIG="${1:-configs/phase1.yaml}"
PY="${AGENT_PYTHON:-python}"
exec "$PY" -m biomni_uncertainty.cli aggregate --config "$CONFIG" "${@:2}"
