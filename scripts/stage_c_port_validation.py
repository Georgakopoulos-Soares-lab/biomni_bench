#!/usr/bin/env python3
"""Stage C gate 1 — run the published LLM-as-a-Verifier implementation on its
own public benchmark trajectories, through the open-weight SGLang port.

This is the gate that separates "the method does not transfer to BiomniEval1"
from "our implementation is broken". It touches no BiomniEval1 data, consumes
no held-out instance, and reads only the trajectories shipped in the reference
repo (`data/`).

Two departures from the published run, both forced and both reported:

* **Verifier model.** The published MedAgentBench figure (73.3%) uses Gemini
  2.5 Flash via Vertex. No Vertex credentials exist on this allocation, so the
  reproduction anchor cannot be run and the port's absolute number is reported
  against the published one — explicitly *not* a controlled comparison
  (`reports/stage_c_stop_rule.md` and the Stage C brief §3 both provide for
  this).
* **Constrained decoding.** `scripts/stage_c_verifier_port.py` replaces the
  reference's vLLM-shaped `structured_outputs` with SGLang's `regex`, because
  SGLang silently ignores the former. See that module for the measurement.

Everything else — criteria, granularity, K, pivots, seed, the tournament, the
reward definition, the swing-task selection — is the published configuration,
unmodified.

Usage
-----
    python scripts/stage_c_port_validation.py \
        --base-url http://<host>:30000/v1 \
        --label biomni_r0_32b \
        --out /scratch/.../stage_c_port_validation
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import stage_c_verifier_port as port  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True, help="OpenAI-compatible SGLang endpoint (…/v1)")
    ap.add_argument("--label", required=True, help="Short verifier identity, used in output paths")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--benchmark", default="medagentbench")
    ap.add_argument("--max-workers", type=int, default=24)
    ap.add_argument("--repo", default=port.DEFAULT_REF_REPO)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    os.environ["OPENAI_BASE_URL"] = args.base_url
    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")
    os.environ["LLM_VERIFIER_REPO"] = args.repo

    # --- port patch + live proof that the constraint is honoured -----------
    error_log = os.path.join(args.out, f"comparison_errors_{args.label}.jsonl")
    if os.path.exists(error_log):
        os.remove(error_log)
    fgr = port.install(error_log=error_log)
    probe = port.self_test(args.base_url)
    probe_path = os.path.join(args.out, f"port_self_test_{args.label}.json")
    with open(probe_path, "w") as f:
        json.dump(probe, f, indent=2)
    print(json.dumps(probe, indent=2))
    if probe["ported_regex"] < port.MIN_ON_SCALE_MASS:
        print("ABORT: constraint not honoured on this endpoint")
        return 1
    print(f"port self-test written: {probe_path}\n")

    # --- provenance of the reference checkout ------------------------------
    ref_commit = subprocess.run(
        ["git", "-C", args.repo, "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    # --- redirect the reference runner's outputs into our tree -------------
    sys.path.insert(0, args.repo)
    from llm_verifier.benchmarks import BENCHMARKS  # noqa: E402

    cfg = BENCHMARKS[args.benchmark]
    cfg.cache = os.path.join(args.out, f"cache_{args.benchmark}_{args.label}.json")
    cfg.results = os.path.join(args.out, f"results_{args.benchmark}_{args.label}.txt")

    meta = {
        "benchmark": args.benchmark,
        "verifier_label": args.label,
        "base_url": args.base_url,
        "reference_repo": args.repo,
        "reference_commit": ref_commit,
        "port_module": os.path.join(HERE, "stage_c_verifier_port.py"),
        "port_self_test": probe,
        "published_config": {
            "criteria": list(cfg.criteria),
            "n_evaluations": cfg.n_evaluations,
            "pivots": cfg.pivots,
            "seed": cfg.seed,
            "granularity": fgr.GRANULARITY,
        },
        "anchor_run": "SKIPPED - no Vertex credentials; not a controlled comparison",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    sys.argv = ["run.py", args.benchmark, "--max-workers", str(args.max_workers)]
    runpy_path = os.path.join(args.repo, "scripts", "run.py")
    import runpy  # noqa: E402

    rc = 0
    try:
        runpy.run_path(runpy_path, run_name="__main__")
    except SystemExit as e:
        rc = int(e.code or 0)

    meta["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta["exit_code"] = rc

    # Failed comparisons are scored 0.5/0.5 by the reference runner. Report how
    # many, so an error-induced tie is never read as verifier indecision.
    errors: list[dict] = []
    if os.path.exists(error_log):
        with open(error_log) as f:
            errors = [json.loads(line) for line in f if line.strip()]
    by_type: dict[str, int] = {}
    for e in errors:
        by_type[e["error_type"]] = by_type.get(e["error_type"], 0) + 1
    meta["comparison_errors"] = {"total": len(errors), "by_type": by_type, "log": error_log}
    print(f"\ncomparison errors: {len(errors)}  {by_type}")
    with open(os.path.join(args.out, f"metadata_{args.label}.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
