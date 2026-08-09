from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Platform(str, Enum):
    ANDROID = "android"
    IOS = "ios"          # reserved, no implementation until Phase 4
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

    def find_all(self, selector: Selector) -> list[UiNode]:
        if self.root is None:
            return []
        return self.root.find_all(selector)


class RecordingHandle(BaseModel):
    recording_id: str
    started_at: datetime


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
