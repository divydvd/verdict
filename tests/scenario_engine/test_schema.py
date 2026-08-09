import pytest
from pydantic import ValidationError

from verdict.scenario_engine.schema import RetryPolicy, ScenarioSpec, StepSpec


def test_step_requires_action_specific_fields():
    with pytest.raises(ValidationError, match="missing required field"):
        StepSpec(action="tap")


def test_step_rejects_unknown_action():
    with pytest.raises(ValidationError, match="Unknown step action"):
        StepSpec(action="teleport")


def test_step_with_required_fields_is_valid():
    step = StepSpec(action="type_text", text="hello")
    assert step.text == "hello"
    assert step.timeout_ms == 5000


def test_scenario_requires_at_least_one_step():
    with pytest.raises(ValidationError, match="at least one step"):
        ScenarioSpec(name="empty", steps=[])


def test_scenario_defaults():
    spec = ScenarioSpec(name="s", steps=[StepSpec(action="type_text", text="hi")])
    assert spec.retries == RetryPolicy(max_attempts=1, backoff_ms=0)
    assert spec.covers == []
    assert spec.tags == []
