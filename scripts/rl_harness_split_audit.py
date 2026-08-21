#!/usr/bin/env python3
"""Freeze the RL-harness train/held-out split, verified against real manifests.

`reports/rl_harness_preregistration.md` SS3. CPU only, no new inference.

**No new manifest is built.** Both pools already exist as frozen, committed
artifacts:

* **Training pool** = `manifests/phase1.jsonl` UNION `manifests/phase2b.jsonl`
  (200 instances, disjoint by construction -- D-22 asserts this at build time).
  These instances have already been used to *generate and measure*
  trajectories in this project, but **never to update any model weight** --
  no RL has ever run here. Reusing them for RL training rollouts is therefore
  clean: what matters for RL is train/eval separation, not
  previously-measured/never-measured separation.
* **Held-out eval pool** = `manifests/scope_main.jsonl` (120 instances, the
  same population D-44/45/46/47/48 already fully characterized for
  Biomni-R0). Chosen specifically so the PRE-RL half of the primary
  comparison is already computed (D-46's Arm A numbers) and needs no new
  measurement -- only a POST-RL rerun on the identical instances.

This script verifies, rather than assumes, that the two pools are disjoint,
and freezes the exact instance lists and per-task counts.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFESTS = REPO / "manifests"


def _pairs(path: Path) -> set[tuple[str, int]]:
    out = set()
    for line in path.read_text().splitlines():
        if line.strip():
            o = json.loads(line)
            out.add((o["task_name"], int(o["task_instance_id"])))
    return out


def main() -> int:
    train = _pairs(MANIFESTS / "phase1.jsonl") | _pairs(MANIFESTS / "phase2b.jsonl")
    held_out = _pairs(MANIFESTS / "scope_main.jsonl")

    overlap = train & held_out
    if overlap:
        raise SystemExit(f"GUARD: train/held-out overlap: {sorted(overlap)[:5]}")

    def by_task(pairs: set[tuple[str, int]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t, _ in pairs:
            counts[t] = counts.get(t, 0) + 1
        return dict(sorted(counts.items()))

    report = {
        "train_pool": {
            "n": len(train),
            "sources": ["manifests/phase1.jsonl", "manifests/phase2b.jsonl"],
            "by_task": by_task(train),
        },
        "held_out_eval_pool": {
            "n": len(held_out),
            "sources": ["manifests/scope_main.jsonl"],
            "by_task": by_task(held_out),
        },
        "overlap": len(overlap),
        "reserved_untouched_never_used": 100,  # per D-45; not spent by this split
    }

    out = REPO / "reports" / "tables" / "rl_harness"
    out.mkdir(parents=True, exist_ok=True)
    (out / "split_audit.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nwrote {out}/split_audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
