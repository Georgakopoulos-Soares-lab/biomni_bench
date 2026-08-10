#!/usr/bin/env python
"""Track-C Step 2 — the candidate-adjudication pilot.

Tests VERIFY's load-bearing premise directly, at a fraction of a real
prospective run's cost: on the 78 `B_substantive_disagreement` instances
identified in Step 1 (D-37), the correct answer is often already present
among the existing candidate trajectories - just minority-held. Handing the
model the candidates and asking it to adjudicate has STRICTLY MORE
information than a real VERIFY trajectory would under D-32's `VerifyView`
(task prompt + one candidate only), so this is an upper bound on what VERIFY
could do. If adjudication cannot beat the plurality floor here, VERIFY cannot
either - a decisive negative result costs nothing but agent time, no new
instances, no held-out pool touched.

Two arms, per `reports/track_c_step2_acceptance_rule.md` (frozen before this
script generated a single trajectory):

* Arm 1 - one-shot, no tools. A bare chat completion, no agent scaffold.
* Arm 2 - the real Biomni A1 agent (`runner.run_trajectory`, same pipeline as
  every other trajectory in this project), given an adjudication-framed
  prompt. This is the arm with the kill-shot property.

Candidates come from already-completed, frozen trajectories (`phase2b` and
`phase1_pooled`). Nothing is regenerated from those pools; only NEW
adjudication trajectories are generated, against a THROWAWAY experiment tree
- never written to `manifests/` or `configs/`, no experiment ID registered.

    python scripts/track_c_adjudication_pilot.py prep   --out <dir>
    python scripts/track_c_adjudication_pilot.py arm1   --out <dir> --endpoint <url>
    python scripts/track_c_adjudication_pilot.py arm2   --out <dir> --endpoint <url> \
        --output-root <scratch_output_root> --python <agent_python>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pandas as pd  # noqa: E402

from biomni_uncertainty.benchmark import prompt_hash  # noqa: E402
from biomni_uncertainty.config import load_config  # noqa: E402
from biomni_uncertainty.policy import build_pools  # noqa: E402
from biomni_uncertainty.provenance import DirtyTreeError, assert_clean_tree  # noqa: E402
from biomni_uncertainty.sampling import RunSpec, make_run_id, run_dir_for  # noqa: E402

N_SAMPLES_PER_ARM = 3
SEED_BASE = 9000  # a stream distinct from every prior experiment's seed_base

ADJUDICATION_PREAMBLE = """IMPORTANT CONTEXT: multiple independent analyses have already been conducted \
for the question below, and produced the following candidate answers. Your task now is NOT to solve the \
question from scratch - it is to ADJUDICATE between these existing candidates and determine which one is \
most likely correct. You may use any tools, evidence, or verification you find useful to decide, but your \
final answer MUST be exactly one of the candidates listed below, reproduced in the same format the question \
below asks for.

Candidate answers under consideration:
{candidate_list}

--- Original question ---

{original_prompt}"""


# --------------------------------------------------------------------------
# prep: build the candidate set from frozen artifacts
# --------------------------------------------------------------------------


def _stratum_b_instances(pooled: pd.DataFrame, pool_label: str) -> list[dict]:
    pools = build_pools(pooled)
    out = []
    for pool in pools:
        v = pool.views(tuple(range(pool.k)))
        usable = [x for x in v if x.usable]
        distinct: dict[str, str] = {}
        for x in usable:
            distinct.setdefault(x.cluster_key, x.canonical_answer)
        if len(usable) < 2 or len(distinct) == 1:
            continue
        out.append(
            {
                "pool": pool_label,
                "task_name": pool.task_name,
                "task_instance_id": pool.task_instance_id,
                "global_instance_id": pool.rows[0]["global_instance_id"],
                "n_usable": len(usable),
                "candidates": sorted(distinct.values()),
            }
        )
    return out


def _load_prompts(path: Path) -> dict[tuple[str, int], str]:
    out = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out[(d["task_name"], int(d["task_instance_id"]))] = d["prompt"]
    return out


def cmd_prep(args: argparse.Namespace) -> int:
    args.out.mkdir(parents=True, exist_ok=True)

    p2b = pd.read_csv("/scratch/11034/atzanakak/biomni_unc_runs/phase2b/results/tables/p2b_pooled_trajectories.csv")
    p1 = pd.read_csv("/scratch/11034/atzanakak/biomni_unc_runs/phase1_pooled/results/tables/trajectories.csv")
    p1 = p1[p1.condition == "instrumented"]

    instances = _stratum_b_instances(p2b, "phase2b") + _stratum_b_instances(p1, "phase1_pooled")
    prompts = {}
    prompts.update(_load_prompts(REPO / "manifests" / "phase2b.jsonl"))
    prompts.update(_load_prompts(REPO / "manifests" / "phase1.jsonl"))

    missing = [r for r in instances if (r["task_name"], r["task_instance_id"]) not in prompts]
    if missing:
        raise SystemExit(f"{len(missing)} instances have no matching original prompt: {missing[:3]}")

    for r in instances:
        original = prompts[(r["task_name"], r["task_instance_id"])]
        candidate_list = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(r["candidates"]))
        r["adjudication_prompt"] = ADJUDICATION_PREAMBLE.format(candidate_list=candidate_list, original_prompt=original)

    out_path = args.out / "candidates.jsonl"
    with open(out_path, "w") as fh:
        for r in instances:
            fh.write(json.dumps(r) + "\n")

    (args.out / "exclusion_list.json").write_text(
        json.dumps(
            {
                "note": "Instances used as candidate sources in the Step-2 adjudication pilot. "
                "MUST be excluded from any future confirmatory VERIFY manifest.",
                "instances": [
                    {"task_name": r["task_name"], "task_instance_id": r["task_instance_id"]} for r in instances
                ],
            },
            indent=2,
        )
    )

    print(f"{len(instances)} stratum-B instances")
    print(pd.DataFrame(instances).groupby("pool").size().to_string())
    print(f"\nwrote {out_path}")
    print(f"wrote {args.out / 'exclusion_list.json'}")
    return 0


# --------------------------------------------------------------------------
# arm 1: one-shot, no tools
# --------------------------------------------------------------------------

#: Biomni-R0 is a reasoning model that always emits a <think> block before
#: answering (the same convention the agent scaffold relies on elsewhere in
#: this project). A raw one-shot completion has no stop-sequence to bound
#: that block, so it must be given enough tokens to finish reasoning AND
#: answer, and the answer must be asked for in an explicitly delimited form -
#: a bare "reproduce the candidate verbatim" instruction at 512 tokens
#: truncated mid-<think> on every sample in a 3-instance smoke test and never
#: reached an answer at all.
ARM1_MAX_TOKENS = 2048
FINAL_ANSWER_TAG = "FINAL ANSWER:"


def _chat_completion(endpoint: str, model: str, prompt: str, *, temperature: float, seed: int):
    import requests

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt + f"\n\nThink as needed, then end your response with a line reading exactly "
                f"'{FINAL_ANSWER_TAG} <candidate>', where <candidate> is reproduced verbatim from the list above.",
            }
        ],
        "temperature": temperature,
        "seed": seed,
        "max_tokens": ARM1_MAX_TOKENS,
    }
    t0 = time.time()
    r = requests.post(f"{endpoint.rstrip('/')}/chat/completions", json=payload, timeout=180)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    return text, time.time() - t0


def _match_candidate(text: str, candidates: list[str]) -> str | None:
    """Extract the FINAL ANSWER line if present (the primary path); otherwise
    fall back to whatever follows the last </think>, then to the whole text.
    Exact match after normalization only - no substring fallback, because
    several candidate sets in this pilot are single letters or short tokens
    (crispr_delivery: 'c'/'f') that would spuriously substring-match almost
    any reasoning text."""
    tail = text
    if FINAL_ANSWER_TAG in text:
        tail = text.rsplit(FINAL_ANSWER_TAG, 1)[1]
    elif "</think>" in text:
        tail = text.rsplit("</think>", 1)[1]
    norm = tail.strip().strip(".").strip("*").strip().lower()
    for c in candidates:
        if norm == str(c).strip().lower():
            return c
    # last resort: does the tail START with a candidate (handles trailing
    # punctuation/whitespace variants the strip above didn't catch)
    starts = [c for c in candidates if norm.startswith(str(c).strip().lower())]
    return starts[0] if len(starts) == 1 else None


def _one_arm1_call(endpoint: str, model: str, r: dict, s: int) -> dict:
    seed = SEED_BASE + s
    try:
        text, dt = _chat_completion(endpoint, model, r["adjudication_prompt"], temperature=0.7, seed=seed)
    except Exception as exc:  # noqa: BLE001
        return {"sample": s, "error": str(exc)}
    picked = _match_candidate(text, r["candidates"])
    return {"sample": s, "raw": text[:300], "picked": picked, "elapsed": dt}


def cmd_arm1(args: argparse.Namespace) -> int:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    instances = [json.loads(x) for x in (args.out / "candidates.jsonl").read_text().splitlines() if x.strip()]
    cfg = load_config(REPO / "configs" / "phase2b.yaml")
    model = cfg.model.identifier

    # Plain HTTP calls, no shared local state (unlike Arm 2's Biomni REPL,
    # which forces one process per trajectory) - thread-pool concurrency is
    # safe here, matching this project's usual per-endpoint concurrency.
    jobs = [(idx, r, s) for idx, r in enumerate(instances) for s in range(N_SAMPLES_PER_ARM)]
    samples_by_instance: dict[int, list] = {idx: [] for idx in range(len(instances))}
    done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = {pool.submit(_one_arm1_call, args.endpoint, model, r, s): idx for idx, r, s in jobs}
        for fut in as_completed(futs):
            idx = futs[fut]
            samples_by_instance[idx].append(fut.result())
            done += 1
            if done % 20 == 0:
                print(f"[arm1] {done}/{len(jobs)} calls", flush=True)

    results = []
    for idx, r in enumerate(instances):
        samples = sorted(samples_by_instance[idx], key=lambda s: s["sample"])
        results.append(
            {**{k: r[k] for k in ("pool", "task_name", "task_instance_id", "candidates")}, "samples": samples}
        )

    out_path = args.out / "arm1_results.jsonl"
    with open(out_path, "w") as fh:
        for r in results:
            fh.write(json.dumps(r) + "\n")
    print(f"wrote {out_path}")
    return 0


# --------------------------------------------------------------------------
# arm 2: the real agent
# --------------------------------------------------------------------------


def cmd_arm2_specs(args: argparse.Namespace) -> int:
    """Build the RunSpec list for Arm 2 and dispatch it through the real
    concurrency/resume/retry machinery every other trajectory in this project
    uses (`dispatcher.dispatch`), not a bespoke loop."""
    from biomni_uncertainty.dispatcher import check_endpoints, dispatch, load_endpoints

    try:
        assert_clean_tree(REPO, allow_dirty=args.allow_dirty)
    except DirtyTreeError as exc:
        raise SystemExit(f"REFUSING TO LAUNCH: {exc}") from exc

    instances = [json.loads(x) for x in (args.out / "candidates.jsonl").read_text().splitlines() if x.strip()]
    if args.limit:
        instances = instances[: args.limit]

    # A real, on-disk throwaway config (experiment.name differs from
    # phase2b.yaml; everything else - model/budget/controller settings -
    # byte-identical) rather than mutating the loaded pydantic model in
    # place, which is fragile and was the wrong approach on the first pass.
    cfg = load_config(args.config)

    specs: list[RunSpec] = []
    for r in instances:
        for s in range(N_SAMPLES_PER_ARM):
            condition = "adjudication"
            run_id = make_run_id(cfg.experiment_id, r["task_name"], r["task_instance_id"], condition, s)
            base = {
                "task_name": r["task_name"],
                "task_instance_id": r["task_instance_id"],
                "condition": condition,
                "trajectory_index": s,
            }
            specs.append(
                RunSpec(
                    experiment_id=cfg.experiment_id,
                    run_id=run_id,
                    condition=condition,
                    task_name=r["task_name"],
                    global_instance_id=r["global_instance_id"],
                    task_instance_id=r["task_instance_id"],
                    trajectory_index=s,
                    prompt=r["adjudication_prompt"],
                    prompt_hash=prompt_hash(r["adjudication_prompt"]),
                    split="val",
                    requested_seed=SEED_BASE + s,
                    confidence_mode=cfg.confidence.mode,
                    model=cfg.model.identifier,
                    model_revision=cfg.model.revision,
                    temperature=cfg.model.temperature,
                    max_tokens=cfg.model.max_tokens,
                    timeout_seconds=cfg.execution.run_timeout_seconds,
                    run_dir=str(run_dir_for(cfg, base)),
                )
            )

    print(f"{len(specs)} Arm-2 trajectory specs ({len(instances)} instances x {N_SAMPLES_PER_ARM} samples)")
    if args.dry_run:
        print("[dry-run] nothing dispatched")
        return 0

    endpoints = check_endpoints(load_endpoints(args.endpoints), cfg.model.identifier)
    if not any(e.healthy for e in endpoints):
        raise SystemExit("no healthy endpoint")

    summary = dispatch(specs, endpoints, cfg, str(args.config), resume=True, python=args.python)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prep")
    p_prep.add_argument("--out", type=Path, required=True)
    p_prep.set_defaults(func=cmd_prep)

    p_arm1 = sub.add_parser("arm1")
    p_arm1.add_argument("--out", type=Path, required=True)
    p_arm1.add_argument("--endpoint", required=True)
    p_arm1.add_argument("--concurrency", type=int, default=8)
    p_arm1.set_defaults(func=cmd_arm1)

    p_arm2 = sub.add_parser("arm2")
    p_arm2.add_argument("--out", type=Path, required=True)
    p_arm2.add_argument("--config", type=Path, required=True)
    p_arm2.add_argument("--endpoints", required=True, type=Path)
    p_arm2.add_argument("--python", default=None)
    p_arm2.add_argument("--limit", type=int, default=None)
    p_arm2.add_argument("--dry-run", action="store_true")
    p_arm2.add_argument("--allow-dirty", action="store_true")
    p_arm2.set_defaults(func=cmd_arm2_specs)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
