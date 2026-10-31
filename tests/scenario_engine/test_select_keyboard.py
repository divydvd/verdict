from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from verdict.core.models import Platform, UiNode
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.scenario_engine.parser import parse_scenario
from verdict.scenario_engine.runner import run_scenario
from verdict.scenario_engine.schema import (
    MissingPlatformSelectorError,
    MissingPlatformValueError,
    ScenarioSpec,
    StepSpec,
)

SMARTYPE_IME = "bha.keys.smartype.debug/bha.keys.smartype.FlorisImeService"


def _run(driver: FakeDeviceDriver, **step_fields):
    step = StepSpec(action="select_keyboard", **step_fields)
    spec = ScenarioSpec(name="keyboard", steps=[step])
    return run_scenario(spec, driver, session_id="s", evidence_dir=driver.evidence_dir)


def test_select_keyboard_needs_a_keyboard():
    with pytest.raises(ValidationError, match="missing required field\\(s\\): keyboard"):
        StepSpec(action="select_keyboard")


@pytest.mark.parametrize("keyboard", ["", "  ", {}, {"ios": ""}])
def test_select_keyboard_rejects_an_empty_keyboard(keyboard):
    with pytest.raises(ValidationError, match="'keyboard'"):
        StepSpec(action="select_keyboard", keyboard=keyboard)


def test_select_keyboard_rejects_an_unknown_platform():
    with pytest.raises(ValidationError):
        StepSpec(action="select_keyboard", keyboard={"windows": "x"})


def test_for_platform_selects_the_keyboard_of_the_platform():
    step = StepSpec(action="select_keyboard", keyboard={"android": SMARTYPE_IME, "ios": "SmarType"})
    assert step.for_platform(Platform.IOS).keyboard == "SmarType"
    assert step.for_platform(Platform.ANDROID).keyboard == SMARTYPE_IME


def test_for_platform_fails_without_a_keyboard_for_the_platform():
    step = StepSpec(action="select_keyboard", keyboard={"ios": "SmarType"})
    with pytest.raises(MissingPlatformValueError, match="no keyboard for platform 'android' \\(it has: ios\\)"):
        step.for_platform(Platform.ANDROID)


def test_a_missing_selector_is_also_a_missing_platform_value():
    assert issubclass(MissingPlatformSelectorError, MissingPlatformValueError)


def test_for_platform_resolves_the_selector_and_the_keyboard_together():
    step = StepSpec(
        action="select_keyboard",
        keyboard={"ios": "SmarType"},
        selector={"ios": {"resource_id": "keyboard_view"}},
    )
    resolved = step.for_platform(Platform.IOS)
    assert resolved.keyboard == "SmarType"
    assert resolved.selector is not None and resolved.selector.resource_id == "keyboard_view"


def test_parser_reads_a_per_platform_keyboard(tmp_path):
    path = tmp_path / "scenario.yaml"
    path.write_text(
        "name: keyboard\n"
        "steps:\n"
        "  - action: select_keyboard\n"
        "    keyboard:\n"
        f"      android: {SMARTYPE_IME}\n"
        "      ios: SmarType\n"
        "    selector: {resource_id: keyboard_view}\n"
    )
    step = parse_scenario(path).steps[0]
    assert step.keyboard == {Platform.ANDROID: SMARTYPE_IME, Platform.IOS: "SmarType"}


def test_runner_selects_the_keyboard_of_the_driver_platform(tmp_path):
    driver = FakeDeviceDriver(platform=Platform.IOS, evidence_dir=tmp_path)
    result = _run(driver, keyboard={"android": SMARTYPE_IME, "ios": "Emoji"})
    assert result.passed
    assert driver.selected_keyboards == ["Emoji"]
    assert driver.active_keyboard == "Emoji"


def test_runner_waits_for_the_selector_after_the_switch(tmp_path):
    driver = FakeDeviceDriver(evidence_dir=tmp_path)
    driver.set_hierarchy(UiNode(resource_id="keyboard_view"))
    result = _run(driver, keyboard=SMARTYPE_IME, selector={"resource_id": "keyboard_view"})
    assert result.passed
    assert result.timeline.events[0].assertion_results[0].passed


def test_runner_fails_when_the_selector_does_not_show(tmp_path):
    driver = FakeDeviceDriver(evidence_dir=tmp_path)
    driver.set_hierarchy(UiNode(resource_id="other"))
    result = _run(driver, keyboard=SMARTYPE_IME, selector={"resource_id": "keyboard_view"}, timeout_ms=10)
    assert not result.passed
    assert result.timeline.events[0].error.startswith("timed out: select_keyboard")


def test_runner_fails_when_the_driver_cannot_select_the_keyboard(tmp_path):
    driver = FakeDeviceDriver(evidence_dir=tmp_path, available_keyboards={"English (US)"})
    result = _run(driver, keyboard="SmarType")
    assert not result.passed
    assert result.timeline.events[0].error == "select_keyboard: no keyboard 'SmarType'"


def test_runner_fails_without_a_keyboard_for_the_platform(tmp_path):
    driver = FakeDeviceDriver(evidence_dir=tmp_path)
    result = _run(driver, keyboard={"ios": "SmarType"})
    assert not result.passed
    assert "no keyboard for platform 'android'" in result.timeline.events[0].error
    assert driver.selected_keyboards == []


@dataclass
class _NoKeyboardDriver(FakeDeviceDriver):
    """A driver without the `KeyboardDriver` capability."""

    select_keyboard = None  # type: ignore[assignment]


def test_runner_fails_clearly_when_the_driver_has_no_keyboard_capability(tmp_path):
    driver = _NoKeyboardDriver(evidence_dir=tmp_path)
    result = _run(driver, keyboard="SmarType")
    assert not result.passed
    assert result.timeline.events[0].error == "select_keyboard: the android driver cannot select a keyboard"
