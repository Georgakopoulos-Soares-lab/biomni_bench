"""Command-line interface.

Every command exits non-zero on failure, prints the paths of what it produced,
and never prints a secret.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from biomni_uncertainty.config import Config, load_cluster_config, load_config, unresolved_placeholders

DEFAULT_API_KEY = "EMPTY"


def _eprint(*a: Any) -> None:
    print(*a, file=sys.stderr)


def _load(args: argparse.Namespace) -> Config:
    overrides = {}
    for kv in getattr(args, "set", None) or []:
        if "=" not in kv:
            raise SystemExit(f"--set expects key.path=value, got {kv!r}")
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
        overrides[k] = v
    return load_config(args.config, overrides)


def _repos() -> tuple[str | None, str | None]:
    here = Path(__file__).resolve().parents[2]
    project = str(here) if (here / ".git").exists() else None
    biomni = os.environ.get("BIOMNI_SRC")
    if not biomni:
        try:
            import biomni

            candidate = Path(biomni.__file__).resolve().parents[1]
            biomni = str(candidate) if (candidate / ".git").exists() else None
        except ImportError:
            biomni = None
    return project, biomni


# --------------------------------------------------------------------------
# inspect-env
# --------------------------------------------------------------------------


def cmd_inspect_env(args: argparse.Namespace) -> int:
    from biomni_uncertainty.provenance import environment_manifest, redacted_env_names, write_json_atomic

    project, biomni = _repos()
    man = environment_manifest(
        project_repo=project,
        biomni_repo=biomni,
        include_pip_freeze=not args.fast,
        include_cli_tools=not args.fast,
    )
    man["secret_bearing_env_var_names"] = redacted_env_names()

    if args.endpoint:
        from biomni_uncertainty.runner import probe_endpoint

        man["endpoint_check"] = probe_endpoint(args.endpoint, args.model or "unknown").to_dict()

    print(json.dumps({k: v for k, v in man.items() if k != "pip_freeze"}, indent=2, default=str))
    if args.output:
        p = write_json_atomic(args.output, man)
        print(f"\nwrote {p}")
    return 0


# --------------------------------------------------------------------------
# prepare-manifest
# --------------------------------------------------------------------------


def cmd_prepare_manifest(args: argparse.Namespace) -> int:
    from biomni_uncertainty.benchmark import build_manifest, load_eval1, manifest_hash, write_manifest

    cfg = _load(args)
    df = load_eval1(cfg.benchmark.parquet_uri, cfg.benchmark.local_parquet)
    entries, report = build_manifest(
        df,
        per_task_target=cfg.benchmark.per_task_target,
        target_total_instances=cfg.benchmark.target_total_instances,
        manifest_seed=cfg.benchmark.manifest_seed,
        preferred_split=cfg.benchmark.preferred_split,
        exclude_tasks=cfg.benchmark.exclude_tasks,
        max_prompt_chars=cfg.benchmark.max_prompt_chars,
    )
    mhash = manifest_hash(entries)

    print("=" * 72)
    print(f"MANIFEST for experiment {cfg.experiment_id}")
    print("=" * 72)
    print(f"benchmark source        : {df.attrs.get('source')}")
    print(f"dataset fingerprint     : {report['dataset_fingerprint'][:32]}...")
    print(f"available splits        : {report['available_splits']}")
    print(f"split used              : {report['split_used']}")
    print(f"held-out split available: {report['held_out_split_available']}")
    print(f"manifest seed           : {cfg.benchmark.manifest_seed}")
    print(f"total selected          : {len(entries)} (target {cfg.benchmark.target_total_instances})")
    print("\ncount by task:")
    for t, n in sorted(report["counts_by_task"].items()):
        print(f"  {t:<34} {n}")
    print("\ncount by split:")
    for s, n in sorted(report["counts_by_split"].items()):
        print(f"  {s:<34} {n}")
    if report.get("short_tasks"):
        print(f"\ntasks with fewer than {cfg.benchmark.per_task_target} suitable instances: {report['short_tasks']}")
    if report.get("redistributed"):
        print(f"redistributed extra instances: {report['redistributed']}")
    print(f"\nprompt length (chars)   : {report.get('prompt_length_chars')}")
    print("\nexclusions:")
    if report["exclusions"]:
        for e in report["exclusions"]:
            print(f"  - {e['reason']} (n={e['n']})")
    else:
        print("  (none)")
    print(f"\nMANIFEST HASH           : {mhash}")

    if args.dry_run:
        print("\n[dry-run] nothing written")
        return 0

    out = Path(args.output or (Path("manifests") / f"{cfg.experiment_id}.jsonl"))
    mpath, gpath = write_manifest(entries, df, out)
    report["manifest_hash"] = mhash
    report["n_entries"] = len(entries)
    rpath = out.with_suffix("").with_suffix(".report.json")
    from biomni_uncertainty.provenance import write_json_atomic

    write_json_atomic(rpath, report)
    print(f"\nwrote manifest      : {mpath}")
    print(f"wrote ground truth  : {gpath}   (NEVER passed to the agent)")
    print(f"wrote report        : {rpath}")
    return 0


# --------------------------------------------------------------------------
# expand-runs
# --------------------------------------------------------------------------


def cmd_expand_runs(args: argparse.Namespace) -> int:
    from biomni_uncertainty.benchmark import read_manifest
    from biomni_uncertainty.sampling import expand_runs, run_manifest_hash, write_run_manifest

    cfg = _load(args)
    entries = read_manifest(args.manifest)
    specs = expand_runs(entries, cfg)

    by_cond: dict[str, int] = {}
    for s in specs:
        by_cond[s.condition] = by_cond.get(s.condition, 0) + 1
    print(f"instances              : {len(entries)}")
    print(f"total planned runs     : {len(specs)}")
    for c, n in sorted(by_cond.items()):
        print(f"  {c:<20} {n}")
    print(f"instrumented K         : {cfg.trajectories.instrumented_k}")
    print(f"standard K             : {cfg.trajectories.standard_k}")
    print(f"confidence mode        : {cfg.confidence.mode}")
    print(f"temperature            : {cfg.model.temperature}")
    print(f"run manifest hash      : {run_manifest_hash(specs)}")

    if args.dry_run:
        print("[dry-run] nothing written")
        return 0
    out = Path(args.output or (Path("manifests") / f"{cfg.experiment_id}_runs.jsonl"))
    p = write_run_manifest(specs, out)
    print(f"wrote {p}")
    return 0


# --------------------------------------------------------------------------
# run-one
# --------------------------------------------------------------------------


def cmd_run_one(args: argparse.Namespace) -> int:
    from biomni_uncertainty.runner import probe_endpoint, run_trajectory
    from biomni_uncertainty.sampling import RunSpec

    cfg = _load(args)
    spec = RunSpec.from_dict(json.loads(Path(args.run_spec).read_text()))
    api_key = os.environ.get("BIOMNI_CUSTOM_API_KEY", DEFAULT_API_KEY)

    check = probe_endpoint(args.endpoint, spec.model)
    if not check.reachable:
        _eprint(f"endpoint {args.endpoint} unreachable: {check.error}")
        return 2
    if check.external_provider_keys_present:
        _eprint(
            "WARNING: external LLM provider keys are present in the environment: "
            f"{check.external_provider_keys_present}. Biomni is configured for the local endpoint only, "
            "but unset them to remove any possibility of a paid API call."
        )

    project, biomni = _repos()
    rec = run_trajectory(
        cfg,
        spec,
        args.endpoint,
        api_key=api_key,
        project_repo=project,
        biomni_repo=biomni,
        endpoint_check=check,
    )
    print(
        json.dumps(
            {
                "run_id": rec["run_id"],
                "completed": rec["completed"],
                "failure_class": rec["failure_class"],
                "wall_time_seconds": rec["wall_time_seconds"],
                "answer_canonical": rec.get("answer_canonical"),
                "answer_parse_status": rec.get("answer_parse_status"),
                "confidence": rec.get("final_confidence"),
                "confidence_parse_status": rec.get("confidence_parse_status"),
                "run_dir": spec.run_dir,
            },
            indent=2,
        )
    )
    return 0 if rec["completed"] else 1


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------


def cmd_dispatch(args: argparse.Namespace) -> int:
    from biomni_uncertainty.dispatcher import check_endpoints, dispatch, load_endpoints
    from biomni_uncertainty.sampling import read_run_manifest

    cfg = _load(args)
    specs = read_run_manifest(args.run_manifest)
    endpoints = load_endpoints(args.endpoints)
    if args.max_concurrent_per_endpoint:
        for e in endpoints:
            e.max_concurrent = args.max_concurrent_per_endpoint
    endpoints = check_endpoints(endpoints, cfg.model.identifier)
    for e in endpoints:
        print(
            f"[endpoint] {e.label} {e.url} healthy={e.healthy} models={e.served_models} seed_supported={e.seed_supported}"
        )
    if not any(e.healthy for e in endpoints):
        _eprint("No healthy endpoints; aborting.")
        return 2

    summary = dispatch(
        specs,
        endpoints,
        cfg,
        args.config,
        resume=not args.no_resume,
        dry_run=args.dry_run,
        python=args.python,
    )
    out = cfg.output_dir / "dispatch_summary.json"
    if not args.dry_run:
        from biomni_uncertainty.provenance import write_json_atomic

        write_json_atomic(out, summary)
        print(f"wrote {out}")
    return 0


# --------------------------------------------------------------------------
# aggregate / status / analyze
# --------------------------------------------------------------------------


def _load_specs_and_evaluator(cfg: Config, args: argparse.Namespace):
    from biomni_uncertainty.evaluation import OfficialEvaluator
    from biomni_uncertainty.sampling import read_run_manifest

    run_manifest = args.run_manifest or (Path("manifests") / f"{cfg.experiment_id}_runs.jsonl")
    gt = args.ground_truth or (Path("manifests") / f"{cfg.experiment_id}.groundtruth.jsonl")
    specs = read_run_manifest(run_manifest)
    evaluator = OfficialEvaluator.from_groundtruth_file(gt)
    return specs, evaluator


def cmd_aggregate(args: argparse.Namespace) -> int:
    from biomni_uncertainty.aggregation import build_tables, status_summary, write_tables
    from biomni_uncertainty.provenance import write_json_atomic

    cfg = _load(args)
    specs, evaluator = _load_specs_and_evaluator(cfg, args)
    tables = build_tables(specs, cfg, evaluator)
    out_dir = cfg.results_dir / "tables"
    written = write_tables(tables, out_dir)
    summary = status_summary(tables["trajectories"])
    write_json_atomic(cfg.results_dir / "status_summary.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    for _k, v in sorted(written.items()):
        print(f"wrote {v}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from biomni_uncertainty.aggregation import collect_run_records, status_summary

    cfg = _load(args)
    specs, _ = _load_specs_and_evaluator(cfg, args)
    df = collect_run_records(specs)
    print(json.dumps(status_summary(df), indent=2, default=str))
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    import pandas as pd

    from biomni_uncertainty import analysis as A
    from biomni_uncertainty import plotting as P
    from biomni_uncertainty.aggregation import build_tables, status_summary, write_tables
    from biomni_uncertainty.provenance import write_json_atomic

    cfg = _load(args)
    specs, evaluator = _load_specs_and_evaluator(cfg, args)
    tables = build_tables(specs, cfg, evaluator)
    out_dir = cfg.results_dir
    write_tables(tables, out_dir / "tables")

    inst_df = tables["instrumented"]
    instances = tables["instances"]
    rep = cfg.analysis.bootstrap_replicates
    seed = cfg.analysis.bootstrap_seed
    lf = cfg.analysis.primary_length_field

    results: dict[str, Any] = {
        "experiment_id": cfg.experiment_id,
        "config_hash": cfg.hash(),
        "status": status_summary(tables["trajectories"]),
        "trajectories": tables["trajectories"],
        "instrumented": inst_df,
        "availability": tables["availability"],
    }

    if len(inst_df):
        results["oracle_at_k"] = A.oracle_at_k(inst_df, cfg.trajectories.instrumented_k)
        results["candidate_generation"] = A.candidate_generation_report(inst_df, instances)
        results["selectors"] = A.evaluate_selectors(
            inst_df, length_field=lf, epsilon=cfg.analysis.srlm_epsilon, replicates=rep, seed=seed
        )
        results["calibration"] = A.confidence_calibration(
            inst_df, n_bins=cfg.analysis.calibration_bins, replicates=rep, seed=seed
        )
        results["signal_auroc"] = A.signal_auroc_table(inst_df, replicates=rep, seed=seed)
        results["learned_selector_exploratory"] = A.learned_selector_cv(inst_df, seed=seed)
    if len(inst_df) and len(tables["standard"]):
        results["perturbation"] = A.prompt_perturbation(inst_df, tables["standard"], replicates=rep, seed=seed)

    figs = P.generate_all(results, out_dir, length_field=lf)
    results["figures"] = figs

    # Persist every derived table next to the figures.
    tdir = out_dir / "tables"
    tdir.mkdir(parents=True, exist_ok=True)
    for key in ("oracle_at_k", "signal_auroc", "availability"):
        v = results.get(key)
        if isinstance(v, pd.DataFrame) and len(v):
            v.to_csv(tdir / f"{key}.csv", index=False)
    for key in ("selectors", "candidate_generation"):
        block = results.get(key) or {}
        for name, v in block.items():
            if isinstance(v, pd.DataFrame) and len(v):
                v.to_csv(tdir / f"{key}__{name}.csv", index=False)
    calib = results.get("calibration") or {}
    for name, v in calib.items():
        if isinstance(v, pd.DataFrame) and len(v):
            v.to_csv(tdir / f"calibration__{name}.csv", index=False)

    summary = _json_safe(results)
    p = write_json_atomic(out_dir / "analysis.json", summary)
    print(
        json.dumps(
            {k: summary[k] for k in ("status", "candidate_generation", "calibration") if k in summary},
            indent=2,
            default=str,
        )[:6000]
    )
    print(f"\nwrote {p}")
    print(f"figures + tables under {out_dir}")
    return 0


def _json_safe(obj: Any) -> Any:
    import numpy as np
    import pandas as pd

    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


# --------------------------------------------------------------------------
# check-cluster
# --------------------------------------------------------------------------


def cmd_check_cluster(args: argparse.Namespace) -> int:
    cfg = load_cluster_config(args.cluster_config)
    missing = unresolved_placeholders(cfg)
    print(json.dumps(cfg, indent=2, default=str))
    if missing:
        print("\nUNRESOLVED CLUSTER PLACEHOLDERS (must be filled before launching):")
        for m in missing:
            print(f"  - {m}")
        return 1
    print("\nAll cluster placeholders resolved.")
    return 0


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m biomni_uncertainty.cli",
        description="Phase 1: intrinsic uncertainty signals in Biomni trajectories.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_config(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--config", required=True, help="path to a YAML experiment config")
        sp.add_argument("--set", action="append", metavar="key.path=value", help="override a config value (repeatable)")

    s = sub.add_parser("inspect-env", help="print and optionally save the environment manifest")
    s.add_argument("--output", help="write the full manifest (including pip freeze) to this JSON path")
    s.add_argument("--endpoint", help="also probe this OpenAI-compatible endpoint")
    s.add_argument("--model", help="model id used for the endpoint probe")
    s.add_argument("--fast", action="store_true", help="skip pip freeze and CLI tool detection")
    s.set_defaults(func=cmd_inspect_env)

    s = sub.add_parser("prepare-manifest", help="build the balanced pilot manifest")
    add_config(s)
    s.add_argument("--output", help="output .jsonl path")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_prepare_manifest)

    s = sub.add_parser("expand-runs", help="expand a manifest into per-trajectory run specs")
    add_config(s)
    s.add_argument("--manifest", required=True)
    s.add_argument("--output")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_expand_runs)

    s = sub.add_parser("run-one", help="execute exactly one trajectory")
    add_config(s)
    s.add_argument("--run-spec", required=True)
    s.add_argument("--endpoint", required=True)
    s.set_defaults(func=cmd_run_one)

    s = sub.add_parser("dispatch", help="run all pending trajectories across healthy endpoints")
    add_config(s)
    s.add_argument("--run-manifest", required=True)
    s.add_argument("--endpoints", required=True, help="endpoints.json written by the launcher")
    s.add_argument("--no-resume", action="store_true", help="re-run everything, ignoring COMPLETE markers")
    s.add_argument("--max-concurrent-per-endpoint", type=int)
    s.add_argument("--python", help="python interpreter for run-one subprocesses")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_dispatch)

    for name, fn, helptext in (
        ("aggregate", cmd_aggregate, "collect run records into Parquet/CSV tables"),
        ("status", cmd_status, "print completion status"),
        ("analyze", cmd_analyze, "run the frozen analysis and generate all figures"),
    ):
        s = sub.add_parser(name, help=helptext)
        add_config(s)
        s.add_argument("--run-manifest")
        s.add_argument("--ground-truth")
        s.set_defaults(func=fn)

    s = sub.add_parser("check-cluster", help="validate a cluster config for unresolved placeholders")
    s.add_argument("--cluster-config", required=True)
    s.set_defaults(func=cmd_check_cluster)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _eprint("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        _eprint(f"ERROR: {type(exc).__name__}: {exc}")
        if os.environ.get("BIOMNI_UNC_TRACEBACK"):
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
