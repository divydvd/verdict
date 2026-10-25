from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable

from verdict.core.exceptions import DriverError
from verdict.core.models import UiHierarchy, UiNode

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


def dump_with_retry(
    dump: Callable[[], str],
    *,
    attempts: int,
    pause_s: float,
    sleep: Callable[[float], None],
    retry_on: tuple[type[Exception], ...],
) -> UiHierarchy:
    """Dump and parse the hierarchy. Right after a fast Compose transition the
    dump can fail or come back with no root node. Pause `pause_s` and dump
    again, up to `attempts` dumps in total. Raises `DriverError` when every
    dump fails; returns the last empty hierarchy when every dump is empty.
    """
    retryable: tuple[type[Exception], ...] = (ET.ParseError, *retry_on)
    last_error: Exception | None = None
    hierarchy: UiHierarchy | None = None
    for attempt in range(max(1, attempts)):
        if attempt:
            sleep(pause_s)
        try:
            raw_xml = dump()
            hierarchy = UiHierarchy(raw_xml=raw_xml, root=parse_hierarchy_xml(raw_xml))
        except retryable as exc:
            last_error = exc
            continue
        if hierarchy.root is not None:
            return hierarchy
    if hierarchy is not None:
        return hierarchy
    raise DriverError(f"hierarchy dump failed after {max(1, attempts)} attempt(s): {last_error}")
