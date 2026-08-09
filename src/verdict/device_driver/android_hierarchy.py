from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from verdict.core.models import UiNode

_BOUNDS_PATTERN = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
    match = _BOUNDS_PATTERN.match(raw)
    if match is None:
        return None
    left, top, right, bottom = (int(group) for group in match.groups())
    return (left, top, right, bottom)


def _node_from_element(element: ET.Element) -> UiNode:
    attrib = element.attrib
    return UiNode(
        resource_id=attrib.get("resource-id") or None,
        text=attrib.get("text") or None,
        content_desc=attrib.get("content-desc") or None,
        class_name=attrib.get("class") or None,
        bounds=_parse_bounds(attrib.get("bounds", "")),
        children=[_node_from_element(child) for child in element],
    )


def parse_hierarchy_xml(raw_xml: str) -> UiNode | None:
    """Parse a `uiautomator dump`-style hierarchy XML (`<hierarchy><node.../></hierarchy>`)
    into a `UiNode` tree. Returns None if the hierarchy has no root node.
    """
    hierarchy_element = ET.fromstring(raw_xml)
    root_element = next(iter(hierarchy_element), None)
    if root_element is None:
        return None
    return _node_from_element(root_element)
