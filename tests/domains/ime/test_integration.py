"""End-to-end proof that the domains/ime plugin bundle wires cleanly into
run_scenario(): its actions extend the step vocabulary via
schema.register_action/runner.register_action_handler, and its assertions
are reachable through the standard `assert` step, exactly like builtins.
"""

from verdict.core.models import UiNode
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.domains.ime import actions, assertions  # noqa: F401  self-register
from verdict.scenario_engine.runner import run_scenario
from verdict.scenario_engine.schema import ScenarioSpec, StepSpec


def test_ime_scenario_runs_end_to_end_through_run_scenario():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(
        UiNode(
            resource_id="keyboard_view",
            children=[UiNode(resource_id="text_field", text="I received ")],
        )
    )
    spec = ScenarioSpec(
        name="ime-e2e",
        steps=[
            StepSpec(action="tap", selector={"resource_id": "text_field"}),
            StepSpec(action="type_keys", text="I recieve"),
            StepSpec(action="trigger_autocorrect"),
            StepSpec(action="assert", assertion="keyboard_visible"),
            StepSpec(action="assert", assertion="text_inserted", args={"text": "received"}),
        ],
    )

    result = run_scenario(spec, driver, session_id="s1")

    assert result.passed is True
    assert driver.typed_keys == [("I recieve", 150), (" ", 150)]
    assert driver.typed_text == []
