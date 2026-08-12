#!/usr/bin/env bash
#SBATCH --job-name=stage_c_verdict
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --output=%x-%j.out
#SBATCH --error=%x-%j.out
#
# Stage C — the frozen verdict run, both cells, one node.
#
# Submit with account/partition/time supplied on the command line; nothing
# site-specific is hardcoded here (CLAUDE.md coding standards):
#
#   sbatch -A <account> -p <partition> -t 06:00:00 \
#          --export=ALL,STAGE_C_OUT=<dir>,PROJECT_ROOT=<repo>,\
# C1_MODEL=<path>,C2_MODEL=<path>,SERVER_PYTHON=<py>,AGENT_PYTHON=<py>,HF_HOME=<dir> \
#          slurm/stage_c_verdict.sbatch
#
# Serves both verifier cells on one 4-GPU node (tp2 each) and scores them in
# parallel — they are independent, share no state, and write separate caches.
#
# Resuming a killed dispatch is infrastructure recovery, not a re-run (stop
# rule §6): scoring is cached per directed (criterion, task, a, b, rep) key, so
# re-submitting continues rather than rescoring.
set -euo pipefail

: "${STAGE_C_OUT:?set STAGE_C_OUT}"
: "${PROJECT_ROOT:?set PROJECT_ROOT}"
: "${C1_MODEL:?set C1_MODEL}"
: "${C2_MODEL:?set C2_MODEL}"
: "${SERVER_PYTHON:?set SERVER_PYTHON}"
: "${AGENT_PYTHON:?set AGENT_PYTHON}"

C1_PORT="${C1_PORT:-30010}"
C2_PORT="${C2_PORT:-30000}"
MAX_WORKERS="${MAX_WORKERS:-24}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-65536}"
# D-04: Biomni-R0-32B's native 40960 is too small; served with the model card's
# YaRN override at factor 1.0, an identity transform on the RoPE frequencies.
# Mirrors configs/cluster.yaml's serving.json_model_override_args exactly.
#
# NOT written as "${C2_OVERRIDE:-{...}}": the default contains JSON braces, and
# bash ends the parameter expansion at the first brace that balances, which
# silently swallowed the "}" closing "rope_scaling". That moved
# max_position_embeddings *inside* rope_scaling, so the top-level override
# never applied, the derived context stayed 40960, and the server refused the
# requested 65536. Single quotes, plain assignment, no escaping.
if [[ -z "${C2_OVERRIDE:-}" ]]; then
  C2_OVERRIDE='{"rope_scaling":{"rope_type":"yarn","factor":1.0,"original_max_position_embeddings":32768}, "max_position_embeddings": 131072}'
fi

# Fail loudly rather than serve a silently-wrong context: the override must be
# valid JSON and must carry max_position_embeddings at the TOP level.
"${AGENT_PYTHON}" - "${C2_OVERRIDE}" <<'PY' || exit 1
import json, sys
try:
    d = json.loads(sys.argv[1])
except json.JSONDecodeError as e:
    sys.exit(f"C2_OVERRIDE is not valid JSON: {e}")
if "max_position_embeddings" not in d:
    sys.exit("C2_OVERRIDE lacks a top-level max_position_embeddings; "
             "the D-04 context override would silently not apply")
if "rope_scaling" not in d:
    sys.exit("C2_OVERRIDE lacks rope_scaling")
print(f"[stage_c] C2 override validated: {json.dumps(d)}")
PY

LOGS="${STAGE_C_OUT}/logs"
mkdir -p "${LOGS}"
HOST="$(hostname -f)"

# A non-interactive Slurm shell does not carry the module environment the
# servers need: without these, python fails on libpython3.12.so.1.0 and, later
# and far more confusingly, CUDA-graph capture dies on GLIBCXX_3.4.31 while
# loading a JIT-compiled sgl_kernel .so — which SGLang misreports as a
# suggestion to lower --mem-fraction-static.
export LD_LIBRARY_PATH="/opt/apps/gcc/13.2.0/lib64:/opt/apps/gcc/13.2.0/lib:/opt/apps/python/3.12.11/lib:${LD_LIBRARY_PATH:-}"

echo "[stage_c] host=${HOST} out=${STAGE_C_OUT}"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader || true

launch() {  # launch <label> <model> <port> <gpus> [override]
  local label="$1" model="$2" port="$3" gpus="$4" override="${5:-}"
  local args=(--model "${model}" --port "${port}" --gpus "${gpus}" --tp 2
              --context-length "${CONTEXT_LENGTH}" --dtype bfloat16
              --log-dir "${LOGS}" --label "${label}")
  [[ -n "${override}" ]] && args+=(--override-args "${override}")
  SERVER_PYTHON="${SERVER_PYTHON}" \
    nohup bash "${PROJECT_ROOT}/scripts/launch_sglang_server.sh" "${args[@]}" \
    > "${LOGS}/launch_${label}.log" 2>&1 &
}

wait_healthy() {  # wait_healthy <port> <label>
  local port="$1" label="$2" deadline=$((SECONDS + 2400))
  until curl -sf "http://${HOST}:${port}/v1/models" > /dev/null 2>&1; do
    if (( SECONDS > deadline )); then
      echo "[stage_c] FATAL: ${label} did not become healthy on :${port}" >&2
      tail -40 "${LOGS}/sglang_${label}.log" >&2 || true
      exit 1
    fi
    sleep 15
  done
  echo "[stage_c] ${label} healthy on :${port} after ${SECONDS}s"
}

launch c2_biomni_r0 "${C2_MODEL}" "${C2_PORT}" 0,1 "${C2_OVERRIDE}"
launch c1_gemma4    "${C1_MODEL}" "${C1_PORT}" 2,3
wait_healthy "${C2_PORT}" c2_biomni_r0
wait_healthy "${C1_PORT}" c1_gemma4

score() {  # score <cell> <port>
  "${AGENT_PYTHON}" "${PROJECT_ROOT}/scripts/stage_c_run.py" score \
      --out "${STAGE_C_OUT}" --cell "$1" \
      --base-url "http://${HOST}:$2/v1" --max-workers "${MAX_WORKERS}" \
      > "${LOGS}/score_$1.log" 2>&1
}

echo "[stage_c] scoring both cells in parallel"
score c1 "${C1_PORT}" & P1=$!
score c2 "${C2_PORT}" & P2=$!

RC=0
wait "${P1}" || RC=1
wait "${P2}" || RC=1

echo "[stage_c] c1 tail:"; tail -20 "${LOGS}/score_c1.log" || true
echo "[stage_c] c2 tail:"; tail -20 "${LOGS}/score_c2.log" || true
echo "[stage_c] done rc=${RC}"
echo "[stage_c] NOTE: no verdict computed here. Run scripts/stage_c_analyze.py separately."
exit "${RC}"
