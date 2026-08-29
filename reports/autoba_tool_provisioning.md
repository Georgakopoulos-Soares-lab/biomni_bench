# AutoBA/bioTaskBench execution-environment tool audit

Date: 2026-08-29. Covers all 34 bioTaskBench tasks' `context.expected_tools`
fields, ahead of freezing the confirmatory K=4 panel
(`reports/autoba_k4_pilot_v1_preregistration.md`), per instruction: audit
before freezing, replace unsupportable tasks before the panel is frozen, not
after seeing outcomes.

## Execution environment

AutoBA's own generated code runs inside
`/scratch/11034/atzanakak/genomas_admission/venv` (Python 3.11.8, activated
via `scripts/autoba_biotaskbench_agent.py`'s `EXEC_ENV_PREFIX`, which also
sets the `LD_LIBRARY_PATH` this node's `gcc/14.2.0 python3/3.11.8` module
combination requires). This is the same venv the project already uses
(`biomni-uncertainty` editable-installed into it).

This node (TACC Vista) has **no `conda`/`mamba` anywhere on `PATH`, no `R`/
`Rscript`, and `module avail` lists only the HPC toolchain** (compilers, MPI,
CUDA, math libraries) — no bioinformatics domain modules. Provisioning this
session is therefore limited to `pip install` into the execution venv.

## Installed this session (pip, verified by direct invocation, not just a clean `pip install` exit code)

| Tool | Package | Version | Verification |
| --- | --- | --- | --- |
| pysam | `pysam` | 0.24.0 | `import pysam; pysam.__version__` |
| scikit-allel | `scikit-allel` | 1.3.13 | `import allel; allel.__version__` |
| MACS3 | `MACS3` | 3.0.4 | `macs3 --version` |
| QUAST | `quast` | 5.2.0 | `quast.py --version` |
| NanoStat | `NanoStat` | 1.6.0 | `NanoStat --version` |
| Scanpy | `scanpy` | 1.11.5 | `import scanpy; scanpy.__version__` |
| Squidpy | `squidpy` | 1.8.2 | `import squidpy; squidpy.__version__` |

All seven are pure-Python or ship prebuilt/compilable-without-conda wheels;
none needed a system package beyond the already-loaded `gcc/14.2.0` toolchain.

## Already available (no action needed)

`Python`, `numpy`, `pandas`, `scipy`, `statsmodels`, `scikit-learn` (all used
throughout the project already); `awk` (system utility, present on any POSIX
node, unrelated to the venv).

## Not installed this session, and why

| Tool | Named by | Why not installed |
| --- | --- | --- |
| R / Rscript | 28 of 34 tasks | No R and no conda/mamba on this node; building R from source plus the Bioconductor packages below is a multi-hour, high-risk undertaking judged out of scope for this pass. |
| DESeq2, edgeR, limma, methylKit, ChIPseeker | chipseq-004/005, meth-001/002, chipseq-003, prot-003 | Bioconductor R packages; blocked on R itself. |
| HOMER | chipseq-001/002/003 | Perl-based toolkit distributed with its own genome-annotation database downloads; no conda path, not pip-installable. |
| MEME suite | chipseq-002 | C/C++ source build with its own dependency chain (no conda); judged out of scope for this pass. |
| bedtools, samtools (as CLI binaries) | chipseq-003/005 | C/C++ binaries; no conda. `pysam` (installed) already covers BAM/SAM/FASTA parsing needs in pure Python without the standalone CLI. |
| VCFtools | popgen-001 | C++ binary; no conda. |
| PLINK | popgen-003/004 | Distributed as a compiled binary; upstream builds are x86_64-only and this node is aarch64 (Grace-Hopper) — no compatible prebuilt binary exists, and PLINK 1.9's build system does not target aarch64 cleanly. |

## Is any task actually unexecutable?

**No task's grading criteria require a specific tool's provenance.** Every
one of the 34 tasks' `evaluation.criteria` (`harness/grader.py::grade_task`)
scores a plain output file's structure and numeric/set content
(`file_check`/`column_check`/`range_check`/`set_overlap`/
`numeric_correlation`/`code_executes`) — never which binary produced it. This
was already the case for the admitted `assembly-001` task, which lists
`QUAST` in `expected_tools` yet was solved end-to-end in pure pandas
(`reports/autoba_admission.md` Sec 1/3): `expected_tools` is a suggested
toolkit, not an enforced dependency.

Concretely, every chip-seq/population-genetics criterion inspected this
session (`chipseq-001..005`, `popgen-001/003/004`) grades a TSV/BED file's
columns, ranges, set overlap, or correlation against a reference — the same
shape as `assembly-001`. Fst, Hardy-Weinberg, PCA/outlier detection, and
differential-peak statistics are all standard formulas implementable directly
in `numpy`/`scipy`/`pandas` (already available); motif discovery
(`chipseq-002`, nominally MEME) is the one case where a from-scratch Python
substitute is qualitatively harder, not merely more code.

**No task is excluded from the candidate pool on infeasibility grounds.**
Unlike a task requiring a genuinely unreachable external service or
proprietary data, every named tool above computes something a
Python-native equivalent can approximate using packages already present.
Whether AutoBA actually *produces* a correct Python-native substitute when
the "expected" tool is unavailable is exactly the kind of empirical finding
the confirmatory campaign should surface — not something to pre-decide by
excluding the task.

## How this shapes panel selection

`reports/autoba_k4_pilot_v1_preregistration.md`'s task selection prefers
cells that exercise a **genuinely installed** tool this session (MACS3,
pysam, scikit-allel, Scanpy, Squidpy, NanoStat, QUAST) for the "requires a
real bioinformatics binary/package" diversity axis, so that axis is tested
against tools actually confirmed present rather than tools whose
availability is unverified. Tasks naming an unavailable tool (R/HOMER/MEME/
PLINK/etc.) are not excluded, but are not preferentially selected for that
specific diversity cell either, to avoid manufacturing an artificial
"blocked" result out of an environment gap rather than a genuine agent
limitation.
