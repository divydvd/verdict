from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from verdict.assertions.base import assertion_registry
from verdict.core.exceptions import DriverError, ElementNotFoundError, VerdictError
from verdict.core.models import AssertionResult, RunContext, Timeline, TimelineEvent
from verdict.device_driver.base import DeviceDriver, KeyboardDriver
from verdict.evidence.collector import EvidenceCollector
from verdict.scenario_engine.schema import ScenarioSpec, StepSpec


class ScenarioResult(BaseModel):
    passed: bool
    attempts: int
    timeline: Timeline
    blocked: bool = False
    # The runner did not run the scenario: the driver platform is not in
    # `ScenarioSpec.platforms`. `skip_reason` says why.
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIPPED"
        if self.blocked:
            return "BLOCKED"
        return "PASSED" if self.passed else "FAILED"


_PASSED, _FAILED, _BLOCKED = "passed", "failed", "blocked"


def _do_install(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.path is not None
    driver.install(step.path)


def _do_uninstall(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.package is not None
    driver.uninstall(step.package)


def _do_launch(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.package is not None
    driver.launch(step.package, step.activity)


def _do_clear_data(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.package is not None
    driver.clear_data(step.package)


def _do_tap(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.selector is not None
    driver.tap_selector(step.selector)


def _do_type_text(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.text is not None
    driver.type_text(step.text)


def _do_type_keys(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.text is not None
    driver.type_keys(step.text, step.interval_ms)


def _do_swipe(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.x1 is not None and step.y1 is not None and step.x2 is not None and step.y2 is not None
    driver.swipe(step.x1, step.y1, step.x2, step.y2, step.duration_ms)


def _do_scroll(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.direction is not None
    driver.scroll(step.direction, step.selector)


def _do_press_key(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> None:
    assert step.key is not None
    driver.press_key(step.key)


def _do_wait_for(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> AssertionResult:
    assert step.selector is not None
    ok = driver.wait_for(step.selector, step.timeout_ms)
    message = f"wait_for {step.selector!r} within {step.timeout_ms}ms"
    return AssertionResult(passed=ok, message=message if ok else f"timed out: {message}")


def _read_checked(driver: DeviceDriver, step: StepSpec) -> bool:
    assert step.selector is not None
    found, checkable = driver.dump_hierarchy().find_checkable(step.selector)
    if found is None:
        raise ElementNotFoundError(f"ensure_checked: no element matching {step.selector!r}")
    if checkable is None:
        raise DriverError(
            f"ensure_checked: the element matching {step.selector!r} is not checkable, "
            "and it has no checkable ancestor"
        )
    return checkable.checked


def _do_ensure_checked(
    driver: DeviceDriver,
    step: StepSpec,
    ctx: RunContext,
    sleep: Callable[[float], None] = time.sleep,
) -> AssertionResult:
    """Set a switch or a check box to `step.checked`. Tap only when the state
    differs, then read the state again (with the `settle_ms` re-checks).
    After the tap, a missing element is a re-check, not a failure: the screen
    can redraw.
    """
    assert step.checked is not None
    wanted = step.checked
    if _read_checked(driver, step) == wanted:
        return AssertionResult(passed=True, message=f"ensure_checked {step.selector!r}: already {wanted}")
    assert step.selector is not None
    driver.tap_selector(step.selector)
    state = f"the state is still {not wanted}"
    for attempt in range(step.settle_attempts + 1):
        if attempt:
            sleep(step.settle_ms / 1000)
        try:
            if _read_checked(driver, step) == wanted:
                return AssertionResult(
                    passed=True, message=f"ensure_checked {step.selector!r}: tapped, now {wanted}"
                )
            state = f"the state is still {not wanted}"
        except ElementNotFoundError:
            state = "the element is missing"
    return AssertionResult(
        passed=False,
        message=f"ensure_checked {step.selector!r}: tapped, but {state}",
    )


def _do_select_keyboard(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> AssertionResult | None:
    """Select a keyboard by its name. See ADR-0010.

    The driver selects the keyboard and checks that it is active. With a
    `selector`, the step then waits up to `timeout_ms` for that element of the
    selected keyboard (for example `keyboard_view`).
    """
    assert isinstance(step.keyboard, str)
    if not isinstance(driver, KeyboardDriver):
        raise DriverError(
            f"select_keyboard: the {driver.platform.value} driver cannot select a keyboard"
        )
    driver.select_keyboard(step.keyboard)
    if step.selector is None:
        return None
    ok = driver.wait_for(step.selector, step.timeout_ms)
    message = f"select_keyboard '{step.keyboard}': {step.selector!r} within {step.timeout_ms}ms"
    return AssertionResult(passed=ok, message=message if ok else f"timed out: {message}")


def _do_assert(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> AssertionResult:
    assert step.assertion is not None
    assertion = assertion_registry.get(step.assertion, **step.args)
    return assertion.check(ctx)


_ACTIONS: dict[str, Callable[[DeviceDriver, StepSpec, RunContext], AssertionResult | None]] = {
    "install": _do_install,
    "uninstall": _do_uninstall,
    "launch": _do_launch,
    "clear_data": _do_clear_data,
    "tap": _do_tap,
    "type_text": _do_type_text,
    "type_keys": _do_type_keys,
    "swipe": _do_swipe,
    "scroll": _do_scroll,
    "press_key": _do_press_key,
    "wait_for": _do_wait_for,
    "ensure_checked": _do_ensure_checked,
    "select_keyboard": _do_select_keyboard,
    "assert": _do_assert,
}


def register_action_handler(
    name: str, handler: Callable[[DeviceDriver, StepSpec, RunContext], AssertionResult | None]
) -> None:
    """Counterpart to `schema.register_action` — wires the runtime handler
    for a domain-registered action name. See `domains/ime/actions.py`.
    """
    if name in _ACTIONS:
        raise ValueError(f"action handler '{name}' is already registered")
    _ACTIONS[name] = handler


def _settle_and_recheck(
    driver: DeviceDriver,
    step: StepSpec,
    ctx: RunContext,
    first: AssertionResult,
    sleep: Callable[[float], None],
) -> AssertionResult:
    """Re-check a failed `assert` step after `settle_ms`, up to
    `settle_attempts` times. The hierarchy can lag a fast Compose transition
    (SmarType testing doc, caveat 3). The message says how many re-checks ran.
    """
    result = first
    for recheck in range(1, step.settle_attempts + 1):
        sleep(step.settle_ms / 1000)
        result = _do_assert(driver, step, ctx)
        if result.passed:
            message = f"{result.message} (passed on re-check {recheck} after {step.settle_ms} ms)"
            return result.model_copy(update={"message": message})
    if step.settle_attempts:
        message = f"{result.message} (still failing after {step.settle_attempts} re-check(s))"
        result = result.model_copy(update={"message": message})
    return result


def _run_once(
    spec: ScenarioSpec,
    driver: DeviceDriver,
    ctx: RunContext,
    timeline: Timeline,
    sleep: Callable[[float], None] = time.sleep,
    blocked_errors: tuple[type[BaseException], ...] = (),
) -> str:
    collector = EvidenceCollector(driver, ctx.evidence_dir)
    for index, spec_step in enumerate(spec.steps):
        step = spec_step
        step_id = f"{index}:{step.action}"
        error: str | None = None
        passed = True
        blocked = False
        assertion_results: list[AssertionResult] = []

        start = time.perf_counter()
        try:
            step = spec_step.for_platform(driver.platform)
            action_fn = _ACTIONS[step.action]
            result: AssertionResult | None
            if action_fn is _do_ensure_checked:
                result = _do_ensure_checked(driver, step, ctx, sleep)
            else:
                result = action_fn(driver, step, ctx)
            if step.action == "assert" and result is not None and not result.passed:
                result = _settle_and_recheck(driver, step, ctx, result, sleep)
        except VerdictError as exc:
            passed = False
            error = str(exc)
        except blocked_errors as exc:
            passed = False
            blocked = True
            error = f"BLOCKED: the device connection failed: {type(exc).__name__}: {exc}"
        else:
            if result is not None:
                assertion_results.append(result)
                passed = result.passed
                if not passed:
                    error = result.message
        finally:
            ctx.last_action_duration_ms = (time.perf_counter() - start) * 1000

        # With the connection down, an evidence capture fails too.
        evidence_refs = [] if blocked else collector.capture_all(spec.evidence.always, index)
        if not passed and not blocked:
            evidence_refs += collector.capture_all(spec.evidence.on_failure, index)

        timeline.events.append(
            TimelineEvent(
                timestamp=datetime.now(UTC),
                step_id=step_id,
                action=step.action,
                passed=passed,
                error=error,
                evidence_refs=evidence_refs,
                assertion_results=assertion_results,
            )
        )

        if blocked:
            return _BLOCKED
        if not passed:
            return _FAILED

    return _PASSED


def run_scenario(
    spec: ScenarioSpec,
    driver: DeviceDriver,
    session_id: str,
    run_id: str | None = None,
    evidence_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    blocked_errors: tuple[type[BaseException], ...] = (),
) -> ScenarioResult:
    """Execute a parsed scenario against `driver`, retrying the whole
    scenario up to `spec.retries.max_attempts` times on failure.

    An exception in `blocked_errors` (a lost device connection) stops the run
    with no retry. The result is BLOCKED and keeps the partial timeline.

    When `spec.platforms` does not include `driver.platform`, the runner runs
    no step. The result is SKIPPED, with `skip_reason` and an empty timeline.
    Each step gets the selector for `driver.platform` before it runs. A step
    with no selector for that platform fails with a clear error.
    """
    resolved_run_id = run_id or str(uuid.uuid4())
    resolved_evidence_dir = evidence_dir or Path(f"/tmp/verdict-evidence-{resolved_run_id}")

    max_attempts = max(1, spec.retries.max_attempts)
    timeline = Timeline(run_id=resolved_run_id, scenario_name=spec.name)

    if not spec.supports(driver.platform):
        supported = ", ".join(platform.value for platform in spec.platforms or ())
        return ScenarioResult(
            passed=False,
            skipped=True,
            skip_reason=(
                f"the scenario supports only {supported}; the device platform is "
                f"{driver.platform.value}"
            ),
            attempts=0,
            timeline=timeline,
        )

    for attempt in range(1, max_attempts + 1):
        ctx = RunContext(
            session_id=session_id,
            run_id=resolved_run_id,
            scenario_name=spec.name,
            driver=driver,
            variables=spec.variables,
            evidence_dir=resolved_evidence_dir,
        )
        timeline = Timeline(run_id=resolved_run_id, scenario_name=spec.name)
        outcome = _run_once(spec, driver, ctx, timeline, sleep, blocked_errors)
        if outcome == _PASSED:
            return ScenarioResult(passed=True, attempts=attempt, timeline=timeline)
        if outcome == _BLOCKED:
            return ScenarioResult(passed=False, blocked=True, attempts=attempt, timeline=timeline)
        if attempt < max_attempts and spec.retries.backoff_ms:
            sleep(spec.retries.backoff_ms / 1000)

    return ScenarioResult(passed=False, attempts=max_attempts, timeline=timeline)
