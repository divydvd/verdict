import pytest
from pydantic import ValidationError

from verdict.core.models import Selector, UiHierarchy, UiNode


def test_selector_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        Selector()


def test_selector_accepts_single_field():
    Selector(resource_id="suggestion_chip")


def test_uinode_matches_on_resource_id():
    node = UiNode(resource_id="suggestion_chip", text="will")
    assert node.matches(Selector(resource_id="suggestion_chip"))
    assert not node.matches(Selector(resource_id="other_id"))


def test_uinode_matches_requires_all_specified_fields():
    node = UiNode(resource_id="suggestion_chip", text="will")
    assert not node.matches(Selector(resource_id="suggestion_chip", text="wild"))
    assert node.matches(Selector(resource_id="suggestion_chip", text="will"))


def test_hierarchy_find_walks_children():
    root = UiNode(
        class_name="root",
        children=[
            UiNode(class_name="row", children=[UiNode(resource_id="target", text="hi")]),
        ],
    )
    hierarchy = UiHierarchy(raw_xml="<xml/>", root=root)
    found = hierarchy.find(Selector(resource_id="target"))
    assert found is not None
    assert found.text == "hi"


def test_hierarchy_find_returns_none_when_missing():
    hierarchy = UiHierarchy(raw_xml="<xml/>", root=UiNode(class_name="root"))
    assert hierarchy.find(Selector(resource_id="missing")) is None


def test_hierarchy_find_all_returns_every_match():
    root = UiNode(
        class_name="root",
        children=[
            UiNode(class_name="chip", resource_id="suggestion"),
            UiNode(class_name="chip", resource_id="suggestion"),
            UiNode(class_name="chip", resource_id="other"),
        ],
    )
    hierarchy = UiHierarchy(raw_xml="<xml/>", root=root)
    matches = hierarchy.find_all(Selector(resource_id="suggestion"))
    assert len(matches) == 2


def test_hierarchy_find_on_empty_root_returns_none():
    hierarchy = UiHierarchy(raw_xml="<xml/>", root=None)
    assert hierarchy.find(Selector(resource_id="anything")) is None
    assert hierarchy.find_all(Selector(resource_id="anything")) == []
