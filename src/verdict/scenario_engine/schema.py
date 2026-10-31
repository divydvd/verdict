from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from verdict.core.exceptions import VerdictError
from verdict.core.models import Direction, KeyInput, Platform, Selector, normalize_key

_PLATFORM_KEYS = frozenset(platform.value for platform in Platform)


class MissingPlatformValueError(VerdictError):
    """The step has per-platform values, but none for the driver platform."""


class MissingPlatformSelectorError(MissingPlatformValueError):
    """The step has per-platform selectors, but none for the driver platform."""

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
    "select_keyboard": ("keyboard",),
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
    """One scenario step.

    `selector` has two forms. The plain form applies to all platforms:
    `selector: {resource_id: "send"}`. The per-platform form has one
    selector for each platform: `selector: {android: {...}, ios: {...}}`.
    The parser moves the per-platform form into `selector_variants`. The
    runner calls `for_platform()` to put the variant for the driver platform
    into `selector` before it runs the step.
    """

    action: str
    selector: Selector | None = None
    selector_variants: dict[Platform, Selector] | None = None
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
    # `select_keyboard` only: the keyboard to select. The plain form applies to
    # all platforms. The per-platform form is `{android: IME_ID, ios: NAME}`.
    keyboard: str | dict[Platform, str] | None = None

    @model_validator(mode="before")
    @classmethod
    def _split_platform_selector(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        selector = data.get("selector")
        if not isinstance(selector, dict) or not _PLATFORM_KEYS.intersection(selector):
            return data
        unknown = sorted(str(key) for key in selector if key not in _PLATFORM_KEYS)
        if unknown:
            raise ValueError(
                f"a per-platform selector can have only platform keys "
                f"({', '.join(sorted(_PLATFORM_KEYS))}); unknown key(s): {', '.join(unknown)}"
            )
        if data.get("selector_variants") is not None:
            raise ValueError("give the per-platform selectors in 'selector' only")
        return {**data, "selector": None, "selector_variants": selector}

    @model_validator(mode="after")
    def _validate_required_fields(self) -> StepSpec:
        required = _REQUIRED_FIELDS.get(self.action)
        if required is None:
            known = ", ".join(sorted(_REQUIRED_FIELDS))
            raise ValueError(f"Unknown step action '{self.action}'. Known actions: {known}")
        if self.selector is not None and self.selector_variants is not None:
            raise ValueError("a step can have 'selector' or 'selector_variants', not both")
        if self.selector_variants is not None and not self.selector_variants:
            raise ValueError("'selector_variants' must have at least one platform")
        if isinstance(self.keyboard, dict) and not self.keyboard:
            raise ValueError("a per-platform 'keyboard' must have at least one platform")
        keyboard_names = self.keyboard.values() if isinstance(self.keyboard, dict) else [self.keyboard]
        if any(name is not None and not name.strip() for name in keyboard_names):
            raise ValueError("'keyboard' must not be empty")
        missing = [
            field
            for field in required
            if getattr(self, field) is None
            and not (field == "selector" and self.selector_variants is not None)
        ]
        if missing:
            raise ValueError(
                f"step action '{self.action}' is missing required field(s): {', '.join(missing)}"
            )
        return self

    def for_platform(self, platform: Platform) -> StepSpec:
        """Return this step with the values for `platform`: the selector in
        `selector`, and the keyboard name in `keyboard`.

        A step with no per-platform values does not change. Raises
        `MissingPlatformSelectorError` when the step has per-platform
        selectors, but none for `platform`. Raises `MissingPlatformValueError`
        when the step has a per-platform keyboard, but none for `platform`.
        """
        update: dict[str, Any] = {}
        if self.selector_variants is not None:
            variant = self.selector_variants.get(platform)
            if variant is None:
                given = ", ".join(sorted(p.value for p in self.selector_variants))
                raise MissingPlatformSelectorError(
                    f"step action '{self.action}' has no selector for platform "
                    f"'{platform.value}' (it has: {given})"
                )
            update.update(selector=variant, selector_variants=None)
        if isinstance(self.keyboard, dict):
            keyboard = self.keyboard.get(platform)
            if keyboard is None:
                given = ", ".join(sorted(p.value for p in self.keyboard))
                raise MissingPlatformValueError(
                    f"step action '{self.action}' has no keyboard for platform "
                    f"'{platform.value}' (it has: {given})"
                )
            update["keyboard"] = keyboard
        return self.model_copy(update=update) if update else self


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
    # The platforms that the scenario supports. None means all platforms.
    platforms: list[Platform] | None = None
    steps: list[StepSpec]
    retries: RetryPolicy = Field(default_factory=RetryPolicy)
    evidence: EvidencePolicy = Field(default_factory=EvidencePolicy)

    @model_validator(mode="after")
    def _non_empty_steps(self) -> ScenarioSpec:
        if not self.steps:
            raise ValueError("scenario must have at least one step")
        if self.platforms is not None and not self.platforms:
            raise ValueError("'platforms' must have at least one platform; remove it for all platforms")
        return self

    def supports(self, platform: Platform) -> bool:
        return self.platforms is None or platform in self.platforms
