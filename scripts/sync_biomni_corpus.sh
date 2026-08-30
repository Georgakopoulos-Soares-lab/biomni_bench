#!/usr/bin/env bash
# Reproducible Stampede3 -> shared /work2 -> destination-scratch transfer of
# the scientifically relevant slice of a Biomni-uncertainty experiment's raw
# run tree, for reliability/distillation-audit analysis.
#
# Codifies the procedure worked out by hand in
# reports/biomni_trajectory_distillation_audit.md SS0.1 and PROJECT_STATUS.md,
# after two real mistakes on the first attempt:
#
#   1. `zstd -T0` (one compression context per core) OOM'd the Stampede3
#      LOGIN node on 39G/124G source trees, because `artifacts/` (raw
#      tool-execution byproducts: downloaded references, intermediate files,
#      plots) turned out to be 99-100% of the size and is NOT needed for
#      reliability/SFT analysis - the model-visible content already lives in
#      `stdout.log` (full multi-turn transcript) and `events.jsonl`
#      (telemetry + R5-capped excerpts), verified directly against real
#      trajectories. This script transfers only the small files by default
#      and never spawns a multi-threaded compressor on a login node's behalf.
#   2. The first small-file list omitted `final_response.txt` and
#      `parsed_answer.json`, which `biomni_uncertainty.sampling.is_valid_complete()`
#      requires alongside `metadata.json`/`events.jsonl` to recognize a
#      trajectory as complete. Silent under-transfer was caught only because
#      `scripts/pool_and_analyze_phase1_5.py` reported 0 rescues instead of
#      the documented 42. This script's default file list includes both.
#
# Usage (run ON THE SOURCE MACHINE, e.g. a Stampede3 login node or - for
# anything beyond a few GB - an idev/interactive compute session):
#
#   scripts/sync_biomni_corpus.sh --exp phase1 --exp phase1_5 --exp phase2b \
#       --source /scratch/11034/atzanakak/biomni_unc_runs \
#       --stage  /work2/11034/atzanakak/biomni_bench/_distillation_transfer
#
# Then, from the destination machine (e.g. this project's Vista session),
# run again with --apply-dest to verify + unpack what landed in --stage:
#
#   scripts/sync_biomni_corpus.sh --exp phase1 --exp phase1_5 --exp phase2b \
#       --stage /work/11034/atzanakak/biomni_bench/_distillation_transfer \
#       --dest  /scratch/11034/atzanakak/biomni_unc_runs \
#       --apply-dest
#
# The exact commands used for the current Stampede3 -> Vista transfer
# (2026-08-30, before this script existed) are reproduced at the bottom of
# this file as a comment, for the record.

set -euo pipefail

SOURCE=""
STAGE=""
DEST=""
EXPERIMENTS=()
DRY_RUN=0
APPLY_DEST=0
# Scientifically relevant per-trajectory files: prompt/config/run identity,
# completion markers, telemetry events, human-readable full transcript, the
# model's final-turn text and parsed/canonical answer, and the official
# reward once present in the aggregated results tables (those tables, not
# individual reward files, are the reward record - see the results/ pattern
# below). Never includes `artifacts/` (large, not model-visible, excluded by
# construction: `find` below is not recursive into any directory literally
# named `artifacts`).
FILE_NAMES=(
  events.jsonl config.json run_spec.json metadata.json
  stdout.log stderr.log
  final_response.txt parsed_answer.json
  COMPLETE FAILED
)

usage() {
  cat <<'EOF'
Usage:
  Source-side (compress + stage):
    sync_biomni_corpus.sh --exp NAME [--exp NAME ...] --source DIR --stage DIR [--dry-run]

  Destination-side (verify + unpack):
    sync_biomni_corpus.sh --exp NAME [--exp NAME ...] --stage DIR --dest DIR --apply-dest [--dry-run]

Options:
  --exp NAME       Experiment subdirectory name under --source/--dest (repeatable).
  --source DIR     Source output_root (e.g. Stampede3's biomni_unc_runs). Source-side only.
  --stage DIR      Shared staging directory both sides can see (e.g. /work2/.../_distillation_transfer).
  --dest DIR       Destination output_root to unpack into. Destination-side only.
  --apply-dest     Run the destination-side verify+unpack step instead of the source-side compress+stage step.
  --dry-run        Print what would happen (sizes, file counts, commands) without writing/deleting anything.
  -h, --help       Show this help.

Also also includes reports/results tables when present
(<exp>/results/**), since those hold the aggregated reward/scoring records
and are typically tiny compared to raw run trees.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --exp) EXPERIMENTS+=("$2"); shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --stage) STAGE="$2"; shift 2 ;;
    --dest) DEST="$2"; shift 2 ;;
    --apply-dest) APPLY_DEST=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ${#EXPERIMENTS[@]} -eq 0 ]]; then
  echo "ERROR: at least one --exp NAME is required" >&2
  exit 2
fi
if [[ -z "$STAGE" ]]; then
  echo "ERROR: --stage DIR is required" >&2
  exit 2
fi

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------------------
# Source-side: measure, then compress only the scientifically relevant files.
# ---------------------------------------------------------------------------
source_side() {
  [[ -n "$SOURCE" ]] || { echo "ERROR: --source DIR is required for the source-side step" >&2; exit 2; }
  [[ -d "$SOURCE" ]] || { echo "ERROR: source directory does not exist: $SOURCE" >&2; exit 2; }
  mkdir -p "$STAGE"

  echo "=== size summary (informational - decide before compressing) ==="
  for exp in "${EXPERIMENTS[@]}"; do
    local d="$SOURCE/$exp"
    if [[ ! -d "$d" ]]; then
      echo "SKIP: $exp not found under $SOURCE"
      continue
    fi
    local total artifacts
    total=$(du -sh "$d" 2>/dev/null | cut -f1)
    artifacts=$(find "$d" -type d -name artifacts -exec du -ch {} + 2>/dev/null | tail -1 | cut -f1)
    echo "$exp: total=$total  artifacts/=${artifacts:-0}"
  done
  echo
  echo "NOTE: if artifacts/ is not the overwhelming majority of an experiment's"
  echo "size the way it was for phase1 (39G, 100% artifacts/) and phase2b"
  echo "(124G, 99% artifacts/), stop and reconsider before excluding it - this"
  echo "script's default exclusion is an established fact about THIS project's"
  echo "data shape, not a universal one. artifacts/ is never deleted; it stays"
  echo "on the source machine, recoverable, for whoever needs it later."
  echo

  for exp in "${EXPERIMENTS[@]}"; do
    local d="$SOURCE/$exp"
    [[ -d "$d" ]] || continue

    local find_expr=()
    for n in "${FILE_NAMES[@]}"; do
      find_expr+=(-o -name "$n")
    done
    find_expr=("${find_expr[@]:1}")  # drop the leading -o

    local n_files
    n_files=$(find "$d" -type f \( "${find_expr[@]}" \) 2>/dev/null | wc -l)
    echo "$exp: $n_files scientifically-relevant files (events/config/logs/final_response/parsed_answer/markers)"

    local archive="$exp.tar.gz"
    local results_archive="$exp.results.tar.gz"

    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "[dry-run] would tar $n_files files under $d into $STAGE/$archive"
      [[ -d "$d/results" ]] && echo "[dry-run] would tar $d/results into $STAGE/$results_archive"
      continue
    fi

    if [[ "$n_files" -eq 0 ]]; then
      echo "  WARNING: 0 matching files under $d, skipping archive (nothing to transfer)"
    else
      # NOTE: -C must precede -T on GNU tar's command line - it only affects
      # file names that appear after it, including names read via -T. Putting
      # it after -T (as an earlier version of this script did) silently
      # makes tar resolve every listed path against the CALLER's cwd instead
      # of $d, and fails with "Cannot stat" for every single file.
      ( cd "$d" && find . -type f \( "${find_expr[@]}" \) -print0 ) \
        | tar --null -C "$d" -T - -czf "$STAGE/$archive.partial"
      mv "$STAGE/$archive.partial" "$STAGE/$archive"
      sha256sum "$STAGE/$archive" > "$STAGE/$archive.sha256"
      echo "  wrote $STAGE/$archive ($(du -h "$STAGE/$archive" | cut -f1))"
    fi

    # Aggregated results/ tables (rewards, taxonomy, figures) if present -
    # small, and carries the official-reward/scoring record.
    if [[ -d "$d/results" ]]; then
      tar -czf "$STAGE/$results_archive.partial" -C "$d" results
      mv "$STAGE/$results_archive.partial" "$STAGE/$results_archive"
      sha256sum "$STAGE/$results_archive" > "$STAGE/$results_archive.sha256"
      echo "  wrote $STAGE/$results_archive ($(du -h "$STAGE/$results_archive" | cut -f1))"
    fi
  done

  echo
  echo "=== staged at $STAGE ==="
  [[ "$DRY_RUN" -eq 1 ]] || ls -lh "$STAGE"
  echo
  echo "Source data was only ever READ, never modified or deleted."
}

# ---------------------------------------------------------------------------
# Destination-side: verify checksums, then unpack (never overwriting an
# already-populated experiment directory without being told to).
# ---------------------------------------------------------------------------
dest_side() {
  [[ -n "$DEST" ]] || { echo "ERROR: --dest DIR is required for --apply-dest" >&2; exit 2; }
  [[ -d "$STAGE" ]] || { echo "ERROR: stage directory does not exist: $STAGE" >&2; exit 2; }
  run mkdir -p "$DEST"

  local failures=0
  for exp in "${EXPERIMENTS[@]}"; do
    for kind in "" ".results"; do
      local archive="$STAGE/$exp$kind.tar.gz"
      [[ -f "$archive" ]] || continue
      local sumfile="$archive.sha256"
      if [[ ! -f "$sumfile" ]]; then
        echo "FAIL: $archive has no checksum file, refusing to unpack" >&2
        failures=$((failures + 1))
        continue
      fi
      echo "=== verifying $archive ==="
      if ! ( cd "$STAGE" && sha256sum -c "$(basename "$sumfile")" ); then
        echo "FAIL: checksum mismatch for $archive - refusing to unpack, source is untouched" >&2
        failures=$((failures + 1))
        continue
      fi
      local target="$DEST/$exp"
      if [[ "$kind" == "" && -d "$target" ]]; then
        local existing
        existing=$(find "$target" -type f 2>/dev/null | wc -l)
        if [[ "$existing" -gt 0 ]]; then
          echo "NOTE: $target already has $existing files; tar will merge/overwrite matching paths only, never delete unrelated existing files."
        fi
      fi
      run mkdir -p "$target"
      run tar -xzf "$archive" -C "$target"
      echo "unpacked $archive -> $target"
    done
  done

  if [[ "$failures" -gt 0 ]]; then
    echo
    echo "=== VALIDATION SUMMARY: FAILED ($failures archive(s)) ===" >&2
    exit 1
  fi

  echo
  echo "=== VALIDATION SUMMARY: OK ==="
  for exp in "${EXPERIMENTS[@]}"; do
    local n
    n=$(find "$DEST/$exp" -name events.jsonl 2>/dev/null | wc -l)
    echo "$exp: $n events.jsonl files present under $DEST/$exp"
  done
}

if [[ "$APPLY_DEST" -eq 1 ]]; then
  dest_side
else
  source_side
fi

# ---------------------------------------------------------------------------
# Exact commands actually used for the current Stampede3 -> Vista transfer
# (2026-08-30), before this script existed, kept here for the record:
#
#   # On Stampede3 (source):
#   SRC=/scratch/11034/atzanakak/biomni_unc_runs
#   STAGE=/work2/11034/atzanakak/biomni_bench/_distillation_transfer
#   mkdir -p "$STAGE"
#   cd "$SRC"
#   for exp in phase1 phase1_5 phase2b; do
#     find "$exp" -type f \( \
#         -name events.jsonl -o -name config.json -o -name run_spec.json \
#         -o -name metadata.json -o -name stdout.log -o -name stderr.log \
#         -o -name COMPLETE -o -name FAILED \
#       \) -print0 | tar --null -T - -czf "${exp}_small.tar.gz"
#     sha256sum "${exp}_small.tar.gz" > "${exp}_small.tar.gz.sha256"
#   done
#   # (top-up round, after discovering is_valid_complete()'s full file list:)
#   for exp in phase1 phase1_5 phase2b; do
#     find "$exp" -type f \( -name final_response.txt -o -name parsed_answer.json \) \
#       -print0 | tar --null -T - -czf "${exp}_top_up.tar.gz"
#     sha256sum "${exp}_top_up.tar.gz" > "${exp}_top_up.tar.gz.sha256"
#   done
#   mv ./*_small.tar.gz* ./*_top_up.tar.gz* "$STAGE"/
#
#   # On Vista (destination, /work2 and /work are the same Lustre filesystem):
#   STAGE=/work/11034/atzanakak/biomni_bench/_distillation_transfer
#   DEST=/scratch/11034/atzanakak/biomni_unc_runs
#   mkdir -p "$DEST"
#   cd "$STAGE" && sha256sum -c ./*.sha256
#   for exp in phase1 phase1_5 phase2b; do
#     tar -xzf "${exp}_small.tar.gz" -C "$DEST"
#     tar -xzf "${exp}_top_up.tar.gz" -C "$DEST"
#   done
# ---------------------------------------------------------------------------
