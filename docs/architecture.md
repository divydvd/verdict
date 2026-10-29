# SmarType Agentic Mobile Testing Platform — Architecture v1.0 (Frozen)

**Status:** Frozen. This document defines Architecture v1.0. Implementation should follow it.
Modify only when implementation uncovers a genuine architectural flaw — not because an
alternative design would also work.

**Repo:** standalone, single repository (e.g. `verdict`), separate from `smartype/`.
Naming is not architecturally significant and can change without invalidating this document.

**Changelog:**
- v0.1 (draft) — initial module sketch, single flat `DeviceDriver`, no planning/plugin/performance
  discussion.
- v1.0 (this document) — Principal Engineer review completed (§3); driver interface decomposed;
  plugin architecture, performance engine, domain module, regression planner, and richer agent
  API added; explicit Out of Scope list; ADRs added.

---

## 1. Vision & Scope

An AI-driven testing platform that executes end-to-end mobile scenarios, collects evidence,
verifies behaviour (including via an LLM that inspects screenshots/UI hierarchy/logs), and
produces reports — exposed through a typed interface that an AI coding agent (Claude Code,
Codex, Gemini CLI, or a human via CLI) can drive directly.

Android first. Only the Device Driver layer is platform-specific; everything above it is
platform-agnostic by construction (see §10).

**Is this "agentic" or "a sophisticated automation framework"?** Both, deliberately. §3.1
explains why we reject building an autonomous test-strategy planner *inside* the framework —
that is the calling agent's job. What makes this platform agentic is: (a) LLM-backed judgment
where deterministic checks aren't sufficient, (b) a rich, introspectable, agent-callable
interface (§9) that lets an external agent compose novel test strategies at runtime instead of
only running canned end-to-end scripts, and (c) an explicit (deferred) path to autonomous UI
exploration (§3.5). It is intentionally *not* a black box that decides on its own what SmarType
features need testing.

**Non-goals:** we are not building a new UI automation protocol, a new device-control transport,
a new CI system, or a general-purpose reasoning engine. Those are solved problems (or solved by
the calling agent). Our value-add is IME-aware assertions/domain knowledge, evidence packaging,
LLM-based verification, and an agent-callable interface.

## 2. Architectural Principles

These principles are the load-bearing rationale behind every decision in this document; when in
doubt during implementation, defer to these over local convenience.

1. **Planning is external.** The platform executes and verifies. Deciding *what* to test is the
   calling agent's responsibility, informed by the platform's introspection APIs. See ADR-0006.
2. **Deterministic first, LLM supplemental.** Every core behavior has a deterministic assertion.
   LLM verification is used for genuinely subjective/visual judgment or to explain a deterministic
   failure — never as the sole arbiter of core pass/fail. See ADR-0004.
3. **Only the driver boundary is platform-specific.** Scenario Engine, Assertions, Evidence,
   Reporting, LLM layer, and Agent Interface are platform-agnostic. See ADR-0005, ADR-0007.
4. **Everything extensible is a plugin behind a `Protocol` + registry**, not an if/else ladder.
   See §7.
5. **Small core, optional extensions.** Phase 1 ships the minimum that makes SmarType testing
   genuinely useful. Advanced capabilities are explicitly deferred or rejected until a real need
   is demonstrated (§15) — not spec'd in detail speculatively.
6. **Reproducibility over cleverness.** Every run produces a replayable, inspectable Timeline
   (§6.4). Understanding why a run passed or failed should never require re-running it.

## 3. Critical Design Review (v0.1 → v1.0)

This section documents the review that produced this version. Each item: why the prior approach
was insufficient, what problem the proposal solves, the tradeoffs, and phase placement.

### 3.1 Planning Layer — **Rejected as an in-framework subsystem; partially accepted as introspection APIs**

- **Why v0.1 was insufficient:** it only executes predefined scenarios; nothing determines *what*
  should be tested. Taken literally, "planning engine" would mean building an AI that reasons over
  the SmarType codebase to invent test coverage.
- **Problem with building it in-framework:** this duplicates exactly what an AI coding agent with
  repo access (Claude Code, Codex, Gemini CLI) already does well. Building a second, weaker
  planning brain inside the testing tool adds substantial complexity, cost, and non-determinism
  for a capability we already have externally.
- **What we do instead:** the framework exposes read-only **introspection APIs**
  (`list_scenarios`, `describe_scenario`, `list_capabilities`, §9) so an external agent can
  discover what's testable and compose a plan by calling `run_scenario`/`verify_*` in whatever
  sequence its own reasoning determines. Planning and execution are cleanly separated by being in
  different processes/actors entirely — the agent plans, the framework executes and verifies.
- **Tradeoffs:** the framework cannot "decide to go test something" unsupervised; it requires an
  orchestrating agent or CI trigger. Acceptable — it was never meant to run fully unattended
  without a driver.
- **Phase:** introspection APIs ship in Phase 3 (Agent Interface). No in-framework planner, ever
  (see §15).

### 3.2 Regression Planner — **Accepted, deterministic only**

- **Why v0.1 was insufficient:** no mechanism to avoid running the full suite on every change.
- **Problem solved:** minimum-necessary scenario selection from a code diff.
- **Design:** deterministic, not inferred. Each scenario declares a `covers` field (glob
  patterns/feature tags). The planner matches changed file paths against `covers` across all
  scenarios and returns the union. A documented fallback smoke-tag set runs when no scenario
  matches, so under-tagging fails safe (over-testing) rather than silently skipping coverage. See
  ADR-0008 for why this is tag-based rather than ML/embedding-based.
- **Tradeoffs:** requires scenario authors to keep `covers` accurate; won't catch relatedness a
  human might infer (e.g. a shared-utility refactor) unless tagged. Explicitly accepted — a
  deterministic, auditable answer to "why did this scenario run" is worth more than a smarter but
  opaque one at this stage.
- **Phase:** 2 (needs a meaningful scenario corpus to be worth selecting among).

### 3.3 Plugin Architecture — **Accepted, formalized as a first-class pattern from Phase 1**

- **Why v0.1 was insufficient:** only `DeviceDriver` was designed as a swappable interface;
  Assertions/Reports/LLM providers/Evidence collectors were implicitly hardcoded modules.
- **Problem solved:** consistent extensibility for every "future extension" the requirements list
  (drivers, assertions, reports, LLM providers, evidence collectors, performance analyzers)
  without bespoke wiring per capability.
- **Design:** every extensible capability is a `Protocol` + a `Registry[T]` (register/get/list).
  Built-ins self-register at import time; external plugins register via Python
  `importlib.metadata.entry_points` — no custom plugin-loading protocol invented. See §7.
- **Tradeoffs:** more ceremony than a hardcoded module for a single Android implementation, but
  the pattern is cheap (a registry is ~20 lines) and pays for itself the moment a second
  implementation of any capability exists (which happens as early as Phase 2's second `LlmProvider`).
- **What we explicitly reject:** a plugin marketplace, versioned plugin manifests, or sandboxing —
  none of that is warranted at this scale (§15).
- **Phase:** 1 (the pattern itself — registries + protocols). Concrete plugins beyond what Android
  Phase 1 needs are added only when needed.

### 3.4 Performance Engine — **Partially accepted; scope narrowed sharply**

- **Why v0.1 was insufficient:** performance was implicitly "just another assertion"
  (`latency_under(ms)`). That's actually fine for point-in-time latencies (startup, suggestion,
  typing) because they're derivable from timestamps already in the Timeline — no new subsystem
  needed. It is **not** fine for memory/CPU/battery/FPS, which require continuous background
  sampling that starts before and stops after a scenario, producing a time-series — a
  fundamentally different shape than a post-step boolean check.
- **Problem solved:** a narrow `PerformanceEngine`/`PerformanceCollector` plugin abstraction
  (`start_profiling(metrics) -> ProfilingSession`, `stop_profiling(session) -> PerformanceReport`)
  that assertions then read from, keeping "is this a pass" decisions in the Assertion Library and
  "how do we gather this data" in a dedicated, pluggable collector.
- **Tradeoffs / explicit scope cut:** memory and CPU (via `adb shell dumpsys meminfo`/`top`) are
  cheap and directly relevant to an IME running inside every app's process — in scope. **FPS and
  battery are explicitly rejected for v1**: FPS instrumentation (Perfetto/systrace) and battery
  measurement (requires controlled charging/lab conditions) are high-effort, low-relevance for a
  keyboard app, and easy to get wrong in ways that produce noisy, untrustworthy data. Revisit only
  if a concrete bug or user complaint motivates it (§15).
- **Phase:** startup/suggestion/typing latency — Phase 1, as ordinary assertions (no new
  subsystem). Memory/CPU `PerformanceEngine` — Phase 2. FPS/battery — rejected/deferred indefinitely.

### 3.5 Exploration Mode — **Accepted direction, scoped as a scenario *generator*, deferred to Phase 4**

- **Why v0.1 was insufficient:** it can only replay what a human already wrote as YAML; it can't
  discover untested paths or novel crashes.
- **Problem solved:** autonomous UI discovery (LLM looks at screenshot + hierarchy, decides next
  action, loops with bounds) can surface issues no one thought to script.
- **Why not build it now:** this is a genuinely hard, research-adjacent feature (state dedup,
  loop/safety bounds, cost control on LLM calls per step, flaky/non-reproducible by nature). Doing
  it half-well produces an expensive, unreliable feature that erodes trust in the platform.
- **Key design constraint (accepted now, to avoid a future parallel execution paradigm):**
  exploration's output must be a normal scenario YAML (with `covers`/`tags`), not a second
  execution model. An explored path that finds something interesting gets "frozen" into a
  regular, deterministic, replayable scenario — the YAML format stays the single source of truth
  for regression testing. This pairs naturally with the Timeline→scenario compiler (§3.6).
- **Phase:** 4 (optional; may never be built if Phase 1–3 scenario authoring proves sufficient).

### 3.6 Device Pool — **Accepted, but scoped to "enable concurrency," not "build a scheduler"**

- **Why v0.1 was insufficient:** implicitly single-device (MCP server held one "current session").
- **Problem solved:** running scenarios across multiple devices/emulators concurrently for CI speed.
- **Key realization:** because `DeviceDriver` was never designed as a process-wide singleton (each
  session gets its own driver instance bound to a device serial), multi-device concurrency is
  already a natural consequence of the existing design — running N sessions in parallel, each with
  its own driver instance, requires no new subsystem.
- **What we reject:** a bespoke distributed job queue/scheduler. That problem is already solved by
  CI systems (GitHub Actions matrix builds, `pytest-xdist`) and by an orchestrating agent simply
  calling `run_scenario(session_id=...)` against multiple sessions from `list_devices()`. Building
  our own scheduler would duplicate infrastructure every CI system already provides.
- **Phase:** `list_devices()` + explicit `session_id` (enabling external parallelism) — Phase 3.
  No custom scheduler, ever (§15).

### 3.7 Timeline / Session Recorder — **Accepted as a formalization of the existing Evidence Collector output, not a new subsystem**

- **Why v0.1 was insufficient:** "RunManifest" was described loosely as a JSON blob correlating
  artifacts; "replayable timeline" implies an ordered, structured, chronologically-walkable record.
- **Problem solved:** precise data model (`Timeline` = ordered list of `TimelineEvent{timestamp,
  step_id, action, evidence_refs, assertion_results}`) that Report Generator, LLM layer, and (later)
  a scenario-compiler can all consume consistently. This is a schema-precision fix on work already
  planned for Phase 1, not new scope.
- **Tradeoffs:** none material — renaming/tightening a data structure we were building anyway.
  Literal record-and-playback (regenerating a scenario YAML from an ad hoc Timeline) is a genuinely
  new capability and is deferred alongside Exploration Mode (§3.5), since they share the same use case.
- **Phase:** Timeline formalization — Phase 1. Timeline→scenario compiler — Phase 4.

### 3.8 SmarType-specific intelligence (IME domain module) — **Accepted, restructures Phase 1 layout**

- **Why v0.1 was insufficient:** IME-specific knowledge (autocorrect, AI suggestions, clipboard
  suggestions, language switching, gesture typing, themes) was scattered across generic-looking
  `assertions/keyboard.py`, `assertions/suggestions.py`, etc., indistinguishable from
  platform-generic assertions like `app_did_not_crash`.
- **Problem solved:** a dedicated `domains/ime/` package groups IME-specific Selectors (known
  resource-ids/content-descriptions for SmarType's suggestion strip, AI overlay, clipboard chip,
  language-switch key), Actions (`trigger_autocorrect`, `select_suggestion`, `swipe_type`), and
  Assertions (`autocorrect_applied`, `suggestion_contains`, `clipboard_suggestion_shown`,
  `theme_matches`, `language_switched`) — separated from truly generic, reusable assertions
  (`app_did_not_crash`, `latency_under`, `screenshot_captured`) that stay in `assertions/`.
- **Tradeoffs:** none — this is free organizational value; these are exactly the assertions Phase 1
  needs anyway, just grouped coherently. It also sets the precedent that a "domain" is itself a
  plugin bundle (selectors + actions + assertions), consistent with §7.
- **Phase:** 1 — this is not additional scope, it's better organization of existing Phase 1 scope.

### 3.9 Long-term extensibility (Android/iOS/Desktop/Web) — **Driver interface decomposed; no new drivers built**

- **Why v0.1 was insufficient:** the single flat `DeviceDriver` protocol mixed universal input
  primitives (`tap`, `type_text`, `screenshot`) with mobile-app-lifecycle methods (`install_apk`,
  `uninstall`, `clear_data`) and Android-specific diagnostics (`collect_logcat`). A Web driver has
  no "APK to install" — there's no clean way to implement that interface without fake/no-op methods.
- **Problem solved:** decompose into `InputDriver` (tap/swipe/scroll/type/press_key/screenshot/
  dump_hierarchy/wait_for — truly universal across mobile/desktop/web, though selector semantics
  differ), `AppLifecycleDriver` (install/uninstall/launch/clear_data — mobile-app-specific; a Web
  driver would instead implement a `WebLifecycleDriver` with `navigate(url)`/`clear_cookies()`),
  and `DiagnosticsDriver` (logs/recording/bugreport — semantics adapt per platform, e.g. logcat vs.
  browser console). `DeviceDriver = InputDriver & AppLifecycleDriver & DiagnosticsDriver` for the
  mobile case; Android's implementation satisfies the composition.
- **Tradeoffs:** three protocols instead of one, for a Phase 1 that only ships one implementation
  anyway. Accepted because retrofitting this decomposition later (after Scenario Engine/Assertions
  are written against a flat interface) would be a breaking change touching every layer above the
  driver — cheap to design correctly now, expensive to fix later.
- **What we explicitly do NOT do:** implement Web or Desktop drivers. This section is a design
  accommodation, not new build scope (§15).
- **Phase:** 1 (the protocol decomposition itself, even though only `AndroidUiautomator2Driver`
  ships). iOS driver — Phase 4. Web/Desktop drivers — indefinitely deferred.

### 3.10 Agent Experience — **APIs expanded: introspection + explicit sessions**

- **Why v0.1 was insufficient:** no discoverability (an agent calling cold has no way to know what
  scenarios/assertions/capabilities exist without out-of-band docs); "current session" was
  implicit process state, which breaks the moment two sessions are wanted (multi-device, §3.6) or
  two agent calls interleave.
- **Problem solved:** explicit `session_id` threaded through every tool call (`start_session` /
  `end_session`, returned/passed on every subsequent call), plus introspection tools
  (`list_scenarios`, `describe_scenario`, `list_capabilities`, `list_devices`). See §9 for the full
  surface.
- **What we explicitly reject adding:** a rigid machine-readable failure/reason-code taxonomy on
  `VerificationResult` (free-text `message` + structured `evidence_refs` is sufficient for an LLM
  consumer — premature schema ossification is a real cost, not a hypothetical one); and an
  in-framework permission/confirmation layer for destructive actions (`install_apk`,
  `clear_data`) — the MCP host (Claude Code's own tool-approval flow) already solves this, and
  duplicating it inside the platform is redundant.
- **Phase:** 3 (Agent Interface), but the *design* (explicit session_id, introspection tools) is
  frozen now so Phase 1/2 internals don't need to be reshaped to accommodate it later.

## 4. Reuse vs. Build — Decision Matrix

| Concern | Decision | Tool | Why |
|---|---|---|---|
| Low-level device control (tap/swipe/type/dump hierarchy/wait) | **Reuse** | [`uiautomator2`](https://github.com/openatx/uiautomator2) (Python) | Mature, widely used, wraps ADB + an on-device automation HTTP server. See ADR-0002. |
| Install/uninstall, logcat, screenrecord, bugreport, raw shell | **Reuse** | `adb` via `adbutils` | OS-level primitives with no IME-specific behaviour. |
| Declarative flow format for simple, non-IME-specific smoke flows | **Reuse (optional adapter)** | Maestro | `MaestroAdapter` implements a subset of `AppLifecycleDriver`-adjacent flow-running for teams with existing Maestro flows. Not the primary engine — no concept of IME-specific assertions. Deferred, not on the Phase 1 critical path. |
| Cross-platform driver for iOS | **Reuse (Phase 4)** | Appium (XCUITest driver) | De facto standard for iOS. Not adopted for Android v1 — see ADR-0002. |
| Visual diffing / image assertions | **Reuse** | OpenCV (`opencv-python`) | Template matching, pixel-diff, and pre-cropping regions before sending to the LLM. |
| Emulator lifecycle | **Reuse** | Android Emulator console / `avdmanager` / `emulator -avd` | Standard tooling. |
| Scenario DSL, IME domain module, Assertion Library, Evidence Collector/Timeline, Report Generator, Regression Planner, Performance Engine (mem/cpu), LLM Verification Layer, Agent Interface, Plugin Registry | **Build** | — | SmarType/IME-specific domain knowledge and agent-facing contracts that don't exist anywhere else — the platform's actual value-add. |

## 5. High-Level Architecture

```
                         ┌───────────────────────────────────────────┐
                         │        External Planning Agent             │
                         │   (Claude Code / Codex / Gemini CLI /      │
                         │    CI trigger — decides WHAT to test)       │
                         └───────────────────┬───────────────────────┘
                                             │ MCP tool calls
                                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     Agent Interface (MCP server + CLI)                    │
│  start_session · list_scenarios · describe_scenario · list_capabilities · │
│  run_scenario · verify_keyboard · verify_suggestions · verify_theme ·     │
│  verify_clipboard · collect_evidence · analyze_failure · plan_regression  │
│  · list_devices · end_session                                            │
└───────┬───────────────────────┬───────────────────────┬──────────────────┘
       │                       │                       │
       ▼                       ▼                       ▼
┌────────────────┐   ┌─────────────────────┐   ┌───────────────────────┐
│ Scenario Engine  │   │ Regression Planner    │   │ LLM Verification Layer │
│ parser/runner,    │   │ covers-tag matching   │   │ (pluggable LlmProvider)│
│ variables, retry  │   │ against changed files │   │ screenshot/hierarchy/  │
└────────┬─────────┘   └───────────┬────────────┘   │ log analysis, failure  │
        │                          │ selects        │ explanation            │
        │                          ▼                └───────────┬─────────────┘
        │              ┌─────────────────────┐                 │ (assertions escalate
        │              │  Scenario Catalog      │                 │  ambiguous checks)
        │              │  (covers/tags index)   │                 │
        │              └─────────────────────┘                 │
        ▼                                                       │
┌──────────────────────────────┐                               │
│   Assertion Library (generic)  │◄──────────────────────────────┘
│   crash · latency · screenshot │
├──────────────────────────────┤
│   domains/ime (IME-specific)   │   ← selectors + actions + assertions
│   autocorrect · suggestions ·  │      bundled as a plugin package (§7)
│   clipboard · theme · language │
└───────────────┬───────────────┘
                │
                ▼
┌──────────────────────────────┐        ┌───────────────────────────────┐
│         Device Driver           │        │   Evidence Collector + Timeline  │
│  InputDriver ⋂ AppLifecycleDriver│───────►│  ordered TimelineEvents,          │
│  ⋂ DiagnosticsDriver (§10)       │        │  screenshots/video/logs/hierarchy │
│  Android impl: uiautomator2/adb  │        └───────────────┬───────────────────┘
│  (+ optional MaestroAdapter,     │                        │
│   future IosAppiumDriver)        │                        ▼
└──────────────────────────────┘        ┌───────────────────────────────┐
                                          │       Performance Engine          │
                                          │  (Phase 2, mem/cpu collectors,    │
                                          │   plugin, feeds latency/perf       │
                                          │   assertions)                     │
                                          └───────────────────────────────┘
                                                          │
                                                          ▼
                                          ┌───────────────────────────────┐
                                          │        Report Generator           │
                                          │   Markdown / HTML / JSON +        │
                                          │   failed-step analysis            │
                                          └───────────────────────────────┘

     All capabilities in dashed boxes below are registered via the Plugin
     Registry (§7): Device Drivers, Assertions, Report renderers, LLM
     providers, Evidence collectors, Performance collectors.
```

Orchestration (Scenario Engine, Regression Planner, Assertion Library, domains/ime, Evidence
Collector, Performance Engine, Report Generator, LLM Verification Layer, Agent Interface) is
entirely platform-agnostic. The **only** place that knows about Android vs. iOS/Web/Desktop is
the Device Driver implementation (§10).

## 6. Module Responsibilities & Interfaces

### 6.1 Device Driver (`device_driver/`)

Decomposed into composable protocols (see §3.9, §10 for rationale):

```python
class InputDriver(Protocol):
    def tap(self, x: int, y: int) -> None: ...
    def tap_selector(self, selector: Selector) -> None: ...
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None: ...
    def scroll(self, direction: Direction, selector: Selector | None = None) -> None: ...
    def type_text(self, text: str) -> None: ...                # may paste; not key events
    def type_keys(self, text: str, interval_ms: int = 150) -> None: ...  # one key input per char
    def press_key(self, key: KeyEvent | int | str) -> None: ...  # BACK, HOME, ... or any key code
    def screenshot(self) -> Path: ...
    def dump_hierarchy(self) -> UiHierarchy: ...
    def wait_for(self, selector: Selector, timeout_ms: int) -> bool: ...

class AppLifecycleDriver(Protocol):
    def install(self, path: str) -> None: ...
    def uninstall(self, package: str) -> None: ...
    def launch(self, package: str, activity: str | None = None) -> None: ...
    def clear_data(self, package: str) -> None: ...

class DiagnosticsDriver(Protocol):
    def collect_logs(self, since: datetime | None = None) -> Path: ...
    def start_recording(self) -> RecordingHandle: ...
    def stop_recording(self, handle: RecordingHandle) -> Path: ...
    def collect_bugreport(self) -> Path | None: ...          # optional capability

class DeviceDriver(InputDriver, AppLifecycleDriver, DiagnosticsDriver, Protocol):
    platform: Platform    # ANDROID | IOS | DESKTOP | WEB (reserved)
```

- `AndroidUiautomator2Driver` — Phase 1, wraps `uiautomator2` + `adbutils`, satisfies the full
  composition.
- `MaestroAdapter` — optional, implements a `run_flow(path) -> FlowResult` capability consumed by
  a `maestro_flow` scenario step type. Deferred past Phase 1.
- `IosAppiumDriver` — Phase 4, via Appium's XCUITest driver.
- A hypothetical `WebPlaywrightDriver` (not built) would implement `InputDriver` +
  `DiagnosticsDriver` (console logs) + a `WebLifecycleDriver` (`navigate`/`clear_cookies`) instead
  of `AppLifecycleDriver` — illustrating why the decomposition matters even though nothing beyond
  Android ships now.

### 6.2 Scenario Engine (`scenario_engine/`)

- `schema.py` — Pydantic models for the scenario spec: steps, variables, retries, waits,
  assertions, `covers` (glob patterns/feature tags for the Regression Planner), `tags` (for
  `list_scenarios` filtering).
- `parser.py` — loads + validates a scenario file, resolves `${var}` substitution.
- `runner.py` — executes steps against a `DeviceDriver`, handles retry/backoff and wait
  conditions, invokes assertions, writes `TimelineEvent`s to the Evidence Collector. A failed
  `assert` step is re-checked after a short settle (`settle_ms`, `settle_attempts`), because the
  hierarchy can lag a fast UI transition; the message records the re-checks.
- `actions/` — built-in reusable step types (`tap`, `type_text`, `type_keys`, `swipe`, `wait_for`,
  `ensure_checked`, `maestro_flow`) — IME-specific actions live in `domains/ime/actions.py`, not here.
- `ensure_checked` sets a switch or a check box to a known state:

  ```yaml
  - action: ensure_checked
    selector: {text: "Auto-correct"}
    checked: true
  ```

  The runner reads the `checked` attribute of the matched node, or of its nearest checkable
  ancestor (a Compose `Modifier.toggleable` row holds the title text as a child). It taps only
  when the state differs, then reads the state again with the `settle_ms` re-checks. After the
  tap, a missing node is read again in the same re-checks, because the screen can redraw. The
  step fails when the state does not change, or when no matched node or ancestor is checkable.

### 6.3 Assertion Library (`assertions/`) + `domains/ime/`

Common interface:

```python
class Assertion(Protocol):
    name: str
    def check(self, ctx: RunContext) -> AssertionResult: ...

AssertionResult(passed: bool, message: str, evidence_refs: list[EvidenceRef])
```

- `assertions/` — generic, platform/domain-agnostic: `app_did_not_crash` (logcat crash-signature
  scan), `latency_under(ms)`, `screenshot_captured`.
- `domains/ime/` — SmarType/IME-specific bundle (selectors + actions + assertions together, as a
  self-contained plugin package, see §3.8, §7): `keyboard_visible`, `ai_suggestion_visible`,
  `text_inserted`, `clipboard_updated`, `autocorrect_applied`, `suggestion_contains`,
  `clipboard_suggestion_shown`, `theme_matches`, `language_switched`.

Assertions that are inherently visual/ambiguous (e.g. "suggestion visible and legible") delegate
to the LLM Verification Layer rather than hardcoding brittle pixel/XPath checks — but always as a
supplement to, never a replacement for, a deterministic existence/state check (ADR-0004).

### 6.4 Evidence Collector & Timeline (`evidence/`)

An active orchestrator (not a passive folder) called by the Scenario Engine at step boundaries
and on failure. Produces a `Timeline` — an ordered, structured record:

```python
class TimelineEvent(BaseModel):
    timestamp: datetime
    step_id: str
    action: str
    evidence_refs: list[EvidenceRef]
    assertion_results: list[AssertionResult]

class Timeline(BaseModel):
    run_id: str
    scenario_name: str
    events: list[TimelineEvent]
```

The Timeline is the single artifact Report Generator, LLM layer, and (Phase 4) a
Timeline→scenario compiler all consume. Correlates every artifact (screenshot, video segment,
logcat slice, hierarchy dump, bugreport) with a step id and timestamp.

### 6.5 Performance Engine (`performance/`) — Phase 2

```python
class PerformanceCollector(Protocol):
    name: str
    def start(self, metrics: list[MetricType]) -> ProfilingSession: ...
    def stop(self, session: ProfilingSession) -> PerformanceReport: ...

class MetricType(Enum):
    STARTUP_LATENCY = "startup_latency"       # derived from Timeline timestamps, no collector needed
    SUGGESTION_LATENCY = "suggestion_latency"  # derived from Timeline timestamps, no collector needed
    TYPING_LATENCY = "typing_latency"          # derived from Timeline timestamps, no collector needed
    MEMORY = "memory"                          # DumpsysMemCollector, Phase 2
    CPU = "cpu"                                # DumpsysCpuCollector, Phase 2
    FPS = "fps"                                # reserved, not implemented — see §15
    BATTERY = "battery"                        # reserved, not implemented — see §15
```

Latency metrics need no dedicated collector — they're read off `TimelineEvent` timestamps by
ordinary assertions. Memory/CPU require continuous sampling across a scenario's lifetime, hence
the dedicated `start`/`stop` session shape. FPS/battery are reserved in the enum (so the design
isn't blocked later) but have no implementation — see §3.4, §15.

### 6.6 Regression Planner (`regression/`) — Phase 2

```python
def select_scenarios(changed_files: list[str], catalog: ScenarioCatalog) -> list[ScenarioRef]: ...
```

Matches `changed_files` against each scenario's `covers` glob patterns. Returns the union, or the
documented fallback smoke-tag set if nothing matches. Purely deterministic — see ADR-0008.

### 6.7 Report Generator (`reporting/`)

Consumes a completed `Timeline` + assertion results (+ optional LLM failure explanations) and
renders Markdown, HTML (Jinja2, embeds screenshots/video links inline), and JSON (for CI
ingestion / further agent processing). Failed-step sections always include: the step definition,
the failed assertion, relevant evidence thumbnails, and — if requested — the LLM's explanation.
Renderers (`MarkdownRenderer`, `HtmlRenderer`, `JsonRenderer`) are plugins (§7).

### 6.8 LLM Verification Layer (`llm_verification/`)

```python
class LlmProvider(Protocol):
    name: str
    def analyze_image(self, image: Path, prompt: str) -> str: ...
    def analyze_text(self, text: str, prompt: str) -> str: ...

class LlmVerifier:
    def verify_screenshot(self, image: Path, expectation: str) -> VerificationResult: ...
    def verify_hierarchy(self, hierarchy: UiHierarchy, expectation: str) -> VerificationResult: ...
    def verify_logs(self, log_excerpt: str, expectation: str) -> VerificationResult: ...
    def explain_failure(self, run: RunContext, failed_step: Step) -> FailureExplanation: ...
```

`LlmProvider` is a plugin (§7); Claude (Anthropic API, vision-capable) is the first
implementation. OpenCV pre-crops screenshots to the relevant region before sending to the LLM —
cheaper and more reliable than asking the model to locate coordinates itself. Called both by
assertions that opt into LLM verification and directly by the Agent Interface (`analyze_failure`).

### 6.9 Agent Interface (`agent_interface/`) — Phase 3

See §9 for the full tool surface and session model.

## 7. Plugin Architecture

Every extensible capability follows the same shape: a `Protocol` defining the capability, and a
`Registry[T]` for registration/lookup.

```python
class Registry(Generic[T]):
    def register(self, name: str, factory: Callable[..., T]) -> None: ...
    def get(self, name: str) -> T: ...
    def list(self) -> list[str]: ...
```

One registry per capability: `driver_registry`, `assertion_registry`, `report_renderer_registry`,
`llm_provider_registry`, `evidence_collector_registry`, `performance_collector_registry`.
Built-ins self-register at import time. External plugins register via a
`verdict.plugins` `importlib.metadata` entry-point group, discovered at startup —
standard Python packaging mechanism, no custom plugin-loading protocol invented.

`domains/ime/` is itself structured as a plugin bundle (a package that registers its Selectors,
Actions, and Assertions on import) — establishing the pattern future domain packages (should the
platform ever generalize beyond SmarType) would follow.

**Explicitly rejected:** a plugin marketplace, versioned/signed plugin manifests, or execution
sandboxing for third-party plugins. At this project's scale, a simple in-process registry is
sufficient; those concerns are for platforms with untrusted third-party plugin ecosystems, which
this is not (§15).

## 8. Multi-Device / Concurrency Model

`DeviceDriver` instances are per-session, never process-wide singletons — a deliberate Phase 1
decision that makes concurrency a consequence of the existing design rather than a new subsystem.

```
Agent
  ├─ start_session(device_id=A) → session_A → run_scenario(session_A, ...)
  ├─ start_session(device_id=B) → session_B → run_scenario(session_B, ...)
  └─ (each session owns its own DeviceDriver instance, RunContext, Timeline)
```

`list_devices()` enumerates connected devices/emulators; the agent (or CI matrix) decides how to
distribute scenarios across them. The framework provides device-targeting, not scheduling — see
§3.6 for why a bespoke scheduler is explicitly rejected.

## 9. Agent Interface & MCP API

Exposed as an MCP server (ADR-0003) plus a thin CLI for humans/CI. Every stateful call takes an
explicit `session_id` — no implicit "current session" (see §3.10).

```python
# Session
start_session(device_id: str | None = None, platform: str = "android") -> SessionHandle
end_session(session_id: str) -> None

# Introspection (read-only, no device required)
list_scenarios(tags: list[str] | None = None) -> list[ScenarioSummary]
describe_scenario(name: str) -> ScenarioDetail
list_capabilities() -> CapabilitiesManifest     # registered drivers/assertions/llm providers/etc.
list_devices() -> list[DeviceSummary]

# Execution
run_scenario(session_id: str, scenario_path: str, variables: dict = {}) -> RunResult
plan_regression(changed_files: list[str]) -> list[ScenarioSummary]     # Phase 2+

# Verification (operate on the session's current app/editor state)
verify_keyboard(session_id: str, expectation: str = "visible") -> VerificationResult
verify_suggestions(session_id: str, expected_contains: list[str] | None = None) -> VerificationResult
verify_theme(session_id: str, expected_theme: str) -> VerificationResult
verify_clipboard(session_id: str, expected_text: str) -> VerificationResult

# Evidence & analysis
collect_evidence(session_id: str, kinds: list[str] = ["screenshot", "hierarchy", "logcat"]) -> EvidenceBundle
analyze_failure(session_id: str, run_id: str, step_id: str) -> FailureExplanation
```

Design choices explained in §3.10: `session_id` is explicit (enables multi-device, avoids
interleaving bugs); introspection tools require no device connection (an agent can plan before
allocating a device); `VerificationResult` stays free-text + evidence-refs rather than a rigid
reason-code taxonomy; no in-framework permission layer — destructive calls (`run_scenario` doing
`install`/`clear_data`) rely on the MCP host's own tool-approval flow (e.g. Claude Code's).

## 10. Long-Term Extensibility (Android / iOS / Desktop / Web)

Only `device_driver/` is platform-specific, and as of v1.0 it's decomposed (§3.9, §6.1) so that:

- **Android** (Phase 1): `AndroidUiautomator2Driver` implements `InputDriver & AppLifecycleDriver
  & DiagnosticsDriver` in full.
- **iOS** (Phase 4): `IosAppiumDriver` implements the same composition via Appium's XCUITest
  driver. Scenario specs gain a `platform: android | ios` field; selectors may need per-platform
  variants (the same pattern Appium/Maestro already use).
- **Desktop / Web** (not scheduled, design-only): would implement `InputDriver` +
  `DiagnosticsDriver` plus a platform-appropriate lifecycle protocol (`WebLifecycleDriver` with
  `navigate`/`clear_cookies` instead of `install`/`uninstall`) — accommodated by the decomposition
  without forcing fake implementations of mobile-only methods. No code for this ships until there's
  a concrete SmarType desktop/web surface to test.

Everything above the driver layer (Scenario Engine, Regression Planner, Assertion Library,
Evidence/Timeline, Performance Engine, Report Generator, LLM layer, Agent Interface) is unchanged
by any of the above.

## 11. Directory Structure

```
verdict/
├── pyproject.toml
├── src/verdict/
│   ├── device_driver/
│   │   ├── base.py                  # InputDriver, AppLifecycleDriver, DiagnosticsDriver, DeviceDriver
│   │   ├── android_uiautomator2.py
│   │   ├── android_adb.py
│   │   ├── maestro_adapter.py       # optional, deferred
│   │   └── ios_appium.py            # phase 4
│   ├── scenario_engine/
│   │   ├── schema.py                # includes `covers`, `tags`
│   │   ├── parser.py
│   │   ├── runner.py
│   │   └── actions/
│   ├── assertions/                  # generic only
│   │   ├── base.py
│   │   ├── stability.py             # app_did_not_crash
│   │   ├── latency.py               # latency_under
│   │   └── visual.py                # screenshot_captured
│   ├── domains/
│   │   └── ime/                     # SmarType-specific plugin bundle
│   │       ├── selectors.py
│   │       ├── actions.py
│   │       └── assertions.py        # keyboard/suggestions/clipboard/theme/language
│   ├── evidence/
│   │   ├── collector.py
│   │   ├── timeline.py              # TimelineEvent, Timeline
│   │   └── store.py
│   ├── performance/                 # phase 2
│   │   ├── base.py                  # PerformanceCollector, MetricType
│   │   └── android_dumpsys.py
│   ├── regression/                  # phase 2
│   │   └── planner.py
│   ├── reporting/
│   │   ├── generator.py
│   │   ├── renderers/                # markdown.py, html.py, json.py — each a plugin
│   │   └── templates/
│   ├── llm_verification/
│   │   ├── base.py                  # LlmProvider protocol
│   │   ├── claude_provider.py
│   │   ├── screenshot_analyzer.py
│   │   ├── hierarchy_analyzer.py
│   │   ├── log_analyzer.py
│   │   └── failure_explainer.py
│   ├── agent_interface/             # phase 3
│   │   ├── mcp_server.py
│   │   └── cli.py
│   ├── plugins/
│   │   └── registry.py              # Registry[T], all capability registries
│   └── core/
│       ├── config.py
│       ├── session.py
│       └── exceptions.py
├── scenarios/                        # reference SmarType scenarios
│   ├── keyboard/
│   ├── ai_suggestions/
│   └── clipboard/
├── tests/
└── docs/
    ├── architecture.md
    ├── implementation-plan.md
    └── adr/
```

## 12. Example Scenario

```yaml
name: ai_suggestion_appears_after_typo
covers:
  - "app/src/main/kotlin/bha/keys/smartype/ime/nlp/**"
  - "app/src/main/kotlin/bha/keys/smartype/ime/nlp/ai/**"
tags: [smoke, ai_suggestions]
variables:
  target_app: bha.keys.smartype.debug
steps:
  - action: install
    path: ${apk_path}
  - action: launch
    package: ${target_app}
  - action: tap
    selector: { resource_id: "text_field" }
  - action: type_text
    text: "I recieve"
  - action: wait_for
    selector: { description: "ai_suggestion_chip" }
    timeout_ms: 2000
  - action: assert
    assertion: ai_suggestion_visible
  - action: assert
    assertion: latency_under
    args: { ms: 500 }
retries:
  max_attempts: 2
  backoff_ms: 500
evidence:
  on_failure: [screenshot, hierarchy, logcat]
  always: [screenshot]
```

## 13. Data Flow (single scenario run)

1. Agent calls `start_session(device_id)` → gets `session_id`.
2. Agent calls `run_scenario(session_id, path)`.
3. Scenario Engine parses + validates YAML, opens a `RunContext` bound to the session's
   `DeviceDriver`, starts a `Timeline`.
4. Runner executes steps; each step appends a `TimelineEvent` (with a lightweight screenshot).
5. Assertions run inline (generic + `domains/ime`); failures capture full evidence (hierarchy,
   logcat, bugreport) and, if LLM-backed, call `LlmVerifier`.
6. On completion, Report Generator renders MD/HTML/JSON from the `Timeline` + assertion results.
7. Agent may call `analyze_failure(session_id, run_id, step_id)` for a root-cause explanation, or
   `collect_evidence` mid-run.
8. Agent calls `end_session(session_id)` when done.

## 14. Architecture Decisions

Full rationale for each is in `docs/adr/`. Index:

- [ADR-0001](adr/0001-standalone-repository.md) — Standalone repository
- [ADR-0002](adr/0002-uiautomator2-over-appium-android.md) — uiautomator2 over Appium for Android v1
- [ADR-0003](adr/0003-mcp-over-custom-protocol.md) — MCP over a custom protocol for the Agent Interface
- [ADR-0004](adr/0004-llm-verification-supplemental.md) — LLM verification is supplemental, not a replacement for deterministic assertions
- [ADR-0005](adr/0005-platform-independent-orchestration.md) — Orchestration layer is platform-independent
- [ADR-0006](adr/0006-planning-is-external.md) — Planning is external to the framework
- [ADR-0007](adr/0007-layered-device-driver-protocols.md) — Device Driver decomposed into layered protocols
- [ADR-0008](adr/0008-deterministic-regression-selection.md) — Regression scenario selection is deterministic, tag-based

## 15. Out of Scope / Future Work

Explicit rejections (not "later," but "no, and here's why") and deferrals (genuinely future, not
speculative detail):

**Rejected — will not be built:**
- **In-framework autonomous test-strategy/planning engine.** Duplicates the calling agent's own
  reasoning capability (§3.1, ADR-0006).
- **Distributed device job queue/scheduler.** Duplicates CI infrastructure that already exists
  (GitHub Actions matrix, `pytest-xdist`); the framework provides device-targeting primitives
  instead (§3.6).
- **Plugin marketplace / signed / versioned plugin manifests / sandboxing.** Unwarranted at this
  scale; a simple entry-points registry is sufficient (§7).
- **Rigid machine-readable failure/reason-code taxonomy.** Free-text `message` + `evidence_refs`
  is sufficient for an LLM-consuming agent; a fixed taxonomy ossifies prematurely (§3.10).
- **In-framework permission/confirmation system for destructive actions.** Delegated to the MCP
  host's own tool-approval flow (§3.10).

**Deferred — real ideas, not scheduled until a concrete need exists:**
- **Exploration Mode** (§3.5) — Phase 4 at the earliest, scoped as a scenario *generator*, not a
  parallel execution paradigm.
- **Timeline → scenario compiler** (record & playback) (§3.7) — Phase 4, pairs with Exploration Mode.
- **iOS driver** (§10) — Phase 4; design is accommodated now, no implementation yet.
- **Desktop / Web drivers** (§10) — indefinitely deferred; design accommodated, no concrete
  SmarType desktop/web product surface yet.
- **FPS / battery profiling** (§3.4, §6.5) — indefinitely deferred; high effort, low relevance for
  an IME, easy to produce untrustworthy data. Revisit only given a concrete bug/need.

## 16. Implementation Phases

Full detail (milestones, dependencies, testing strategy) in
[`docs/implementation-plan.md`](implementation-plan.md). Summary:

1. **Phase 1 — Core Execution Substrate (Android).** Layered Device Driver, Scenario Engine,
   generic Assertion Library + `domains/ime`, Evidence Collector/Timeline, Report Generator,
   Plugin Registry pattern established. CLI only. Single device.
2. **Phase 2 — Verification Intelligence.** LLM Verification Layer (pluggable `LlmProvider`),
   Performance Engine (memory/CPU only), Regression Planner.
3. **Phase 3 — Agent Interface.** MCP server, explicit session model, introspection tools,
   multi-device targeting via `list_devices`.
4. **Phase 4 — Advanced / Optional.** Exploration Mode, Timeline→scenario compiler, iOS driver.
   Revisit FPS/battery only if motivated by a concrete need.
