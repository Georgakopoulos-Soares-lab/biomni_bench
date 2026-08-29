#!/usr/bin/env bash
# Launch the frozen AutoBA K=4 pilot v1 confirmatory campaign: 12 tasks x K=4,
# one scripts/run_autoba_k4_reliability.py invocation per task, sequential
# (single GH200), exactly matching the parameters frozen in
# reports/autoba_k4_pilot_v1_preregistration.md and its manifest (SHA-256
# 6709a7762512820e3073cfe0002c0be9f56596acddd79b5f4eecf29caeb38579).
#
# Not a scored artifact itself -- an orchestration wrapper around the already
#-frozen per-task runner, so the 12 invocations don't have to be typed by
# hand. Nothing about the frozen protocol (model, timeout, early-completion
# parameters, source commits, scorer) is decided here; it is all passed
# through unchanged from the arguments below, which match the manifest.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY=/scratch/11034/atzanakak/biomni_vista/envs/biotaskbench/bin/python3
BIOTASKBENCH_ROOT=/work/11034/atzanakak/biomni_bench/external_agents/bioTaskBench
ENDPOINT=http://127.0.0.1:8000
MODEL=Qwen3-Coder-30B-A3B-Instruct
SOURCE_COMMIT=a9f8f1244faf8b33cf1154150d612acf5026a4d9
BENCHMARK_REVISION=c9206d570098349143fec3d14d97699928a3bb13
PREFIX=/scratch/11034/atzanakak/genomas_admission/autoba_admission/autoba_k4_pilot_v1_20260829
LOG="$PREFIX.driver.log"

mkdir -p "$(dirname "$PREFIX")"
: > "$LOG"

# Order and numbering exactly as in the preregistration's task table.
TASKS=(
  "01:chip-seq:chipseq-001"
  "02:crispr-screens:crispr-001"
  "03:genome-assembly:assembly-002"
  "04:long-read-sequencing:lrs-001"
  "05:metabolomics:metab-001"
  "06:methylation-analysis:meth-001"
  "07:multi-omics-integration:moi-001"
  "08:population-genetics:popgen-001"
  "09:proteomics:prot-001"
  "10:spatial-transcriptomics:stx-001"
  "11:chip-seq:chipseq-002"
  "12:crispr-screens:crispr-003"
)

echo "CAMPAIGN_START $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"

for entry in "${TASKS[@]}"; do
  IFS=":" read -r num domain test_id <<< "$entry"
  root="${PREFIX}/${num}_${test_id}_k4"
  echo "TASK_START ${num} ${domain}/${test_id} $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
  if "$PY" "$REPO_ROOT/scripts/run_autoba_k4_reliability.py" \
      --campaign-root "$root" \
      --biotaskbench-root "$BIOTASKBENCH_ROOT" \
      --domain "$domain" --test-id "$test_id" \
      --endpoint "$ENDPOINT" --model "$MODEL" \
      --k 4 --timeout-seconds 1800 --done-stable-seconds 60 --poll-seconds 10 \
      --source-commit "$SOURCE_COMMIT" \
      --benchmark-revision "$BENCHMARK_REVISION" \
      >> "$LOG" 2>&1; then
    echo "TASK_DONE ${num} ${domain}/${test_id} $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
  else
    echo "TASK_FAILED ${num} ${domain}/${test_id} $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
  fi
done

echo "CAMPAIGN_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
