#!/usr/bin/env python
"""Evidence-channel reliability diagnostic (VERIFY prerequisite item 1).

Reproduces the D-30 tool failures directly against the pinned Biomni tool
functions — no LLM calls, no agent, no GPU — and measures whether each
candidate route is reliable enough to be a VERIFY evidence source. Every query
used is a **real query the agent actually issued** during Phase 2B (drawn from
`events.jsonl`), so the measurement reflects the actual workload rather than
hand-picked queries.

Two outcome classes are distinguished, because the diagnostic in Track C found
that they are NOT the same thing:

* **error** — the call raised, or the tool's own exception handler returned an
  ``"Error: ..."`` string;
* **empty** — the call returned with no exception but no usable content. This
  is invisible to `runner.py`'s failure classification (a tool call that
  "succeeds" but retrieves nothing is logged as `status: "ok"`), so it is a
  distinct, previously-unmeasured failure mode reported separately here.

    python scripts/evidence_channel_diagnostic.py --out <dir> [--n-per-tool 8]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from glob import glob
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BIOMNI_SRC = Path("/work2/11034/atzanakak/biomni_bench/biomni_src")
sys.path.insert(0, str(BIOMNI_SRC))
sys.path.insert(0, str(REPO / "src"))

PHASE2B_RUNS = Path("/scratch/11034/atzanakak/biomni_unc_runs/phase2b/runs")
SEED = 20260810


def real_queries(tool: str, n: int) -> list[str]:
    """Queries the agent actually issued for `tool` during Phase 2B, sampled
    deterministically. Falls back to nothing if the tool was never called -
    the caller then knows to skip it rather than inventing a query."""
    rows = []
    for ev in glob(str(PHASE2B_RUNS / "*" / "i*" / "*" / "t*" / "events.jsonl")):
        for line in Path(ev).read_text(errors="replace").splitlines():
            if '"tool_call_start"' not in line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = e.get("payload") or {}
            if p.get("tool_name") == tool and p.get("argument_excerpt"):
                rows.append(p["argument_excerpt"])
    rng = random.Random(SEED)
    rng.shuffle(rows)
    # argument_excerpt is the raw call-site text, e.g. `"query" , max_papers=5`
    # or an f-string; extract just the quoted query for a clean function call.
    cleaned = []
    for r in rows:
        r = r.strip()
        if r.startswith('f"') or r.startswith("f'"):
            continue  # skip f-strings; we don't have the interpolated variable
        if r.startswith('"') or r.startswith("'"):
            q = r[1:].split(r[0], 1)[0]
            if q:
                cleaned.append(q)
    return cleaned[:n]


def call(fn, *args, **kwargs) -> dict:
    t0 = time.time()
    try:
        out = fn(*args, **kwargs)
    except Exception as exc:  # the whole point of this script is to observe this
        return {"outcome": "error", "detail": f"{type(exc).__name__}: {exc}", "elapsed": time.time() - t0}
    text = out if isinstance(out, str) else str(out)
    elapsed = time.time() - t0
    if text.strip().lower().startswith("error"):
        return {"outcome": "error", "detail": text[:200], "elapsed": elapsed}
    if not text.strip() or len(text.strip()) < 20:
        return {"outcome": "empty", "detail": f"len={len(text)}", "elapsed": elapsed}
    return {"outcome": "ok", "detail": text[:120].replace("\n", " "), "elapsed": elapsed}


def run_trials(name: str, fn, queries: list[str], **kwargs) -> dict:
    trials = []
    for q in queries:
        r = call(fn, q, **kwargs)
        r["query"] = q[:80]
        trials.append(r)
        time.sleep(0.5)  # be a polite, not-abusive caller of public services
    n = len(trials)
    n_ok = sum(1 for t in trials if t["outcome"] == "ok")
    n_err = sum(1 for t in trials if t["outcome"] == "error")
    n_empty = sum(1 for t in trials if t["outcome"] == "empty")
    return {
        "tool": name,
        "n_trials": n,
        "n_ok": n_ok,
        "n_error": n_err,
        "n_empty": n_empty,
        "ok_rate": n_ok / n if n else float("nan"),
        "trials": trials,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-per-tool", type=int, default=8)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    from biomni.tool.literature import query_arxiv, query_pubmed, query_scholar, search_google

    results = {}

    print("== AFTER: query_pubmed (pymed installed) ==")
    qs = real_queries("query_pubmed", args.n_per_tool)
    results["query_pubmed"] = run_trials("query_pubmed", query_pubmed, qs, max_papers=3)
    print(f"  {results['query_pubmed']['n_ok']}/{results['query_pubmed']['n_trials']} ok")

    print("== AFTER: query_arxiv (arxiv installed) ==")
    qs = real_queries("query_pubmed", args.n_per_tool)[: args.n_per_tool]  # arxiv had 0 real calls in Phase 2B
    results["query_arxiv"] = run_trials("query_arxiv", query_arxiv, qs, max_papers=2)
    print(f"  {results['query_arxiv']['n_ok']}/{results['query_arxiv']['n_trials']} ok")

    print("== AFTER: query_scholar (scholarly installed) ==")
    qs = real_queries("query_scholar", args.n_per_tool)
    results["query_scholar"] = run_trials("query_scholar", query_scholar, qs)
    print(
        f"  {results['query_scholar']['n_ok']}/{results['query_scholar']['n_trials']} ok, "
        f"{results['query_scholar']['n_error']} error"
    )

    print("== AFTER (unchanged): search_google (already installed pre-diagnosis) ==")
    qs = real_queries("search_google", args.n_per_tool)
    results["search_google"] = run_trials("search_google", search_google, qs, num_results=2)
    print(
        f"  {results['search_google']['n_ok']}/{results['search_google']['n_trials']} ok, "
        f"{results['search_google']['n_empty']} empty (silent failure - no exception raised)"
    )

    print("== NOT TESTED: advanced_web_search_claude (excluded by policy - proprietary API) ==")
    results["advanced_web_search_claude"] = {
        "tool": "advanced_web_search_claude",
        "n_trials": 0,
        "excluded_reason": "requires anthropic package + ANTHROPIC_API_KEY; "
        "introducing a proprietary LLM API dependency was explicitly ruled out",
    }

    (args.out / "evidence_channel_diagnostic.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nwrote {args.out}/evidence_channel_diagnostic.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
