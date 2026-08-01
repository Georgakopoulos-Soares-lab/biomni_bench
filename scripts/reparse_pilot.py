#!/usr/bin/env python3
"""One-time data repair: re-run canonicalization on stored raw responses.

Used once, after `canonicalization.py` gained the symbol-first-conclusion
pattern (found necessary on real Phase-1 data: ~30% of gwas_causal_gene_*
trajectories declared a clear answer, symbol-first, that the label-first-only
fallback could not extract). No model call is made; every raw response is
already on disk. This only fixes the parsed_answer/canonical-answer fields;
rewards are recomputed fresh at aggregation time from the corrected canonical
answer, so nothing here touches a reward directly.

Also relabels the two `unknown_failure` runs that were in fact
`model_context_overflow` under a second error phrasing the classifier did not
yet recognise (fixed in the same commit).

Every touched run is logged; nothing is silently changed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from biomni_uncertainty.canonicalization import parse_final_response  # noqa: E402
from biomni_uncertainty.provenance import write_json_atomic  # noqa: E402


def main(runs_root: str) -> None:
    root = Path(runs_root)
    n_checked = n_reparsed = n_changed = n_relabelled = 0

    for meta_path in sorted(root.glob("**/metadata.json")):
        run_dir = meta_path.parent
        meta = json.loads(meta_path.read_text())
        n_checked += 1

        if meta.get("failure_class") == "unknown_failure" and not meta.get("completed"):
            err = (meta.get("error") or "").lower()
            if "context length" in err and "longer than" in err:
                meta["failure_class"] = "model_context_overflow"
                write_json_atomic(meta_path, meta)
                n_relabelled += 1
            continue

        resp_path = run_dir / "final_response.txt"
        spec_path = run_dir / "run_spec.json"
        parsed_path = run_dir / "parsed_answer.json"
        if not (resp_path.exists() and spec_path.exists() and parsed_path.exists()):
            continue

        spec = json.loads(spec_path.read_text())
        raw = resp_path.read_text()
        old_parsed = json.loads(parsed_path.read_text())
        n_reparsed += 1

        new_parsed = parse_final_response(
            spec["task_name"],
            raw,
            spec["prompt"],
            confidence_requested=(spec["confidence_mode"] != "none"),
        )

        if new_parsed["parsed"]["status"] == old_parsed["parsed"]["status"]:
            continue

        write_json_atomic(parsed_path, new_parsed)
        meta["final_answer_parsed"] = new_parsed["parsed"]["raw"]
        meta["answer_canonical"] = new_parsed["parsed"]["canonical"]
        meta["answer_parse_status"] = new_parsed["parsed"]["status"]
        meta["answer_cluster_key"] = new_parsed["parsed"]["cluster_key"]
        if meta.get("completed") and meta.get("failure_class") == "agent_parse_failure":
            if new_parsed["parsed"]["status"] == "ok":
                meta["failure_class"] = None
        write_json_atomic(meta_path, meta)
        n_changed += 1
        print(
            f"  {meta['run_id']}: {old_parsed['parsed']['status']} -> "
            f"{new_parsed['parsed']['status']} "
            f"({old_parsed['parsed']['canonical']!r} -> {new_parsed['parsed']['canonical']!r})"
        )

    print(f"\nchecked={n_checked} reparsed={n_reparsed} changed={n_changed} relabelled={n_relabelled}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs")
