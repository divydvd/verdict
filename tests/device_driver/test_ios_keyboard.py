from __future__ import annotations

import pytest

from tests.device_driver.fake_appium import FakeAppiumSession, make_driver
from verdict.core.exceptions import DriverError, ElementNotFoundError
from verdict.device_driver.base import KeyboardDriver
from verdict.device_driver.ios_appium import BY_ACCESSIBILITY_ID, BY_IOS_PREDICATE
from verdict.device_driver.ios_keyboard import parse_keyboard_menu

_CLOSED = (
    '<AppiumAUT><XCUIElementTypeApplication type="XCUIElementTypeApplication" name="Notes">'
    '<XCUIElementTypeButton type="XCUIElementTypeButton" name="Next keyboard" label="Next keyboard"'
    ' x="8" y="775" width="69" height="70" traits="KeyboardKey, Button"/>'
    "</XCUIElementTypeApplication></AppiumAUT>"
)


def _cell(label: str, *lines: str, selected: bool = False) -> str:
    traits = "Selected" if selected else ""
    texts = "".join(
        f'<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" value="{line}" name="{line}"'
        f' label="{line}" traits="StaticText"/>'
        for line in lines
    )
    return (
        f'<XCUIElementTypeCell type="XCUIElementTypeCell" name="{label}" label="{label}" traits="{traits}">'
        '<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" traits="StaticText"/>'
        f"{texts}</XCUIElementTypeCell>"
    )


def _menu(active: str) -> str:
    """The globe-key list as XCUITest shows it on iOS 26 (see ADR-0010)."""
    cells = [
        _cell("Keyboard Settings…", "Keyboard Settings…"),
        _cell("Emoji", "Emoji", selected=active == "Emoji"),
        _cell("English (US)", "English (US)", selected=active == "English (US)"),
        _cell("SmarType, English", "SmarType", "English", selected=active == "SmarType"),
        '<XCUIElementTypeCell type="XCUIElementTypeCell" traits=""/>',
    ]
    return (
        '<AppiumAUT><XCUIElementTypeApplication type="XCUIElementTypeApplication" name="Notes">'
        '<XCUIElementTypeOther type="XCUIElementTypeOther" name="PopoverDismissRegion"'
        ' label="dismiss popup" x="0" y="0" width="390" height="844" traits=""/>'
        '<XCUIElementTypeOther type="XCUIElementTypeOther" name="InputSwitcherView"'
        ' x="5" y="395" width="228" height="375" traits="">'
        '<XCUIElementTypeTable type="XCUIElementTypeTable" name="InputSwitcherTable" traits="">'
        f"{''.join(cells)}</XCUIElementTypeTable></XCUIElementTypeOther>"
        '<XCUIElementTypeButton type="XCUIElementTypeButton" name="Next keyboard" label="Next keyboard"'
        ' x="8" y="775" width="69" height="70" traits="KeyboardKey, Button"/>'
        "</XCUIElementTypeApplication></AppiumAUT>"
    )


def _cell_locator(label: str) -> tuple[str, str]:
    return (BY_IOS_PREDICATE, f'name == "{label}" AND type == "XCUIElementTypeCell"')


def _setup(tmp_path, *sources: str, globe: str = "Next keyboard"):
    session = FakeAppiumSession()
    session.page_sources = list(sources)
    session.add_element(BY_ACCESSIBILITY_ID, globe, "globe")
    driver, _ = make_driver(tmp_path, session, keyboard_menu_wait_ms=1000)
    return driver, session


def _long_presses(session: FakeAppiumSession) -> list[dict]:
    return [
        call[2]["actions"][0]["actions"]
        for call in session.calls
        if call[:2] == ("execute", "actions") and call[2]["actions"][0]["actions"][2]["duration"] == 1000
    ]


def _taps(session: FakeAppiumSession) -> list[tuple[int, int]]:
    points = []
    for call in session.calls:
        if call[:2] == ("execute", "actions"):
            steps = call[2]["actions"][0]["actions"]
            if steps[2]["duration"] == 100:
                points.append((steps[0]["x"], steps[0]["y"]))
    return points


def test_parse_keyboard_menu_reads_names_titles_and_active_cell():
    menu = parse_keyboard_menu(_menu("English (US)"))
    assert menu is not None
    assert [(item.label, item.title) for item in menu.items] == [
        ("Keyboard Settings…", "Keyboard Settings…"),
        ("Emoji", "Emoji"),
        ("English (US)", "English (US)"),
        ("SmarType, English", "SmarType"),
    ]
    assert menu.active is not None and menu.active.title == "English (US)"
    # The middle of the gap above the list (0..395), in the dismiss region.
    assert menu.dismiss_point == (195, 197)


def test_parse_keyboard_menu_is_none_when_the_list_is_closed():
    assert parse_keyboard_menu(_CLOSED) is None


def test_pick_matches_the_first_line_or_the_full_label():
    menu = parse_keyboard_menu(_menu("Emoji"))
    assert menu is not None
    assert menu.pick("SmarType").label == "SmarType, English"
    assert menu.pick("SmarType, English").label == "SmarType, English"


def test_pick_with_two_matches_asks_for_the_full_label():
    raw = _menu("Emoji").replace(
        "</XCUIElementTypeTable>", _cell("SmarType, Hindi", "SmarType", "Hindi") + "</XCUIElementTypeTable>"
    )
    menu = parse_keyboard_menu(raw)
    assert menu is not None
    with pytest.raises(DriverError, match="more than one keyboard matches 'SmarType'"):
        menu.pick("SmarType")
    assert menu.pick("SmarType, Hindi").title == "SmarType"


def test_ios_driver_is_a_keyboard_driver(tmp_path):
    driver, _ = _setup(tmp_path, _CLOSED)
    assert isinstance(driver, KeyboardDriver)


def test_select_keyboard_taps_the_name_and_checks_the_selected_cell(tmp_path):
    driver, session = _setup(tmp_path, _menu("English (US)"), _CLOSED, _menu("Emoji"), _CLOSED)
    session.add_element(*_cell_locator("Emoji"), "emoji-cell")

    driver.select_keyboard("Emoji")

    assert ("click", "emoji-cell") in session.calls
    presses = _long_presses(session)
    assert len(presses) == 2
    assert presses[0][0] == {"type": "pointerMove", "duration": 0, "x": 42, "y": 810, "origin": "viewport"}
    assert _taps(session) == [(195, 197)]


def test_select_keyboard_does_nothing_when_the_keyboard_is_already_active(tmp_path):
    driver, session = _setup(tmp_path, _menu("Emoji"), _CLOSED)

    driver.select_keyboard("Emoji")

    assert not [call for call in session.calls if call[0] == "click"]
    assert len(_long_presses(session)) == 1
    assert _taps(session) == [(195, 197)]


def test_select_keyboard_fails_and_closes_the_list_when_the_name_is_missing(tmp_path):
    driver, session = _setup(tmp_path, _menu("English (US)"), _CLOSED)

    with pytest.raises(DriverError) as error:
        driver.select_keyboard("Klingon")

    message = str(error.value)
    assert "no keyboard 'Klingon'" in message
    assert "'Emoji', 'English (US)', 'SmarType'" in message
    assert "Settings > General > Keyboard > Keyboards" in message
    assert _taps(session) == [(195, 197)]


def test_select_keyboard_fails_when_another_keyboard_stays_active(tmp_path):
    driver, session = _setup(tmp_path, _menu("English (US)"), _CLOSED, _menu("English (US)"), _CLOSED)
    session.add_element(*_cell_locator("Emoji"), "emoji-cell")

    with pytest.raises(DriverError, match="tapped 'Emoji', but the active keyboard is 'English \\(US\\)'"):
        driver.select_keyboard("Emoji")


def test_select_keyboard_fails_when_the_list_stays_open_after_the_tap(tmp_path):
    driver, session = _setup(tmp_path, _menu("English (US)"))
    session.add_element(*_cell_locator("Emoji"), "emoji-cell")

    with pytest.raises(DriverError, match="stayed open after the tap on 'Emoji'"):
        driver.select_keyboard("Emoji")


def test_select_keyboard_fails_when_the_list_does_not_open(tmp_path):
    driver, _ = _setup(tmp_path, _CLOSED)

    with pytest.raises(DriverError, match="did not open after a long press"):
        driver.select_keyboard("Emoji")


def test_select_keyboard_fails_without_a_globe_key(tmp_path):
    session = FakeAppiumSession()
    session.page_sources = [_CLOSED]
    driver, _ = make_driver(tmp_path, session, keyboard_menu_wait_ms=1000)

    with pytest.raises(ElementNotFoundError, match="no globe key .*Tap a text field first"):
        driver.select_keyboard("Emoji")


def test_select_keyboard_uses_the_globe_key_of_a_keyboard_extension(tmp_path):
    driver, session = _setup(tmp_path, _menu("SmarType"), _CLOSED, globe="next_keyboard_key")

    driver.select_keyboard("SmarType")

    assert ("find", BY_ACCESSIBILITY_ID, "next_keyboard_key") in session.calls
    assert len(_long_presses(session)) == 1
