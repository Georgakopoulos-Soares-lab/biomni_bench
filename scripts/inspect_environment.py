#!/usr/bin/env python3
"""Thin wrapper around `cli inspect-env` for use in job scripts and README steps."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from biomni_uncertainty.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["inspect-env", *sys.argv[1:]]))
