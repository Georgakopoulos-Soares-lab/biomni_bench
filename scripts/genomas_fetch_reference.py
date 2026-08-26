#!/usr/bin/env python3
"""Acquire and attest held-out GenoTEX reference outputs for new traits.

Mirrors ``genomas_admission.py``'s attested-fetch pattern (remote manifest via
``list_repo_tree``, download, then re-hash and compare) but for
``output/preprocess/<trait>`` -- the reference GenoMAS's native
``eval.py::evaluate_dataset_selection`` scores predictions against.

Only ``cohort_info.json`` and the reference ``code/*.py`` scripts are fetched
per trait, matching the minimal footprint the original
``Alcohol_Flush_Reaction`` admission reference used -- never the bulk
``gene_data``/``clinical_data`` CSVs, which the scorer never reads and which
would otherwise pull the trait's full solution data into a held-out location.
This reference directory is never mounted into an agent worktree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download


def remote_manifest(repo_id: str, revision: str, traits: list[str]) -> dict:
    api = HfApi()
    files = []
    for trait in traits:
        path_in_repo = f"output/preprocess/{trait}"
        found_cohort_info = False
        for item in api.list_repo_tree(repo_id, repo_type="dataset", revision=revision,
                                        path_in_repo=path_in_repo, recursive=True, expand=True):
            if getattr(item, "size", None) is None:  # a directory entry
                continue
            name = item.path.rsplit("/", 1)[-1]
            if name != "cohort_info.json" and not name.endswith(".py"):
                continue
            found_cohort_info = found_cohort_info or name == "cohort_info.json"
            lfs = getattr(item, "lfs", None)
            files.append({"path": item.path, "size": item.size, "sha256": getattr(lfs, "sha256", None)})
        if not found_cohort_info:
            raise RuntimeError(f"no reference cohort_info.json found for trait '{trait}' in {repo_id}@{revision}")
    return {"schema_version": "genotex-reference-manifest-v1", "repo_id": repo_id, "revision": revision,
            "traits": traits, "retrieved_at": datetime.now(UTC).isoformat(), "file_count": len(files),
            "total_bytes": sum(f["size"] for f in files), "files": files}


def verify(reference_root: Path, manifest: dict) -> dict:
    mismatches, observed = [], []
    for expected in manifest["files"]:
        p = reference_root / expected["path"]
        if not p.is_file():
            mismatches.append({"path": expected["path"], "reason": "missing"})
            continue
        actual_size = p.stat().st_size
        with p.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        observed.append({"path": expected["path"], "size": actual_size, "sha256": digest})
        if actual_size != expected["size"] or (expected["sha256"] and digest != expected["sha256"]):
            mismatches.append({"path": expected["path"], "reason": "checksum_or_size_mismatch",
                                "expected": expected, "actual": observed[-1]})
    return {"schema_version": "genotex-reference-verification-v1", "verified_at": datetime.now(UTC).isoformat(),
            "reference_root": str(reference_root), "expected_file_count": manifest["file_count"],
            "observed_file_count": len(observed), "verified": not mismatches, "mismatches": mismatches,
            "observed": observed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--repo-id", default="Liu-Hy/GenoTEX")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--trait", action="append", required=True, dest="traits")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    manifest = remote_manifest(args.repo_id, args.revision, args.traits)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if args.download:
        for f in manifest["files"]:
            hf_hub_download(args.repo_id, filename=f["path"], repo_type="dataset", revision=args.revision,
                            local_dir=args.reference_root, cache_dir=args.reference_root.parent / "hf_cache")

    result = verify(args.reference_root, manifest)
    args.verification.parent.mkdir(parents=True, exist_ok=True)
    args.verification.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["verified"]:
        raise SystemExit("GenoTEX reference verification failed")


if __name__ == "__main__":
    main()
