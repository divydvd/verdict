"""Known Selectors for SmarType's IME UI. See docs/architecture.md §3.8, §6.3.

THE CONTRACT: each selector uses `resource_id`. The app sets the same name
on each platform:

- Android: a Compose `Modifier.testTag(NAME)`, with `testTagsAsResourceId`
  on. uiautomator2 then reads the tag as the resource id.
- iOS: `accessibilityIdentifier = NAME`. XCUITest reads it as `name`.
  VoiceOver does not read it aloud.

Do not use `description` for these hooks. On iOS, `description` maps to the
accessibility label, which VoiceOver reads aloud. `docs/ime-selector-contract.md`
gives the full list.
"""

from __future__ import annotations

from verdict.core.models import Selector

KEYBOARD_ROOT = Selector(resource_id="keyboard_view")
TEXT_FIELD = Selector(resource_id="text_field")
SUGGESTION_STRIP = Selector(resource_id="suggestion_strip")
AI_SUGGESTION_CHIP = Selector(resource_id="ai_suggestion_chip")
CLIPBOARD_SUGGESTION_CHIP = Selector(resource_id="clipboard_suggestion_chip")
LANGUAGE_SWITCH_KEY = Selector(resource_id="language_switch_key")
THEME_INDICATOR = Selector(resource_id="theme_indicator")
