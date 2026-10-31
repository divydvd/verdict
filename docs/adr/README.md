# Architecture Decision Records

Records the major design decisions behind the [Agentic Mobile Testing Platform architecture](../agentic-testing-platform-architecture.md) (frozen v1.0). New ADRs are added only when
implementation surfaces a genuine architectural flaw in a frozen decision — not simply because an
alternative design would also work.

| ADR | Title |
|---|---|
| [0001](0001-standalone-repository.md) | Standalone repository |
| [0002](0002-uiautomator2-over-appium-android.md) | uiautomator2 over Appium for Android v1 |
| [0003](0003-mcp-over-custom-protocol.md) | MCP over a custom protocol for the Agent Interface |
| [0004](0004-llm-verification-supplemental.md) | LLM verification is supplemental, not a replacement for deterministic assertions |
| [0005](0005-platform-independent-orchestration.md) | Orchestration layer is platform-independent |
| [0006](0006-planning-is-external.md) | Planning is external to the framework |
| [0007](0007-layered-device-driver-protocols.md) | Device Driver decomposed into layered protocols |
| [0008](0008-deterministic-regression-selection.md) | Regression scenario selection is deterministic, tag-based |
| [0009](0009-ios-driver-appium-xcuitest.md) | iOS driver through Appium XCUITest |
