from __future__ import annotations

import xml.etree.ElementTree as ET

from verdict.core.models import UiHierarchy, UiNode

# The root element of an Appium XCUITest page source.
_APPIUM_ROOT_TAG = "AppiumAUT"

# XCUITest element types that show an on/off state in their `value` ("1" or "0").
SWITCH_TYPES = frozenset({"XCUIElementTypeSwitch", "XCUIElementTypeToggle"})


def _int_attr(attrib: dict[str, str], name: str) -> int | None:
    raw = attrib.get(name)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_bounds(attrib: dict[str, str]) -> tuple[int, int, int, int] | None:
    x, y = _int_attr(attrib, "x"), _int_attr(attrib, "y")
    width, height = _int_attr(attrib, "width"), _int_attr(attrib, "height")
    if x is None or y is None or width is None or height is None:
        return None
    return (x, y, x + width, y + height)


def _node_from_element(element: ET.Element) -> UiNode:
    attrib = element.attrib
    class_name = attrib.get("type") or element.tag or None
    label = attrib.get("label") or None
    value = attrib.get("value") or None
    checkable = class_name in SWITCH_TYPES
    # The value of a switch is its state, not its text. Use the label as the text.
    text = label if checkable else (value or label)
    return UiNode(
        resource_id=attrib.get("name") or None,
        text=text,
        content_desc=label,
        class_name=class_name,
        bounds=_parse_bounds(attrib),
        checkable=checkable,
        checked=checkable and value == "1",
        children=[_node_from_element(child) for child in element],
    )


def parse_ios_hierarchy_xml(raw_xml: str) -> UiNode | None:
    """Parse an XCUITest page source into a `UiNode` tree.

    The attributes map as follows: `name` to `resource_id`, `label` to
    `content_desc`, `value` (or else `label`) to `text`, `type` to
    `class_name`, and `x`, `y`, `width`, `height` to `bounds`. A switch is
    checkable. Its `value` "1" means checked. Returns None when the page
    source has no element.

    Appium puts the application under an `AppiumAUT` root. With one child,
    that child is the root. With more than one child, all of them go under a
    synthetic root with no attributes.
    """
    root = ET.fromstring(raw_xml)
    if root.tag != _APPIUM_ROOT_TAG:
        return _node_from_element(root)
    children = [_node_from_element(element) for element in root]
    if not children:
        return None
    if len(children) == 1:
        return children[0]
    return UiNode(class_name="hierarchy", children=children)


def parse_ios_hierarchy(raw_xml: str) -> UiHierarchy:
    """Return a `UiHierarchy` for an XCUITest page source."""
    return UiHierarchy(raw_xml=raw_xml, root=parse_ios_hierarchy_xml(raw_xml))
