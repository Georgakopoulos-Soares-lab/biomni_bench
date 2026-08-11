#!/usr/bin/env python
"""Generate the operator review sheet for A.5b's 18 `singled_out` instances.

WHY: the 51% figure rests on an automated heuristic that already had one bug
inflating it (the prose-vs-gene-list regex, which put it at 24 before the fix
brought it to 18). A heuristic that has been wrong once should be spot-checked
by a human before a manuscript claim rests on it.

WHAT THIS IS AND IS NOT: this is a **reading-comprehension** check — did this
trajectory actually discuss the correct answer preferentially, or is the count
an artifact? It is NOT a domain judgment, so it does not fall under the
deferred reviewer categories in A.5 (stale labels, incorrect labels, multiple
defensible answers), which genuinely need subject-matter expertise.

**This script does not adjudicate anything.** It emits evidence and blank
verdict fields for the operator to fill in. The agreement rate is computed and
reported only once the operator returns the completed sheet.

    python scripts/stage_a_review_sheet.py --out reports/a5b_review_sheet.md
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PHASE2B = Path("/scratch/11034/atzanakak/biomni_unc_runs/phase2b/results/tables")
STAGE_A = REPO / "reports" / "tables" / "stage_a"
CONTEXT_CHARS = 220
MAX_EXCERPTS = 3


def _load_triage():
    spec = importlib.util.spec_from_file_location("stage_a_label_triage", REPO / "scripts" / "stage_a_label_triage.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stage_a_label_triage"] = mod
    spec.loader.exec_module(mod)
    return mod


TRIAGE = _load_triage()


def model_text(run_dir: str) -> str:
    p = Path(run_dir) / "transcript.json"
    if not p.exists():
        return ""
    try:
        msgs = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    return "\n".join(TRIAGE.OBS_RE.sub(" ", str(m.get("content") or "")) for m in msgs if m.get("type") == "AIMessage")


def excerpts(text: str, token: str) -> list[str]:
    out = []
    for m in re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", text, re.I):
        a, b = max(0, m.start() - CONTEXT_CHARS), min(len(text), m.end() + CONTEXT_CHARS)
        out.append(re.sub(r"\s+", " ", text[a:b]).strip())
        if len(out) >= MAX_EXCERPTS:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    tri = pd.read_csv(STAGE_A / "a5_label_triage.csv")
    tri["task_instance_id"] = tri.task_instance_id.astype(int)
    flagged = tri[tri.singled_out.fillna(False).astype(bool)].sort_values(["task_name", "task_instance_id"])

    traj = pd.read_csv(PHASE2B / "p2b_pooled_trajectories.csv")
    traj["task_instance_id"] = traj.task_instance_id.astype(int)

    prompts, gts = {}, {}
    for line in (REPO / "manifests" / "phase2b.jsonl").read_text().splitlines():
        r = json.loads(line)
        prompts[(r["task_name"], int(r["task_instance_id"]))] = r["prompt"]
    for line in (REPO / "manifests" / "phase2b.groundtruth.jsonl").read_text().splitlines():
        r = json.loads(line)
        gts[(r["task_name"], int(r["task_instance_id"]))] = str(r["answer"])

    L = []
    L.append("# A.5b review sheet — operator adjudication of the 18 `singled_out` instances\n")
    L.append(
        "**What you are judging (reading comprehension, not domain expertise):** for each\n"
        "instance below, did the trajectory *actually discuss the correct answer\n"
        "preferentially over the other candidates*, or is the automated count an artifact\n"
        "(e.g. the answer appears only inside an enumeration of the candidate list, or\n"
        "inside copied code, or is a substring coincidence)?\n"
    )
    L.append(
        "**How to fill this in:** replace each `VERDICT: [ ]` with `AGREE` (the heuristic is\n"
        "right — the answer really was singled out) or `DISAGREE` (artifact), optionally with\n"
        "a short note. Return the edited file; the agreement rate will be computed from it\n"
        "and reported. Judging a subset is fine — leave the rest blank.\n"
    )
    L.append(
        "**Context.** These 18 are instances where *no* trajectory committed the correct\n"
        "answer, yet the model appears to have discussed it more than the wrong candidates.\n"
        "The manuscript claim resting on this is that a substantial part of the "
        '"30% unreachable"\nfigure is a commitment failure rather than a generation ceiling.\n'
    )
    L.append("\n---\n")

    for r in flagged.itertuples():
        key = (r.task_name, int(r.task_instance_id))
        gt = gts[key]
        toks = TRIAGE.gt_search_tokens(r.task_name, gt, prompts[key])
        cands = TRIAGE.candidates_from_prompt(r.task_name, prompts[key])

        L.append(f"\n## {r.task_name} / instance {r.task_instance_id}\n")
        L.append(f"- **Ground truth:** `{gt[:120]}`")
        L.append(f"- **Searched for:** {', '.join(f'`{t}`' for t in toks) if toks else '(none)'}")
        L.append(f"- **Candidates in prompt:** {len(cands)}")
        L.append(
            f"- **Automated counts:** correct answer mentioned {r.gt_mentions_model_text}x; "
            f"average wrong candidate {r.mean_wrong_candidate_mentions}x"
        )
        committed = [
            (t.answer_canonical if pd.notna(t.answer_canonical) else "(unparseable)")
            for t in traj[(traj.task_name == key[0]) & (traj.task_instance_id == key[1])].itertuples()
        ]
        L.append(f"- **What the trajectories committed:** {', '.join(f'`{c}`' for c in committed)}")
        L.append("\n**Excerpts around the correct answer in the model's own text:**\n")

        shown = 0
        for t in traj[(traj.task_name == key[0]) & (traj.task_instance_id == key[1])].itertuples():
            txt = model_text(t.run_dir)
            for tok in toks:
                for ex in excerpts(txt, tok):
                    L.append(f"> …{ex}…\n")
                    shown += 1
                    if shown >= MAX_EXCERPTS:
                        break
                if shown >= MAX_EXCERPTS:
                    break
            if shown >= MAX_EXCERPTS:
                break
        if shown == 0:
            L.append("> _(no excerpt extracted — flag this as DISAGREE if the count looks unsupported)_\n")

        L.append("\n**VERDICT: [ ]**  _(AGREE / DISAGREE, optional note)_\n")
        L.append("\n---\n")

    L.append(
        "\n### Once returned\n\n"
        "The agreement rate is computed over the completed verdicts and reported in\n"
        "`reports/stage_a_decomposition.md` and a `D-` entry. If the operator disagrees on a\n"
        "material fraction, the 51% figure is corrected or withdrawn accordingly — it is a\n"
        "heuristic estimate and is labelled as one until this sheet comes back.\n"
    )

    args.out.write_text("\n".join(L))
    print(f"wrote {args.out} covering {len(flagged)} instances")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
