#!/usr/bin/env python3
"""Generate the frozen Phase-1 pilot manifest and print its hash.

Equivalent to:
    python -m biomni_uncertainty.cli prepare-manifest --config configs/phase1.yaml
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from biomni_uncertainty.cli import main  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:] or ["--config", str(ROOT / "configs" / "phase1.yaml")]
    sys.exit(main(["prepare-manifest", *args]))
