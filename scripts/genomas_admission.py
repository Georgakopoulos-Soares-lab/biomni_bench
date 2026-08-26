#!/usr/bin/env python3
"""Acquire and attest the pinned public GenoTEX input tree for one smoke.

The downloader deliberately requests only raw ``input/**`` files.  Reference
outputs remain outside the agent's workspace and are never mounted into a run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download


def remote_manifest(repo_id: str, revision: str) -> dict:
    api = HfApi()
    files = []
    for item in api.list_repo_tree(repo_id, repo_type="dataset", revision=revision, path_in_repo="input", recursive=True, expand=True):
        if getattr(item, "size", None) is None:
            continue
        lfs = getattr(item, "lfs", None)
        files.append({"path": item.path, "size": item.size, "sha256": getattr(lfs, "sha256", None)})
    if not files:
        raise RuntimeError(f"no input files found in {repo_id}@{revision}")
    return {"schema_version": "genotex-input-manifest-v1", "repo_id": repo_id, "revision": revision,
            "retrieved_at": datetime.now(UTC).isoformat(), "file_count": len(files),
            "total_bytes": sum(f["size"] for f in files), "files": files}


def verify(data_root: Path, manifest: dict) -> dict:
    mismatches, observed = [], []
    for expected in manifest["files"]:
        p = data_root / expected["path"]
        if not p.is_file():
            mismatches.append({"path": expected["path"], "reason": "missing"})
            continue
        actual_size = p.stat().st_size
        with p.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        observed.append({"path": expected["path"], "size": actual_size, "sha256": digest})
        if actual_size != expected["size"] or (expected["sha256"] and digest != expected["sha256"]):
            mismatches.append({"path": expected["path"], "reason": "checksum_or_size_mismatch", "expected": expected, "actual": observed[-1]})
    return {"schema_version": "genotex-input-verification-v1", "verified_at": datetime.now(UTC).isoformat(),
            "data_root": str(data_root), "expected_file_count": manifest["file_count"], "observed_file_count": len(observed),
            "verified": not mismatches, "mismatches": mismatches, "observed": observed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--repo-id", default="Liu-Hy/GenoTEX")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--max-workers", type=int, default=2,
                        help="Bound concurrent Hugging Face requests (default: 2).")
    args = parser.parse_args()
    manifest = remote_manifest(args.repo_id, args.revision)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if args.download:
        snapshot_download(args.repo_id, repo_type="dataset", revision=args.revision, allow_patterns=["input/**"],
                          local_dir=args.data_root, cache_dir=args.data_root.parent / "hf_cache",
                          max_workers=args.max_workers)
    result = verify(args.data_root, manifest)
    args.verification.parent.mkdir(parents=True, exist_ok=True)
    args.verification.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["verified"]:
        raise SystemExit("GenoTEX input verification failed")


if __name__ == "__main__":
    main()
