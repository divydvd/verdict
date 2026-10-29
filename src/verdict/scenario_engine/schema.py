from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from verdict.core.models import Direction, KeyInput, Selector, normalize_key

# One entry per action name: the StepSpec fields that must be non-None for
# that action. Mirrors the DeviceDriver protocol methods 1:1 (plus `assert`
# for invoking the Assertion Library) so the mapping stays obvious rather
# than needing a bespoke per-action step subclass.
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "install": ("path",),
    "uninstall": ("package",),
    "launch": ("package",),
    "clear_data": ("package",),
    "tap": ("selector",),
    "type_text": ("text",),
    "type_keys": ("text",),
    "swipe": ("x1", "y1", "x2", "y2"),
    "scroll": ("direction",),
    "press_key": ("key",),
    "wait_for": ("selector",),
    "ensure_checked": ("selector", "checked"),
    "assert": ("assertion",),
}


def register_action(name: str, required_fields: tuple[str, ...] = ()) -> None:
    """Extend the known step-action vocabulary. Lets a domain plugin bundle
    (e.g. `domains/ime/actions.py`) add its own action names at import time
    without `scenario_engine` depending on any domain package — the
    dependency points the other way, as it must (domains sit above the
    engine, see docs/architecture.md §6.2, §6.4).
    """
    if name in _REQUIRED_FIELDS:
        raise ValueError(f"action '{name}' is already registered")
    _REQUIRED_FIELDS[name] = required_fields


class StepSpec(BaseModel):
    action: str
    selector: Selector | None = None
    text: str | None = None
    path: str | None = None
    package: str | None = None
    activity: str | None = None
    timeout_ms: int = 5000
    assertion: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    x1: int | None = None
    y1: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int = 300
    interval_ms: int = Field(default=150, ge=0)
    # `assert` only: re-check a failed assertion after a pause, so a fast UI
    # transition does not give a false failure. 0 attempts turns this off.
    settle_ms: int = Field(default=300, ge=0)
    settle_attempts: int = Field(default=2, ge=0)
    direction: Direction | None = None
    # A named KeyEvent ("enter") or any platform key code (18, "KEYCODE_POUND").
    key: Annotated[KeyInput, BeforeValidator(normalize_key)] | None = None
    # `ensure_checked` only: the wanted state of a switch or a check box.
    checked: bool | None = None

    @model_validator(mode="after")
    def _validate_required_fields(self) -> StepSpec:
        required = _REQUIRED_FIELDS.get(self.action)
        if required is None:
            known = ", ".join(sorted(_REQUIRED_FIELDS))
            raise ValueError(f"Unknown step action '{self.action}'. Known actions: {known}")
        missing = [field for field in required if getattr(self, field) is None]
        if missing:
            raise ValueError(
                f"step action '{self.action}' is missing required field(s): {', '.join(missing)}"
            )
        return self


class RetryPolicy(BaseModel):
    max_attempts: int = 1
    backoff_ms: int = 0


class EvidencePolicy(BaseModel):
    on_failure: list[str] = Field(default_factory=list)
    always: list[str] = Field(default_factory=list)


class ScenarioSpec(BaseModel):
    name: str
    covers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    steps: list[StepSpec]
    retries: RetryPolicy = Field(default_factory=RetryPolicy)
    evidence: EvidencePolicy = Field(default_factory=EvidencePolicy)

    @model_validator(mode="after")
    def _non_empty_steps(self) -> ScenarioSpec:
        if not self.steps:
            raise ValueError("scenario must have at least one step")
        return self
