from verdict.assertions.base import assertion_registry
from verdict.core.models import AssertionResult, UiNode
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.scenario_engine.runner import run_scenario
from verdict.scenario_engine.schema import EvidencePolicy, RetryPolicy, ScenarioSpec, StepSpec


class _PassAssertion:
    name = "always_pass"

    def check(self, ctx):
        return AssertionResult(passed=True, message="ok")


class _FailAssertion:
    name = "always_fail"

    def check(self, ctx):
        return AssertionResult(passed=False, message="nope")


def _happy_path_spec(**overrides) -> ScenarioSpec:
    steps = [
        StepSpec(action="install", path="/tmp/app.apk"),
        StepSpec(action="launch", package="bha.keys.smartype.debug"),
        StepSpec(action="tap", selector={"resource_id": "text_field"}),
        StepSpec(action="type_text", text="I recieve"),
        StepSpec(action="wait_for", selector={"description": "ai_suggestion_chip"}, timeout_ms=2000),
        StepSpec(action="assert", assertion="always_pass"),
    ]
    return ScenarioSpec(name="happy", steps=steps, **overrides)


def _driver_with_chip() -> FakeDeviceDriver:
    driver = FakeDeviceDriver()
    driver.set_hierarchy(
        UiNode(
            resource_id="root",
            children=[
                UiNode(resource_id="text_field"),
                UiNode(content_desc="ai_suggestion_chip"),
            ],
        )
    )
    return driver


def test_run_scenario_happy_path_passes():
    assertion_registry.register("always_pass", lambda: _PassAssertion())
    driver = _driver_with_chip()

    result = run_scenario(_happy_path_spec(), driver, session_id="s1")

    assert result.passed is True
    assert result.attempts == 1
    assert len(result.timeline.events) == 6
    assert all(event.passed for event in result.timeline.events)
    assert driver.installed_packages == {"/tmp/app.apk"}
    assert driver.current_package == "bha.keys.smartype.debug"
    assert driver.typed_text == ["I recieve"]


def test_run_scenario_wait_for_timeout_fails():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="text_field"))  # tap target exists, chip never appears
    spec = _happy_path_spec()

    result = run_scenario(spec, driver, session_id="s1")

    assert result.passed is False
    failed_event = result.timeline.events[-1]
    assert failed_event.action == "wait_for"
    assert failed_event.passed is False
    assert "timed out" in failed_event.error


def test_run_scenario_failing_assertion_fails_and_stops():
    assertion_registry.register("always_fail", lambda: _FailAssertion())
    driver = _driver_with_chip()
    spec = ScenarioSpec(
        name="fails",
        steps=[
            StepSpec(action="assert", assertion="always_fail"),
            StepSpec(action="type_text", text="never runs"),
        ],
    )

    result = run_scenario(spec, driver, session_id="s1")

    assert result.passed is False
    assert len(result.timeline.events) == 1
    assert driver.typed_text == []


def test_assertion_args_forwarded_from_step():
    received: list[dict] = []

    def factory(**kwargs):
        received.append(kwargs)
        return _PassAssertion()

    assertion_registry.register("captures_args", factory)
    driver = _driver_with_chip()
    spec = ScenarioSpec(
        name="args",
        steps=[StepSpec(action="assert", assertion="captures_args", args={"ms": 500})],
    )

    run_scenario(spec, driver, session_id="s1")

    assert received == [{"ms": 500}]


def test_retries_whole_scenario_until_max_attempts():
    assertion_registry.register("always_fail", lambda: _FailAssertion())
    driver = _driver_with_chip()
    spec = ScenarioSpec(
        name="retry",
        steps=[StepSpec(action="assert", assertion="always_fail")],
        retries=RetryPolicy(max_attempts=3, backoff_ms=10),
    )
    sleeps: list[float] = []

    result = run_scenario(spec, driver, session_id="s1", sleep=sleeps.append)

    assert result.passed is False
    assert result.attempts == 3
    assert sleeps == [0.01, 0.01]


def test_retries_stop_early_on_success():
    calls = {"n": 0}

    class _FlakyAssertion:
        name = "flaky"

        def check(self, ctx):
            calls["n"] += 1
            return AssertionResult(passed=calls["n"] >= 2, message="flaky")

    assertion_registry.register("flaky", lambda: _FlakyAssertion())
    driver = _driver_with_chip()
    spec = ScenarioSpec(
        name="flaky",
        steps=[StepSpec(action="assert", assertion="flaky")],
        retries=RetryPolicy(max_attempts=3, backoff_ms=0),
    )

    result = run_scenario(spec, driver, session_id="s1", sleep=lambda _: None)

    assert result.passed is True
    assert result.attempts == 2


def test_evidence_captured_per_policy(tmp_path):
    assertion_registry.register("always_pass", lambda: _PassAssertion())
    driver = _driver_with_chip()
    spec = ScenarioSpec(
        name="evidence",
        steps=[StepSpec(action="assert", assertion="always_pass")],
        evidence=EvidencePolicy(always=["screenshot"], on_failure=["hierarchy"]),
    )

    result = run_scenario(spec, driver, session_id="s1", evidence_dir=tmp_path)

    event = result.timeline.events[0]
    assert len(event.evidence_refs) == 1
    assert event.evidence_refs[0].kind == "screenshot"
    assert event.evidence_refs[0].path.exists()


def test_evidence_on_failure_captured_in_addition_to_always(tmp_path):
    assertion_registry.register("always_fail", lambda: _FailAssertion())
    driver = _driver_with_chip()
    spec = ScenarioSpec(
        name="evidence-fail",
        steps=[StepSpec(action="assert", assertion="always_fail")],
        evidence=EvidencePolicy(always=["screenshot"], on_failure=["hierarchy"]),
    )

    result = run_scenario(spec, driver, session_id="s1", evidence_dir=tmp_path)

    event = result.timeline.events[0]
    kinds = {ref.kind for ref in event.evidence_refs}
    assert kinds == {"screenshot", "hierarchy"}


def test_type_keys_step_reaches_driver_with_interval():
    driver = FakeDeviceDriver()
    spec = ScenarioSpec(
        name="keys", steps=[StepSpec(action="type_keys", text="helllo ", interval_ms=200)]
    )
    result = run_scenario(spec, driver, session_id="s1")
    assert result.passed is True
    assert driver.typed_keys == [("helllo ", 200)]


def test_press_key_step_passes_key_code_to_driver():
    driver = FakeDeviceDriver()
    spec = ScenarioSpec(name="keys", steps=[StepSpec(action="press_key", key="KEYCODE_POUND")])
    assert run_scenario(spec, driver, session_id="s1").passed is True
    assert driver.pressed_keys == ["KEYCODE_POUND"]
