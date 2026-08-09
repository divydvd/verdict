# ADR-0002: uiautomator2 over Appium for Android v1

## Status
Accepted

## Context
The platform needs robust, low-level Android UI automation primitives (tap, swipe, type, dump
hierarchy, wait) as the foundation of the `InputDriver`/`AppLifecycleDriver` implementation for
Android. Appium (with its UiAutomator2 driver) and the standalone `uiautomator2` Python library
both wrap the same underlying Android UiAutomator2 instrumentation.

## Decision
Use [`uiautomator2`](https://github.com/openatx/uiautomator2) (+ `adbutils`) directly as the
Android `DeviceDriver` implementation for v1. Do not run Appium for Android.

## Consequences
**Positive:**
- No Appium server process to run/manage — `uiautomator2` talks to a lightweight on-device HTTP
  automation server directly via ADB, reducing moving parts and latency.
- Faster iteration for a Python-native automation stack — mature, widely used, actively
  maintained library with a Pythonic API that matches our orchestration language.
- Avoids Appium's driver-abstraction overhead (WebDriver protocol translation) for a case where
  we don't need cross-tool interoperability.

**Negative:**
- When iOS is added (architecture §10, Phase 4), the platform will use two different underlying
  automation technologies (`uiautomator2` for Android, Appium/XCUITest for iOS). Mitigated by the
  fact that both are hidden behind the same `DeviceDriver` composed protocol — orchestration code
  never sees the difference.
- If a future need for Android/iOS test-code reuse via a single automation tool becomes more
  valuable than the current performance/simplicity win, this decision should be revisited (e.g.
  switching Android to Appium's UiAutomator2 driver too, for a single Appium-based backend).

## Alternatives Considered
- **Appium (UiAutomator2 driver) for Android now.** Rejected: an extra server process and
  WebDriver-protocol translation layer add latency and operational overhead with no current
  benefit, since iOS isn't in scope for Phase 1.
- **Espresso.** Rejected: Espresso is a white-box/instrumented testing framework that must be
  compiled into the app under test (or a test APK built against it). Unsuitable for black-box
  end-to-end testing against an already-built, potentially released APK, which is the platform's
  core use case.
