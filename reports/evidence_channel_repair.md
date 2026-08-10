# Evidence-channel repair — before/after, and what was excluded and why

**Written:** 2026-08-10. **VERIFY prerequisite items 1 and 2**
(`reports/verify_prerequisites.md`), addressed together as instructed: item 1's
repair decisions and item 2's provenance instrumentation are two sides of the
same question — a route is only a valid VERIFY evidence source if it is both
*reliable* and *auditable*. **CPU-only, no GPU, no model calls, no agent driver,
no manifest.** Every diagnostic call is a direct call to the pinned Biomni tool
function, using real queries the agent actually issued during Phase 2B.

> **Bottom line.** Two tools are genuinely repaired by installing missing pure
> Python packages: `query_pubmed` (0% → **100%** success, 8/8 real trials) and
> `query_arxiv` (0% → **100%**, 8/8). Two tools are **excluded**, not repaired,
> for reasons stated in advance and confirmed by direct measurement:
> `query_scholar` (deterministic upstream package incompatibility, 0/8) and
> `advanced_web_search_claude` (requires a proprietary API key, never tested,
> excluded by the standing rule against introducing one). A third finding,
> not anticipated going in: **`search_google` — previously read as "healthy"
> at 3.4% error in the Track-C diagnostic — is unreliable in a way the old
> instrumentation could not see** (0/8 in direct testing; it fails silently,
> without raising, so the D-30 error-rate metric missed it entirely). **VERIFY's
> evidence route is therefore: `query_pubmed` + `query_arxiv` + the
> already-healthy structured databases. No general web-search tool is
> currently reliable.**

---

## 1. Method

For each candidate tool: reproduce the exact failure recorded in D-30, identify
the precise missing dependency or requirement, decide repair vs. substitute vs.
exclude per the brief's explicit decision rule, then measure before/after
reliability with **real queries the agent actually issued** (extracted from
`events.jsonl`'s `tool_call_start.argument_excerpt`), not hand-picked ones.
8 trials per tool, one call every 0.5 s (a deliberately polite rate against
public services, not a load test). Driver:
`scripts/evidence_channel_diagnostic.py`. Raw output:
`<output_root>/evidence_channel/results/evidence_channel_diagnostic.json`.

Two outcome classes, because D-30's own measurement conflated them:

* **error** — an exception, or the tool's own handler returning an
  `"Error: ..."` string (what the original runner's `failed_tool_call_count`
  already captures);
* **empty** — the call returns with **no exception** and no usable content.
  Invisible to the existing failure classification, and — as this diagnosis
  found — not a hypothetical case.

---

## 2. Per-tool diagnosis and decision

### `query_pubmed` — REPAIR (local dependency, reproducibly fixed)

**Cause.** `from pymed import PubMed` inside the function body (deferred
import); the package was never installed in the agent environment
(`biomni_unc`). Confirmed: `ModuleNotFoundError: No module named 'pymed'`,
reproduced directly before any change.

**External-service check.** `pymed` wraps NCBI's public E-utilities API with no
API key required for the query volumes here — a local dependency failure, not
an external-service requirement.

**Fix.** `pip install pymed` (version `0.8.9`) into the agent environment. One
package, no upstream code touched, no config change.

**Measured after:** **8/8 (100%)** real Phase-2B queries returned usable
content (e.g. `"CRISPR delivery methods primary macrophages electroporation
RNP"` → a real paper title/abstract/journal). Against D-30's measured 68.9%
error rate (197/286 calls) before repair.

### `query_arxiv` — REPAIR (local dependency, reproducibly fixed)

**Cause.** `import arxiv` inside the function body; not installed. Not in
D-30's top-tool-failure table because the agent essentially never selected it
during Phase 2B (retrieval offered it rarely and the model rarely chose it),
but it is a legitimate, zero-key literature source worth having available.

**External-service check.** Wraps arXiv's public API, no key required — local
dependency, not external-service.

**Fix.** `pip install arxiv` (version `4.0.1`).

**Measured after:** **8/8 (100%)** on real queries.

### `query_scholar` — EXCLUDE (reproducibly broken, not a design choice)

**Cause, reproduced precisely.** `from scholarly import ProxyGenerator,
scholarly`; `scholarly` was not installed (`ModuleNotFoundError`). Installing
it (version `1.7.11`, with its own `free_proxy` dependency `1.2.2`) does **not**
fix the tool:

```
pg.FreeProxies()
  → scholarly/_proxy_generator.py:550, in FreeProxies
  → scholarly/_proxy_generator.py:518, in _fp_coroutine
  → freeproxy.get_proxy_list()
TypeError: FreeProxy.get_proxy_list() missing 1 required positional argument: 'repeat'
```

This is a **signature mismatch between two currently-released third-party
packages** — `scholarly` 1.7.11 calls `free_proxy`'s `get_proxy_list()` without
the argument `free_proxy` 1.2.2 now requires. It is deterministic: **3/3
trials failed identically** before the formal 8-trial run was even started,
and the formal run confirms it: **0/8 (0%)**, every trial the identical
`TypeError`.

**Decision, per the brief's explicit framework.**
* (a) *Repair* — would require pinning a specific older, compatible pair of
  `scholarly`/`free_proxy` versions, which is fragile (the next environment
  rebuild silently reintroduces the incompatibility) and does not address the
  deeper problem: `query_scholar`'s underlying mechanism is scraping Google
  Scholar through **free, unauthenticated rotating proxies** — a category of
  approach that is inherently unreliable and easily broken by either side
  changing unannounced, independent of this specific bug.
* (b) *Substitute* — no open, zero-dependency scholarly-literature API
  exists as a drop-in; `query_pubmed`/`query_arxiv` already cover the
  literature-search need this tool was meant to serve.
* (c) *Exclude* — **selected.** `query_scholar` is not part of VERIFY's
  evidence route. The package is left installed (harmless, non-proprietary)
  but the tool is not used.

### `advanced_web_search_claude` — EXCLUDE (proprietary API, never tested)

**Cause.** `import anthropic`, and `client = anthropic.Anthropic(api_key=...)`
reading `ANTHROPIC_API_KEY` or `biomni.config.default_config.api_key`. Neither
the package nor a key is present in this environment.

**External-service check.** This is squarely the case the brief warns against:
repairing it means introducing a call to a proprietary LLM API
(Anthropic's `web_search_20250305` tool) from inside a testbed whose entire
premise is evaluating an **open-weights** agent (Biomni-R0-32B). Doing so would
(i) violate the standing rule already in `CLAUDE.md` against proprietary API
calls, extended here from Phase 1 to this phase for the same reason; (ii) add
an unaccounted cost and a second model in the loop; (iii) create a real
scientific confound — any VERIFY advantage attributable to this tool could not
be separated from "a stronger closed model did the verifying," which is a
different, larger experiment this project has explicitly deferred
(`reports/phase2_plan.md` §2.9, "small closed-model validation subset —
requires budget approval + data policy, a separate decision").

**Decision.** (a) repair — **rejected outright**, per instruction, without
even installing the package or requesting a key. (b) substitute — see below.
(c) **exclude — selected.** Never tested; excluded by policy before
measurement, which is itself the correct outcome of the decision framework
when option (a) is disqualified on its face.

Separately, D-30 measured 57 occurrences of
`cannot import name 'advanced_web_search_claude' from 'biomni'` — the correct
import (`from biomni.tool.literature import advanced_web_search_claude`, shown
verbatim in the system prompt) was sometimes written by the model as
`from biomni import advanced_web_search_claude`. That is a **model behavior
failure, not an environment defect**, would recur regardless of any repair
here, and is moot once the tool is excluded from VERIFY's route.

### `search_google` — EXCLUDE, and this is the new finding

**Prior read (D-30).** 59 calls, 2 errors, **3.4% error rate — looked
healthy**, and was the presumed fallback once `advanced_web_search_claude` was
ruled out as proprietary.

**What direct measurement found.** `search_google` wraps `googlesearch-python`
(already installed, version `1.3.0`), which scrapes Google's search-results
HTML. On 8 real Phase-2B queries — plus a preliminary check on a generic,
maximally-easy query (`"python programming language"`) — **every call returned
zero results, with no exception raised**:

```
Searching for BRCA1 breast cancer gene function with 3 results and en language
[no output — the internal generator yielded nothing]
```

Direct HTTP reachability to `google.com` is fine (`200 OK`); the scraping
approach itself is what fails, almost certainly because Google serves
non-browser-like requests a blocking or consent page rather than raw results —
a standard, expected failure mode for unofficial scraping libraries, and not
specific to this cluster or this project's network.

**Why D-30 missed this.** The runner's failure classification checks whether a
tool call raised or returned an `"Error: ..."` string. `search_google` catches
its own exceptions internally, prints a diagnostic to stdout, and returns an
**empty string** — which is neither. It was counted as a successful call. This
is exactly the "empty vs error" distinction this diagnosis was designed to
surface, and it changes the practical picture: **the true reliable-evidence
tool count from D-30's healthy-looking list drops by one.**

**Decision.** (a) repair — would mean working around Google's anti-scraping
measures (rotating user agents, proxies, delays), which is the same fragile,
ToS-adjacent category of fix rejected for `query_scholar`, for an approach with
no official API behind it at all. (b) substitute — no zero-dependency,
open, non-scraping general web-search tool is available in Biomni's current
toolset. (c) **exclude — selected.**

### Structured databases — unchanged, not re-measured

`query_gwas_catalog`, `query_monarch`, `query_ensembl`, `query_opentarget`,
`query_clinvar`, `query_pubchem`, `query_gtopdb`, `query_synapse` were already
healthy in D-30 (6.4–10.7% each), call direct, keyed biomedical database APIs
rather than scraping, and nothing in this repair touched their dependency
chain. **Not re-measured here** — there is no reason to expect a change, and
re-testing every already-healthy tool would be exactly the "install everything"
scope the brief warned against.

---

## 3. Before/after summary

| tool | before (D-30, agent-driven) | after (direct, 8 real queries) | decision |
| --- | --- | --- | --- |
| `query_pubmed` | 68.9% error (197/286) | **0% error (0/8)** | **REPAIR** — `pymed` installed |
| `query_arxiv` | not meaningfully sampled | **0% error (0/8)** | **REPAIR** — `arxiv` installed |
| `query_scholar` | 80.0% error (16/20) | **100% error (8/8)**, deterministic | **EXCLUDE** — reproducible upstream incompatibility |
| `advanced_web_search_claude` | 77.0% error (107/139) | not tested | **EXCLUDE** — proprietary API, rejected on policy |
| `search_google` | 3.4% error (2/59) — *looked healthy* | **100% empty (8/8)**, 0 exceptions | **EXCLUDE** — silent scraping failure the old metric missed |
| structured databases (8 tools) | 6.4–10.7% each | unchanged, not re-tested | **RETAIN**, already the reliable floor |

**Target stated in the brief: single-digit or otherwise clearly acceptable
failure rates comparable to the structured tools.** `query_pubmed` and
`query_arxiv` at 0/8 clear that bar outright. No general web-search tool does,
and none is included in VERIFY's evidence route as a result.

---

## 4. Retrieval-provenance instrumentation (item 2)

**What was added**, in `src/biomni_uncertainty/instrumentation.py`:

* **`retrieval_end.selected_identities`** — the actual **names** of the tools,
  data-lake entries, libraries and know-how documents retrieval selected,
  alongside the existing counts (`selected`). Extracted via `_resource_identity`,
  which mirrors Biomni's own
  `retriever._format_resources_for_prompt`'s three resource shapes (dict / str
  / attribute-bearing object) so the logged name is exactly the one the model
  itself saw. Bounded by the existing retrieval caps
  (`trajectory_budget.retrieval_max_*`) — no new size risk.
* **`code_execution_end.output_hash`** and **`tool_call_end.evidence_output_hash`**
  — a content hash (first 16 hex chars of SHA-256) of the code block's combined
  stdout, propagated to every tool-call event that block contained. **Stated
  limitation, not hidden:** Biomni tools execute inside one `<execute>` block,
  so when a block calls more than one tool the hash cannot be attributed to a
  single call — it is block-level, not call-level. This is a property of how
  Biomni's execution model works, not a shortcut taken here, and it is carried
  into every downstream consumer of the field rather than glossed over.

**Why identities and hashes, not full content.** Per instruction, nothing large
or unnecessary is dumped: names are short strings already bounded by the
retrieval caps, and content is reduced to a 16-character hash rather than
stored raw. The full text remains available separately in
`code_execution_end.stdout_excerpt` (already existed, unchanged, still capped
at `stdout_limit`), so nothing about existing behavior was removed.

**Consumption.** `src/biomni_uncertainty/diversity.py`'s `TrajectoryTrace` and
`extract_trace` now read both fields; `pairwise_diversity` exposes two new
metrics, `retrieval_identity_jaccard` and `evidence_output_jaccard` —
**deliberately kept outside `SIMILARITY_COMPONENTS`**, so `workflow_distance`,
already reported in D-30/`PROJECT_STATUS.md`, is not silently redefined by
data that did not exist when that number was computed. This is exactly the
instrumentation `reports/verify_definition.md` §5.3 specified as a
prerequisite for computing its evidence-identity audit — that audit was left
deliberately uncalibrated pending this data, and remains so: the fields now
exist, but no VERIFY trajectory has been generated yet to calibrate a
threshold from.

**Regression tests**, proving the fields are populated, not merely present in
the code:

* `tests/test_instrumentation.py` (9 tests) — `_resource_identity`'s three
  input shapes plus its nameless fallback; `retrieval_end` carrying
  `selected_identities` alongside counts, including the empty-selection case;
  `code_execution_end`/`tool_call_end` carrying a matching `output_hash` /
  `evidence_output_hash`; identical output text hashing identically, different
  text hashing differently; empty output hashing to `None`, not to a
  collision-prone placeholder.
* `tests/test_diversity.py` (+5 tests) — `retrieval_identity_jaccard` is
  category-qualified (a data-lake entry and a same-named tool never collide);
  returns `None`, not `0.0`, for traces predating this instrumentation (every
  run in Phase 1 through Phase 2B); `evidence_output_jaccard` detects shared
  retrieved content; both new metrics are asserted **not** to enter
  `SIMILARITY_COMPONENTS` or move `workflow_distance`.

**Full suite: 423 passed** (409 before this work + 14 new), lint clean.

---

## 5. What this does and does not establish

**Established.** VERIFY has a real, working, auditable evidence route:
`query_pubmed` + `query_arxiv` + the eight already-healthy structured
databases. The provenance to audit whether a future VERIFY trajectory actually
used independent evidence — not just asked a similar-sounding question — now
exists in the event log for any run generated from this point forward.

**Not established.**
* **Coverage.** `query_pubmed`/`query_arxiv` serve literature-dependent tasks;
  they do nothing for tasks whose evidence need was general web search (the
  gap `advanced_web_search_claude`/`search_google` would have filled). Some
  claims may simply have no currently-reliable independent-evidence route.
  That is a real constraint on VERIFY mode B's applicability, not a gap in
  this repair.
* **Whether the repaired channel changes agent behavior on healthy
  instances.** Not tested here — that is prerequisite item 4, deliberately
  scoped separately.
* **Whether residual trajectory failure has moved.** Not addressed —
  prerequisite item 3, next.
* **The §5.3 evidence-overlap audit threshold** remains uncalibrated, as
  specified. It requires VERIFY trials to exist before it can be set from data
  rather than guessed.

---

## 6. Reproduction

```bash
python scripts/evidence_channel_diagnostic.py \
    --out <output_root>/evidence_channel/results --n-per-tool 8
```

CPU only, direct calls to public APIs (NCBI, arXiv, Google Scholar's scraping
target, Google's scraping target), ~2 minutes including deliberate
between-call pauses. Writes only `evidence_channel_diagnostic.json`. Requires
network egress; will not run inside a fully offline environment (neither would
any future VERIFY evidence action).

**No frozen artifact was touched.** Environment change: `pymed==0.8.9`,
`arxiv==4.0.1`, `scholarly==1.7.11` (+ its `free_proxy==1.2.2` dependency)
installed into the `biomni_unc` environment. `scholarly` is left installed
despite being excluded from VERIFY's route — harmless, and removing it would
not change anything about the reliability finding.
