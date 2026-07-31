"""Canonicalization tests: every benchmark task type, every failure mode.

For each task the required cases are: correct canonical form, extra prose,
confidence block appended, malformed output, formatting/case variation the
evaluator tolerates, multiple candidate answers, and a missing answer.
"""

from __future__ import annotations

import json

import pytest

from biomni_uncertainty.canonicalization import (
    KNOWN_TASKS,
    extract_solution_block,
    parse_answer,
    parse_final_response,
    parse_prompt_options,
)

OPEN, CLOSE = "<BIOMNI_CONFIDENCE>", "</BIOMNI_CONFIDENCE>"


def conf(v: float = 80) -> str:
    return f'\n{OPEN}\n{{"confidence": {v}}}\n{CLOSE}'


# Realistic prompts distilled from the actual biomni/Eval1 release.
PROMPTS = {
    "crispr_delivery": (
        "Given the case description, identify the MOST relevant CRISPR delivery method from the options below:\n\n"
        "a. Plasmid Transfection\nb. Lentivirus/Retrovirus\nc. RNP/mRNA electroporation\n"
        "d. RNP/mRNA microinjection\ne. mRNA LNP\nf. AAV\n\n"
        "Category: Cell line\nCase Description: I hope to edit HEK293T cell line\n\n"
        "Please provide your response as follows:\n- Most relevant method (select one letter a-f): "
    ),
    "gwas_causal_gene_opentargets": (
        "Your task is to identify likely causal genes within a locus for a given GWAS phenotype. "
        "From the list, provide only the likely causal gene (matching one of the given genes). \n"
        "Identify the causal gene.\nGWAS phenotype: Type 2 diabetes\n"
        "Genes in locus: {ACADS},{ANAPC5},{HNF1A},{KDM2B},{MLEC}"
    ),
    "gwas_variant_prioritization": (
        "Your task is to identify the most promising variant associated wtih a given GWAS phenotype.\n"
        "GWAS phenotype: Bradykinin\n"
        "Variants: rs7700133, rs1280, rs7651090, rs4253311, rs3738934"
    ),
    "lab_bench_dbqa": (
        "The following is a multiple choice question about biology.\n\n"
        "Question: Which gene is in CAHOY_NEURONAL?\nOptions:\nA.RASL10A\nB.Insufficient information.\n"
        "C.EVI2B\nD.TCAF1\nE.KIR3DL3\n\n"
        "You MUST include the letter of the correct answer within the following tags:\n"
        "[ANSWER] and [/ANSWER]."
    ),
    "patient_gene_detection": (
        "Task: Given a patient's phenotypes and a list of candidate genes, identify the causal gene.\n"
        "Phenotypes: HP:0000474, HP:0000733\n"
        "Candidate genes: ENSG00000092330, ENSG00000131174, ENSG00000161011\n\n"
        "Output format: {'causal_gene': [gene1]}"
    ),
    "rare_disease_diagnosis": (
        "Task: given a patient's phenotypes and a list of candidate genes, diagnose the rare disease.\n"
        "Phenotypes: HP:0002650, HP:0000175\nCandidate genes: ['ENSG00000154864']\n\n"
        "Output format: {'disease_name': XXX, 'OMIM_ID': XXX}"
    ),
    "screen_gene_retrieval": (
        "Your task is to identify the gene with the strongest perturbation effect.\n\n"
        "Candidate genes: TMEM37, GINM1, SON, ZNF561-AS1, ITGB6\n\n"
        "Output only the gene symbol of your choice, e.g., BRCA1"
    ),
}
PROMPTS["lab_bench_seqqa"] = PROMPTS["lab_bench_dbqa"]
PROMPTS["gwas_causal_gene_gwas_catalog"] = PROMPTS["gwas_causal_gene_opentargets"]
PROMPTS["gwas_causal_gene_pharmaprojects"] = PROMPTS["gwas_causal_gene_opentargets"]
PROMPTS["hle"] = PROMPTS["lab_bench_dbqa"]


# --------------------------------------------------------------------------
# Solution block
# --------------------------------------------------------------------------


def test_extract_last_solution_block():
    text = "<solution>first</solution> noise <solution>second</solution>"
    body, status = extract_solution_block(text)
    assert (body, status) == ("second", "ok")


def test_unterminated_solution_block_is_flagged():
    body, status = extract_solution_block("thinking <solution>HNF1A")
    assert body == "HNF1A"
    assert status == "unterminated_solution_block"


def test_no_solution_block_is_flagged():
    body, status = extract_solution_block("I could not finish")
    assert status == "no_solution_block"
    assert body == "I could not finish"


def test_empty_response():
    assert extract_solution_block("") == (None, "empty")


# --------------------------------------------------------------------------
# Per-task: correct form
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "task,text,expected",
    [
        ("crispr_delivery", "b", "b"),
        ("gwas_causal_gene_opentargets", "HNF1A", "HNF1A"),
        ("gwas_variant_prioritization", "rs4253311", "rs4253311"),
        ("lab_bench_dbqa", "[ANSWER]C[/ANSWER]", "C"),
        ("lab_bench_seqqa", "[ANSWER]a[/ANSWER]", "A"),
        ("screen_gene_retrieval", "ZNF561-AS1", "ZNF561-AS1"),
        ("hle", "[ANSWER]D[/ANSWER]", "D"),
    ],
)
def test_correct_canonical_form(task, text, expected):
    p = parse_answer(task, text, PROMPTS[task])
    assert p.status == "ok", p
    assert p.canonical == expected


def test_patient_gene_correct_form():
    p = parse_answer(
        "patient_gene_detection", "{'causal_gene': ['ENSG00000161011']}", PROMPTS["patient_gene_detection"]
    )
    assert p.status == "ok"
    assert json.loads(p.canonical) == {"causal_gene": ["ENSG00000161011"]}
    assert p.cluster_key == "ENSG00000161011"


def test_rare_disease_correct_form():
    p = parse_answer(
        "rare_disease_diagnosis",
        '{"disease_name": "Gordon syndrome", "OMIM_ID": "114300"}',
        PROMPTS["rare_disease_diagnosis"],
    )
    assert p.status == "ok"
    assert json.loads(p.canonical)["OMIM_ID"] == "114300"
    assert p.cluster_key == "114300"


# --------------------------------------------------------------------------
# Per-task: extra prose
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "task,text,expected",
    [
        (
            "crispr_delivery",
            "Based on the evidence, HEK293T cells are easy to transfect.\n"
            "- Most relevant method (select one letter a-f): a",
            "a",
        ),
        (
            "gwas_causal_gene_opentargets",
            "After reviewing Open Targets, the strongest evidence points to HNF1A, "
            "a known MODY3 gene.\n\nAnswer: HNF1A",
            "HNF1A",
        ),
        (
            "gwas_variant_prioritization",
            "The variant with the strongest association signal is rs4253311.",
            "rs4253311",
        ),
        (
            "lab_bench_dbqa",
            "Let me reason about each option. EVI2B is neuronal.\n\n[ANSWER]C[/ANSWER]",
            "C",
        ),
        ("screen_gene_retrieval", "The gene with the strongest effect is SON.", "SON"),
    ],
)
def test_extra_prose(task, text, expected):
    p = parse_answer(task, text, PROMPTS[task])
    assert p.status == "ok", p
    assert p.canonical == expected


def test_patient_gene_with_prose():
    p = parse_answer(
        "patient_gene_detection",
        "The phenotype profile matches a lysosomal disorder.\nOutput: {'causal_gene': ['ENSG00000161011']}",
        PROMPTS["patient_gene_detection"],
    )
    assert p.status == "ok"
    assert p.cluster_key == "ENSG00000161011"


def test_rare_disease_with_prose_and_prefixed_omim():
    p = parse_answer(
        "rare_disease_diagnosis",
        "This is consistent with Gordon syndrome (OMIM: #114300).",
        PROMPTS["rare_disease_diagnosis"],
    )
    assert p.status == "ok"
    assert p.cluster_key == "114300"


def test_rare_disease_integer_omim_normalized_to_string():
    p = parse_answer(
        "rare_disease_diagnosis",
        '{"disease_name": "Gordon syndrome", "OMIM_ID": 114300}',
        PROMPTS["rare_disease_diagnosis"],
    )
    # The official evaluator compares with ==, so an int would score 0 against
    # the string ground truth. Canonicalization must emit a digit string.
    assert json.loads(p.canonical)["OMIM_ID"] == "114300"


# --------------------------------------------------------------------------
# Confidence block appended
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "task,answer,expected",
    [
        ("crispr_delivery", "b", "b"),
        ("gwas_causal_gene_opentargets", "HNF1A", "HNF1A"),
        ("gwas_variant_prioritization", "rs4253311", "rs4253311"),
        ("lab_bench_dbqa", "[ANSWER]C[/ANSWER]", "C"),
        ("screen_gene_retrieval", "SON", "SON"),
        ("patient_gene_detection", "{'causal_gene': ['ENSG00000161011']}", None),
        ("rare_disease_diagnosis", '{"disease_name": "X", "OMIM_ID": "114300"}', None),
    ],
)
def test_confidence_block_appended_does_not_break_parsing(task, answer, expected):
    raw = f"<solution>\n{answer}{conf(73.25)}\n</solution>"
    out = parse_final_response(task, raw, PROMPTS[task])
    assert out["confidence"]["status"] == "ok"
    assert out["confidence"]["confidence"] == pytest.approx(0.7325)
    assert out["parsed"]["status"] == "ok", out
    if expected is not None:
        assert out["parsed"]["canonical"] == expected


def test_malformed_confidence_still_yields_answer():
    raw = f"<solution>\nHNF1A\n{OPEN}\noops\n{CLOSE}\n</solution>"
    out = parse_final_response("gwas_causal_gene_opentargets", raw, PROMPTS["gwas_causal_gene_opentargets"])
    assert out["confidence"]["status"] == "malformed_json"
    assert out["parsed"]["canonical"] == "HNF1A"


# --------------------------------------------------------------------------
# Malformed / missing answers
# --------------------------------------------------------------------------


@pytest.mark.parametrize("task", sorted(KNOWN_TASKS))
def test_empty_answer_is_empty_status(task):
    p = parse_answer(task, "   ", PROMPTS[task])
    assert p.status == "empty"
    assert p.canonical is None


@pytest.mark.parametrize(
    "task,text",
    [
        ("gwas_variant_prioritization", "I could not determine a variant."),
        ("patient_gene_detection", "No gene identified."),
        ("rare_disease_diagnosis", "Unable to diagnose."),
        ("lab_bench_dbqa", "The question is unanswerable given the tools."),
    ],
)
def test_unparseable_answers(task, text):
    p = parse_answer(task, text, PROMPTS[task])
    assert p.status == "unparseable"
    assert p.canonical is None


# --------------------------------------------------------------------------
# Case / formatting variation the evaluator tolerates
# --------------------------------------------------------------------------


def test_gene_symbol_case_normalized_upper():
    # Evaluator compares .strip().upper(), so lowercase is a safe normalization.
    p = parse_answer("gwas_causal_gene_opentargets", "hnf1a", PROMPTS["gwas_causal_gene_opentargets"])
    assert p.canonical == "HNF1A"


def test_crispr_letter_normalized_lower():
    p = parse_answer("crispr_delivery", "B", PROMPTS["crispr_delivery"])
    assert p.canonical == "b"


def test_lab_bench_letter_normalized_upper():
    p = parse_answer("lab_bench_dbqa", "[ANSWER]c[/ANSWER]", PROMPTS["lab_bench_dbqa"])
    assert p.canonical == "C"


def test_variant_prefix_case_normalized_and_raw_kept():
    p = parse_answer("gwas_variant_prioritization", "RS4253311", PROMPTS["gwas_variant_prioritization"])
    # The official evaluator is case-SENSITIVE here; we normalize the prefix and
    # keep the raw token so the strict reward can quantify the difference.
    assert p.canonical == "rs4253311"
    assert p.raw == "RS4253311"


def test_screen_gene_preserves_hyphenated_symbol():
    p = parse_answer("screen_gene_retrieval", "znf561-as1", PROMPTS["screen_gene_retrieval"])
    assert p.canonical == "ZNF561-AS1"


# --------------------------------------------------------------------------
# Multiple candidate answers
# --------------------------------------------------------------------------


def test_multiple_genes_mentioned_is_ambiguous():
    p = parse_answer(
        "gwas_causal_gene_opentargets",
        "Both HNF1A and KDM2B are plausible.",
        PROMPTS["gwas_causal_gene_opentargets"],
    )
    assert p.status == "ambiguous"
    assert p.canonical is None
    assert set(p.detail["candidate_hits"]) == {"HNF1A", "KDM2B"}


def test_multiple_genes_but_explicit_final_answer_resolves():
    p = parse_answer(
        "gwas_causal_gene_opentargets",
        "I considered KDM2B and MLEC.\nAnswer: HNF1A",
        PROMPTS["gwas_causal_gene_opentargets"],
    )
    assert p.status == "ok"
    assert p.canonical == "HNF1A"


def test_multiple_variants_is_ambiguous():
    p = parse_answer(
        "gwas_variant_prioritization",
        "Either rs4253311 or rs1280 could work.",
        PROMPTS["gwas_variant_prioritization"],
    )
    assert p.status == "ambiguous"


def test_conflicting_letters_is_ambiguous():
    p = parse_answer("lab_bench_dbqa", "[ANSWER]C[/ANSWER] ... actually [ANSWER]D[/ANSWER]", PROMPTS["lab_bench_dbqa"])
    assert p.status == "ambiguous"


def test_patient_gene_multiple_genes_is_a_set():
    p = parse_answer(
        "patient_gene_detection",
        "{'causal_gene': ['ENSG00000131174', 'ENSG00000092330']}",
        PROMPTS["patient_gene_detection"],
    )
    assert p.status == "ok"
    # Cluster key is order-independent so two runs listing the same set agree.
    assert p.cluster_key == "ENSG00000092330|ENSG00000131174"
    assert p.detail["n_predicted"] == 2


def test_patient_gene_cluster_key_is_order_independent():
    a = parse_answer("patient_gene_detection", "{'causal_gene': ['ENSG00000092330','ENSG00000131174']}", "")
    b = parse_answer("patient_gene_detection", "{'causal_gene': ['ENSG00000131174','ENSG00000092330']}", "")
    assert a.cluster_key == b.cluster_key


# --------------------------------------------------------------------------
# Prompt option parsing
# --------------------------------------------------------------------------


def test_prompt_options_parsed_per_task():
    assert parse_prompt_options("crispr_delivery", PROMPTS["crispr_delivery"]) == list("abcdef")
    assert "HNF1A" in parse_prompt_options("gwas_causal_gene_opentargets", PROMPTS["gwas_causal_gene_opentargets"])
    assert "rs4253311" in parse_prompt_options("gwas_variant_prioritization", PROMPTS["gwas_variant_prioritization"])
    assert parse_prompt_options("lab_bench_dbqa", PROMPTS["lab_bench_dbqa"]) == list("ABCDE")
    assert "ZNF561-AS1" in parse_prompt_options("screen_gene_retrieval", PROMPTS["screen_gene_retrieval"])
    assert "ENSG00000161011" in parse_prompt_options("patient_gene_detection", PROMPTS["patient_gene_detection"])


def test_no_legal_candidate_mentioned_is_unparseable_not_invented():
    # Regression: a loose "answer/gene ..." regex previously extracted the word
    # "with" from prose. When the prompt enumerates candidates and none appear,
    # the answer must be unparseable rather than fabricated.
    p = parse_answer(
        "screen_gene_retrieval",
        "The gene with the strongest effect could not be determined.",
        PROMPTS["screen_gene_retrieval"],
    )
    assert p.status == "unparseable"
    assert p.canonical is None


def test_trailing_punctuation_does_not_break_candidate_match():
    p = parse_answer(
        "screen_gene_retrieval",
        "The gene with the strongest effect is SON.",
        PROMPTS["screen_gene_retrieval"],
    )
    assert p.status == "ok"
    assert p.canonical == "SON"


def test_unknown_task_rejected():
    with pytest.raises(ValueError):
        parse_answer("not_a_task", "x", "")


def test_ground_truth_is_never_an_input():
    import inspect

    from biomni_uncertainty import canonicalization

    for name, fn in inspect.getmembers(canonicalization, inspect.isfunction):
        params = set(inspect.signature(fn).parameters)
        assert not (params & {"answer", "ground_truth", "gt", "label"}), name
