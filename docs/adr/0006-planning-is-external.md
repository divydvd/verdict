# ADR-0006: Planning is external to the framework

## Status
Accepted

## Context
"Agentic" testing platforms can be read two ways: (1) a platform that autonomously decides what
to test and executes that plan, or (2) a platform that executes and verifies scenarios, exposed
through an interface rich enough for an external AI agent to compose test strategies at runtime.
The original requirements explicitly asked for a "Planning Layer" that determines WHAT should be
tested, separate from execution.

## Decision
The framework does not contain an autonomous test-strategy/planning AI. Deciding *what* to test
is the responsibility of the calling agent (Claude Code, Codex, Gemini CLI, or a human via CLI),
assisted by the framework's read-only introspection APIs (`list_scenarios`, `describe_scenario`,
`list_capabilities`, and the deterministic `plan_regression`). The framework's role is execution
and verification, with judgment supplied by the LLM Verification Layer where deterministic checks
aren't sufficient (see ADR-0004) — not by a planning brain that decides test scope.

## Consequences
**Positive:**
- Avoids duplicating a general-purpose reasoning system inside a testing tool. An AI coding agent
  with repository access already reasons well about "what changed, what could be affected, what
  should be tested" — building a second, weaker version of that inside the platform is wasted
  effort and adds non-determinism to something that doesn't need to be non-deterministic.
- Keeps the core small, fast, and deterministic-first (aligned with ADR-0004): routine test runs
  don't require an LLM call just to decide what to run.
- Cleanly separates two concerns that have very different failure modes: "did we pick the right
  tests" (an open-ended reasoning problem, owned by the agent) vs. "did the app behave correctly"
  (a verifiable, mostly-deterministic problem, owned by the framework).

**Negative:**
- The framework alone, without an orchestrating agent or CI trigger, cannot decide to go test
  something — it is not autonomous in isolation. This is accepted as correct scope: nothing in the
  original requirements implies the platform should run fully unattended without any driver.
- Regression-scoped test selection (a legitimate "what should we test" question with a
  deterministic answer) is handled separately by the Regression Planner (ADR-0008), which is
  explicitly *not* the same thing as open-ended planning — it's a scoped, auditable mapping
  problem, not reasoning.

## Alternatives Considered
- **In-framework planning engine that reasons over the SmarType codebase to propose test
  coverage.** Rejected as over-engineering: this is precisely what an AI coding agent with repo
  access already does well. Building a parallel, in-framework version adds substantial complexity
  (an LLM-driven reasoning loop, prompt design, evaluation of its own output) for a capability
  already available externally, and would make the framework itself the source of test-strategy
  bugs rather than the SmarType app.
