from pathlib import Path

from verdict.assertions.base import assertion_registry
from verdict.assertions.generic import (
    AppDidNotCrashAssertion,
    LatencyUnderAssertion,
    ScreenshotCapturedAssertion,
)
from verdict.core.models import RunContext
from verdict.device_driver.fake import FakeDeviceDriver


def _ctx(driver: FakeDeviceDriver, **overrides) -> RunContext:
    defaults = {
        "session_id": "s1",
        "run_id": "r1",
        "scenario_name": "scenario",
        "driver": driver,
        "evidence_dir": driver.evidence_dir,
    }
    defaults.update(overrides)
    return RunContext(**defaults)


def test_builtin_assertions_are_registered():
    assert {"app_did_not_crash", "latency_under", "screenshot_captured"} <= set(
        assertion_registry.list()
    )


def test_app_did_not_crash_passes_on_clean_logs():
    driver = FakeDeviceDriver()
    driver.set_logs("I/ActivityManager: Displaying bha.keys.smartype.debug\n")
    result = AppDidNotCrashAssertion().check(_ctx(driver))
    assert result.passed is True


def test_app_did_not_crash_fails_on_fatal_exception():
    driver = FakeDeviceDriver()
    driver.set_logs("E/AndroidRuntime: FATAL EXCEPTION: main\nProcess: bha.keys.smartype.debug\n")
    result = AppDidNotCrashAssertion().check(_ctx(driver))
    assert result.passed is False
    assert "FATAL EXCEPTION" in result.message
    assert result.evidence_refs[0].kind == "logcat"


def test_app_did_not_crash_scoped_to_package_ignores_other_crashes():
    driver = FakeDeviceDriver()
    driver.set_logs("E/AndroidRuntime: FATAL EXCEPTION: main\nProcess: com.other.app, PID: 123\n")
    result = AppDidNotCrashAssertion(package="bha.keys.smartype.debug").check(_ctx(driver))
    assert result.passed is True


def test_app_did_not_crash_scoped_to_package_matches():
    driver = FakeDeviceDriver()
    driver.set_logs("E/AndroidRuntime: FATAL EXCEPTION: main\nProcess: bha.keys.smartype.debug\n")
    result = AppDidNotCrashAssertion(package="bha.keys.smartype.debug").check(_ctx(driver))
    assert result.passed is False


def test_latency_under_passes_when_within_limit():
    driver = FakeDeviceDriver()
    ctx = _ctx(driver, last_action_duration_ms=100.0)
    result = LatencyUnderAssertion(ms=500).check(ctx)
    assert result.passed is True


def test_latency_under_fails_when_over_limit():
    driver = FakeDeviceDriver()
    ctx = _ctx(driver, last_action_duration_ms=900.0)
    result = LatencyUnderAssertion(ms=500).check(ctx)
    assert result.passed is False


def test_latency_under_fails_when_no_prior_action():
    driver = FakeDeviceDriver()
    result = LatencyUnderAssertion(ms=500).check(_ctx(driver))
    assert result.passed is False
    assert "no prior action" in result.message


def test_screenshot_captured_passes_and_attaches_evidence():
    driver = FakeDeviceDriver()
    result = ScreenshotCapturedAssertion().check(_ctx(driver))
    assert result.passed is True
    assert isinstance(result.evidence_refs[0].path, Path)
    assert result.evidence_refs[0].path.exists()
