"""Known Selectors for SmarType's IME UI. See docs/architecture.md §3.8, §6.3.

CONTRACT, NOT YET INSTRUMENTED: as of 2026-08-09 the SmarType app
(bha.keys.smartype) exposes no stable `Modifier.testTag`/`contentDescription`
hooks anywhere in its IME Compose UI (verified by grepping the app source —
zero matches). The identifiers below are the automation contract this
module expects the app to expose; `domains/ime/actions.py` and
`domains/ime/assertions.py` are written and unit-tested against these names,
but real-device runs will fail to locate elements until SmarType's keyboard,
suggestion strip, AI overlay, clipboard chip, and language-switch key are
annotated to match.
"""

from __future__ import annotations

from verdict.core.models import Selector

KEYBOARD_ROOT = Selector(resource_id="keyboard_view")
TEXT_FIELD = Selector(resource_id="text_field")
SUGGESTION_STRIP = Selector(description="suggestion_strip")
AI_SUGGESTION_CHIP = Selector(description="ai_suggestion_chip")
CLIPBOARD_SUGGESTION_CHIP = Selector(description="clipboard_suggestion_chip")
LANGUAGE_SWITCH_KEY = Selector(description="language_switch_key")
THEME_INDICATOR = Selector(description="theme_indicator")
