#!/usr/bin/env python3
"""Normalize an existing Biomni table and recompute Reliability Suite v1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from biomni_uncertainty.adapters.biomni import normalize_biomni_table
from biomni_uncertainty.reliability import evaluate_reliability


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--k", type=int, default=4)
    args = parser.parse_args()
    records = normalize_biomni_table(args.input_csv)
    args.records.parent.mkdir(parents=True, exist_ok=True)
    args.records.write_text("".join(json.dumps(r, default=str) + "\n" for r in records), encoding="utf-8")
    report = evaluate_reliability(records, k=args.k)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
