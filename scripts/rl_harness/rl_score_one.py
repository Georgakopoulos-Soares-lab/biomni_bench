#!/usr/bin/env python
"""Score exactly one completed Biomni trajectory with the official evaluator.

Runs in the `biomni_unc` environment (needs `biomni_uncertainty` +
`biomni.eval.biomni_eval1` importable). Never reimplements reward logic --
this is a thin CLI wrapper around the same `evaluation.OfficialEvaluator`
every other phase uses, so an RL rollout's reward is the identical scoring
path as Phase 1/2B, not a parallel reimplementation.

Usage:
    python scripts/rl_harness/rl_score_one.py --run-dir DIR --groundtruth PATH

Prints a single JSON line to stdout:
    {"reward": float|null, "strict_reward": float|null, "status": str,
     "error": str|null, "task_name": str, "task_instance_id": int}

A trajectory with no parseable answer (context-overflow, budget termination,
degenerate output) scores 0.0 with status "unparseable_answer" -- a defined
reward, not a dropped sample. Only a genuine evaluator exception (malformed
ground truth, an evaluator bug) yields "evaluator_failure" with reward=null;
the RL caller (biomni_lit_agent.py) treats both non-"ok" outcomes other than
"unparseable_answer" the same way it treats a crashed subprocess: a frozen
reward of 0.0, matching this project's own binarize()/reward convention that
every task already scores exactly 0.0 or 1.0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from biomni_uncertainty.evaluation import OfficialEvaluator


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", required=True, help="completed run_dir containing metadata.json")
    p.add_argument("--groundtruth", required=True, help="path to a .groundtruth.jsonl file")
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        print(
            json.dumps(
                {
                    "reward": None,
                    "strict_reward": None,
                    "status": "no_metadata",
                    "error": f"missing {metadata_path}",
                    "task_name": None,
                    "task_instance_id": None,
                }
            )
        )
        return 1

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    task_name = metadata["task_name"]
    task_instance_id = int(metadata["task_instance_id"])
    answer_canonical = metadata.get("answer_canonical")

    evaluator = OfficialEvaluator.from_groundtruth_file(args.groundtruth)
    result = evaluator.evaluate(task_name, task_instance_id, answer_canonical)

    out = result.to_dict()
    print(json.dumps(out))
    return 0 if result.status != "no_ground_truth" else 2


if __name__ == "__main__":
    sys.exit(main())
