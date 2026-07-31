#!/usr/bin/env python3
"""Wait for SGLang replicas to become healthy, then aggregate endpoints.json.

Two modes:

``--url URL``
    Poll one endpoint's ``/v1/models`` until it answers or the timeout expires.

``--aggregate --endpoints-dir DIR --expected-nodes N``
    Wait until N per-node files have appeared, merge them into ``endpoints.json``
    and poll every endpoint until all are healthy. Exits non-zero if any server
    never becomes ready, so the dispatcher is never started against a half-up
    cluster.

Per-node files are written by launch_node_servers.sh with an atomic rename, so
the merge here never races with a node still publishing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def probe(url: str, timeout: float = 5.0) -> tuple[bool, list[str], str | None]:
    models_url = url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(models_url, timeout=timeout) as r:  # noqa: S310 - operator-supplied local URL
            if r.status != 200:
                return False, [], f"HTTP {r.status}"
            data = json.loads(r.read().decode())
            return True, [m["id"] for m in data.get("data", [])], None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as exc:
        return False, [], repr(exc)


def wait_one(url: str, timeout: int, interval: float) -> int:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        ok, models, err = probe(url)
        if ok:
            print(f"[wait_for_server] READY {url} models={models}")
            return 0
        last = err
        remaining = int(deadline - time.time())
        print(f"[wait_for_server] waiting for {url} ({remaining}s left): {err}", flush=True)
        time.sleep(interval)
    print(f"[wait_for_server] TIMEOUT after {timeout}s for {url}: {last}", file=sys.stderr)
    return 1


def aggregate(endpoints_dir: Path, expected_nodes: int, out: Path, timeout: int, interval: float) -> int:
    deadline = time.time() + timeout

    # Phase 1: every expected node must publish its file.
    node_files: list[Path] = []
    while time.time() < deadline:
        node_files = sorted(endpoints_dir.glob("node_*.json"))
        if len(node_files) >= expected_nodes:
            break
        print(
            f"[wait_for_server] {len(node_files)}/{expected_nodes} nodes have published endpoints",
            flush=True,
        )
        time.sleep(interval)
    if len(node_files) < expected_nodes:
        print(
            f"[wait_for_server] TIMEOUT: only {len(node_files)}/{expected_nodes} nodes published endpoints",
            file=sys.stderr,
        )
        return 1

    endpoints = []
    for f in node_files:
        try:
            payload = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[wait_for_server] unreadable {f}: {exc}", file=sys.stderr)
            return 1
        endpoints.extend(payload.get("endpoints", []))

    if not endpoints:
        print("[wait_for_server] no endpoints published", file=sys.stderr)
        return 1

    # Phase 2: every endpoint must answer /v1/models.
    healthy: dict[str, list[str]] = {}
    while time.time() < deadline and len(healthy) < len(endpoints):
        for ep in endpoints:
            if ep["url"] in healthy:
                continue
            ok, models, err = probe(ep["url"])
            if ok:
                healthy[ep["url"]] = models
                print(f"[wait_for_server] READY {ep['label']} {ep['url']} models={models}", flush=True)
            else:
                print(f"[wait_for_server] not ready {ep['label']}: {err}", flush=True)
        if len(healthy) < len(endpoints):
            time.sleep(interval)

    if len(healthy) < len(endpoints):
        missing = [e["url"] for e in endpoints if e["url"] not in healthy]
        print(f"[wait_for_server] TIMEOUT: {len(missing)} replica(s) never became ready: {missing}", file=sys.stderr)
        return 1

    doc = {
        "created_at": time.time(),
        "n_nodes": len(node_files),
        "n_endpoints": len(endpoints),
        "endpoints": endpoints,
        "served_models": healthy,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, out)
    print(f"[wait_for_server] ALL {len(endpoints)} replica(s) healthy; wrote {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", help="poll a single endpoint base URL, e.g. http://host:30000/v1")
    p.add_argument("--aggregate", action="store_true", help="merge per-node files into endpoints.json")
    p.add_argument("--endpoints-dir", type=Path)
    p.add_argument("--expected-nodes", type=int, default=1)
    p.add_argument("--output", type=Path, default=Path("endpoints.json"))
    p.add_argument("--timeout", type=int, default=2400)
    p.add_argument("--interval", type=float, default=10.0)
    args = p.parse_args()

    if args.aggregate:
        if not args.endpoints_dir:
            p.error("--aggregate requires --endpoints-dir")
        return aggregate(args.endpoints_dir, args.expected_nodes, args.output, args.timeout, args.interval)
    if args.url:
        return wait_one(args.url, args.timeout, args.interval)
    p.error("pass --url or --aggregate")
    return 2


if __name__ == "__main__":
    sys.exit(main())
