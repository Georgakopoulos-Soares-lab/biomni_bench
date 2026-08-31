#!/bin/bash
#SBATCH --job-name=genomas-data
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=12:00:00
#
# Site-specific #SBATCH values are supplied on the command line, never
# hardcoded (see slurm/README.md):
#
#   sbatch --account=$ACCOUNT --partition=$PARTITION \
#          --output="$ADMISSION/logs/download-%j.out" \
#          --error="$ADMISSION/logs/download-%j.err" \
#          slurm/genomas_download.sbatch
#
# ROOT and ADMISSION can be set explicitly; otherwise they derive from the
# standard TACC filesystem variables ($STOCKYARD, the site-wide work
# filesystem root -- not $WORK, which is a per-system subdirectory of it;
# $SCRATCH). Neither is exported by every site, so this fails loudly rather
# than silently landing somewhere unexpected if they are unset.

set -euo pipefail
export LD_LIBRARY_PATH=/opt/apps/gcc14/cuda12/python3/3.11.8/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
ROOT="${ROOT:-${STOCKYARD:+$STOCKYARD/biomni_bench/biomni-uncertainty}}"
: "${ROOT:?set ROOT explicitly, or run on a site that exports \$STOCKYARD}"
ADMISSION="${ADMISSION:-${SCRATCH:+$SCRATCH/genomas_admission}}"
: "${ADMISSION:?set ADMISSION explicitly, or run on a site that exports \$SCRATCH}"
mkdir -p "$ADMISSION/logs" "$ADMISSION/provenance"
"$ADMISSION/venv/bin/python" "$ROOT/scripts/genomas_admission.py" \
  --data-root "$ADMISSION/genotex_data" \
  --manifest "$ADMISSION/provenance/genotex_input_manifest.json" \
  --verification "$ADMISSION/provenance/genotex_input_verification.json" \
  --revision 9d50c9020256e8c943e02b6c0ad843017cd76cf8 --download
