import pytest
from pydantic import ValidationError

from verdict.core.models import KeyEvent, Selector, UiHierarchy, UiNode, normalize_key


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (KeyEvent.BACK, KeyEvent.BACK),
        ("enter", KeyEvent.ENTER),
        ("DELETE", KeyEvent.DELETE),
        (18, 18),
        ("18", 18),
        ("KEYCODE_POUND", "KEYCODE_POUND"),
        ("pound", "POUND"),
        (" space ", "SPACE"),
    ],
)
def test_normalize_key_accepts_named_keys_and_any_key_code(raw, expected):
    assert normalize_key(raw) == expected


@pytest.mark.parametrize("raw", [-1, True, "", "KEYCODE POUND", "rm -rf", "a;b", 1.5, None])
def test_normalize_key_rejects_invalid_keys(raw):
    with pytest.raises(ValueError):
        normalize_key(raw)
