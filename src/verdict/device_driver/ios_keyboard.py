"""Read the iOS keyboard list (the globe-key menu) from an XCUITest page source.

A long press on the globe key ("Next keyboard") shows a table of the keyboards
that are on. Each keyboard is a cell. The cell label is the keyboard name, and
for some keyboards also a subtitle ("SmarType, English"). The first static
text in the cell is the name only. The cell of the active keyboard has the
`Selected` trait. Tested on iOS 26.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from verdict.core.exceptions import DriverError

GLOBE_KEY_NAMES = ("Next keyboard", "next_keyboard_key")
"""The system globe key first, then the name that a keyboard extension gives
its own globe key (see docs/ime-selector-contract.md)."""

KEYBOARD_TABLE_NAME = "InputSwitcherTable"
_KEYBOARD_VIEW_NAME = "InputSwitcherView"
_DISMISS_REGION_NAME = "PopoverDismissRegion"
_CELL = "XCUIElementTypeCell"
_STATIC_TEXT = "XCUIElementTypeStaticText"

Bounds = tuple[int, int, int, int]


@dataclass(frozen=True)
class KeyboardMenuItem:
    label: str
    title: str
    selected: bool

    def matches(self, name: str) -> bool:
        return name in (self.title, self.label)


@dataclass(frozen=True)
class KeyboardMenu:
    items: tuple[KeyboardMenuItem, ...]
    dismiss_point: tuple[int, int] | None

    @property
    def active(self) -> KeyboardMenuItem | None:
        return next((item for item in self.items if item.selected), None)

    def names(self) -> str:
        return ", ".join(f"'{item.title}'" for item in self.items) or "(none)"

    def pick(self, name: str) -> KeyboardMenuItem:
        """Return the one item that `name` matches: its title or its full label."""
        exact = [item for item in self.items if item.label == name]
        found = exact or [item for item in self.items if item.matches(name)]
        if not found:
            raise DriverError(
                f"select_keyboard: no keyboard '{name}' in the globe-key list. "
                f"The list has: {self.names()}. Turn the keyboard on in "
                "Settings > General > Keyboard > Keyboards."
            )
        if len(found) > 1:
            labels = ", ".join(f"'{item.label}'" for item in found)
            raise DriverError(
                f"select_keyboard: more than one keyboard matches '{name}': {labels}. "
                "Give the full label."
            )
        return found[0]


def _bounds(element: ET.Element) -> Bounds | None:
    try:
        x, y = int(float(element.attrib["x"])), int(float(element.attrib["y"]))
        width, height = int(float(element.attrib["width"])), int(float(element.attrib["height"]))
    except (KeyError, ValueError):
        return None
    return (x, y, x + width, y + height)


def _find_named(root: ET.Element, name: str) -> ET.Element | None:
    return next((element for element in root.iter() if element.get("name") == name), None)


def _item(cell: ET.Element) -> KeyboardMenuItem | None:
    label = cell.get("label")
    if not label:
        return None
    texts = (element.get("value") or element.get("label") for element in cell.iter(_STATIC_TEXT))
    title = next((text for text in texts if text), label)
    traits = {trait.strip() for trait in (cell.get("traits") or "").split(",")}
    return KeyboardMenuItem(label=label, title=title, selected="Selected" in traits)


def _dismiss_point(root: ET.Element) -> tuple[int, int] | None:
    """A point in the dismiss region, in the largest gap above or below the list."""
    region, view = _find_named(root, _DISMISS_REGION_NAME), _find_named(root, _KEYBOARD_VIEW_NAME)
    region_bounds = _bounds(region) if region is not None else None
    view_bounds = _bounds(view) if view is not None else None
    if region_bounds is None or view_bounds is None:
        return None
    left, top, right, bottom = region_bounds
    above, below = view_bounds[1] - top, bottom - view_bounds[3]
    y = top + above // 2 if above >= below else view_bounds[3] + below // 2
    return ((left + right) // 2, y)


def parse_keyboard_menu(raw_xml: str) -> KeyboardMenu | None:
    """Return the keyboard list in `raw_xml`, or None when the list is not open."""
    root = ET.fromstring(raw_xml)
    table = _find_named(root, KEYBOARD_TABLE_NAME)
    if table is None:
        return None
    items = tuple(item for cell in table.iter(_CELL) if (item := _item(cell)) is not None)
    return KeyboardMenu(items=items, dismiss_point=_dismiss_point(root))
