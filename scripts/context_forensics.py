#!/usr/bin/env python
"""Context-growth forensics over stored run event logs.

Answers, from evidence already on disk (no model calls, no GPU):

* where the context of a Biomni trajectory actually goes;
* whether ``model_context_overflow`` is a budget problem or a behavioural one;
* what a prompt/tool/output repair would and would not buy.

Reads ``<output_root>/<experiment>/runs/**/events.jsonl`` plus ``metadata.json``
and writes a tidy per-call table, a per-run table and a printed summary.

Usage::

    python scripts/context_forensics.py --runs-root <output_root>/phase1/runs \
        --out-dir reports/forensics
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import Counter
from pathlib import Path

# The served window and the per-request generation reservation. A request is
# rejected when input + max_tokens exceeds the window, so the effective input
# ceiling is CONTEXT_WINDOW - MAX_TOKENS.
CONTEXT_WINDOW = 65536
MAX_TOKENS = 8192

# Qwen3-32B (this model's base) is trained at 32,768 tokens of context; the
# 40,960 in config.json is that plus one 8,192-token generation. This is the
# boundary the forensics tests against.
NATIVE_CONTEXT = 32768


def read_events(path: Path) -> list[dict]:
    """Read a JSONL event log, stopping at a truncated tail line."""
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                break
    return out


def load_runs(runs_root: Path) -> list[dict]:
    """Build one record per run directory from its event log and metadata."""
    runs = []
    for ev_path in sorted(runs_root.glob("*/i*/*/t*/events.jsonl")):
        d = ev_path.parent
        meta_path = d / "metadata.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        failed_path = d / "FAILED"
        failed = json.loads(failed_path.read_text()) if failed_path.exists() else {}

        calls, retrieval_selected, retrieval_offered = [], None, None
        for e in read_events(ev_path):
            p = e.get("payload") or {}
            if e["event_type"] == "llm_request_end":
                u = p.get("usage") or {}
                calls.append(
                    {"inp": u.get("input_tokens"), "out": u.get("output_tokens"), "fin": p.get("finish_reason")}
                )
            elif e["event_type"] == "retrieval_end":
                retrieval_selected = p.get("selected")
            elif e["event_type"] == "retrieval_start":
                retrieval_offered = {k: p.get(k) for k in ("n_tools", "n_data_lake", "n_libraries")}

        # metadata.json is absent when the process was killed before it could be
        # written; FAILED still records why. Those runs are NOT missing evidence.
        failure_class = meta.get("failure_class") or failed.get("failure_class")
        completed = meta.get("completed", False)
        outcome = "completed" if completed else (failure_class or "unknown")

        runs.append(
            {
                "run_dir": str(d.relative_to(runs_root)),
                "task": d.parts[-4],
                "instance": d.parts[-3],
                "condition": d.parts[-2],
                "trajectory": d.parts[-1],
                "completed": completed,
                "failure_class": failure_class,
                "outcome": outcome,
                "has_metadata": meta_path.exists(),
                "wall_time_seconds": meta.get("wall_time_seconds") or failed.get("wall_time_seconds"),
                "calls": calls,
                "retrieval_selected": retrieval_selected,
                "retrieval_offered": retrieval_offered,
            }
        )
    return runs


def derive(r: dict) -> dict:
    """Per-run derived context statistics.

    Call 0 is Biomni's tool-retrieval query, which is not part of the agent
    conversation; calls 1.. are the agent loop, so the growth ledger is built
    over those only.
    """
    c = r["calls"]
    loop = c[1:]
    r["n_calls"] = len(c)
    r["peak_input_tokens"] = max([x["inp"] for x in c if x["inp"]], default=0)
    r["retrieval_input_tokens"] = c[0]["inp"] if c else None
    r["retrieval_output_tokens"] = c[0]["out"] if c else None
    r["retrieval_finish_reason"] = c[0]["fin"] if c else None
    # The first agent-loop call carries the whole post-retrieval system prompt
    # plus the task prompt, and nothing else: it is the fixed overhead.
    r["post_retrieval_prompt_tokens"] = loop[0]["inp"] if loop else None
    r["n_runaway"] = sum(1 for x in loop if x["fin"] == "length")
    r["first_runaway_at_tokens"] = next((x["inp"] for x in loop if x["fin"] == "length"), None)
    r["first_runaway_step"] = next((i for i, x in enumerate(loop) if x["fin"] == "length"), None)

    # Growth ledger: each step's input grows by (previous output) + (observation
    # appended by the executor). Anything beyond the previous output is tool
    # output; the rest is the model's own text re-entering the context.
    obs = gen = 0
    for i in range(1, len(loop)):
        delta = loop[i]["inp"] - loop[i - 1]["inp"]
        prev_out = loop[i - 1]["out"] or 0
        obs += max(0, delta - prev_out)
        gen += max(0, min(delta, prev_out))
    r["tool_output_tokens_in_context"] = obs
    r["model_output_tokens_in_context"] = gen
    return r


def summarize(runs: list[dict]) -> None:
    groups: dict[str, list[dict]] = {}
    for r in runs:
        groups.setdefault("completed" if r["completed"] else "failed", []).append(r)
    comp, fail = groups.get("completed", []), groups.get("failed", [])
    med = lambda xs: st.median(xs) if xs else float("nan")  # noqa: E731

    print(f"runs: {len(runs)}  completed: {len(comp)}  failed: {len(fail)}")
    print(f"failure classes: {dict(Counter(r['failure_class'] for r in fail))}\n")

    print("1. FIXED OVERHEAD — the post-retrieval system prompt is small")
    print("-" * 74)
    base = [r["post_retrieval_prompt_tokens"] for r in runs if r["post_retrieval_prompt_tokens"]]
    q = st.quantiles(base, n=4)
    print(
        f"   post-retrieval prompt + task, tokens: median {med(base):.0f} "
        f"(p25 {q[0]:.0f}, p75 {q[2]:.0f}, max {max(base)})"
    )
    sel = [r["retrieval_selected"] for r in runs if r["retrieval_selected"]]
    for k, offered in (("tools", 224), ("data_lake", 76), ("libraries", 113)):
        v = sorted(s.get(k, 0) for s in sel)
        print(
            f"   retrieval selected {k:<10} median {med(v):5.1f} / {offered:3d} offered "
            f"(p95 {v[int(0.95 * len(v))]}, max {max(v)})"
        )

    print("\n2. THE DOMINANT MECHANISM — runaway (unterminated) generations")
    print("-" * 74)
    for name, rs in (("completed", comp), ("failed", fail)):
        any_r = sum(1 for r in rs if r["n_runaway"] > 0)
        print(
            f"   {name:<10} n={len(rs):3d}  with >=1 runaway generation: {any_r:3d} ({any_r / len(rs):5.1%})  "
            f"median count {med([r['n_runaway'] for r in rs]):.0f}"
        )
    firsts = [r["first_runaway_at_tokens"] for r in runs if r["first_runaway_at_tokens"]]
    print(
        f"   input tokens when the FIRST runaway fired: median {med(firsts):.0f} "
        f"(min {min(firsts)}, max {max(firsts)}) — far below the {CONTEXT_WINDOW}-token ceiling"
    )

    print("\n3. RUNAWAY RATE VS INPUT CONTEXT LENGTH (per agent-loop call)")
    print("-" * 74)
    calls = [
        (x["inp"], x["fin"] == "length")
        for r in runs
        for x in r["calls"][1:]
        if x["inp"] is not None and x["fin"] is not None
    ]
    edges = [0, 8192, 16384, 24576, NATIVE_CONTEXT, 40960, 49152, 10**9]
    for lo, hi in zip(edges, edges[1:], strict=False):
        sub = [c for c in calls if lo <= c[0] < hi]
        if not sub:
            continue
        n = sum(1 for c in sub if c[1])
        mark = "  <-- base model's trained context" if lo == NATIVE_CONTEXT else ""
        print(
            f"   {lo:6d}-{min(hi, CONTEXT_WINDOW):6d}: {len(sub):5d} calls, {n:4d} runaway ({n / len(sub):6.1%}){mark}"
        )

    print("\n4. CONFOUND CHECK — runs whose prompt ALONE already exceeded the boundary")
    print("-" * 74)
    big = [r for r in runs if (r["post_retrieval_prompt_tokens"] or 0) >= NATIVE_CONTEXT]
    ran = sum(1 for r in big if r["calls"][1]["fin"] == "length")
    print(
        f"   {len(big)} runs began past {NATIVE_CONTEXT} tokens; {ran} degenerated on their FIRST agent call; "
        f"{sum(1 for r in big if not r['completed'])} failed."
    )
    print("   No conversation history had accumulated, so trajectory difficulty cannot explain this.")

    print("\n5. WHERE THE CONTEXT GOES (median tokens per run)")
    print("-" * 74)
    for name, rs in (("completed", comp), ("failed", fail)):
        print(
            f"   {name:<10} prompt {med([r['post_retrieval_prompt_tokens'] or 0 for r in rs]):6.0f} | "
            f"model output {med([r['model_output_tokens_in_context'] for r in rs]):7.0f} | "
            f"tool output {med([r['tool_output_tokens_in_context'] for r in rs]):7.0f}"
        )

    print("\n6. HEADROOM — how much of the served window healthy trajectories use")
    print("-" * 74)
    peaks = sorted(r["peak_input_tokens"] for r in comp)
    print(
        f"   completed runs, peak input tokens: median {med(peaks):.0f}, p95 "
        f"{peaks[int(0.95 * len(peaks))]}, max {max(peaks)}"
    )
    for ceiling in (24576, 28672, NATIVE_CONTEXT):
        n = sum(1 for p in peaks if p > ceiling)
        nf = sum(1 for r in fail if r["peak_input_tokens"] > ceiling)
        print(
            f"   input budget {ceiling:6d}: would truncate {n:3d}/{len(peaks)} completed runs; "
            f"would catch {nf:3d}/{len(fail)} failed runs before the hard ceiling"
        )

    print("\n7. COUNTERFACTUAL — bounding what a runaway generation contributes")
    print("-" * 74)
    for cap in (512, 1024, 2048):
        adj = []
        for r in fail:
            excess = sum(x["out"] - cap for x in r["calls"][1:-1] if x["fin"] == "length" and x["out"] > cap)
            adj.append(r["peak_input_tokens"] - excess)
        under = sum(1 for a in adj if a <= CONTEXT_WINDOW - MAX_TOKENS)
        print(
            f"   truncate runaway output to {cap:5d} tokens: median peak "
            f"{med([r['peak_input_tokens'] for r in fail]):6.0f} -> {med(adj):6.0f}; "
            f"{under}/{len(fail)} failed runs stay under the request ceiling"
        )
    ok = sorted(x["out"] for r in runs for x in r["calls"][1:] if x["fin"] == "stop" and x["out"] is not None)
    for cap in (1024, 2048, 4096):
        n = sum(1 for x in ok if x > cap)
        print(f"   cost: max_tokens={cap:5d} would truncate {n:4d}/{len(ok)} healthy generations ({n / len(ok):.2%})")

    print("\n8. WASTE")
    print("-" * 74)
    tw = sum(r["wall_time_seconds"] or 0 for r in runs)
    fw = sum(r["wall_time_seconds"] or 0 for r in fail)
    print(
        f"   wall-clock spent on trajectories that produced no answer: {fw / 3600:.1f} h of "
        f"{tw / 3600:.1f} h ({fw / tw:.1%})"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-root", required=True, type=Path)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    runs = [derive(r) for r in load_runs(args.runs_root)]
    if not runs:
        raise SystemExit(f"no run directories with events.jsonl under {args.runs_root}")
    summarize(runs)

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        per_run = args.out_dir / "context_forensics_per_run.json"
        per_run.write_text(json.dumps([{k: v for k, v in r.items() if k != "calls"} for r in runs], indent=2))
        per_call = args.out_dir / "context_forensics_per_call.jsonl"
        with open(per_call, "w", encoding="utf-8") as fh:
            for r in runs:
                for i, x in enumerate(r["calls"]):
                    fh.write(
                        json.dumps(
                            {
                                "run_dir": r["run_dir"],
                                "task": r["task"],
                                "outcome": r["outcome"],
                                "call_index": i,
                                "is_retrieval_call": i == 0,
                                "input_tokens": x["inp"],
                                "output_tokens": x["out"],
                                "finish_reason": x["fin"],
                            }
                        )
                        + "\n"
                    )
        print(f"\nwrote {per_run} and {per_call}")


if __name__ == "__main__":
    main()
