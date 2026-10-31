from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Platform(str, Enum):
    ANDROID = "android"
    IOS = "ios"          # IosAppiumDriver, see ADR-0009
    DESKTOP = "desktop"  # reserved, no implementation planned
    WEB = "web"          # reserved, no implementation planned


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class KeyEvent(str, Enum):
    BACK = "back"
    HOME = "home"
    ENTER = "enter"
    DELETE = "delete"
    TAB = "tab"


KeyInput = KeyEvent | int | str
"""A key for `press_key`: a named `KeyEvent`, or any platform key code as a
number (`18`) or a name (`KEYCODE_POUND`, or `POUND`)."""

_KEY_NAME = re.compile(r"[A-Za-z0-9_]+")


def normalize_key(value: object) -> KeyInput:
    """Validate a key and return its canonical form: a `KeyEvent` for the
    named keys ("enter", "back", ...), an `int` for a numeric key code, or an
    upper-case key name. Raises `ValueError` for anything else.
    """
    if isinstance(value, KeyEvent):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value < 0:
            raise ValueError(f"key code must be 0 or more, got {value}")
        return value
    if isinstance(value, str):
        name = value.strip()
        if name.isdigit():
            return int(name)
        try:
            return KeyEvent(name.lower())
        except ValueError:
            pass
        if not _KEY_NAME.fullmatch(name):
            raise ValueError(f"key name may use only letters, digits, and '_', got {value!r}")
        return name.upper()
    raise ValueError(f"key must be a KeyEvent, a key code number, or a key name, got {value!r}")


class Selector(BaseModel):
    """Describes a UI element to locate. At least one field must be set.

    Field semantics mirror what Android UiAutomator exposes (resource-id,
    text, content-description, class name) so it maps directly onto both
    uiautomator2 kwargs and UiHierarchy node matching.
    """

    resource_id: str | None = None
    text: str | None = None
    description: str | None = None
    class_name: str | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> Selector:
        if not any((self.resource_id, self.text, self.description, self.class_name)):
            raise ValueError("Selector requires at least one of: resource_id, text, description, class_name")
        return self


class UiNode(BaseModel):
    resource_id: str | None = None
    text: str | None = None
    content_desc: str | None = None
    class_name: str | None = None
    bounds: tuple[int, int, int, int] | None = None
    checkable: bool = False
    checked: bool = False
    children: list[UiNode] = Field(default_factory=list)

    def matches(self, selector: Selector) -> bool:
        return (
            (selector.resource_id is None or self.resource_id == selector.resource_id)
            and (selector.text is None or self.text == selector.text)
            and (selector.description is None or self.content_desc == selector.description)
            and (selector.class_name is None or self.class_name == selector.class_name)
        )

    def find_all(self, selector: Selector) -> list[UiNode]:
        matches: list[UiNode] = []
        if self.matches(selector):
            matches.append(self)
        for child in self.children:
            matches.extend(child.find_all(selector))
        return matches

    def find_checkable(self, selector: Selector) -> tuple[UiNode | None, UiNode | None]:
        """Return the first node that matches `selector`, and the checkable node
        for it: the node itself or its nearest checkable ancestor. A Compose
        row with `Modifier.toggleable` can hold the matched text as a child.
        """
        if self.matches(selector):
            return self, self if self.checkable else None
        for child in self.children:
            found, checkable = child.find_checkable(selector)
            if found is not None:
                if checkable is None and self.checkable:
                    checkable = self
                return found, checkable
        return None, None

    def find(self, selector: Selector) -> UiNode | None:
        if self.matches(selector):
            return self
        for child in self.children:
            found = child.find(selector)
            if found is not None:
                return found
        return None


UiNode.model_rebuild()


class UiHierarchy(BaseModel):
    raw_xml: str
    root: UiNode | None = None

    def find(self, selector: Selector) -> UiNode | None:
        if self.root is None:
            return None
        return self.root.find(selector)

    def find_checkable(self, selector: Selector) -> tuple[UiNode | None, UiNode | None]:
        if self.root is None:
            return None, None
        return self.root.find_checkable(selector)

    def find_all(self, selector: Selector) -> list[UiNode]:
        if self.root is None:
            return []
        return self.root.find_all(selector)


class RecordingHandle(BaseModel):
    recording_id: str
    started_at: datetime


class EvidenceRef(BaseModel):
    kind: str
    path: Path


class AssertionResult(BaseModel):
    passed: bool
    message: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    timestamp: datetime
    step_id: str
    action: str
    passed: bool
    error: str | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    assertion_results: list[AssertionResult] = Field(default_factory=list)


class Timeline(BaseModel):
    run_id: str
    scenario_name: str
    events: list[TimelineEvent] = Field(default_factory=list)


class RunContext(BaseModel):
    """Per-session execution context threaded through a scenario run and
    passed to every Assertion.check(ctx).

    `driver` is typed `Any` rather than `DeviceDriver` deliberately:
    device_driver.base depends on core.models (Selector, UiHierarchy), so
    typing this field as DeviceDriver would create a core <-> device_driver
    import cycle. Callers get the real DeviceDriver back at the type level
    by constructing RunContext through the Scenario Engine, which is
    already typed against DeviceDriver.

    Does not hold a Timeline/EvidenceCollector reference — those are
    constructed by the Scenario Engine (M1.3) and Evidence Collector
    (M1.5) and passed alongside RunContext.
    """

    model_config = {"arbitrary_types_allowed": True}

    session_id: str
    run_id: str
    scenario_name: str
    driver: Any
    variables: dict[str, str] = Field(default_factory=dict)
    evidence_dir: Path
    last_action_duration_ms: float | None = None
