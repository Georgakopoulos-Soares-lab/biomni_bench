#!/usr/bin/env python
"""Stage A.5 - mechanical label triage of the 45 no-correct-trajectory instances.

CPU only, no GPU, no model calls. **No LLM is used to adjudicate any label.**
Using a model to validate labels the model failed on is the circularity this
audit exists to avoid, and it is not done here at any point.

Only the three expertise-free categories are attempted. Stale-label checks,
incorrect-label adjudication and multiple-defensible-answer judgments need
domain reviewers, are NOT performed, and are reported as an explicit limitation.

=========================================================================
INTERPRETATION RULES - FIXED BEFORE ANY NUMBER IN THIS FILE WAS COMPUTED
=========================================================================

**A.5a - evaluator / canonicalisation mismatch.** An instance counts as a
scoring artifact only if some trajectory's answer differs from ground truth
*purely* by normalisation: case, surrounding whitespace/punctuation/quotes,
integer-vs-string identity, or rsID prefix case. Deterministic string work
only. Gene-symbol synonymy needs an offline alias table; if none is available
the check is reported as NOT DONE rather than approximated, because a guessed
alias list would manufacture exactly the corrections it is meant to detect.

**A.5b - answer present in text but not committed.** THE ENUMERATION PROBLEM
IS THE WHOLE DIFFICULTY: on 9 of 10 tasks the prompt supplies a candidate list
that literally contains the correct answer, so "the trajectory mentions the
right answer" is nearly vacuous - a model that echoes the candidate list
"mentions" it without ever considering it. Three separate measures, and the
headline claim rests on the third:

1. `never_mentioned` - the answer never appears in the model's own generated
   text. Strong evidence the answer was never in play.
2. `mentioned` - it appears somewhere in model text. An UPPER BOUND on genuine
   consideration, not a measurement of it.
3. `singled_out` - it appears MORE often than the average wrong candidate from
   the same prompt list. This is the enumeration-robust measure: a model
   enumerating the list mentions every candidate about equally, so a
   preferential mention is evidence the answer was actually distinguished.

Model text = AIMessage content with `<observation>` blocks stripped, so tool
and code OUTPUT cannot be mistaken for the model's own reasoning. Observation
text is counted separately and reported as "retrieved but not used".

Reading: if a material fraction of the 45 *singled out* the correct answer and
still committed something else, then "30% unreachable" is wrong and part of the
failure is commitment/extraction rather than generation. If `singled_out` is
near zero while `mentioned` is high, the mentions are enumeration and the
generation reading survives.

**A.5c - prompt underdetermination.** A structural read of the prompt template,
one per task (templates, so one read fixes every instance of that task -
exactly D-37's procedure for mode-A eligibility). Judgment is about prompt
STRUCTURE - does the prompt supply what is needed to determine the answer
uniquely - never about domain correctness. Fixed in TASK_DETERMINACY below
before any count was taken.

    python scripts/stage_a_label_triage.py --out reports/tables/stage_a
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PHASE2B = Path("/scratch/11034/atzanakak/biomni_unc_runs/phase2b/results/tables")
PREFLIGHT = Path("/scratch/11034/atzanakak/biomni_unc_runs/track_c_preflight/results")
KEY = ["task_name", "task_instance_id"]

#: A.5c - structural determinacy of each task's PROMPT TEMPLATE. Written before
#: any instance was counted. "determinate" = the prompt supplies a closed
#: candidate set and the information needed to choose within it;
#: "requires_external_knowledge" = choosing correctly requires facts the prompt
#: never supplies. This is not a claim that the task is unanswerable - only that
#: the prompt alone does not determine the answer.
TASK_DETERMINACY = {
    "crispr_delivery": (
        "requires_external_knowledge",
        "Closed option list, but choosing among delivery methods needs published knowledge of "
        "what works for the named cell type; the prompt supplies only a one-line case description.",
    ),
    "gwas_causal_gene_gwas_catalog": (
        "requires_external_knowledge",
        "Closed gene list, but causality must come from external GWAS/functional evidence; the "
        "prompt supplies only the phenotype name and the locus gene list.",
    ),
    "gwas_causal_gene_opentargets": (
        "requires_external_knowledge",
        "Same template as gwas_catalog, differing only in the evidence source the label was drawn "
        "from; the prompt still supplies phenotype plus locus gene list and no causal evidence.",
    ),
    "gwas_causal_gene_pharmaprojects": (
        "requires_external_knowledge",
        "Same template as gwas_catalog, labelled from drug-pipeline evidence; the prompt again "
        "supplies only the phenotype and the locus gene list, never the evidence needed to choose.",
    ),
    "gwas_variant_prioritization": (
        "requires_external_knowledge",
        "Closed variant list; prioritisation requires external association statistics not in the prompt.",
    ),
    "lab_bench_dbqa": (
        "requires_external_knowledge",
        "Closed options; answering requires a specific database fact (e.g. miRDB v6.0 content) "
        "that the prompt does not contain.",
    ),
    "lab_bench_seqqa": (
        "determinate",
        "The sequence is supplied in full and the answer is computable from it by ORF translation - "
        "the one task whose prompt determines its own answer. Matches D-37's mode-A finding.",
    ),
    "patient_gene_detection": (
        "requires_external_knowledge",
        "Closed gene list, but mapping HPO phenotype codes to a causal gene requires external "
        "gene-phenotype databases.",
    ),
    "rare_disease_diagnosis": (
        "requires_external_knowledge",
        "Open-ended disease name + OMIM id; requires external disease knowledge. The only task whose "
        "answer is NOT contained in its prompt.",
    ),
    "screen_gene_retrieval": (
        "requires_external_knowledge",
        "Closed gene list; identifying the strongest perturbation effect requires screen data the "
        "prompt does not supply (confirmed by reading the full template in D-37 1b).",
    ),
}

OBS_RE = re.compile(r"<observation>.*?</observation>", re.DOTALL)
SOLUTION_RE = re.compile(r"<solution>(.*?)</solution>", re.DOTALL)


def candidates_from_prompt(task: str, prompt: str) -> list[str]:
    """Extract the closed candidate set the prompt supplies, per task template."""
    if task.startswith("gwas_causal_gene"):
        return re.findall(r"\{([^}]+)\}", prompt)
    if task == "gwas_variant_prioritization":
        m = re.search(r"Variants:\s*(.+)", prompt)
        return [x.strip() for x in m.group(1).split(",")] if m else []
    if task in ("patient_gene_detection", "rare_disease_diagnosis", "screen_gene_retrieval"):
        # Anchor on the literal "Candidate genes:" LABEL. A looser
        # case-insensitive "candidate genes" matches the prose instruction
        # ("From the following list of candidate genes, select ...") that
        # precedes the real list in screen_gene_retrieval, which silently
        # yields two garbage candidates and makes every comparison against
        # "the average wrong candidate" vacuously favourable.
        m = re.search(r"Candidate genes:\s*\[?([^\]\n]+)", prompt)
        return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()] if m else []
    if task == "crispr_delivery":
        return [t.strip() for _, t in re.findall(r"^([a-f])\.\s*(.+)$", prompt, re.M)]
    if task.startswith("lab_bench"):
        return [t.strip() for _, t in re.findall(r"^([A-E])\.\s*(.+)$", prompt, re.M)]
    return []


def gt_search_tokens(task: str, answer: str, prompt: str) -> list[str]:
    """The string(s) whose presence in text means 'the correct answer appears'.

    For lettered tasks the letter itself is meaningless in prose, so the mapped
    OPTION TEXT is used; where that option text is itself too short to search
    for reliably (lab_bench options are sometimes single amino-acid letters),
    the instance is reported as not assessable rather than guessed at.
    """
    if task == "rare_disease_diagnosis":
        try:
            d = json.loads(answer)
            return [t for t in (d.get("OMIM_ID"), d.get("disease_name")) if t]
        except (json.JSONDecodeError, AttributeError):
            return [answer]
    if task == "crispr_delivery":
        opts = dict(re.findall(r"^([a-f])\.\s*(.+)$", prompt, re.M))
        t = opts.get(answer.strip().lower(), "").strip()
        return [t] if len(t) >= 4 else []
    if task.startswith("lab_bench"):
        opts = dict(re.findall(r"^([A-E])\.\s*(.+)$", prompt, re.M))
        t = opts.get(answer.strip().upper(), "").strip()
        return [t] if len(t) >= 4 else []
    return [answer]


def count_mentions(text: str, token: str) -> int:
    if not token:
        return 0
    return len(re.findall(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", text, re.I))


def normalised_equal(a: str, b: str) -> bool:
    """A.5a: do these differ ONLY by normalisation?"""
    if a is None or b is None:
        return False

    def norm(x):
        # Strip surrounding whitespace, quotes and trailing punctuation
        # REPEATEDLY: a single pass leaves "'BRCA1'." as "BRCA1'" because the
        # trailing quote is only exposed after the period is removed, which
        # would let a genuine scoring artifact slip past this check.
        x = str(x)
        prev = None
        while prev != x:
            prev = x
            x = x.strip().strip("'\"").strip().rstrip(".,;:")
        return x.lower()

    if norm(a) == norm(b):
        return True
    try:  # integer-vs-string identity (e.g. an OMIM id)
        if float(a) == float(b):
            return True
    except (TypeError, ValueError):
        pass
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pre = pd.read_csv(PREFLIGHT / "instance_table__phase2b.csv")
    pre["task_instance_id"] = pre.task_instance_id.astype(int)
    nocorrect = pre[pre.no_correct_trajectory.astype(bool)][KEY]
    target = {tuple(x) for x in nocorrect.values}

    traj = pd.read_csv(PHASE2B / "p2b_pooled_trajectories.csv")
    traj["task_instance_id"] = traj.task_instance_id.astype(int)

    prompts, gts = {}, {}
    for line in (REPO / "manifests" / "phase2b.jsonl").read_text().splitlines():
        r = json.loads(line)
        prompts[(r["task_name"], int(r["task_instance_id"]))] = r["prompt"]
    for line in (REPO / "manifests" / "phase2b.groundtruth.jsonl").read_text().splitlines():
        r = json.loads(line)
        gts[(r["task_name"], int(r["task_instance_id"]))] = str(r["answer"])

    rows = []
    for key in sorted(target):
        task, tid = key
        prompt, answer = prompts[key], gts[key]
        toks = gt_search_tokens(task, answer, prompt)
        cands = candidates_from_prompt(task, prompt)
        wrong = [c for c in cands if not any(normalised_equal(c, t) for t in toks)]

        model_text, obs_text, sol_text = [], [], []
        committed = []
        per_traj = []  # (parsed_ok, canonical, solution_text) - kept per trajectory
        for r in traj[(traj.task_name == task) & (traj.task_instance_id == tid)].itertuples():
            d = Path(r.run_dir)
            committed.append(r.answer_canonical)
            tp = d / "transcript.json"
            if not tp.exists():
                continue
            try:
                msgs = json.loads(tp.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            mine = []
            for m in msgs:
                if m.get("type") != "AIMessage":
                    continue  # never the prompt: the answer is IN the prompt on 9/10 tasks
                c = str(m.get("content") or "")
                obs_text.extend(OBS_RE.findall(c))
                model_text.append(OBS_RE.sub(" ", c))
                blocks = SOLUTION_RE.findall(c)
                sol_text.extend(blocks)
                mine.extend(blocks)
            per_traj.append(
                {
                    "parsed_ok": str(getattr(r, "answer_parse_status", "")) == "ok" and pd.notna(r.answer_canonical),
                    "canonical": r.answer_canonical,
                    "solution": "\n".join(mine),
                }
            )

        mt = "\n".join(model_text)
        ot = "\n".join(obs_text)
        st = "\n".join(sol_text)

        assessable = bool(toks)
        gt_hits = max((count_mentions(mt, t) for t in toks), default=0) if assessable else None
        # `singled_out` compares the answer against the OTHER candidates, so it
        # is only meaningful when the answer is itself drawn from that closed
        # set. On rare_disease_diagnosis the candidates are genes while the
        # answer is a disease + OMIM id, so there is no comparable wrong-answer
        # set and the measure is undefined - but `never_mentioned` is unusually
        # clean there, because it is the one task whose answer is NOT in the
        # prompt and so cannot be mentioned by mere enumeration.
        gt_is_a_candidate = assessable and any(any(normalised_equal(c, t) for t in toks) for c in cands)
        wrong_hits = [count_mentions(mt, c) for c in wrong] if (wrong and gt_is_a_candidate) else []
        mean_wrong = (sum(wrong_hits) / len(wrong_hits)) if wrong_hits else None

        # A.5a - scoring artifact?
        artifact = any(normalised_equal(c, answer) and str(c) != str(answer) for c in committed if pd.notna(c))
        # Two very different things, kept apart. The solution blocks here are
        # long prose reports, so the answer routinely APPEARS inside one that
        # commits a different gene - that is discussion, not a lost answer.
        # A genuine extraction failure requires the trajectory to have produced
        # no parseable answer at all AND its own solution block to contain the
        # correct one.
        gt_in_any_solution = assessable and any(count_mentions(st, t) > 0 for t in toks)

        def gt_dominates(block: str, toks=toks, wrong=wrong) -> bool:
            """Same enumeration-robust logic as `singled_out`, applied inside a
            single solution block: a long prose report that lists many
            candidates is not a commitment to any of them."""
            g = max((count_mentions(block, t) for t in toks), default=0)
            if g == 0:
                return False
            if not wrong:
                return True
            others = [count_mentions(block, c) for c in wrong]
            return g > max(others, default=0)

        unparsed = [p for p in per_traj if not p["parsed_ok"]]
        extraction_failure_loose = assessable and any(
            any(count_mentions(p["solution"], t) > 0 for t in toks) for p in unparsed
        )
        extraction_failure = assessable and any(gt_dominates(p["solution"]) for p in unparsed)

        rows.append(
            {
                "task_name": task,
                "task_instance_id": tid,
                "gt_in_prompt": any(t in prompt for t in toks) if assessable else None,
                "assessable": assessable,
                "n_candidates_in_prompt": len(cands),
                "gt_mentions_model_text": gt_hits,
                "mean_wrong_candidate_mentions": mean_wrong,
                "gt_mentions_observations": (
                    max((count_mentions(ot, t) for t in toks), default=0) if assessable else None
                ),
                "answer_is_one_of_the_prompt_candidates": gt_is_a_candidate,
                "never_mentioned": (gt_hits == 0) if assessable else None,
                "singled_out": (bool(gt_hits > mean_wrong) if (assessable and mean_wrong is not None) else None),
                "gt_in_any_solution_block": gt_in_any_solution,
                "extraction_failure": extraction_failure,
                "extraction_failure_loose": extraction_failure_loose,
                "scoring_artifact_a5a": artifact,
                "determinacy_a5c": TASK_DETERMINACY[task][0],
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(args.out / "a5_label_triage.csv", index=False)

    ass = df[df.assessable]
    summary = {
        "n_no_correct_instances": int(len(df)),
        "n_assessable": int(len(ass)),
        "n_not_assessable": int((~df.assessable).sum()),
        "not_assessable_note": (
            "lettered-option tasks whose correct option text is too short to search for reliably "
            "(e.g. a single amino-acid letter); reported rather than guessed at"
        ),
        "A5a_scoring_artifacts": {
            "n": int(df.scoring_artifact_a5a.sum()),
            "gene_synonym_check": "NOT DONE - no offline alias table available; not approximated",
        },
        "A5b": {
            "never_mentioned": int(ass.never_mentioned.sum()),
            "mentioned": int((~ass.never_mentioned.astype(bool)).sum()),
            "singled_out": int(ass.singled_out.fillna(False).sum()),
            "singled_out_denominator": int(ass.singled_out.notna().sum()),
            "gt_appears_in_some_solution_block": int(ass.gt_in_any_solution_block.sum()),
            "extraction_failure_answer_dominates_block": int(ass.extraction_failure.sum()),
            "extraction_failure_answer_merely_appears": int(ass.extraction_failure_loose.sum()),
            "extraction_failure_note": (
                "a trajectory that produced NO parseable answer while its own solution block "
                "contained the correct one - the answer was generated and lost. Distinguished from "
                "the far commoner case of the answer being discussed inside a long prose solution "
                "that commits a different candidate, which is not a lost answer."
            ),
            "instances_with_gt_in_prompt": int(ass.gt_in_prompt.sum()),
            "reading": (
                "`mentioned` is an upper bound contaminated by candidate-list enumeration; "
                "`singled_out` (mentioned more than the average wrong candidate) is the "
                "enumeration-robust measure and is the one the claim rests on"
            ),
        },
        "A5c_determinacy": {k: {"verdict": v[0], "why": v[1]} for k, v in TASK_DETERMINACY.items()},
        "A5c_counts_over_the_45": df.determinacy_a5c.value_counts().to_dict(),
        "NOT_DONE": [
            "stale-label checks",
            "incorrect-label adjudication",
            "multiple-defensible-answer judgments",
        ],
        "NOT_DONE_why": "each needs domain reviewers; an LLM is deliberately NOT substituted (circularity)",
    }
    by_task = (
        ass.groupby("task_name")
        .agg(
            n=("task_name", "size"),
            never_mentioned=("never_mentioned", "sum"),
            singled_out=("singled_out", lambda s: int(s.fillna(False).sum())),
        )
        .reset_index()
    )
    by_task.to_csv(args.out / "a5_by_task.csv", index=False)
    summary["by_task"] = by_task.to_dict("records")

    # ---- corrected scoring, side by side with official ------------------
    # A.5a found no pure-normalisation artifacts, so official and
    # audit-corrected scoring differ ONLY by the extraction failures: instances
    # where a trajectory generated the correct answer and lost it to parsing.
    # Nothing else in the audit licenses changing a score - in particular
    # `singled_out` does NOT, because considering an answer is not producing it.
    corrected = df[df.extraction_failure.astype(bool)][KEY]
    n_total = int(len(pre))
    official_nocorrect = int(len(df))
    corrected_nocorrect = official_nocorrect - int(len(corrected))
    oracle_official = float(pre.oracle_reward.mean())
    plurality = float(pre.plurality_reward.mean())
    summary["corrected_scoring"] = {
        "n_instances": n_total,
        "no_correct_official": official_nocorrect,
        "no_correct_corrected": corrected_nocorrect,
        "no_correct_rate_official": official_nocorrect / n_total,
        "no_correct_rate_corrected": corrected_nocorrect / n_total,
        "oracle_at_4_official": oracle_official,
        "oracle_at_4_corrected": oracle_official + len(corrected) / n_total,
        "plurality": plurality,
        "selection_headroom_official": oracle_official - plurality,
        "selection_headroom_corrected": oracle_official + len(corrected) / n_total - plurality,
        "what_changed": (
            "only the extraction failures are re-scored; A.5a found 0 pure-normalisation "
            "artifacts, and `singled_out` is deliberately NOT used to re-score anything"
        ),
        "by_task": corrected.groupby("task_name").size().to_dict(),
    }

    (args.out / "a5_label_triage.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
