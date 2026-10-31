from pathlib import Path

import pytest
from pydantic import ValidationError

from verdict.core.exceptions import ScenarioValidationError
from verdict.core.models import Direction, Platform, Selector, UiNode
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.reporting.renderers.html import HtmlRenderer
from verdict.reporting.renderers.json import JsonRenderer
from verdict.reporting.renderers.markdown import MarkdownRenderer
from verdict.scenario_engine.parser import parse_scenario
from verdict.scenario_engine.runner import run_scenario
from verdict.scenario_engine.schema import MissingPlatformSelectorError, ScenarioSpec, StepSpec

PER_PLATFORM = {"android": {"resource_id": "com.app:id/send"}, "ios": {"resource_id": "sendButton"}}


def _screen() -> UiNode:
    return UiNode(
        resource_id="root",
        children=[
            UiNode(resource_id="com.app:id/send", bounds=(0, 0, 10, 10)),
            UiNode(resource_id="sendButton", bounds=(100, 100, 110, 110)),
        ],
    )


def _driver(platform: Platform) -> FakeDeviceDriver:
    driver = FakeDeviceDriver(platform=platform)
    driver.set_hierarchy(_screen())
    return driver


# --- schema -----------------------------------------------------------------


def test_plain_selector_is_unchanged():
    step = StepSpec(action="tap", selector={"resource_id": "send"})
    assert step.selector == Selector(resource_id="send")
    assert step.selector_variants is None
    assert step.for_platform(Platform.IOS) is step


def test_per_platform_selector_parses_into_variants():
    step = StepSpec(action="tap", selector=PER_PLATFORM)
    assert step.selector is None
    assert step.selector_variants == {
        Platform.ANDROID: Selector(resource_id="com.app:id/send"),
        Platform.IOS: Selector(resource_id="sendButton"),
    }


@pytest.mark.parametrize("action", ["tap", "wait_for"])
def test_per_platform_selector_satisfies_required_selector(action):
    StepSpec(action=action, selector={"ios": {"text": "Send"}})


def test_per_platform_selector_works_for_ensure_checked_and_scroll():
    StepSpec(action="ensure_checked", selector={"ios": {"text": "Auto"}}, checked=True)
    StepSpec(action="scroll", direction=Direction.DOWN, selector={"android": {"text": "List"}})


def test_for_platform_puts_the_variant_in_selector():
    step = StepSpec(action="tap", selector=PER_PLATFORM)
    resolved = step.for_platform(Platform.IOS)
    assert resolved.selector == Selector(resource_id="sendButton")
    assert resolved.selector_variants is None
    assert step.selector_variants is not None


def test_for_platform_without_variant_raises():
    step = StepSpec(action="tap", selector={"android": {"text": "Send"}})
    with pytest.raises(MissingPlatformSelectorError, match="no selector for platform 'ios'"):
        step.for_platform(Platform.IOS)


def test_per_platform_selector_rejects_a_mixed_form():
    with pytest.raises(ValidationError, match="unknown key\\(s\\): resource_id"):
        StepSpec(action="tap", selector={"android": {"text": "a"}, "resource_id": "b"})


def test_per_platform_selector_rejects_an_empty_variant():
    with pytest.raises(ValidationError, match="at least one of"):
        StepSpec(action="tap", selector={"ios": {}})


def test_per_platform_selector_rejects_a_non_mapping_variant():
    with pytest.raises(ValidationError):
        StepSpec(action="tap", selector={"ios": "sendButton"})


def test_step_rejects_selector_and_selector_variants_together():
    with pytest.raises(ValidationError, match="not both"):
        StepSpec(
            action="tap",
            selector={"text": "a"},
            selector_variants={"ios": {"text": "b"}},
        )


def test_step_rejects_empty_selector_variants():
    with pytest.raises(ValidationError, match="at least one platform"):
        StepSpec(action="tap", selector_variants={})


def test_scenario_platforms_default_to_all():
    spec = ScenarioSpec(name="s", steps=[StepSpec(action="type_text", text="hi")])
    assert spec.platforms is None
    assert all(spec.supports(platform) for platform in Platform)


def test_scenario_platforms_parse_and_reject_unknown_values():
    spec = ScenarioSpec(name="s", platforms=["ios"], steps=[StepSpec(action="type_text", text="hi")])
    assert spec.platforms == [Platform.IOS]
    assert not spec.supports(Platform.ANDROID)
    with pytest.raises(ValidationError):
        ScenarioSpec(name="s", platforms=["windows"], steps=[StepSpec(action="type_text", text="x")])


def test_scenario_platforms_rejects_an_empty_list():
    with pytest.raises(ValidationError, match="at least one platform"):
        ScenarioSpec(name="s", platforms=[], steps=[StepSpec(action="type_text", text="hi")])


def test_parser_reads_both_selector_forms(tmp_path: Path):
    path = tmp_path / "s.yaml"
    path.write_text(
        """
name: both_forms
platforms: [android, ios]
variables:
  ios_id: sendButton
steps:
  - action: tap
    selector: { text: "Hello" }
  - action: tap
    selector:
      android: { resource_id: "com.app:id/send" }
      ios: { resource_id: "${ios_id}" }
"""
    )
    spec = parse_scenario(path)
    assert spec.platforms == [Platform.ANDROID, Platform.IOS]
    assert spec.steps[0].selector == Selector(text="Hello")
    assert spec.steps[1].selector_variants == {
        Platform.ANDROID: Selector(resource_id="com.app:id/send"),
        Platform.IOS: Selector(resource_id="sendButton"),
    }


def test_parser_reports_an_invalid_per_platform_selector(tmp_path: Path):
    path = tmp_path / "s.yaml"
    path.write_text(
        """
name: bad
steps:
  - action: tap
    selector:
      ios: { resource_id: "sendButton" }
      windows: { resource_id: "send" }
"""
    )
    with pytest.raises(ScenarioValidationError, match="windows"):
        parse_scenario(path)


# --- runner -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "expected_tap"),
    [(Platform.ANDROID, (5, 5)), (Platform.IOS, (105, 105))],
)
def test_runner_taps_the_variant_for_the_driver_platform(platform, expected_tap):
    driver = _driver(platform)
    spec = ScenarioSpec(
        name="send",
        steps=[
            StepSpec(action="wait_for", selector=PER_PLATFORM),
            StepSpec(action="tap", selector=PER_PLATFORM),
        ],
    )
    result = run_scenario(spec, driver, session_id="s")
    assert result.status == "PASSED"
    assert driver.tap_calls == [expected_tap]


def test_runner_passes_the_variant_to_scroll():
    driver = _driver(Platform.IOS)
    spec = ScenarioSpec(
        name="scroll",
        steps=[StepSpec(action="scroll", direction=Direction.DOWN, selector={"ios": {"text": "List"}})],
    )
    assert run_scenario(spec, driver, session_id="s").passed
    assert driver.scroll_calls == [(Direction.DOWN, Selector(text="List"))]


def test_runner_plain_selector_works_on_ios():
    driver = _driver(Platform.IOS)
    spec = ScenarioSpec(name="plain", steps=[StepSpec(action="tap", selector={"resource_id": "sendButton"})])
    assert run_scenario(spec, driver, session_id="s").passed
    assert driver.tap_calls == [(105, 105)]


def test_runner_fails_the_step_without_a_variant_for_the_platform():
    driver = _driver(Platform.IOS)
    spec = ScenarioSpec(
        name="android_only_step",
        steps=[
            StepSpec(action="type_text", text="hi"),
            StepSpec(action="tap", selector={"android": {"resource_id": "com.app:id/send"}}),
            StepSpec(action="type_text", text="not reached"),
        ],
    )
    result = run_scenario(spec, driver, session_id="s")
    assert result.status == "FAILED"
    events = result.timeline.events
    assert [event.passed for event in events] == [True, False]
    assert events[1].action == "tap"
    assert events[1].error is not None
    assert "no selector for platform 'ios'" in events[1].error
    assert driver.tap_calls == []
    assert driver.typed_text == ["hi"]


def test_runner_skips_a_scenario_for_an_unsupported_platform():
    driver = _driver(Platform.IOS)
    spec = ScenarioSpec(
        name="android_only",
        platforms=[Platform.ANDROID],
        steps=[StepSpec(action="type_text", text="hi")],
    )
    result = run_scenario(spec, driver, session_id="s")
    assert result.skipped
    assert not result.passed
    assert result.status == "SKIPPED"
    assert result.attempts == 0
    assert result.skip_reason == "the scenario supports only android; the device platform is ios"
    assert result.timeline.events == []
    assert driver.typed_text == []


def test_runner_runs_a_scenario_for_a_supported_platform():
    driver = _driver(Platform.IOS)
    spec = ScenarioSpec(
        name="ios_only", platforms=[Platform.IOS], steps=[StepSpec(action="type_text", text="hi")]
    )
    result = run_scenario(spec, driver, session_id="s")
    assert result.status == "PASSED"
    assert not result.skipped
    assert result.skip_reason is None


def test_reports_show_a_skipped_result():
    spec = ScenarioSpec(
        name="android_only", platforms=["android"], steps=[StepSpec(action="type_text", text="hi")]
    )
    result = run_scenario(spec, _driver(Platform.IOS), session_id="s", run_id="r1")
    markdown = MarkdownRenderer().render(result)
    assert "**Result:** SKIPPED" in markdown
    assert "**Skip reason:** the scenario supports only android" in markdown
    html = HtmlRenderer().render(result)
    assert '<span class="skip">SKIPPED</span>' in html
    assert "Skip reason:</strong> the scenario supports only android" in html
    assert '"skipped": true' in JsonRenderer().render(result)
