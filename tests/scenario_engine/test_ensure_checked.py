from verdict.core.models import Selector, UiNode
from verdict.device_driver.android_hierarchy import parse_hierarchy_xml
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.scenario_engine.runner import run_scenario
from verdict.scenario_engine.schema import ScenarioSpec, StepSpec


class _SwitchDriver(FakeDeviceDriver):
    """A tap on the matched element flips the switch, like a Compose
    `Modifier.toggleable` row. `flips=False` simulates a tap with no effect."""

    def __init__(self, switch: UiNode, root: UiNode, flips: bool = True) -> None:
        super().__init__()
        self.switch = switch
        self.flips = flips
        self.set_hierarchy(root)

    def tap_selector(self, selector: Selector) -> None:
        super().tap_selector(selector)
        if self.flips:
            self.switch.checked = not self.switch.checked


def _row(checked: bool, checkable: bool = True) -> UiNode:
    # The merged toggleable row holds the title text as a child node.
    return UiNode(
        class_name="android.view.View",
        checkable=checkable,
        checked=checked,
        bounds=(0, 900, 1080, 1100),
        children=[UiNode(text="Auto-correct", bounds=(40, 920, 600, 980))],
    )


def _run(driver: FakeDeviceDriver, checked: bool):
    step = StepSpec(action="ensure_checked", selector={"text": "Auto-correct"}, checked=checked, settle_ms=0)
    return run_scenario(ScenarioSpec(name="ensure", steps=[step]), driver, session_id="s", evidence_dir=driver.evidence_dir)


def test_already_on_does_not_tap():
    row = _row(checked=True)
    driver = _SwitchDriver(row, UiNode(children=[row]))
    result = _run(driver, checked=True)
    assert result.passed
    assert driver.tap_calls == []
    assert row.checked is True


def test_off_taps_once_and_reads_on():
    row = _row(checked=False)
    driver = _SwitchDriver(row, UiNode(children=[row]))
    result = _run(driver, checked=True)
    assert result.passed
    assert len(driver.tap_calls) == 1
    assert row.checked is True


def test_can_turn_a_switch_off():
    row = _row(checked=True)
    driver = _SwitchDriver(row, UiNode(children=[row]))
    assert _run(driver, checked=False).passed
    assert row.checked is False


def test_fails_when_the_tap_does_not_change_the_state():
    row = _row(checked=False)
    driver = _SwitchDriver(row, UiNode(children=[row]), flips=False)
    result = _run(driver, checked=True)
    assert not result.passed
    assert "still False" in (result.timeline.events[-1].error or "")


def test_fails_clearly_when_the_element_is_not_checkable():
    row = _row(checked=False, checkable=False)
    driver = _SwitchDriver(row, UiNode(children=[row]))
    result = _run(driver, checked=True)
    assert not result.passed
    assert "not checkable" in (result.timeline.events[-1].error or "")
    assert driver.tap_calls == []


def test_parser_reads_checkable_and_checked():
    root = parse_hierarchy_xml(
        '<hierarchy><node class="android.view.View" checkable="true" checked="true" bounds="[0,0][10,10]">'
        '<node text="Auto-correct" checkable="false" checked="false" bounds="[0,0][5,5]"/></node></hierarchy>'
    )
    assert root is not None
    assert (root.checkable, root.checked) == (True, True)
    assert (root.children[0].checkable, root.children[0].checked) == (False, False)
