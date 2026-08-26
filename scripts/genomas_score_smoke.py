#!/usr/bin/env python3
"""Run GenoMAS's native selector scorer on one declared smoke task."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from biomni_uncertainty.adapters.genomas import normalize_condition_arg  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True,
                        help="Clean, pinned GenoMAS worktree.")
    parser.add_argument("--pred-dir", type=Path, required=True)
    parser.add_argument("--ref-dir", type=Path, required=True,
                        help="Held-out GenoTEX output root, never exposed to the agent.")
    parser.add_argument("--trait", required=True)
    parser.add_argument("--condition", default=None,
                        help="Condition name (e.g. Age, Gender). Omit, or pass 'None', for the unconditioned task.")
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    args.condition = normalize_condition_arg(args.condition)

    os.chdir(args.source)
    sys.path.insert(0, str(args.source))
    import eval as genomas_eval  # noqa: PLC0415

    # Keep the upstream metric implementation unchanged while restricting only
    # its task iterator to the declared K=1 smoke boundary.
    genomas_eval.get_question_pairs = lambda _path: [(args.trait, args.condition)]
    results = genomas_eval.main(str(args.pred_dir), str(args.ref_dir), tasks=["selection"])
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
