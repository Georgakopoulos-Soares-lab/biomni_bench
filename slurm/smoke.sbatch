#!/usr/bin/env bash
# Single-node GPU smoke test: 2 instances x (2 instrumented + 1 standard) = 6 runs.
#
#   sbatch --account=$ACCOUNT --partition=$PARTITION --nodes=1 \
#          --gres=gpu:4 --time=02:00:00 --job-name=biomni-unc-smoke \
#          slurm/smoke.sbatch configs/cluster.yaml configs/smoke.yaml
#
# Site-specific #SBATCH values are passed on the command line, never hardcoded.
#SBATCH --output=logs/slurm-smoke-%j.out
#SBATCH --error=logs/slurm-smoke-%j.err

set -euo pipefail
exec bash "$(dirname "${BASH_SOURCE[0]}")/phase1_two_nodes.sbatch" "$@"
