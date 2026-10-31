from __future__ import annotations

from verdict.core.models import Selector
from verdict.domains.ime import selectors

_EXPECTED = {
    "KEYBOARD_ROOT": "keyboard_view",
    "TEXT_FIELD": "text_field",
    "SUGGESTION_STRIP": "suggestion_strip",
    "AI_SUGGESTION_CHIP": "ai_suggestion_chip",
    "CLIPBOARD_SUGGESTION_CHIP": "clipboard_suggestion_chip",
    "LANGUAGE_SWITCH_KEY": "language_switch_key",
    "THEME_INDICATOR": "theme_indicator",
}


def test_each_ime_selector_uses_only_resource_id() -> None:
    found = {name: value for name, value in vars(selectors).items() if isinstance(value, Selector)}
    assert set(found) == set(_EXPECTED)
    for name, selector in found.items():
        assert selector == Selector(resource_id=_EXPECTED[name]), name
