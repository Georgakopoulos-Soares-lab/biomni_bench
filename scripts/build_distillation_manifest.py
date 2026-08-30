#!/usr/bin/env python3
"""Build the two frozen SFT training manifests (control + treatment) for the
Biomni trajectory-distillation pilot, from the training-eligible corpus
(`phase1_pooled` K=4 + `phase2b_primary` K=2, per
`reports/biomni_trajectory_distillation_audit.md`).

Trajectory representation (decided in `close_out.md`'s B1/B2, evidence in
`reports/biomni_distillation_pilot_preregistration.md`): Option 2 -
"assistant trajectory with tool context". Reconstructed from each
trajectory's `stdout.log` (LangChain's own pretty-printed message log,
verified against `biomni.agent.a1`'s actual graph code, not guessed from
formatting):

* the run's single "Human Message" block is the task prompt (user turn);
* every subsequent "Ai Message" block is either a REAL generation (Biomni's
  own `generate()` node output - reasoning + prose + `<execute>`/`<solution>`)
  or a SYNTHETIC observation Biomni's `execute()` node injects as
  `AIMessage(content=f"<observation>{result}</observation>")` - verified in
  `biomni/agent/a1.py` line ~1550. Both are literally `assistant`-role
  messages in Biomni's own runtime (there is no `tool` role in this agent),
  so re-roling them would create a train/serve mismatch; instead each
  message here carries a `trainable` flag so a loss mask can be built
  without touching role structure.
* the system turn is NOT the true per-instance system prompt (that is
  rebuilt fresh per LLM call from RAG-retrieved resource descriptions,
  `a1.py::_generate_system_prompt`, and is never persisted verbatim -
  confirmed by inspecting the pinned source, not assumed) - a single fixed
  placeholder is used instead, and every manifest row says so explicitly
  (`system_prompt_is_placeholder: true`) rather than silently pretending to
  reconstruct it.

Never overwrites `manifests/phase1*.jsonl`/`manifests/phase2b*.jsonl`/
`manifests/scope_main.jsonl`. Asserts zero overlap with the held-out set
before writing anything, and hard-fails otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

HEADER_RE = re.compile(r"^={10,}\s+(Human|Ai) Message\s+={10,}\s*$")
OBS_RE = re.compile(r"^\s*<observation>.*</observation>\s*$", re.DOTALL)

SYSTEM_PLACEHOLDER = (
    "[Biomni system prompt placeholder - the true per-instance system prompt is rebuilt at "
    "generation time from RAG-retrieved tool/data-lake descriptions and is not persisted verbatim; "
    "see reports/biomni_distillation_pilot_preregistration.md SS(B1) for why this is a documented "
    "limitation, not a silent approximation.]"
)


def parse_stdout_log(path: Path) -> list[dict[str, Any]]:
    """Return an ordered list of {role, content, trainable} dicts.

    role is always "user" or "assistant" (matches Biomni's own runtime -
    there is no distinct tool role). trainable=False for the initial user
    turn and for injected `<observation>` blocks; True for every real
    assistant generation.
    """
    text = path.read_text(errors="replace")
    blocks: list[tuple[str, str]] = []
    cur_role: str | None = None
    cur: list[str] = []
    for line in text.split("\n"):
        m = HEADER_RE.match(line)
        if m:
            if cur_role is not None:
                blocks.append((cur_role, "\n".join(cur)))
            cur_role, cur = m.group(1), []
        else:
            cur.append(line)
    if cur_role is not None:
        blocks.append((cur_role, "\n".join(cur)))

    messages = [{"role": "system", "content": SYSTEM_PLACEHOLDER, "trainable": False}]
    for role, content in blocks:
        content = content.strip("\n")
        if role == "Human":
            messages.append({"role": "user", "content": content, "trainable": False})
        else:
            is_observation = bool(OBS_RE.match(content.strip()))
            messages.append({"role": "assistant", "content": content, "trainable": not is_observation})
    return messages


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def select_control(group: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Lowest-index COMPLETED trajectory, reward-agnostic."""
    completed = [r for r in group if r["completed"]]
    if not completed:
        return None
    return min(completed, key=lambda r: r["trajectory_index"])


def select_treatment(group: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Lowest-index trajectory among officially correct ones; None if no correct trajectory."""
    correct = [r for r in group if r["completed"] and r.get("correct") is True]
    if not correct:
        return None
    return min(correct, key=lambda r: r["trajectory_index"])


def load_source(csv_path: Path, *, trajectory_indices: set[int] | None) -> dict[str, list[dict[str, Any]]]:
    import pandas as pd

    df = pd.read_csv(csv_path)
    if "condition" in df.columns:
        df = df[df["condition"] == "instrumented"]
    if trajectory_indices is not None:
        df = df[df["trajectory_index"].isin(trajectory_indices)]
    df["task_id"] = df["task_name"] + "/" + df["task_instance_id"].astype(str)
    df["correct"] = df["correct"].astype("boolean") if "correct" in df.columns else None

    groups: dict[str, list[dict[str, Any]]] = {}
    for task_id, g in df.groupby("task_id"):
        groups[task_id] = g.to_dict("records")
    return groups


def build_examples(
    groups: dict[str, list[dict[str, Any]]],
    *,
    source_experiment: str,
    source_config: str,
    k_source: int,
    selector,
    selection_rule: str,
) -> list[dict[str, Any]]:
    examples = []
    for task_id, group in sorted(groups.items()):
        chosen = selector(group)
        if chosen is None:
            continue
        run_dir = Path(str(chosen["run_dir"]))
        stdout_path = run_dir / "stdout.log"
        if not stdout_path.exists():
            print(f"WARNING: {task_id} missing stdout.log at {stdout_path}, skipping", file=sys.stderr)
            continue
        messages = parse_stdout_log(stdout_path)
        prompt_text = next((m["content"] for m in messages if m["role"] == "user"), "")
        target_text = "\n".join(m["content"] for m in messages if m["role"] == "assistant" and m["trainable"])
        examples.append(
            {
                "task_id": task_id,
                "global_instance_id": chosen.get("global_instance_id"),
                "source_experiment": source_experiment,
                "source_config": source_config,
                "trajectory_index": int(chosen["trajectory_index"]),
                "official_reward": chosen.get("reward"),
                "completion_status": "completed" if chosen["completed"] else "incomplete",
                "selection_rule": selection_rule,
                "raw_run_path": str(run_dir),
                "trajectory_hash": _hash(json.dumps(messages, sort_keys=True)),
                "prompt_hash": _hash(prompt_text),
                "target_hash": _hash(target_text),
                "K_source": k_source,
                "n_messages": len(messages),
                "n_trainable_assistant_messages": sum(
                    1 for m in messages if m["role"] == "assistant" and m["trainable"]
                ),
                "messages": messages,
            }
        )
    return examples


def assert_no_held_out_overlap(task_ids: set[str], scope_main_path: Path) -> None:
    held_out = set()
    with scope_main_path.open() as fh:
        for line in fh:
            row = json.loads(line)
            held_out.add(f"{row['task_name']}/{row['task_instance_id']}")
    overlap = task_ids & held_out
    if overlap:
        raise SystemExit(
            f"FATAL: {len(overlap)} generated task IDs overlap the held-out set "
            f"({scope_main_path}): {sorted(overlap)[:10]}... Refusing to write any manifest."
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase1-pooled-trajectories", type=Path, required=True)
    ap.add_argument("--phase2b-trajectories", type=Path, required=True)
    ap.add_argument("--scope-main", type=Path, default=Path("manifests/scope_main.jsonl"))
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()

    p1_groups = load_source(args.phase1_pooled_trajectories, trajectory_indices=None)
    p2b_groups = load_source(args.phase2b_trajectories, trajectory_indices={0, 1})

    control = build_examples(
        p1_groups,
        source_experiment="phase1_pooled",
        source_config="configs/phase1.yaml+phase1_5.yaml",
        k_source=4,
        selector=select_control,
        selection_rule="vanilla_sft_lowest_index_completed",
    ) + build_examples(
        p2b_groups,
        source_experiment="phase2b_primary",
        source_config="configs/phase2b.yaml",
        k_source=2,
        selector=select_control,
        selection_rule="vanilla_sft_lowest_index_completed",
    )
    treatment = build_examples(
        p1_groups,
        source_experiment="phase1_pooled",
        source_config="configs/phase1.yaml+phase1_5.yaml",
        k_source=4,
        selector=select_treatment,
        selection_rule="reward_positive_lowest_index_correct",
    ) + build_examples(
        p2b_groups,
        source_experiment="phase2b_primary",
        source_config="configs/phase2b.yaml",
        k_source=2,
        selector=select_treatment,
        selection_rule="reward_positive_lowest_index_correct",
    )

    all_task_ids = {e["task_id"] for e in control} | {e["task_id"] for e in treatment}
    assert_no_held_out_overlap(all_task_ids, args.scope_main)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, examples in (("control_vanilla_sft", control), ("treatment_reward_positive_ensemble", treatment)):
        out = args.output_dir / f"{name}.jsonl"
        with out.open("w") as fh:
            for ex in examples:
                fh.write(json.dumps(ex) + "\n")
        assistant_tokens_chars = sum(
            len(m["content"]) for ex in examples for m in ex["messages"] if m["role"] == "assistant" and m["trainable"]
        )
        print(f"{name}: {len(examples)} examples -> {out}  (~{assistant_tokens_chars:,} trainable assistant chars)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
