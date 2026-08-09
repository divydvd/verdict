from pathlib import Path

import pytest

from verdict.core.exceptions import ScenarioValidationError
from verdict.scenario_engine.parser import parse_scenario

SCENARIO_YAML = """
name: ai_suggestion_appears_after_typo
covers:
  - "app/src/main/kotlin/bha/keys/smartype/ime/nlp/**"
tags: [smoke, ai_suggestions]
variables:
  target_app: bha.keys.smartype.debug
steps:
  - action: install
    path: ${apk_path}
  - action: launch
    package: ${target_app}
  - action: tap
    selector: { resource_id: "text_field" }
  - action: type_text
    text: "I recieve"
  - action: wait_for
    selector: { description: "ai_suggestion_chip" }
    timeout_ms: 2000
  - action: assert
    assertion: ai_suggestion_visible
  - action: assert
    assertion: latency_under
    args: { ms: 500 }
retries:
  max_attempts: 2
  backoff_ms: 500
evidence:
  on_failure: [screenshot, hierarchy]
  always: [screenshot]
"""


def test_parse_scenario_substitutes_variables(tmp_path: Path):
    scenario_file = tmp_path / "scenario.yaml"
    scenario_file.write_text(SCENARIO_YAML)

    spec = parse_scenario(scenario_file, variables={"apk_path": "/tmp/app.apk"})

    assert spec.name == "ai_suggestion_appears_after_typo"
    assert spec.steps[0].path == "/tmp/app.apk"
    assert spec.steps[1].package == "bha.keys.smartype.debug"
    assert spec.retries.max_attempts == 2
    assert spec.evidence.always == ["screenshot"]
    assert spec.steps[6].args == {"ms": 500}


def test_parse_scenario_missing_variable_raises(tmp_path: Path):
    scenario_file = tmp_path / "scenario.yaml"
    scenario_file.write_text(SCENARIO_YAML)

    with pytest.raises(ScenarioValidationError, match="apk_path"):
        parse_scenario(scenario_file)


def test_parse_scenario_invalid_schema_raises(tmp_path: Path):
    scenario_file = tmp_path / "bad.yaml"
    scenario_file.write_text("name: bad\nsteps: []\n")

    with pytest.raises(ScenarioValidationError):
        parse_scenario(scenario_file)


def test_parse_scenario_non_mapping_raises(tmp_path: Path):
    scenario_file = tmp_path / "list.yaml"
    scenario_file.write_text("- 1\n- 2\n")

    with pytest.raises(ScenarioValidationError, match="mapping"):
        parse_scenario(scenario_file)
