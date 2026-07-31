"""Mock integration test: manifest -> runs -> aggregation -> selectors -> report.

Runs entirely on CPU, with no GPU and no Biomni data-lake download.

Two mocks are used:

1. A real in-process OpenAI-compatible HTTP server, driven through a real
   ``langchain_openai.ChatOpenAI`` client, so the endpoint probe and the LLM
   telemetry callback are exercised against genuine response shapes.
2. Synthesized run directories written through the real ``EventLogger``,
   ``parse_final_response``, atomic-write and completion-marker code paths, so
   aggregation and analysis run over the real artifact contract.

The fake benchmark covers three answer formats (letter-in-tags, gene symbol,
JSON object) and includes a successful tool call, a failed tool call and a
malformed confidence response.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pandas as pd
import pytest

from biomni_uncertainty import analysis as A
from biomni_uncertainty import plotting as P
from biomni_uncertainty.aggregation import build_tables, status_summary, write_tables
from biomni_uncertainty.benchmark import build_manifest, manifest_hash, read_manifest, write_manifest
from biomni_uncertainty.canonicalization import parse_final_response
from biomni_uncertainty.config import Config
from biomni_uncertainty.evaluation import OfficialEvaluator
from biomni_uncertainty.events import EventLogger
from biomni_uncertainty.instrumentation import TrajectoryStats, make_llm_callback
from biomni_uncertainty.provenance import write_json_atomic
from biomni_uncertainty.sampling import COMPLETE_MARKER, expand_runs, write_marker

OPEN, CLOSE = "<BIOMNI_CONFIDENCE>", "</BIOMNI_CONFIDENCE>"


# ==========================================================================
# Part 1: fake OpenAI-compatible endpoint
# ==========================================================================


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _json(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json(200, {"object": "list", "data": [{"id": "biomni/Biomni-R0-32B-Preview", "object": "model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        # Deterministic when a seed is supplied, so the seed probe reports True.
        text = "seeded-reply" if req.get("seed") is not None else f"unseeded-{id(req) % 1000}"
        self._json(
            200,
            {
                "id": "chatcmpl-mock-1",
                "object": "chat.completion",
                "model": req.get("model", "mock"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 137, "completion_tokens": 42, "total_tokens": 179},
            },
        )


@pytest.fixture(scope="module")
def fake_endpoint():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def test_endpoint_probe_reports_models_and_seed_support(fake_endpoint):
    from biomni_uncertainty.runner import probe_endpoint

    chk = probe_endpoint(fake_endpoint, "biomni/Biomni-R0-32B-Preview", timeout=10)
    assert chk.reachable
    assert chk.served_models == ["biomni/Biomni-R0-32B-Preview"]
    assert chk.seed_supported is True


def test_probe_of_a_dead_endpoint_is_unreachable_not_an_exception():
    from biomni_uncertainty.runner import probe_endpoint

    chk = probe_endpoint("http://127.0.0.1:1/v1", "m", timeout=2)
    assert chk.reachable is False
    assert chk.error


def test_llm_callback_records_token_usage_from_a_real_client(tmp_path, fake_endpoint):
    """Token counts must come from the endpoint's usage block."""
    ChatOpenAI = pytest.importorskip("langchain_openai").ChatOpenAI

    logger = EventLogger("mockrun", tmp_path / "events.jsonl")
    stats = TrajectoryStats()
    llm = ChatOpenAI(
        model="biomni/Biomni-R0-32B-Preview",
        base_url=fake_endpoint,
        api_key="EMPTY",
        temperature=0.7,
        seed=1234,
        callbacks=[make_llm_callback(logger, stats)],
    )
    out = llm.invoke("hello")

    assert out.content == "seeded-reply"
    assert stats.llm_call_count == 1
    assert stats.token_usage_available is True
    assert stats.total_input_tokens == 137
    assert stats.total_output_tokens == 42
    assert stats.total_tokens == 179
    assert stats.model_time_seconds > 0
    assert stats.finish_reasons == ["stop"]

    types = [
        e["event_type"]
        for e in __import__("biomni_uncertainty.events", fromlist=["x"]).read_events(tmp_path / "events.jsonl")
    ]
    assert "llm_request_start" in types and "llm_request_end" in types


# ==========================================================================
# Part 2: fake benchmark
# ==========================================================================

FAKE_PROMPTS = {
    "lab_bench_dbqa": (
        "The following is a multiple choice question about biology.\n\n"
        "Question: Which gene is neuronal?\nOptions:\nA.RASL10A\nB.EVI2B\nC.TCAF1\nD.KIR3DL3\n\n"
        "You MUST include the letter of the correct answer within the following tags:\n"
        "[ANSWER] and [/ANSWER]."
    ),
    "gwas_causal_gene_opentargets": (
        "Identify the causal gene.\nGWAS phenotype: Type 2 diabetes\nGenes in locus: {ACADS},{HNF1A},{KDM2B},{MLEC}"
    ),
    "rare_disease_diagnosis": (
        "Task: diagnose the rare disease.\nPhenotypes: HP:0002650\n"
        "Candidate genes: ['ENSG00000154864']\n\nOutput format: {'disease_name': XXX, 'OMIM_ID': XXX}"
    ),
}
FAKE_ANSWERS = {
    "lab_bench_dbqa": "B",
    "gwas_causal_gene_opentargets": "HNF1A",
    "rare_disease_diagnosis": '{"disease_name": "Gordon syndrome", "OMIM_ID": "114300"}',
}


def fake_benchmark_df(n_per_task: int = 2) -> pd.DataFrame:
    rows, gid = [], 0
    for task in sorted(FAKE_PROMPTS):
        for i in range(n_per_task):
            rows.append(
                {
                    "instance_id": gid,
                    "task_instance_id": i,
                    "prompt": FAKE_PROMPTS[task] + f"\n(instance {i})",
                    "task_name": task,
                    "split": "val",
                    "answer": FAKE_ANSWERS[task],
                }
            )
            gid += 1
    return pd.DataFrame(rows)


# Per (task, instance, trajectory): the solution body and whether the tool failed.
# Designed so that:
#   - instance 0 of lab_bench: first trajectory WRONG, majority right -> selection can help
#   - instance 1 of lab_bench: all trajectories wrong -> no headroom
#   - gwas instance 0: t2 has a MALFORMED confidence block
#   - rare_disease instance 0: t1 has a FAILED tool call
def scripted_answer(task: str, tid: int, traj: int) -> tuple[str, float | None, bool, str]:
    """Returns (solution_body, confidence_0_100 or None, tool_failed, confidence_form)."""
    if task == "lab_bench_dbqa":
        if tid == 0:
            body = "[ANSWER]C[/ANSWER]" if traj == 0 else "[ANSWER]B[/ANSWER]"
            conf = 90.0 if traj == 0 else [None, 70.0, 55.0, 80.0][traj]
            return body, conf, False, "ok"
        return "[ANSWER]D[/ANSWER]", 40.0 + traj, False, "ok"
    if task == "gwas_causal_gene_opentargets":
        if tid == 0:
            body = "HNF1A" if traj != 3 else "KDM2B"
            if traj == 2:
                return body, None, False, "malformed"
            return body, 60.0 + 10 * traj, False, "ok"
        return "MLEC", 30.0, False, "ok"
    # rare_disease_diagnosis
    if tid == 0:
        body = (
            '{"disease_name": "Gordon syndrome", "OMIM_ID": "114300"}'
            if traj < 2
            else '{"disease_name": "Other", "OMIM_ID": "999999"}'
        )
        return body, 75.0, traj == 1, "ok"
    return '{"disease_name": "Other", "OMIM_ID": "222222"}', 20.0, False, "ok"


def build_raw_response(body: str, conf: float | None, form: str) -> str:
    if form == "malformed":
        block = f"{OPEN}\nI am about 70 percent sure\n{CLOSE}"
    elif conf is None:
        block = ""
    else:
        block = f'{OPEN}\n{{"confidence": {conf}}}\n{CLOSE}'
    return f"Reasoning about the task.\n\n<solution>\n{body}\n{block}\n</solution>"


def write_fake_run(spec, cfg: Config) -> None:
    """Synthesize one run directory through the real artifact code paths."""
    task, tid, traj = spec.task_name, spec.task_instance_id, spec.trajectory_index
    body, conf, tool_failed, form = scripted_answer(task, tid, traj)
    instrumented = spec.condition == "instrumented"
    # Condition A never emits a confidence block.
    raw = build_raw_response(body, conf if instrumented else None, form if instrumented else "none")

    run_dir = Path(spec.run_dir)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    log = EventLogger(spec.run_id, run_dir / "events.jsonl")

    log.emit("agent_start", task_name=task, endpoint=spec.model, api_key="sk-should-be-redacted-123456")
    n_llm = 3 + traj
    out_tokens = 300 + 120 * traj + (250 if tool_failed else 0)
    for step in range(n_llm):
        log.emit("llm_request_start", request_id=f"r{step}", model=spec.model)
        log.emit(
            "llm_request_end",
            request_id=f"r{step}",
            duration_seconds=1.5,
            usage={
                "input_tokens": 1000,
                "output_tokens": out_tokens // n_llm,
                "total_tokens": 1000 + out_tokens // n_llm,
            },
            finish_reason="stop",
        )
    log.emit("tool_call_start", step_index=1, tool_name="query_opentargets", argument_hash="abc123")
    log.emit("code_execution_start", step_index=1, language="python", code_hash="h1")
    log.emit(
        "code_execution_end",
        step_index=1,
        duration_seconds=2.0,
        status="error" if tool_failed else "ok",
        error="Error: ModuleNotFoundError: no module named 'pyensembl'" if tool_failed else None,
    )
    log.emit("tool_call_end", step_index=1, tool_name="query_opentargets", status="error" if tool_failed else "ok")
    log.emit("final_answer", canonical=body)

    parsed = parse_final_response(task, raw, spec.prompt, confidence_requested=instrumented)
    log.emit(
        "confidence_extracted",
        status=parsed["confidence"]["status"],
        confidence_0_100=parsed["confidence"]["confidence_0_100"],
        n_blocks=parsed["confidence"]["n_blocks"],
    )

    (run_dir / "final_response.txt").write_text(raw)
    write_json_atomic(run_dir / "parsed_answer.json", parsed)
    write_json_atomic(run_dir / "config.json", cfg.snapshot())

    stats = {
        "llm_call_count": n_llm,
        "total_input_tokens": 1000 * n_llm,
        "total_output_tokens": out_tokens,
        "total_tokens": 1000 * n_llm + out_tokens,
        "token_usage_available": True,
        "model_time_seconds": 1.5 * n_llm,
        "tool_time_seconds": 2.0,
        "code_execution_count": 1,
        "tool_call_count": 1,
        "unique_tool_count": 1,
        "failed_tool_call_count": 1 if tool_failed else 0,
        "failed_tool_call_fraction": 1.0 if tool_failed else 0.0,
        "repeated_tool_call_count": 0,
        "repeated_tool_call_fraction": 0.0,
        "retry_count": 0,
        "parse_error_count": 0,
        "exception_count": 0,
        "retrieval_count": 1,
        "generated_chars": out_tokens * 4,
        "message_count": 2 * n_llm,
        "ai_message_count": n_llm,
        "observation_count": 1,
        "execute_block_count": 1,
        "solution_block_count": 1,
        "parse_error_message_count": 0,
        "visible_plan_step_count": n_llm - 1,
        "plan_revision_count": None,
        "finish_reasons": ["stop"] * n_llm,
    }
    conf_block = parsed["confidence"]
    record = {
        **{
            k: getattr(spec, k)
            for k in (
                "experiment_id",
                "run_id",
                "condition",
                "task_name",
                "global_instance_id",
                "task_instance_id",
                "trajectory_index",
                "split",
                "requested_seed",
                "model",
                "model_revision",
                "temperature",
                "max_tokens",
                "confidence_mode",
                "timeout_seconds",
                "prompt_hash",
            )
        },
        "seed_supported": True,
        "endpoint": "http://mock/v1",
        "completed": True,
        "failure_class": None,
        "wall_time_seconds": 20.0 + 8 * traj + (30 if tool_failed else 0),
        "started_at": 1.0,
        "ended_at": 2.0,
        "trajectory_stats": stats,
        "final_response_raw_chars": len(raw),
        "solution_block_status": parsed["solution_block_status"],
        "final_answer_parsed": parsed["parsed"]["raw"],
        "answer_canonical": parsed["parsed"]["canonical"],
        "answer_parse_status": parsed["parsed"]["status"],
        "answer_cluster_key": parsed["parsed"]["cluster_key"],
        "final_confidence": conf_block["confidence"],
        "final_confidence_0_100": conf_block["confidence_0_100"],
        "confidence_parse_status": conf_block["status"],
    }
    write_json_atomic(run_dir / "metadata.json", record)
    write_marker(run_dir, COMPLETE_MARKER, {"run_id": spec.run_id, "completed": True, "failure_class": None})


@pytest.fixture
def mock_experiment(tmp_path):
    cfg = Config.model_validate(
        {
            "experiment": {"name": "mock", "seed": 1, "output_root": str(tmp_path / "out")},
            "benchmark": {"target_total_instances": 6, "per_task_target": 2, "manifest_seed": 20260731},
            "trajectories": {"instrumented_k": 4, "standard_k": 1},
            "execution": {"data_path": str(tmp_path / "data")},
            "analysis": {"bootstrap_replicates": 200, "calibration_bins": 4},
        }
    )
    df = fake_benchmark_df(2)
    entries, report = build_manifest(
        df, per_task_target=2, target_total_instances=6, manifest_seed=20260731, preferred_split="val"
    )
    mpath, gpath = write_manifest(entries, df, tmp_path / "manifests" / "mock.jsonl")
    specs = expand_runs(read_manifest(mpath), cfg)
    for s in specs:
        write_fake_run(s, cfg)
    evaluator = OfficialEvaluator.from_groundtruth_file(gpath)
    return {
        "cfg": cfg,
        "specs": specs,
        "evaluator": evaluator,
        "entries": entries,
        "report": report,
        "manifest_hash": manifest_hash(entries),
        "tmp": tmp_path,
    }


# ==========================================================================
# Part 3: the pipeline
# ==========================================================================


def test_mock_pipeline_produces_expected_run_count(mock_experiment):
    specs = mock_experiment["specs"]
    assert len(mock_experiment["entries"]) == 6
    assert len(specs) == 6 * 5  # K=4 instrumented + 1 standard
    assert all((Path(s.run_dir) / COMPLETE_MARKER).exists() for s in specs)


def test_secrets_do_not_leak_into_event_logs(mock_experiment):
    for s in mock_experiment["specs"][:3]:
        raw = (Path(s.run_dir) / "events.jsonl").read_text()
        assert "sk-should-be-redacted-123456" not in raw
        assert "[REDACTED]" in raw


def test_aggregation_builds_all_tables(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    assert set(tables) >= {"trajectories", "instrumented", "instances", "standard", "availability"}
    assert len(tables["trajectories"]) == 30
    assert len(tables["instrumented"]) == 24
    assert len(tables["standard"]) == 6
    assert len(tables["instances"]) == 6

    t = tables["trajectories"]
    assert t["reward"].notna().all()
    assert t["completed"].all()
    # Consensus features joined onto instrumented trajectories.
    for c in ("cluster_key", "agreement_fraction", "in_plurality_cluster", "instance_plurality_fraction"):
        assert c in tables["instrumented"].columns


def test_scripted_scenarios_are_scored_as_designed(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    inst = tables["instrumented"]

    # lab_bench instance 0: trajectory 0 wrong, the other three correct.
    g = inst[(inst.task_name == "lab_bench_dbqa") & (inst.task_instance_id == 0)].sort_values("trajectory_index")
    assert list(g["correct"]) == [0, 1, 1, 1]

    # lab_bench instance 1: all wrong -> no headroom for any selector.
    g = inst[(inst.task_name == "lab_bench_dbqa") & (inst.task_instance_id == 1)]
    assert g["correct"].sum() == 0

    # One trajectory has a malformed confidence block, recorded not defaulted.
    bad = inst[inst.confidence_parse_status == "malformed_json"]
    assert len(bad) == 1
    assert bad["final_confidence"].isna().all()

    # One trajectory has a failed tool call.
    assert (inst["failed_tool_call_count"] > 0).sum() == 1


def test_selector_evaluation_and_oracle_headroom(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    inst = tables["instrumented"]

    sel = A.evaluate_selectors(inst, length_field="total_output_tokens", epsilon=1e-3, replicates=200, seed=1)
    summary = sel["summary"].set_index("selector")
    assert len(sel["per_instance"]) == 6
    # Oracle must be >= every deployable selector, by construction.
    oracle = summary.loc["oracle", "point"]
    for name in ("first", "plurality", "srlm_style", "rank_combination", "max_confidence", "min_length"):
        assert summary.loc[name, "point"] <= oracle + 1e-9, name
    # Plurality beats first here: instance lab_bench/0 has first wrong, majority right.
    assert summary.loc["plurality", "point"] > summary.loc["first", "point"]
    # Every selector reports full provenance.
    d = sel["selection_detail"]
    assert d["reason"].notna().all()
    assert set(d["selector"].unique()) >= {"first", "plurality", "oracle", "srlm_style"}


def test_oracle_at_k_is_monotone_non_decreasing(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    ok = A.oracle_at_k(tables["instrumented"], 4)
    assert list(ok["k"]) == [1, 2, 3, 4]
    vals = ok["oracle_all_subsets"].tolist()
    assert all(vals[i] <= vals[i + 1] + 1e-9 for i in range(len(vals) - 1))
    assert ok["n_instances"].min() == 6


def test_candidate_generation_report(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    rep = A.candidate_generation_report(tables["instrumented"], tables["instances"])
    s = rep["summary"]
    assert s["n_instances"] == 6
    assert 0 <= s["p_first_correct"] <= s["p_any_correct"] <= 1
    assert s["oracle_headroom_pp"] >= 0
    assert s["p_first_wrong_other_right"] > 0  # lab_bench/0 by construction


def test_calibration_and_missing_confidence_reported_separately(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    cal = A.confidence_calibration(tables["instrumented"], n_bins=4, replicates=200, seed=1)
    assert cal["n_trajectories_total"] == 24
    assert cal["n_with_valid_confidence"] < 24  # malformed + missing are excluded
    assert 0 < cal["confidence_parse_rate"] < 1
    assert cal["brier"] is not None
    assert "malformed_json" in cal["parse_status_counts"]
    assert len(cal["reliability"]) == 4


def test_prompt_perturbation_pairs_conditions(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    pert = A.prompt_perturbation(tables["instrumented"], tables["standard"], replicates=200, seed=1)
    assert pert["n_paired_instances"] == 6
    assert pert["reward_difference"]["n"] == 6
    assert 0.0 <= pert["answer_change_rate"] <= 1.0
    assert pert["completion_rate_standard"] == 1.0


def test_signal_auroc_table_uses_grouped_bootstrap(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    tab = A.signal_auroc_table(tables["instrumented"], replicates=100, seed=1)
    assert "final_confidence" in set(tab["signal"])
    scored = tab[tab["auroc"].notna()]
    assert len(scored) > 0
    assert (scored["auroc"].between(0, 1)).all()
    # n_instances is the number of resampling units, not trajectories.
    assert (scored["n_instances"] <= scored["n"]).all()


def test_learned_selector_is_grouped_and_labelled_exploratory(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    out = A.learned_selector_cv(tables["instrumented"], seed=1)
    assert out["status"] in ("ok", "insufficient_data", "insufficient_groups")
    if out["status"] == "ok":
        assert out["exploratory"] is True
        assert out["n_groups"] == 6


def test_full_report_tables_and_plots_are_generated(mock_experiment, tmp_path):
    m = mock_experiment
    cfg = m["cfg"]
    tables = build_tables(m["specs"], cfg, m["evaluator"])
    out_dir = cfg.results_dir
    written = write_tables(tables, out_dir / "tables")
    assert Path(written["trajectories"]).exists()
    assert Path(written["trajectories_csv"]).exists()
    # Parquet must round-trip despite dict-valued columns.
    back = pd.read_parquet(written["trajectories"])
    assert len(back) == 30

    inst = tables["instrumented"]
    results = {
        "trajectories": tables["trajectories"],
        "instrumented": inst,
        "availability": tables["availability"],
        "oracle_at_k": A.oracle_at_k(inst, 4),
        "selectors": A.evaluate_selectors(
            inst, length_field="total_output_tokens", epsilon=1e-3, replicates=200, seed=1
        ),
        "calibration": A.confidence_calibration(inst, n_bins=4, replicates=200, seed=1),
        "signal_auroc": A.signal_auroc_table(inst, replicates=100, seed=1),
        "perturbation": A.prompt_perturbation(inst, tables["standard"], replicates=200, seed=1),
    }
    figs = P.generate_all(results, out_dir, length_field="total_output_tokens")
    assert len(figs) == 13
    for name, paths in figs.items():
        assert Path(paths["figure"]).exists(), name
        assert Path(paths["table"]).exists(), name  # every plot has a machine-readable table
        assert Path(paths["figure"]).stat().st_size > 1000, name


def test_status_summary_reports_completeness(mock_experiment):
    m = mock_experiment
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    s = status_summary(tables["trajectories"])
    assert s["total_planned_runs"] == 30
    assert s["runs_completed"] == 30
    assert s["runs_missing"] == 0
    assert s["by_condition"] == {"instrumented": 24, "standard": 6}
    assert "malformed_json" in s["confidence_parse_status"]


def test_missing_runs_appear_as_findings_not_silent_gaps(mock_experiment):
    """Deleting a run directory must show up, not vanish."""
    import shutil

    m = mock_experiment
    victim = Path(m["specs"][0].run_dir)
    shutil.rmtree(victim)
    tables = build_tables(m["specs"], m["cfg"], m["evaluator"])
    s = status_summary(tables["trajectories"])
    assert s["runs_missing"] == 1
    assert s["failure_class_counts"].get("missing_run") == 1
    assert len(tables["trajectories"]) == 30  # the row is still there


def test_bootstrap_is_deterministic():
    vals = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    a = A.bootstrap_mean(vals, replicates=500, seed=42)
    b = A.bootstrap_mean(vals, replicates=500, seed=42)
    c = A.bootstrap_mean(vals, replicates=500, seed=43)
    assert (a.point, a.lo, a.hi) == (b.point, b.lo, b.hi)
    assert (a.lo, a.hi) != (c.lo, c.hi)
    assert a.lo <= a.point <= a.hi


def test_paired_bootstrap_is_deterministic_and_paired():
    x = [1.0, 1.0, 0.0, 1.0, 0.0, 0.0]
    y = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    a = A.paired_bootstrap_difference(x, y, replicates=500, seed=7)
    b = A.paired_bootstrap_difference(x, y, replicates=500, seed=7)
    assert a == b
    assert a["difference"] == pytest.approx(2 / 6)
    assert a["n"] == 6


def test_grouped_bootstrap_resamples_groups_not_rows():
    df = pd.DataFrame({"g": ["a"] * 4 + ["b"] * 4, "v": [1.0] * 4 + [0.0] * 4})
    ci = A.grouped_bootstrap(df, "g", lambda d: d["v"].mean(), replicates=400, seed=3)
    assert ci.n == 2
    # With only two groups the resampled mean can only be 0, 0.5 or 1.
    assert ci.lo in (0.0, 0.5, 1.0)
    assert ci.point == pytest.approx(0.5)
