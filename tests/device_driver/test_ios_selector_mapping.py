import pytest

from verdict.core.models import Selector
from verdict.device_driver.ios_appium import (
    BY_ACCESSIBILITY_ID,
    BY_CLASS_NAME,
    BY_IOS_PREDICATE,
    to_ios_locator,
)


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        (Selector(resource_id="sendButton"), (BY_ACCESSIBILITY_ID, "sendButton")),
        (Selector(class_name="XCUIElementTypeButton"), (BY_CLASS_NAME, "XCUIElementTypeButton")),
        (Selector(text="Send"), (BY_IOS_PREDICATE, '(label == "Send" OR value == "Send")')),
        (Selector(description="Send"), (BY_IOS_PREDICATE, 'label == "Send"')),
        (
            Selector(resource_id="sendButton", class_name="XCUIElementTypeButton"),
            (BY_IOS_PREDICATE, 'name == "sendButton" AND type == "XCUIElementTypeButton"'),
        ),
        (
            Selector(resource_id="a", text="b", description="c", class_name="d"),
            (
                BY_IOS_PREDICATE,
                'name == "a" AND (label == "b" OR value == "b") AND label == "c" AND type == "d"',
            ),
        ),
    ],
)
def test_selector_maps_to_ios_locator(selector, expected):
    assert to_ios_locator(selector) == expected


def test_predicate_escapes_quotes_and_backslashes():
    strategy, value = to_ios_locator(Selector(description='say "hi" \\ bye'))
    assert strategy == BY_IOS_PREDICATE
    assert value == 'label == "say \\"hi\\" \\\\ bye"'
