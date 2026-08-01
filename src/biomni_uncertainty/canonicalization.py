"""Task-aware answer extraction and canonicalization for BiomniEval1.

Pipeline for every trajectory::

    raw final response
      -> strip <BIOMNI_CONFIDENCE> block          (confidence.extract_confidence)
      -> extract the last <solution>...</solution>  (extract_solution_block)
      -> task-specific parse                        (parse_answer)
      -> canonical form                             (ParsedAnswer.canonical)

The canonical form is what is handed to the official ``BiomniEval1.evaluate``
and what self-consistency clusters on. Canonicalization is deliberately
ground-truth-free: it only uses the response text and, where the benchmark
prompt enumerates the legal options, the option list parsed from the prompt.

Every parse also keeps ``raw`` (the un-normalized token) so that a *strict*
reward can be computed alongside the primary reward. The difference between the
two quantifies how much credit our normalization grants beyond a literal string
comparison; it is reported, not hidden.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

SOLUTION_RE = re.compile(r"<solution>(.*?)</solution>", re.DOTALL | re.IGNORECASE)
OPEN_SOLUTION_RE = re.compile(r"<solution>(.*)", re.DOTALL | re.IGNORECASE)

# Tasks present in the biomni/Eval1 parquet, plus `hle` which the official
# evaluator supports but which ships with zero instances in this release.
KNOWN_TASKS = (
    "crispr_delivery",
    "gwas_causal_gene_gwas_catalog",
    "gwas_causal_gene_opentargets",
    "gwas_causal_gene_pharmaprojects",
    "gwas_variant_prioritization",
    "hle",
    "lab_bench_dbqa",
    "lab_bench_seqqa",
    "patient_gene_detection",
    "rare_disease_diagnosis",
    "screen_gene_retrieval",
)

ParseStatus = str  # "ok" | "no_solution_block" | "empty" | "unparseable" | "ambiguous"


@dataclass(frozen=True)
class ParsedAnswer:
    """Result of parsing one trajectory's final answer."""

    task_name: str
    status: ParseStatus
    raw: str | None  # the un-normalized extracted token / object string
    canonical: str | None  # normalized string handed to the official evaluator
    cluster_key: str | None  # key used for self-consistency clustering
    detail: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.canonical is not None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Solution-block extraction
# --------------------------------------------------------------------------


def extract_solution_block(text: str) -> tuple[str | None, str]:
    """Return ``(solution_text, status)`` for the LAST solution block in ``text``.

    Falls back to an unterminated ``<solution>`` (generation cut off by the
    token budget) and finally to the whole text, each with a distinct status so
    the fallback rate is measurable.
    """
    if not text:
        return None, "empty"
    matches = list(SOLUTION_RE.finditer(text))
    if matches:
        return matches[-1].group(1).strip(), "ok"
    m = OPEN_SOLUTION_RE.search(text)
    if m:
        return m.group(1).strip(), "unterminated_solution_block"
    return text.strip(), "no_solution_block"


# --------------------------------------------------------------------------
# Prompt option parsing (ground-truth-free disambiguation aids)
# --------------------------------------------------------------------------


def parse_prompt_options(task_name: str, prompt: str) -> list[str]:
    """Extract the legal answer options that the benchmark prompt enumerates."""
    if not prompt:
        return []
    if task_name.startswith("gwas_causal_gene"):
        # "Genes in locus: {APOA1},{APOA4},..."
        return re.findall(r"\{([A-Za-z0-9._\-]+)\}", prompt)
    if task_name == "gwas_variant_prioritization":
        m = re.search(r"Variants:\s*(.+)", prompt)
        return re.findall(r"rs\d+", m.group(1)) if m else re.findall(r"rs\d+", prompt)
    if task_name == "screen_gene_retrieval":
        m = re.search(r"Candidate genes:\s*(.+)", prompt)
        if m:
            return [g.strip() for g in m.group(1).split(",") if g.strip()]
        return []
    if task_name in ("patient_gene_detection", "rare_disease_diagnosis"):
        m = re.search(r"Candidate genes:\s*(.+)", prompt)
        return re.findall(r"ENSG\d+", m.group(1)) if m else re.findall(r"ENSG\d+", prompt)
    if task_name == "crispr_delivery":
        return re.findall(r"^\s*([a-f])\.\s", prompt, re.MULTILINE)
    if task_name.startswith("lab_bench") or task_name == "hle":
        return re.findall(r"^\s*([A-Z])\.", prompt, re.MULTILINE)
    return []


# --------------------------------------------------------------------------
# Task-specific parsers
# --------------------------------------------------------------------------


def parse_answer(task_name: str, text: str, prompt: str | None = None) -> ParsedAnswer:
    """Parse the task answer out of a solution-block body."""
    if task_name not in KNOWN_TASKS:
        raise ValueError(f"Unknown task {task_name!r}. Known: {KNOWN_TASKS}")

    body = (text or "").strip()
    options = parse_prompt_options(task_name, prompt or "")
    if not body:
        return ParsedAnswer(task_name, "empty", None, None, None, {"options": options})

    if task_name == "crispr_delivery":
        return _parse_letter_choice(task_name, body, options, lowercase=True)
    if task_name.startswith("gwas_causal_gene") or task_name == "screen_gene_retrieval":
        return _parse_gene_symbol(task_name, body, options)
    if task_name == "gwas_variant_prioritization":
        return _parse_variant(task_name, body, options)
    if task_name.startswith("lab_bench") or task_name == "hle":
        return _parse_letter_choice(task_name, body, options, lowercase=False, tagged=True)
    if task_name == "patient_gene_detection":
        return _parse_patient_gene(task_name, body, options)
    if task_name == "rare_disease_diagnosis":
        return _parse_rare_disease(task_name, body)
    raise AssertionError("unreachable")


def _parse_letter_choice(
    task_name: str,
    body: str,
    options: list[str],
    *,
    lowercase: bool,
    tagged: bool = False,
) -> ParsedAnswer:
    """Multiple choice. Evaluator compares case-insensitively on a single letter."""
    detail: dict[str, Any] = {"options": options}
    allowed = {o.upper() for o in options} or (set("ABCDEF") if lowercase else set("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))

    candidates: list[str] = []
    if tagged:
        tags = re.findall(r"\[ANSWER\]\s*([A-Za-z])\s*\[/ANSWER\]", body, re.IGNORECASE)
        if tags:
            detail["source"] = "answer_tag"
            candidates = tags
    if not candidates:
        # "Most relevant method (select one letter a-f): b" / "Answer: B" / "b. Lentivirus"
        m = re.search(r"(?:answer|method|option|choice)\s*(?:is)?\s*[:\-]?\s*\(?([A-Za-z])\)?\b", body, re.IGNORECASE)
        if m and m.group(1).upper() in allowed:
            detail["source"] = "labelled"
            candidates = [m.group(1)]
    if not candidates:
        stripped = body.strip().strip("*` \n\t")
        m = re.fullmatch(r"\(?([A-Za-z])\)?[.):]?", stripped)
        if m and m.group(1).upper() in allowed:
            detail["source"] = "bare_letter"
            candidates = [m.group(1)]
    if not candidates:
        # First line that starts with a legal option letter, e.g. "b. Lentivirus/Retrovirus".
        m = re.match(r"\s*\(?([A-Za-z])\)?[.):]\s+\S", body)
        if m and m.group(1).upper() in allowed:
            detail["source"] = "leading_option_line"
            candidates = [m.group(1)]
    if not candidates:
        found = [c for c in re.findall(r"\b([A-Za-z])\b", body) if c.upper() in allowed]
        if found:
            detail["source"] = "loose_scan"
            detail["loose_matches"] = found
            candidates = [found[-1]]

    if not candidates:
        return ParsedAnswer(task_name, "unparseable", None, None, None, detail)

    uniq = {c.upper() for c in candidates}
    if len(uniq) > 1:
        detail["conflicting"] = sorted(uniq)
        return ParsedAnswer(task_name, "ambiguous", candidates[-1], None, None, detail)

    raw = candidates[-1]
    canonical = raw.lower() if lowercase else raw.upper()
    return ParsedAnswer(task_name, "ok", raw, canonical, canonical, detail)


# Declarative "SYMBOL is/was ... causal gene" and "making SYMBOL the prime
# candidate" conclusions. Found necessary on real Phase-1 data: the model
# routinely states its answer symbol-first ("**PDGFRB** is identified as the
# most likely causal gene ...") rather than label-first ("answer: PDGFRB"),
# which the older _LABELLED pattern above does not match. Only the LAST match
# is used (closest to the conclusion), and only when it names a legal option.
_SYMBOL_FIRST_CONCLUSION_RE = re.compile(
    r"\*{0,2}([A-Za-z0-9][A-Za-z0-9._\-]{0,24})\*{0,2}'?s?\s+"
    r"(?:is|was|remains|stands out as|represents)\s+"
    r"(?:identified as\s+|confirmed as\s+|considered\s+)?"
    r"(?:the\s+)?(?:most likely\s+|prime\s+|strongest\s+|best\s+|top\s+|primary\s+)?"
    r"(?:candidate\s+)?causal gene",
    re.IGNORECASE,
)
_MAKING_SYMBOL_CANDIDATE_RE = re.compile(
    r"making\s+\*{0,2}([A-Za-z0-9][A-Za-z0-9._\-]{0,24})\*{0,2}\s+the\s+"
    r"(?:prime|top|best|leading|strongest)\s+candidate",
    re.IGNORECASE,
)


def _search_symbol_first_conclusion(body: str, opt_upper: dict[str, str]) -> str | None:
    for pat in (_SYMBOL_FIRST_CONCLUSION_RE, _MAKING_SYMBOL_CANDIDATE_RE):
        matches = list(pat.finditer(body))
        for m in reversed(matches):
            sym = m.group(1)
            if sym.upper() in opt_upper:
                return sym
    return None


def _parse_gene_symbol(task_name: str, body: str, options: list[str]) -> ParsedAnswer:
    """Gene symbol. Evaluator compares ``.strip().upper()``."""
    detail: dict[str, Any] = {"options": options}
    opt_upper = {o.upper(): o for o in options}

    # 1. If the prompt enumerated candidates, prefer an exact candidate token.
    #    Gene symbols may contain '.' and '-', so tokens keep them internally but
    #    trailing sentence punctuation ("SON.") is stripped before matching.
    if opt_upper:
        tokens = [t.rstrip(".-_") for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9._\-]*", body)]
        hits = [t for t in tokens if t.upper() in opt_upper]
        if hits:
            uniq = {h.upper() for h in hits}
            detail["source"] = "candidate_match"
            detail["candidate_hits"] = sorted(uniq)
            if len(uniq) > 1:
                # Multiple legal candidates mentioned: prefer one that is the whole
                # body or follows an explicit answer label, else declare ambiguity.
                whole = body.strip().strip("*`.,: \n")
                if whole.upper() in opt_upper:
                    return ParsedAnswer(task_name, "ok", whole, whole.upper(), whole.upper(), detail)
                m = re.search(
                    r"(?:answer|gene|causal gene)\s*(?:is)?\s*[:\-]?\s*\**([A-Za-z0-9._\-]+)",
                    body,
                    re.IGNORECASE,
                )
                if m and m.group(1).upper() in opt_upper:
                    detail["source"] = "candidate_match_labelled"
                    return ParsedAnswer(task_name, "ok", m.group(1), m.group(1).upper(), m.group(1).upper(), detail)
                sym = _search_symbol_first_conclusion(body, opt_upper)
                if sym is not None:
                    detail["source"] = "symbol_first_conclusion"
                    return ParsedAnswer(task_name, "ok", sym, sym.upper(), sym.upper(), detail)
                return ParsedAnswer(task_name, "ambiguous", hits[-1], None, None, detail)
            return ParsedAnswer(task_name, "ok", hits[0], hits[0].upper(), hits[0].upper(), detail)

    # 2. No candidate list (or no hit): take a bare symbol-looking body.
    whole = body.strip().strip("*`.,:; \n")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,24}", whole):
        detail["source"] = "bare_symbol"
        return ParsedAnswer(task_name, "ok", whole, whole.upper(), whole.upper(), detail)

    # 3. A labelled answer, e.g. "Causal gene: HNF1A". When the prompt enumerated
    #    candidates and none of them appeared, the response does not name a legal
    #    answer, so this loose fallback must not invent one out of prose.
    if not opt_upper:
        m = re.search(
            r"(?:answer|gene)\s*(?:is)?\s*[:\-]?\s*\**([A-Za-z0-9][A-Za-z0-9._\-]{0,24})", body, re.IGNORECASE
        )
        if m:
            detail["source"] = "labelled"
            return ParsedAnswer(task_name, "ok", m.group(1), m.group(1).upper(), m.group(1).upper(), detail)

    return ParsedAnswer(task_name, "unparseable", None, None, None, detail)


def _parse_variant(task_name: str, body: str, options: list[str]) -> ParsedAnswer:
    """dbSNP rsID.

    The official evaluator compares case-SENSITIVELY. Every ground truth in the
    release uses lowercase ``rs``, so we normalize the prefix to lowercase and
    record the un-normalized token; the strict reward on ``raw`` quantifies how
    often that normalization mattered.
    """
    detail: dict[str, Any] = {"options": options}
    opts = {o.lower() for o in options}
    found = re.findall(r"(?i)\brs\d+\b", body)
    if not found:
        return ParsedAnswer(task_name, "unparseable", None, None, None, detail)

    normed = [f"rs{f[2:]}" for f in found]
    if opts:
        legal = [n for n in normed if n in opts]
        if legal:
            detail["source"] = "candidate_match"
            uniq = list(dict.fromkeys(legal))
            if len(uniq) > 1:
                whole = body.strip().strip("*`.,:; \n")
                if whole.lower() in opts:
                    return ParsedAnswer(task_name, "ok", whole, f"rs{whole[2:]}", f"rs{whole[2:]}", detail)
                detail["conflicting"] = uniq
                return ParsedAnswer(task_name, "ambiguous", found[-1], None, None, detail)
            return ParsedAnswer(task_name, "ok", found[normed.index(uniq[0])], uniq[0], uniq[0], detail)

    uniq = list(dict.fromkeys(normed))
    detail["source"] = "regex_scan"
    if len(uniq) > 1:
        detail["conflicting"] = uniq
        return ParsedAnswer(task_name, "ambiguous", found[-1], None, None, detail)
    return ParsedAnswer(task_name, "ok", found[0], uniq[0], uniq[0], detail)


def _loads_loose(s: str) -> Any:
    """Parse a JSON-ish object, mirroring the official evaluator's json -> ast fallback."""
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"```\s*$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        pass
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        for loader in (json.loads, ast.literal_eval):
            try:
                return loader(m.group(0))
            except Exception:  # noqa: BLE001 - loader-specific errors, both benign
                continue
    return None


def _parse_patient_gene(task_name: str, body: str, options: list[str]) -> ParsedAnswer:
    """``{'causal_gene': [ENSG...]}``.

    The evaluator intersects the predicted gene set with the ground-truth set,
    so the cluster key is the sorted gene set. ``n_predicted`` is retained
    because a large predicted set inflates the official reward.
    """
    detail: dict[str, Any] = {"options": options}
    obj = _loads_loose(body)
    genes: list[str] = []

    if isinstance(obj, dict) and "causal_gene" in obj:
        val = obj["causal_gene"]
        genes = [str(v) for v in (val if isinstance(val, list) else [val])]
        detail["source"] = "json_object"
    else:
        genes = re.findall(r"ENSG\d+", body)
        detail["source"] = "regex_scan"

    genes = [g.strip().upper() for g in genes if g and str(g).strip()]
    genes = list(dict.fromkeys(genes))
    if not genes:
        return ParsedAnswer(task_name, "unparseable", None, None, None, detail)

    detail["n_predicted"] = len(genes)
    canonical = json.dumps({"causal_gene": genes}, separators=(",", ":"))
    cluster_key = "|".join(sorted(genes))
    return ParsedAnswer(task_name, "ok", body.strip()[:2000], canonical, cluster_key, detail)


_OMIM_RE = re.compile(r"(?i)\b(?:OMIM[:#\s]*|MIM[:#\s]*|#)?(\d{5,6})\b")


def _parse_rare_disease(task_name: str, body: str) -> ParsedAnswer:
    """``{'disease_name': XXX, 'OMIM_ID': XXX}``.

    The evaluator compares ``OMIM_ID`` with ``==`` against a ground-truth string
    of digits, so the OMIM id is normalized to a bare digit string (dropping
    ``OMIM:`` / ``#`` prefixes and any int/str difference). ``disease_name`` is
    preserved but is not evaluated.
    """
    detail: dict[str, Any] = {}
    obj = _loads_loose(body)
    omim = None
    name = None

    if isinstance(obj, dict):
        detail["source"] = "json_object"
        name = obj.get("disease_name")
        raw_omim = obj.get("OMIM_ID", obj.get("omim_id"))
        if raw_omim is not None:
            m = _OMIM_RE.search(str(raw_omim))
            omim = m.group(1) if m else None
    if omim is None:
        detail["source"] = detail.get("source", "regex_scan")
        m = re.search(r"(?i)OMIM[_\s]*(?:ID)?\D{0,4}(\d{5,6})", body)
        if not m:
            m = _OMIM_RE.search(body)
        omim = m.group(1) if m else None

    if omim is None:
        return ParsedAnswer(task_name, "unparseable", None, None, None, detail)

    canonical = json.dumps(
        {"disease_name": str(name) if name is not None else "", "OMIM_ID": omim},
        separators=(",", ":"),
    )
    detail["omim_id"] = omim
    detail["disease_name"] = str(name) if name is not None else None
    return ParsedAnswer(task_name, "ok", body.strip()[:2000], canonical, omim, detail)


# --------------------------------------------------------------------------
# Convenience: full pipeline
# --------------------------------------------------------------------------


def parse_final_response(
    task_name: str,
    raw_response: str,
    prompt: str | None = None,
    *,
    confidence_requested: bool = True,
    open_delim: str = "<BIOMNI_CONFIDENCE>",
    close_delim: str = "</BIOMNI_CONFIDENCE>",
) -> dict:
    """Run the full raw-response -> canonical-answer pipeline.

    Returns a dict with the confidence result, the solution-block status and the
    parsed answer, so every intermediate stage stays auditable.
    """
    from biomni_uncertainty.confidence import extract_confidence

    conf = extract_confidence(
        raw_response or "",
        open_delim,
        close_delim,
        requested=confidence_requested,
    )
    solution, sol_status = extract_solution_block(conf.cleaned_text)
    # A confidence block emitted outside the solution block would already be gone;
    # strip again in case the model nested it in an unexpected place.
    conf_inner = extract_confidence(solution or "", open_delim, close_delim, requested=confidence_requested)
    solution_clean = conf_inner.cleaned_text if conf_inner.n_blocks else solution
    if conf.status in ("missing", "not_requested") and conf_inner.ok:
        conf = conf_inner

    parsed = parse_answer(task_name, solution_clean or "", prompt)
    return {
        "confidence": conf.to_dict(),
        "solution_block_status": sol_status,
        "solution_text": solution_clean,
        "parsed": parsed.to_dict(),
    }
