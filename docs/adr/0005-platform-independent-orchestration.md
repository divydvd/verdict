# ADR-0005: Orchestration layer is platform-independent

## Status
Accepted

## Context
The platform must support Android now and potentially iOS (and, unscheduled, Desktop/Web) later,
without a rewrite of the parts of the system that have nothing to do with device control.

## Decision
Only the Device Driver layer is platform-specific. The Scenario Engine, Assertion Library
(generic + domain bundles), Evidence Collector/Timeline, Performance Engine, Report Generator,
LLM Verification Layer, Regression Planner, and Agent Interface all operate purely against the
`DeviceDriver` composed protocol (see ADR-0007) and never contain platform-conditional logic.

## Consequences
**Positive:**
- Adding a new platform means implementing one new `DeviceDriver`-composition implementation; no
  other module needs to change.
- Every non-driver module is testable against `FakeDeviceDriver` without any real device,
  emulator, or platform SDK — keeping the core test suite fast and platform-independent.

**Negative:**
- The composed driver protocol must be genuinely general enough to avoid leaking
  platform-specific concepts (e.g. "install an APK") into what should be universal capabilities
  (e.g. "tap a coordinate"). This was identified as a real risk in the original flat
  `DeviceDriver` design and addressed by decomposing the interface — see ADR-0007.
- Some orchestration-layer code (e.g. `domains/ime` selectors) is inherently tied to how the
  *app* is built for a given platform (Android resource-ids vs. iOS accessibility identifiers),
  even though the orchestration *logic* itself is platform-independent. This is expected and
  handled at the scenario/selector level (per-platform selector variants), not by adding
  platform-conditional code to the orchestration modules themselves.

## Alternatives Considered
- **Platform-conditional logic scattered through Scenario Engine / Assertions** (e.g.
  `if platform == "android": ...`). Rejected: this is exactly the coupling this ADR exists to
  prevent — it would make every orchestration module grow platform-specific branches over time,
  eventually requiring a rewrite to add a new platform cleanly.
