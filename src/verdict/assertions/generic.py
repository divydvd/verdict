from __future__ import annotations

from verdict.assertions.base import assertion_registry
from verdict.core.models import AssertionResult, EvidenceRef, RunContext

_CRASH_MARKERS = ("FATAL EXCEPTION", "ANR in")
_PACKAGE_CONTEXT_WINDOW = 6


class AppDidNotCrashAssertion:
    """Generic, domain-agnostic crash-signature scan over logcat. See
    docs/architecture.md §6.3.
    """

    name = "app_did_not_crash"

    def __init__(self, package: str | None = None) -> None:
        self.package = package

    def check(self, ctx: RunContext) -> AssertionResult:
        log_path = ctx.driver.collect_logs()
        lines = log_path.read_text().splitlines()

        for index, line in enumerate(lines):
            if not any(marker in line for marker in _CRASH_MARKERS):
                continue
            if self.package is None or self._mentions_package(lines, index):
                return AssertionResult(
                    passed=False,
                    message=f"crash signature found: {line.strip()}",
                    evidence_refs=[EvidenceRef(kind="logcat", path=log_path)],
                )

        return AssertionResult(passed=True, message="no crash signature found in logs")

    def _mentions_package(self, lines: list[str], marker_index: int) -> bool:
        window = lines[marker_index : marker_index + _PACKAGE_CONTEXT_WINDOW]
        return any(self.package in line for line in window)  # type: ignore[operator]


class LatencyUnderAssertion:
    """Checks the wall-clock duration of the immediately preceding step,
    recorded on `RunContext.last_action_duration_ms` by the runner.
    """

    name = "latency_under"

    def __init__(self, ms: float) -> None:
        self.ms = ms

    def check(self, ctx: RunContext) -> AssertionResult:
        duration = ctx.last_action_duration_ms
        if duration is None:
            return AssertionResult(passed=False, message="no prior action to measure latency for")
        passed = duration <= self.ms
        return AssertionResult(
            passed=passed,
            message=f"last action took {duration:.1f}ms (limit {self.ms}ms)",
        )


class ScreenshotCapturedAssertion:
    """Captures a screenshot right now and asserts it was written to disk."""

    name = "screenshot_captured"

    def check(self, ctx: RunContext) -> AssertionResult:
        path = ctx.driver.screenshot()
        return AssertionResult(
            passed=path.exists(),
            message=f"screenshot captured at {path}",
            evidence_refs=[EvidenceRef(kind="screenshot", path=path)],
        )


assertion_registry.register("app_did_not_crash", lambda package=None: AppDidNotCrashAssertion(package))
assertion_registry.register("latency_under", lambda ms: LatencyUnderAssertion(ms))
assertion_registry.register("screenshot_captured", lambda: ScreenshotCapturedAssertion())
