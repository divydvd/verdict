from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from verdict.assertions.base import assertion_registry
from verdict.core.exceptions import VerdictError
from verdict.core.models import AssertionResult, RunContext, Timeline, TimelineEvent
from verdict.device_driver.base import DeviceDriver
from verdict.evidence.collector import EvidenceCollector
from verdict.scenario_engine.schema import ScenarioSpec, StepSpec


class ScenarioResult(BaseModel):
    passed: bool
    attempts: int
    timeline: Timeline


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
) -> bool:
    collector = EvidenceCollector(driver, ctx.evidence_dir)
    for index, step in enumerate(spec.steps):
        step_id = f"{index}:{step.action}"
        error: str | None = None
        passed = True
        assertion_results: list[AssertionResult] = []

        start = time.perf_counter()
        try:
            action_fn = _ACTIONS[step.action]
            result = action_fn(driver, step, ctx)
            if step.action == "assert" and result is not None and not result.passed:
                result = _settle_and_recheck(driver, step, ctx, result, sleep)
        except VerdictError as exc:
            passed = False
            error = str(exc)
        else:
            if result is not None:
                assertion_results.append(result)
                passed = result.passed
                if not passed:
                    error = result.message
        finally:
            ctx.last_action_duration_ms = (time.perf_counter() - start) * 1000

        evidence_refs = collector.capture_all(spec.evidence.always, index)
        if not passed:
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

        if not passed:
            return False

    return True


def run_scenario(
    spec: ScenarioSpec,
    driver: DeviceDriver,
    session_id: str,
    run_id: str | None = None,
    evidence_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ScenarioResult:
    """Execute a parsed scenario against `driver`, retrying the whole
    scenario up to `spec.retries.max_attempts` times on failure.
    """
    resolved_run_id = run_id or str(uuid.uuid4())
    resolved_evidence_dir = evidence_dir or Path(f"/tmp/verdict-evidence-{resolved_run_id}")

    max_attempts = max(1, spec.retries.max_attempts)
    timeline = Timeline(run_id=resolved_run_id, scenario_name=spec.name)
    passed = False

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
        passed = _run_once(spec, driver, ctx, timeline, sleep)
        if passed:
            return ScenarioResult(passed=True, attempts=attempt, timeline=timeline)
        if attempt < max_attempts and spec.retries.backoff_ms:
            sleep(spec.retries.backoff_ms / 1000)

    return ScenarioResult(passed=False, attempts=max_attempts, timeline=timeline)
