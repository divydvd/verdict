import xml.etree.ElementTree as ET

import pytest

from tests.device_driver.fake_appium import FIXTURE_XML
from verdict.core.models import Selector
from verdict.device_driver.ios_hierarchy import parse_ios_hierarchy, parse_ios_hierarchy_xml


def test_parse_maps_xcuitest_attributes():
    hierarchy = parse_ios_hierarchy(FIXTURE_XML)

    assert hierarchy.raw_xml == FIXTURE_XML
    assert hierarchy.root is not None
    assert hierarchy.root.class_name == "XCUIElementTypeApplication"
    field = hierarchy.find(Selector(resource_id="messageField"))
    assert field is not None
    assert field.text == "Hello"
    assert field.content_desc == "Message"
    assert field.class_name == "XCUIElementTypeTextField"
    assert field.bounds == (16, 100, 374, 144)
    assert not field.checkable


def test_text_falls_back_to_label_when_value_is_missing():
    button = parse_ios_hierarchy(FIXTURE_XML).find(Selector(resource_id="sendButton"))
    assert button is not None
    assert button.text == "Send"
    assert button.content_desc == "Send"


def test_switch_value_maps_to_checked():
    hierarchy = parse_ios_hierarchy(FIXTURE_XML)
    on = hierarchy.find(Selector(resource_id="autocorrectSwitch"))
    off = hierarchy.find(Selector(resource_id="soundSwitch"))
    assert on is not None and off is not None
    assert on.checkable and on.checked
    assert off.checkable and not off.checked
    assert on.text == "Autocorrect"


def test_several_top_level_elements_go_under_a_synthetic_root():
    root = parse_ios_hierarchy_xml(
        '<AppiumAUT><XCUIElementTypeApplication type="XCUIElementTypeApplication"/>'
        '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="Springboard"/>'
        "</AppiumAUT>"
    )
    assert root is not None
    assert root.class_name == "hierarchy"
    assert len(root.children) == 2


def test_empty_source_has_no_root():
    assert parse_ios_hierarchy_xml("<AppiumAUT/>") is None


def test_source_without_appium_root_is_parsed_directly():
    root = parse_ios_hierarchy_xml('<XCUIElementTypeOther type="XCUIElementTypeOther" x="1" y="2" width="3" height="4"/>')
    assert root is not None
    assert root.bounds == (1, 2, 4, 6)


def test_missing_or_bad_geometry_gives_no_bounds():
    root = parse_ios_hierarchy_xml('<XCUIElementTypeOther x="a" y="0" width="1" height="1"/>')
    assert root is not None
    assert root.bounds is None
    assert root.class_name == "XCUIElementTypeOther"


def test_bad_xml_raises_parse_error():
    with pytest.raises(ET.ParseError):
        parse_ios_hierarchy_xml("<AppiumAUT>")
