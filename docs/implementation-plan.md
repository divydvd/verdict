# Implementation Plan — SmarType Agentic Mobile Testing Platform

Companion to [`architecture.md`](agentic-testing-platform-architecture.md) (frozen v1.0). This
document sequences the build. Sizing is relative (S/M/L/XL), not calendar time — actual duration
depends on team size and is deliberately not fabricated here.

## Phase 1 — Core Execution Substrate (Android)

Goal: a working `smartype-test run scenario.yaml` CLI that installs a debug SmarType build,
executes a scenario against a real device/emulator, checks IME-specific assertions, and produces
a report. No LLM, no MCP, single device.

| # | Milestone | Size | Depends on |
|---|---|---|---|
| M1.1 | Core domain models & protocols: `Selector`, `UiHierarchy`, `RunContext`, `InputDriver`/`AppLifecycleDriver`/`DiagnosticsDriver`/`DeviceDriver` protocols, `Registry[T]` | S | — |
| M1.2 | `FakeDeviceDriver` (in-memory, no device required) satisfying the full protocol | S | M1.1 |
| M1.3 | Scenario Engine: schema, parser, runner — built and unit-tested against `FakeDeviceDriver` | M | M1.2 |
| M1.4 | `AndroidUiautomator2Driver` (uiautomator2 + adbutils) | M | M1.1 |
| M1.5 | Evidence Collector + `Timeline` | M | M1.3, M1.4 |
| M1.6 | Generic Assertion Library: `app_did_not_crash`, `latency_under`, `screenshot_captured` | S | M1.3 |
| M1.7 | `domains/ime/` plugin bundle (selectors/actions/assertions), validated against a real SmarType debug build | L | M1.4, M1.5, M1.6 |
| M1.8 | Report Generator: JSON renderer first (simplest, most testable), then Markdown, then HTML | M | M1.5 |
| M1.9 | CLI (`smartype-test run`) | S | M1.7, M1.8 |

**Dependency notes:** M1.3 is built and fully unit-tested against `FakeDeviceDriver` before
`AndroidUiautomator2Driver` exists — this keeps the fast unit-test suite decoupled from device
availability from day one. M1.4 and M1.3 can proceed in parallel once M1.1 is done. M1.7 is the
milestone that actually proves the platform is useful for SmarType — it requires a real device/
emulator and a debug APK.

**Testing strategy:**
- **Unit tests** (no device): schema validation, parser edge cases (missing fields, bad variable
  refs, malformed `covers` patterns), runner retry/backoff logic, registry register/get/list — all
  against `FakeDeviceDriver`. Runs on every commit, no emulator dependency.
- **Contract tests**: one shared test suite (`test_driver_contract.py`) run against both
  `FakeDeviceDriver` and `AndroidUiautomator2Driver`, the latter behind an `@requires_device`
  marker (skipped unless a device/emulator is attached). Guarantees the real driver satisfies the
  protocol's actual semantics, not just its type signature.
- **Integration tests**: a small set of real `domains/ime` scenarios run against a debug SmarType
  build on one emulator API level in CI. Deliberately minimal matrix for v1 — expand only if a
  specific API-level bug motivates it.
- **Golden-file tests** for Report Generator: a fixed `Timeline` fixture rendered to MD/HTML/JSON
  and diffed against committed golden files — catches template regressions without a live run.

**Exit criteria:** `smartype-test run scenarios/ai_suggestions/typo_correction.yaml` passes
end-to-end against a real SmarType debug build on an emulator, produces a Timeline and all three
report formats, and the full unit + contract test suite is green in CI.

## Phase 2 — Verification Intelligence

Goal: LLM-backed verification for genuinely subjective checks, memory/CPU profiling, and
deterministic regression scenario selection.

| # | Milestone | Size | Depends on |
|---|---|---|---|
| M2.1 | `LlmProvider` protocol + Claude implementation (vision-capable) | S | Phase 1 |
| M2.2 | Screenshot / hierarchy / log analyzers | M | M2.1 |
| M2.3 | LLM-backed assertions wired into `domains/ime` (e.g. "suggestion visually plausible") | M | M2.2 |
| M2.4 | Performance Engine: `PerformanceCollector` protocol, `DumpsysMemCollector`, `DumpsysCpuCollector` | M | Phase 1 |
| M2.5 | Regression Planner: `covers`-tag matching against a diff's changed files, fallback smoke set | S | Phase 1 (needs `covers` in schema, already added M1.3) |

**Dependency notes:** M2.4 and M2.5 have no dependency on the LLM work and can proceed in
parallel with M2.1–M2.3. M2.5's usefulness scales with the size of the scenario corpus — worth
prioritizing once Phase 1 has produced a reasonable set of `domains/ime` scenarios.

**Testing strategy:**
- **Unit tests for analyzers**: fixture screenshots + mocked `LlmProvider` responses —
  deterministic, no live API calls on every PR (cost control).
- **Live LLM test suite**: a small set of tests gated behind an API-key environment variable, run
  manually or nightly — not on every PR.
- **Regression Planner**: unit tests with synthetic changed-file lists asserting expected scenario
  subsets; a property test asserting the fallback smoke set is never empty when nothing matches
  (fail-safe, not fail-silent).
- **Performance collectors**: contract tests against `FakeDeviceDriver` returning canned
  `dumpsys` output for CI; real-device validation run manually/nightly.

**Exit criteria:** an LLM-backed assertion catches a deliberately introduced visual regression
that a deterministic assertion would miss; `plan_regression` on a synthetic diff selects the
expected minimal scenario subset; memory/CPU are captured and asserted on in at least one scenario.

## Phase 3 — Agent Interface

Goal: any MCP-compatible coding agent can drive the platform end-to-end.

| # | Milestone | Size | Depends on |
|---|---|---|---|
| M3.1 | Session model: `start_session`/`end_session`, explicit `session_id` threaded through all calls | S | Phase 1 |
| M3.2 | Introspection tools: `list_scenarios`, `describe_scenario`, `list_capabilities`, `list_devices` | S | M3.1 |
| M3.3 | MCP server wrapping the proven CLI core: `run_scenario`, `verify_*`, `collect_evidence`, `analyze_failure`, `plan_regression` | M | M3.1, M3.2, Phase 2 |
| M3.4 | End-to-end validation: drive real SmarType scenarios from Claude Code | M | M3.3 |

**Testing strategy:**
- MCP tool schema tests: valid JSON schema per tool, round-trip serialization of results.
- Scripted "agent simulation" tests: a harness calls tools in sequence (`start_session` →
  `run_scenario` → `analyze_failure` → `end_session`) and asserts on structured results — the
  primary regression suite for the agent-facing contract.
- Manual dogfood: Claude Code actually drives a real session against a SmarType debug build before
  Phase 3 is considered done — required exit criterion, not optional polish.

**Exit criteria:** from a live Claude Code session, an agent can call `list_scenarios`, run one,
get a failure, call `analyze_failure`, and receive a coherent explanation — without any
out-of-band documentation beyond the tool schemas themselves.

## Phase 4 — Advanced / Exploratory (optional)

Not scoped in detail now, per architecture §15 — designing these in depth before Phase 1–3 exist
would be speculative. When picked up:

- Exploration Mode (scoped as a scenario generator, not a parallel execution model — architecture §3.5)
- Timeline → scenario compiler (record & playback)
- iOS driver (`IosAppiumDriver`)
- FPS/battery profiling — only if a concrete need is identified first

Testing strategy for these will be defined at the point each is actually scoped.

## Cross-Phase Concerns

- **CI**: Phase 1 unit/contract tests run on every PR; device-dependent integration tests run on
  an emulator in CI (single API level for v1). Live-LLM tests (Phase 2+) run nightly/manually only.
- **Versioning**: the platform is versioned independently of the SmarType app (ADR-0001). Scenario
  files reference an APK path/build as an input, not a pinned dependency — no submodule coupling
  to the `smartype` repo.
- **Freeze discipline**: architecture.md is frozen (v1.0). If implementation surfaces a genuine
  flaw (not just an equally-valid alternative), update the architecture doc and add a new ADR
  documenting the change and why — don't silently drift.
