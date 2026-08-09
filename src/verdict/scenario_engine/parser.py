from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from verdict.core.exceptions import ScenarioValidationError
from verdict.scenario_engine.schema import ScenarioSpec

_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _substitute(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                raise ScenarioValidationError(
                    f"Undefined variable '${{{name}}}' referenced in scenario"
                )
            return variables[name]

        return _VAR_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _substitute(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, variables) for item in value]
    return value


def parse_scenario(path: Path, variables: dict[str, str] | None = None) -> ScenarioSpec:
    """Load and validate a scenario YAML file, resolving `${var}` references.

    `variables` are external overrides (e.g. `apk_path` supplied by the
    caller) layered on top of the scenario's own `variables:` block;
    external values win on conflict.
    """
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ScenarioValidationError(f"Scenario file {path} did not parse to a YAML mapping")

    declared_variables = raw.get("variables") or {}
    if not isinstance(declared_variables, dict):
        raise ScenarioValidationError(f"'variables' in {path} must be a mapping")
    merged_variables = {**declared_variables, **(variables or {})}

    substituted = _substitute(raw, merged_variables)
    substituted["variables"] = merged_variables

    try:
        return ScenarioSpec.model_validate(substituted)
    except ValidationError as exc:
        raise ScenarioValidationError(f"Invalid scenario {path}: {exc}") from exc
