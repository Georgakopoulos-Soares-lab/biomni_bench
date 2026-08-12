#!/usr/bin/env bash
# Submit the Stage C verdict run.
#
# MUST be run from a LOGIN node: sbatch is refused on compute nodes.
#
#   slurm/submit_stage_c.sh -A <account> [-p h100] [-t 06:00:00]
#
# Every site path is read from configs/cluster.yaml (gitignored), so nothing
# site-specific lives in the repo. Only the account is required.
set -euo pipefail

ACCOUNT=""; PARTITION="h100"; WALLTIME="06:00:00"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -A|--account)   ACCOUNT="$2"; shift 2 ;;
    -p|--partition) PARTITION="$2"; shift 2 ;;
    -t|--time)      WALLTIME="$2"; shift 2 ;;
    -h|--help)      sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done
[[ -n "${ACCOUNT}" ]] || { echo "ERROR: -A <account> is required" >&2; exit 2; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${REPO}/configs/cluster.yaml"
[[ -f "${CFG}" ]] || { echo "ERROR: ${CFG} not found" >&2; exit 2; }

get() {  # get <key> - first matching "key: value" under paths:
  sed -n "s/^[[:space:]]*$1:[[:space:]]*\"\{0,1\}\([^\"]*\)\"\{0,1\}[[:space:]]*$/\1/p" "${CFG}" | head -1
}

PROJECT_ROOT="$(get project_root)"
C2_MODEL="$(get model_path)"
C1_MODEL="$(get verifier_c1_model_path)"
SERVER_PYTHON="$(get server_python)"
AGENT_PYTHON="$(get agent_python)"
HF_HOME_DIR="$(get hf_home)"
OUTPUT_ROOT="$(get output_root)"
STAGE_C_OUT="${OUTPUT_ROOT}/stage_c"

for v in PROJECT_ROOT C2_MODEL C1_MODEL SERVER_PYTHON AGENT_PYTHON OUTPUT_ROOT; do
  [[ -n "${!v}" ]] || { echo "ERROR: ${v} missing from ${CFG}" >&2; exit 2; }
done
[[ -f "${STAGE_C_OUT}/capsules.jsonl" ]] || {
  echo "ERROR: ${STAGE_C_OUT}/capsules.jsonl not found - run 'stage_c_run.py prep' first" >&2
  exit 2
}

# The run itself refuses a dirty tree (D-36); fail here too, before queueing.
if [[ -n "$(git -C "${REPO}" status --porcelain)" ]]; then
  echo "ERROR: working tree is dirty - commit before launching (D-36)" >&2
  git -C "${REPO}" status --short >&2
  exit 1
fi

echo "submitting Stage C verdict: account=${ACCOUNT} partition=${PARTITION} time=${WALLTIME}"
echo "  commit  : $(git -C "${REPO}" rev-parse HEAD)"
echo "  out     : ${STAGE_C_OUT}"

exec sbatch -A "${ACCOUNT}" -p "${PARTITION}" -t "${WALLTIME}" \
  --export=ALL,STAGE_C_OUT="${STAGE_C_OUT}",PROJECT_ROOT="${PROJECT_ROOT}",\
C1_MODEL="${C1_MODEL}",C2_MODEL="${C2_MODEL}",SERVER_PYTHON="${SERVER_PYTHON}",\
AGENT_PYTHON="${AGENT_PYTHON}",HF_HOME="${HF_HOME_DIR}" \
  "${REPO}/slurm/stage_c_verdict.sbatch"
