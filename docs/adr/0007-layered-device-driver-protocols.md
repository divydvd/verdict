# ADR-0007: Device Driver decomposed into layered protocols

## Status
Accepted

## Context
The original (v0.1) design had a single flat `DeviceDriver` protocol mixing three different kinds
of capability: universal input primitives (`tap`, `swipe`, `type_text`, `screenshot`,
`dump_hierarchy`), mobile-app-lifecycle operations (`install_apk`, `uninstall`, `clear_data`), and
Android-specific diagnostics (`collect_logcat`). This was identified during architecture review
(architecture.md §3.9) as a problem for long-term extensibility: a Web driver, for instance, has
no "APK to install" and no clean way to implement `install_apk` without a fake/no-op method — the
interface would force irrelevant methods on future implementations.

## Decision
Split the driver interface into three composable protocols:
- `InputDriver` — tap, swipe, scroll, type_text, press_key, screenshot, dump_hierarchy, wait_for.
  Genuinely universal across mobile, desktop, and web, even though selector semantics differ per
  platform.
- `AppLifecycleDriver` — install, uninstall, launch, clear_data. Mobile-app-specific; a Web driver
  would instead implement a different lifecycle protocol (e.g. `navigate(url)`, `clear_cookies()`).
- `DiagnosticsDriver` — collect_logs, start/stop_recording, collect_bugreport. Semantics adapt per
  platform (logcat vs. browser console vs. OS event log); `collect_bugreport` is explicitly
  optional (`Path | None`) since it has no Web/Desktop equivalent.

`DeviceDriver = InputDriver & AppLifecycleDriver & DiagnosticsDriver` for the mobile case.
`AndroidUiautomator2Driver` implements the full composition.

## Consequences
**Positive:**
- A future Web or Desktop driver implements `InputDriver` + `DiagnosticsDriver` plus its own
  platform-appropriate lifecycle protocol, without being forced to fake mobile-only methods.
- Smaller, independently testable protocol surfaces — contract tests can target one capability at
  a time.
- Capability discovery becomes a type-level fact ("does this driver support `AppLifecycleDriver`")
  rather than a runtime `NotImplementedError` landmine.

**Negative:**
- Three protocols instead of one, for a Phase 1 that ships exactly one implementation
  (`AndroidUiautomator2Driver`, which satisfies all three anyway). This is pure ceremony in the
  short term.

Accepted despite the short-term ceremony because retrofitting this decomposition *after* the
Scenario Engine, Assertion Library, and Evidence Collector are written against a flat interface
would be a breaking change touching every layer above the driver (ADR-0005) — cheap to design
correctly now, expensive to fix once Phase 1–3 orchestration code exists.

## Alternatives Considered
- **Single flat interface with optional/nullable methods per platform** (e.g.
  `install_apk: Callable | None`). Rejected: leads to runtime `NotImplementedError` surprises
  instead of compile/type-check-time capability discovery, and doesn't actually simplify anything
  over three small protocols — it just moves the same complexity into conditional checks at every
  call site.
