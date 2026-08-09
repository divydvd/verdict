# ADR-0004: LLM verification is supplemental, not a replacement for deterministic assertions

## Status
Accepted

## Context
The platform includes an LLM Verification Layer capable of judging screenshots, UI hierarchy, and
logs. It would be simpler, in some cases, to let the LLM be the sole judge of pass/fail for a
given check rather than also writing a deterministic assertion.

## Decision
Every core SmarType behavior that the platform verifies (keyboard visible, text inserted,
clipboard updated, no crash, latency thresholds) has a deterministic assertion as the primary
pass/fail mechanism. LLM verification is used only for (a) genuinely subjective or visual
judgments that have no reliable deterministic proxy (e.g. "does this look visually broken"), or
(b) as a secondary layer that explains *why* a deterministic assertion already failed
(`analyze_failure`). An LLM call is never the only way to know whether a core scenario passed.

## Consequences
**Positive:**
- The core test suite is reproducible, fast, and cheap — it doesn't depend on external API
  availability, latency, or model behavior drift for basic pass/fail signal.
- CI failures are debuggable deterministically: a failed `clipboard_updated` assertion has an
  exact, inspectable reason (the clipboard content didn't match), not a probabilistic model
  judgment that might differ between runs.
- LLM API cost scales with genuinely-needed subjective checks and failure explanations, not with
  every assertion in every run.

**Negative:**
- Some visual/UX regressions that only an LLM would catch (e.g. a suggestion chip that is present
  in the hierarchy and passes all deterministic checks but is visually rendered wrong — clipped,
  wrong color, overlapping text) are only caught when a scenario explicitly opts into an
  LLM-backed assertion. Teams must remember to add these where visual correctness matters; they
  aren't caught "for free."

## Alternatives Considered
- **LLM-first verification** (the LLM alone decides pass/fail for most checks). Rejected:
  non-deterministic (flaky CI), expensive at scale (every assertion becomes an API call), harder
  to debug (a CI failure message becomes "the model said X" instead of an exact comparison), and
  introduces a hard external dependency for even the most basic pass/fail signal.
