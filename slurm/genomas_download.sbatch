#!/bin/bash
#SBATCH --job-name=genomas-data
#SBATCH --account=MCB26073
#SBATCH --partition=gh
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=12:00:00
#SBATCH --output=/scratch/11034/atzanakak/genomas_admission/logs/download-%j.out
#SBATCH --error=/scratch/11034/atzanakak/genomas_admission/logs/download-%j.err

set -euo pipefail
export LD_LIBRARY_PATH=/opt/apps/gcc14/cuda12/python3/3.11.8/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
ROOT=/work/11034/atzanakak/biomni_bench/biomni-uncertainty
ADMISSION=/scratch/11034/atzanakak/genomas_admission
mkdir -p "$ADMISSION/logs" "$ADMISSION/provenance"
"$ADMISSION/venv/bin/python" "$ROOT/scripts/genomas_admission.py" \
  --data-root "$ADMISSION/genotex_data" \
  --manifest "$ADMISSION/provenance/genotex_input_manifest.json" \
  --verification "$ADMISSION/provenance/genotex_input_verification.json" \
  --revision 9d50c9020256e8c943e02b6c0ad843017cd76cf8 --download
