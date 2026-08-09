# ADR-0008: Regression scenario selection is deterministic, tag-based

## Status
Accepted

## Context
Running the entire scenario suite on every code change doesn't scale as the corpus grows. The
requirements ask for a "Regression Planner" that analyzes source-code changes, infers affected
features, and selects the minimum required scenarios automatically.

## Decision
Each scenario declares a `covers` field: a list of glob patterns (source paths) and/or feature
tags describing what it exercises. The Regression Planner takes a list of changed file paths (from
a git diff) and returns the union of scenarios whose `covers` patterns match at least one changed
file. If no scenario matches, a documented fallback smoke-tag set runs instead of nothing — under-
tagging fails safe (runs more than strictly necessary) rather than silently skipping coverage. No
ML/embedding-based "infer relatedness" is used in v1.

## Consequences
**Positive:**
- Fully deterministic and auditable: "why did this scenario run" always has a literal, inspectable
  answer (a specific `covers` pattern matched a specific changed file) — critical for trusting CI
  results and debugging selection gaps.
- Zero additional infrastructure: no vector database, no embedding model, no training/maintenance
  of a relatedness model.
- Scenario authors directly control their own coverage declarations, colocated with the scenario
  itself — no separate mapping file to keep in sync in a different location.

**Negative:**
- Requires ongoing discipline to keep `covers` accurate as source code moves or scenarios are
  added — a scenario with stale or missing `covers` may not be selected when it should be.
  Mitigated by the fallback smoke set (fails toward over-testing, not under-testing) and by
  treating `covers` accuracy as a normal code-review concern for scenario changes, same as any
  other test metadata.
- Won't catch relatedness a human or LLM might infer but that isn't explicitly tagged (e.g. a
  shared utility function refactor that indirectly affects an untagged scenario). Accepted for v1;
  revisit only if tag-based coverage demonstrates a high false-negative rate in practice — not
  speculatively.

## Alternatives Considered
- **LLM-based "does this diff affect this scenario" classifier.** Rejected for v1: non-
  deterministic (the same diff could get different scenario selections on different runs),
  expensive to run on every PR (one classification call per scenario per diff, or an
  awkward batch design), and hard to audit ("the model thought so" is not a debuggable answer to
  "why did/didn't this scenario run"). Worth reconsidering only if the deterministic approach
  proves to have a materially high false-negative rate that tagging discipline can't fix.
