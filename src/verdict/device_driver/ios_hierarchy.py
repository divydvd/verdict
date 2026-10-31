from __future__ import annotations

import xml.etree.ElementTree as ET

from verdict.core.models import Selector, UiHierarchy, UiNode

# The root element of an Appium XCUITest page source.
_APPIUM_ROOT_TAG = "AppiumAUT"

# XCUITest element types that show an on/off state in their `value` ("1" or "0").
SWITCH_TYPES = frozenset({"XCUIElementTypeSwitch", "XCUIElementTypeToggle"})

# XCUITest element types that report their placeholder as the value when empty.
TEXT_INPUT_TYPES = frozenset({
    "XCUIElementTypeTextField",
    "XCUIElementTypeSecureTextField",
    "XCUIElementTypeSearchField",
    "XCUIElementTypeTextView",
})


class IosUiNode(UiNode):
    """A `UiNode` from an XCUITest page source. A `text` selector matches the
    text or the label, like the live locator (`label OR value`)."""

    def matches(self, selector: Selector) -> bool:
        if selector.text is None or selector.text not in (self.text, self.content_desc):
            return super().matches(selector)
        return super().matches(selector.model_copy(update={"text": None}))


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
    text: str | None
    if checkable:
        # The value of a switch is its state, not its text. Use the label as the text.
        text = label
    elif class_name in TEXT_INPUT_TYPES and (
        value is None or value == attrib.get("placeholderValue")
    ):
        # A text field with no value is empty. Its label is not its text.
        # An empty text field can also report its placeholder as its value. When the
        # typed text equals the placeholder, the parser cannot tell the two
        # apart and gives an empty text. A false FAIL is safer than a false PASS.
        text = ""
    else:
        text = value or label
    return IosUiNode(
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
    `class_name`, and `x`, `y`, `width`, `height` to `bounds`. A text field
    with no `value`, or with its `placeholderValue` as its value, has an
    empty text. The label stays in `content_desc`. If the
    typed text equals the placeholder, the parser cannot tell, and also gives
    an empty text. A false FAIL is safer than a false PASS. A `text` selector
    matches the text or the label (`content_desc`), like the live locator. A switch is
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
    return IosUiNode(class_name="hierarchy", children=children)


def parse_ios_hierarchy(raw_xml: str) -> UiHierarchy:
    """Return a `UiHierarchy` for an XCUITest page source."""
    return UiHierarchy(raw_xml=raw_xml, root=parse_ios_hierarchy_xml(raw_xml))
