#!/usr/bin/env bash
# Matched scope study: idempotent, resumable launcher for BOTH solver arms.
#
#   scripts/scope_main_run.sh            # launch or resume on this node
#   scripts/scope_main_run.sh --status   # report progress, start nothing
#   scripts/scope_main_run.sh --dry-run  # plan only
#
# ---------------------------------------------------------------------------
# WHY THIS EXISTS
#
# The study needs ~55 GPU-hours of trajectory time and a single allocation may
# not cover it. Everything below is therefore safe to run again on a *new*
# allocation, on a *different* node, any number of times:
#
#   * trajectory-level resume is already exact -- `sampling.pending_specs` skips
#     a run only when its COMPLETE marker exists AND all four artifacts are
#     present AND metadata.completed is true, so a trajectory interrupted
#     mid-write is re-run rather than silently skipped;
#   * run directories live under $BIOMNI_UNC_OUTPUT_ROOT on shared scratch, so
#     they survive the allocation that produced them;
#   * servers are probed before launch, so re-running this script on a node that
#     already has healthy endpoints does not start a second copy;
#   * endpoints are rewritten from the CURRENT hostname each time, which is the
#     one thing that genuinely changes between allocations.
#
# PROVENANCE ACROSS ALLOCATIONS. A multi-allocation run must not end up with
# trajectories produced at different project commits -- that is the D-29 failure
# in slow motion. On first launch this script records the launch commit and the
# manifest hash in $OUT/scope_main/LAUNCH.json; on every later invocation it
# REFUSES to continue if HEAD has moved or the manifest changed. Commit results
# only after the run is finished, or use --allow-commit-drift and accept that
# the trajectories are no longer attributable to one tree.
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

MODE="run"
ALLOW_DRIFT=0
for arg in "$@"; do
  case "$arg" in
    --status)             MODE="status" ;;
    --dry-run)            MODE="dry" ;;
    --allow-commit-drift) ALLOW_DRIFT=1 ;;
    -h|--help)            sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

# --- site environment ------------------------------------------------------
export BIOMNI_UNC_OUTPUT_ROOT="${BIOMNI_UNC_OUTPUT_ROOT:-/scratch/11034/atzanakak/biomni_unc_runs}"
export BIOMNI_UNC_EVAL1_PARQUET="${BIOMNI_UNC_EVAL1_PARQUET:-/scratch/11034/atzanakak/biomni_eval1_dataset.parquet}"
export BIOMNI_PATH="${BIOMNI_PATH:-/scratch/11034/atzanakak/biomni_data_root}"
export BIOMNI_UNC_SCRATCH="${BIOMNI_UNC_SCRATCH:-/tmp/biomni_unc_scratch}"
export BIOMNI_SRC="${BIOMNI_SRC:-/work2/11034/atzanakak/biomni_bench/biomni_src}"
export HF_HOME="${HF_HOME:-/scratch/11034/atzanakak/hf_cache}"
export BIOMNI_CUSTOM_API_KEY="${BIOMNI_CUSTOM_API_KEY:-EMPTY}"
# A non-interactive shell on a Stampede3 compute node loads none of the TACC
# modules the interactive job had; without this the server python cannot even
# find libpython, and later CUDA-graph capture dies citing GLIBCXX.
export LD_LIBRARY_PATH="/opt/apps/gcc/13.2.0/lib64:/opt/apps/gcc/13.2.0/lib:/opt/apps/python/3.12.11/lib:${LD_LIBRARY_PATH:-}"

AGENT_PY="${BIOMNI_UNC_AGENT_PYTHON:-/scratch/11034/atzanakak/envs/biomni_unc/bin/python}"
SERVER_PY="${BIOMNI_UNC_SERVER_PYTHON:-/scratch/11034/atzanakak/envs/sglang_srv/bin/python}"

OUT="$BIOMNI_UNC_OUTPUT_ROOT/scope_main"
LOGS="$OUT/logs"
mkdir -p "$LOGS"

MANIFEST="manifests/scope_main.jsonl"
GROUND_TRUTH="manifests/scope_main.groundtruth.jsonl"
HOSTF="$(hostname -f 2>/dev/null || hostname)"

declare -A ARM_CONFIG=( [a]="configs/scope_main_a.yaml" [b]="configs/scope_main_b.yaml" )
declare -A ARM_RUNS=(   [a]="manifests/scope_main_a_runs.jsonl" [b]="manifests/scope_main_b_runs.jsonl" )
declare -A ARM_PORT=(   [a]=30000 [b]=30010 )
declare -A ARM_GPUS=(   [a]="0,1" [b]="2,3" )
declare -A ARM_MODEL=(
  [a]="/scratch/11034/atzanakak/hf_cache/hub/models--biomni--Biomni-R0-32B-Preview/snapshots/71432eb3d5e583bee757e0f9437a17e711e8e3d1"
  [b]="/scratch/11034/atzanakak/hf_cache/hub/models--mistralai--Mistral-Small-3.1-24B-Instruct-2503/snapshots/68faf511d618ef198fef186659617cfd2eb8e33a"
)

# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------
arm_progress() {  # arm -> "done/total"
  local arm="$1" runs="${ARM_RUNS[$arm]}"
  [[ -f "$runs" ]] || { echo "0/0"; return; }
  "$AGENT_PY" - "$runs" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0, "src")
from biomni_uncertainty.sampling import is_valid_complete
specs=[json.loads(x) for x in Path(sys.argv[1]).read_text().splitlines() if x.strip()]
done=sum(1 for s in specs if is_valid_complete(Path(s["run_dir"])))
print(f"{done}/{len(specs)}")
PY
}

print_status() {
  echo "== scope_main progress =="
  for arm in a b; do
    printf '  arm %s (%s): %s\n' "$arm" "$(basename "${ARM_CONFIG[$arm]}")" "$(arm_progress "$arm")"
  done
}

if [[ "$MODE" == "status" ]]; then print_status; exit 0; fi

# ---------------------------------------------------------------------------
# provenance: one tree for the whole multi-allocation run
# ---------------------------------------------------------------------------
if [[ -n "$(git status --porcelain)" ]]; then
  echo "REFUSING: dirty tree. Commit before launching or resuming." >&2
  git status --short >&2
  exit 2
fi
COMMIT="$(git rev-parse HEAD)"
MANIFEST_HASH="$("$AGENT_PY" -c "import hashlib,sys;print(hashlib.sha256(open('$MANIFEST','rb').read()).hexdigest())")"
LAUNCH_FILE="$OUT/LAUNCH.json"

if [[ -f "$LAUNCH_FILE" ]]; then
  PREV_COMMIT="$("$AGENT_PY" -c "import json;print(json.load(open('$LAUNCH_FILE'))['launch_commit'])")"
  PREV_MANIFEST="$("$AGENT_PY" -c "import json;print(json.load(open('$LAUNCH_FILE'))['manifest_hash'])")"
  if [[ "$PREV_MANIFEST" != "$MANIFEST_HASH" ]]; then
    echo "REFUSING: $MANIFEST changed since launch ($PREV_MANIFEST -> $MANIFEST_HASH)." >&2
    echo "The study population is frozen; a changed manifest is a new experiment." >&2
    exit 2
  fi
  if [[ "$PREV_COMMIT" != "$COMMIT" ]]; then
    if [[ "$ALLOW_DRIFT" == "1" ]]; then
      echo "WARNING: commit drift $PREV_COMMIT -> $COMMIT, continuing under --allow-commit-drift." >&2
      echo "         Trajectories in this run are NOT attributable to a single tree." >&2
    else
      echo "REFUSING: HEAD moved since launch ($PREV_COMMIT -> $COMMIT)." >&2
      echo "  Trajectories would carry two different commits. Either check out the" >&2
      echo "  launch commit, or re-run with --allow-commit-drift and record it." >&2
      exit 2
    fi
  fi
else
  "$AGENT_PY" - "$LAUNCH_FILE" "$COMMIT" "$MANIFEST_HASH" <<'PY'
import datetime,hashlib,json,sys
from pathlib import Path
dest,commit,mhash=sys.argv[1],sys.argv[2],sys.argv[3]
Path(dest).parent.mkdir(parents=True,exist_ok=True)
def h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
Path(dest).write_text(json.dumps({
  "launch_commit": commit,
  "manifest_hash": mhash,
  "config_hash_a": h("configs/scope_main_a.yaml"),
  "config_hash_b": h("configs/scope_main_b.yaml"),
  "first_launch_utc": datetime.datetime.now(datetime.UTC).isoformat(),
}, indent=2, sort_keys=True))
print("recorded launch provenance:", dest)
PY
fi

# ---------------------------------------------------------------------------
# run manifests (idempotent; expand-runs is deterministic)
# ---------------------------------------------------------------------------
for arm in a b; do
  if [[ ! -f "${ARM_RUNS[$arm]}" ]]; then
    "$AGENT_PY" -m biomni_uncertainty.cli expand-runs \
      --config "${ARM_CONFIG[$arm]}" --manifest "$MANIFEST" --output "${ARM_RUNS[$arm]}"
  fi
done

# ---------------------------------------------------------------------------
# servers: probe, then launch only what is missing
# ---------------------------------------------------------------------------
server_healthy() { curl -s -m 5 -o /dev/null -w '%{http_code}' "http://localhost:$1/v1/models" 2>/dev/null | grep -q 200; }

for arm in a b; do
  port="${ARM_PORT[$arm]}"
  if server_healthy "$port"; then
    echo "[server] arm $arm already healthy on :$port"
    continue
  fi
  # Extract the serving override from the YAML rather than writing JSON braces in
  # bash. D-43 lost a whole server start to `"${VAR:-{...}}"` ending the
  # parameter expansion at the first balancing brace; this cannot recur here.
  OVERRIDE="$("$AGENT_PY" -c "
import yaml,json
v=yaml.safe_load(open('${ARM_CONFIG[$arm]}'))['model'].get('json_model_override_args')
if v:
    d=json.loads(v)
    assert 'max_position_embeddings' in d, 'override must set a TOP-LEVEL max_position_embeddings'
    print(v)
")"
  echo "[server] launching arm $arm on :$port gpus ${ARM_GPUS[$arm]}"
  setsid nohup env SERVER_PYTHON="$SERVER_PY" LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
    "$HERE/scripts/launch_sglang_server.sh" \
      --model "${ARM_MODEL[$arm]}" --port "$port" --gpus "${ARM_GPUS[$arm]}" --tp 2 \
      --dtype bfloat16 --mem-fraction 0.85 --context-length 65536 \
      --log-dir "$LOGS" --label "scope_main_$arm" \
      ${OVERRIDE:+--override-args "$OVERRIDE"} \
    > "$LOGS/launch_$arm.log" 2>&1 < /dev/null &
done

for arm in a b; do
  port="${ARM_PORT[$arm]}"
  echo -n "[server] waiting for arm $arm on :$port "
  for _ in $(seq 1 240); do
    if server_healthy "$port"; then echo "OK"; break; fi
    sleep 15; echo -n "."
  done
  server_healthy "$port" || { echo; echo "ERROR: arm $arm never became healthy; see $LOGS/sglang_scope_main_$arm.log" >&2; exit 1; }
  cat > "$BIOMNI_UNC_OUTPUT_ROOT/endpoints_scope_main_$arm.json" <<EOF
{"endpoints": [{"url": "http://$HOSTF:$port/v1", "label": "scope_main_${arm}_${HOSTF}", "max_concurrent": 4}]}
EOF
done

# ---------------------------------------------------------------------------
# dispatch both arms in parallel; resume is the default
# ---------------------------------------------------------------------------
print_status
[[ "$MODE" == "dry" ]] && DRY="--dry-run" || DRY=""

PIDS=()
for arm in a b; do
  echo "[dispatch] arm $arm -> $LOGS/dispatch_$arm.log"
  setsid nohup "$AGENT_PY" -m biomni_uncertainty.cli dispatch \
    --config "${ARM_CONFIG[$arm]}" \
    --run-manifest "${ARM_RUNS[$arm]}" \
    --endpoints "$BIOMNI_UNC_OUTPUT_ROOT/endpoints_scope_main_$arm.json" \
    --python "$AGENT_PY" $DRY \
    >> "$LOGS/dispatch_$arm.log" 2>&1 < /dev/null &
  PIDS+=("$!")
done

echo "[dispatch] both arms running (pids ${PIDS[*]}); this script now waits."
echo "[dispatch] safe to kill at any time -- re-run to resume."
FAIL=0
for pid in "${PIDS[@]}"; do wait "$pid" || FAIL=1; done

print_status
"$AGENT_PY" - <<'PY'
import json
from pathlib import Path
for arm in ("a","b"):
    p=Path(f"manifests/scope_main_{arm}_runs.jsonl")
    print(f"arm {arm}: ground truth is manifests/scope_main.groundtruth.jsonl (pass --ground-truth explicitly to aggregate)")
PY
exit "$FAIL"
