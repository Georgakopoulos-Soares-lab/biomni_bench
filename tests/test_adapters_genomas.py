import json
import subprocess
import sys

from biomni_uncertainty.adapters.genomas import (
    memory_rlimit_preexec_fn,
    normalize_condition_arg,
    validate_cohort_info_contract,
)

# Exact shape written by the successful K1 admission run's cohort_info.json.
K1_VALID_SHAPE = {
    "GSE133228": {"is_usable": False, "is_gene_available": False, "is_trait_available": False,
                  "is_available": False, "is_biased": None, "has_age": None, "has_gender": None,
                  "sample_size": None, "note": None}
}


def test_valid_cohort_mapping_is_accepted(tmp_path):
    path = tmp_path / "cohort_info.json"
    path.write_text(json.dumps(K1_VALID_SHAPE), encoding="utf-8")
    result = validate_cohort_info_contract(path)
    assert result == {"artifact_contract_valid": True, "artifact_contract_error": None}


def test_malformed_scalar_artifact_is_rejected(tmp_path):
    path = tmp_path / "cohort_info.json"
    path.write_text(json.dumps({"trait": "Alcohol_Flush_Reaction", "status": "no_matching_directory",
                                 "message": "No TCGA cohort directory found"}), encoding="utf-8")
    result = validate_cohort_info_contract(path)
    assert result["artifact_contract_valid"] is False
    assert "trait" in result["artifact_contract_error"]


def test_partial_scalar_and_valid_mapping_mixed_is_rejected(tmp_path):
    # The k4_03 shape: agent-written diagnostic keys survive alongside a
    # correctly written nested cohort entry.
    path = tmp_path / "cohort_info.json"
    path.write_text(json.dumps({"trait": "Alcohol_Flush_Reaction", "status": "processed",
                                 "cohort": "TCGA_Bladder_Cancer_(BLCA)",
                                 "TCGA_Bladder_Cancer_(BLCA)": {"is_usable": False}}), encoding="utf-8")
    result = validate_cohort_info_contract(path)
    assert result["artifact_contract_valid"] is False


def test_missing_artifact_is_rejected(tmp_path):
    result = validate_cohort_info_contract(tmp_path / "does_not_exist.json")
    assert result["artifact_contract_valid"] is False
    assert "missing" in result["artifact_contract_error"]


def test_invalid_json_is_rejected(tmp_path):
    path = tmp_path / "cohort_info.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = validate_cohort_info_contract(path)
    assert result["artifact_contract_valid"] is False
    assert "JSON" in result["artifact_contract_error"]


def test_normalize_condition_arg_maps_none_sentinels_to_real_none():
    # A literal "--condition None" on a command line must never survive as a
    # truthy string: GenoMAS's environment.py does `if condition` and would
    # otherwise misread it as a real condition/comorbidity trait to process.
    assert normalize_condition_arg(None) is None
    assert normalize_condition_arg("None") is None
    assert normalize_condition_arg("none") is None
    assert normalize_condition_arg("  NONE  ") is None


def test_normalize_condition_arg_passes_through_real_conditions():
    assert normalize_condition_arg("Age") == "Age"
    assert normalize_condition_arg("Gender") == "Gender"
    assert normalize_condition_arg("Hypertension") == "Hypertension"


def test_memory_rlimit_preexec_fn_actually_bounds_the_child_address_space():
    # Regression for the rung-5 K=2 OOM (see
    # reports/genomas_fresh_admission_ladder_20260826.md): a runaway GenoMAS
    # trajectory grew to >110 GiB resident with no cgroup/Slurm limit in play,
    # and Linux's OOM killer victim selection is global, not scoped to the
    # offending process. Confirm the RLIMIT_AS this helper installs actually
    # takes effect in the child, and a child that exceeds it fails locally
    # (MemoryError) rather than being silently unbounded.
    cap_bytes = 256 * 1024 * 1024  # 256 MiB
    proc = subprocess.run(
        [sys.executable, "-c", "import resource; print(resource.getrlimit(resource.RLIMIT_AS))"],
        preexec_fn=memory_rlimit_preexec_fn(cap_bytes), capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"({cap_bytes}, {cap_bytes})"

    over_cap = subprocess.run(
        [sys.executable, "-c", "bytearray(2 * 1024 * 1024 * 1024)"],  # 2 GiB, over the 256 MiB cap
        preexec_fn=memory_rlimit_preexec_fn(cap_bytes), capture_output=True, text=True, timeout=10,
    )
    assert over_cap.returncode != 0
    assert "MemoryError" in over_cap.stderr


def test_empty_mapping_is_a_valid_legitimate_no_match_state(tmp_path):
    # An empty dict is still a (vacuously valid) cohort-id -> metadata mapping;
    # eval.py's iteration and .get(...) calls never fire on it.
    path = tmp_path / "cohort_info.json"
    path.write_text("{}", encoding="utf-8")
    result = validate_cohort_info_contract(path)
    assert result == {"artifact_contract_valid": True, "artifact_contract_error": None}
