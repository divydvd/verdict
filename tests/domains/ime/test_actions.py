import pytest

from verdict.core.exceptions import ElementNotFoundError, VerdictError
from verdict.core.models import RunContext, UiNode
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.domains.ime import actions  # noqa: F401  registers trigger_autocorrect etc.
from verdict.scenario_engine.runner import _ACTIONS
from verdict.scenario_engine.schema import StepSpec


def _ctx(driver: FakeDeviceDriver) -> RunContext:
    return RunContext(
        session_id="s1",
        run_id="r1",
        scenario_name="scenario",
        driver=driver,
        evidence_dir=driver.evidence_dir,
    )


def test_trigger_autocorrect_sends_space_as_key_event_not_paste():
    driver = FakeDeviceDriver()
    step = StepSpec(action="trigger_autocorrect")
    _ACTIONS["trigger_autocorrect"](driver, step, _ctx(driver))
    assert driver.typed_keys == [(" ", 150)]
    assert driver.typed_text == []


def _suggestion_strip() -> UiNode:
    return UiNode(
        resource_id="suggestion_strip",
        children=[
            UiNode(text="hello", bounds=(0, 0, 100, 50)),
            UiNode(text="world", bounds=(100, 0, 200, 50)),
        ],
    )


def test_select_suggestion_by_index_taps_center():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(_suggestion_strip())
    step = StepSpec(action="select_suggestion", args={"index": 1})
    _ACTIONS["select_suggestion"](driver, step, _ctx(driver))
    assert driver.tap_calls == [(150, 25)]


def test_select_suggestion_defaults_to_first():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(_suggestion_strip())
    step = StepSpec(action="select_suggestion")
    _ACTIONS["select_suggestion"](driver, step, _ctx(driver))
    assert driver.tap_calls == [(50, 25)]


def test_select_suggestion_by_text():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(_suggestion_strip())
    step = StepSpec(action="select_suggestion", args={"text": "world"})
    _ACTIONS["select_suggestion"](driver, step, _ctx(driver))
    assert driver.tap_calls == [(150, 25)]


def test_select_suggestion_missing_strip_raises():
    driver = FakeDeviceDriver()
    step = StepSpec(action="select_suggestion")
    with pytest.raises(ElementNotFoundError):
        _ACTIONS["select_suggestion"](driver, step, _ctx(driver))


def test_select_suggestion_index_out_of_range_raises():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(_suggestion_strip())
    step = StepSpec(action="select_suggestion", args={"index": 5})
    with pytest.raises(ElementNotFoundError):
        _ACTIONS["select_suggestion"](driver, step, _ctx(driver))


def test_select_suggestion_unknown_text_raises():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(_suggestion_strip())
    step = StepSpec(action="select_suggestion", args={"text": "nope"})
    with pytest.raises(ElementNotFoundError):
        _ACTIONS["select_suggestion"](driver, step, _ctx(driver))


def test_swipe_type_decomposes_points_into_swipe_segments():
    driver = FakeDeviceDriver()
    step = StepSpec(action="swipe_type", args={"points": [[0, 0], [10, 10], [20, 20]]})
    _ACTIONS["swipe_type"](driver, step, _ctx(driver))
    assert driver.swipe_calls == [(0, 0, 10, 10, 300), (10, 10, 20, 20, 300)]


def test_swipe_type_requires_at_least_two_points():
    driver = FakeDeviceDriver()
    step = StepSpec(action="swipe_type", args={"points": [[0, 0]]})
    with pytest.raises(VerdictError):
        _ACTIONS["swipe_type"](driver, step, _ctx(driver))
