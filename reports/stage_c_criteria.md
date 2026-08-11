# Stage C — BiomniEval1 Verifier Criteria

<!--
FROZEN. Reproduced verbatim from reports/stage_c_preregistration.md §4, which
was committed before any BiomniEval1 capsule was serialized or scored. This
file is the machine-readable copy the verifier actually loads; the report
governs if the two ever disagree.

Replaces the reference implementation's per-benchmark criteria at the published
cardinality of three. Every criterion is label-free: none refers to the correct
answer, and each is computable from the capsule alone.

HTML comments are stripped by the loader, so this note never reaches the model.
-->

## Ground Truth Note

You are scoring a biomedical analysis trajectory. Do NOT trust the agent's self-assessment; its stated confidence is deliberately withheld from you and would not be reliable. The only reliable evidence is what the tools and code actually returned. A correct answer may be a specific entity, a set, or an explicit statement that the evidence does not determine one. Do not favour specific-looking answers over cautious ones, or the reverse. Judge only whether the trajectory's own evidence logically supports what it committed.

## Criteria

### Evidence adequacy and identifier fidelity {#evidence}

Consider only what the trajectory actually queried and retrieved.

  1. Did the tools and databases invoked address the entity the task names?
  2. Are the identifiers used — gene symbols, ENSG IDs, rsIDs, variant coordinates, OMIM codes, drug names, cell lines — the ones the task specifies? Check them character by character.
  3. Were the queries capable of returning evidence bearing on the question asked?

A trajectory that ran no query has no retrieved evidence; score it on that basis, but do not reward querying for its own sake. Ignore the fluency of the write-up.

### Answer–evidence alignment {#alignment}

Look at what the tool and code output actually returned.

  - Where returns were empty, errored, or truncated, the only answers they support are ones that acknowledge it. Asserting a specific biomedical entity from an empty or failed return is fabrication.
  - Where substantive evidence was returned, the committed answer should follow from it. Ignoring returned evidence is equally wrong.
  - Where the answer is computed — a count, a rank, a set — check the computation against the returned records.

Score on alignment between what came back and what was committed.

### Commitment validity {#commitment}

The trajectory must commit exactly one answer, in the form the task requires.

  - Is exactly one answer committed, rather than several left in play?
  - Is it of the required type and cardinality — a single gene symbol versus a list, an identifier versus a name, a set where a set is asked for?
  - Is it drawn from the answer space the task defines, where one is defined?

Discussion of an alternative that is never committed is not an answer.
