# IME selector contract

The IME actions and assertions in `src/verdict/domains/ime/` find the SmarType keyboard UI by
fixed names. This document gives the names and how the app must set them on each platform.

## Rule
Each selector uses `resource_id`. The app sets the same name on Android and on iOS:

| Platform | How the app sets the name | How Verdict reads it |
|---|---|---|
| Android | Compose `Modifier.testTag("NAME")`, with `testTagsAsResourceId = true` on a parent | uiautomator2 `resourceId` |
| iOS | `accessibilityIdentifier = "NAME"` (UIKit), or `.accessibilityIdentifier("NAME")` (SwiftUI) | XCUITest `name` (see ADR-0009) |

Do not use `description` for these hooks:
- On Android, `description` is the content description. TalkBack reads it aloud.
- On iOS, `description` maps to the accessibility label. VoiceOver reads it aloud.

The accessibility identifier and the test tag are not read aloud. Thus the hooks do not change
the screen-reader text.

On iOS, XCUITest `name` falls back to the label when an element has no accessibility identifier.
Thus an element without an identifier can match by its label. Set the identifier on each element
in the table below.

## Names

| Constant in `selectors.py` | Name | Element |
|---|---|---|
| `KEYBOARD_ROOT` | `keyboard_view` | The root view of the keyboard |
| `TEXT_FIELD` | `text_field` | The preview text field in the app (not in the keyboard) |
| `SUGGESTION_STRIP` | `suggestion_strip` | The suggestion strip. Its children are the suggestions, in order |
| `AI_SUGGESTION_CHIP` | `ai_suggestion_chip` | The AI suggestion chip |
| `CLIPBOARD_SUGGESTION_CHIP` | `clipboard_suggestion_chip` | The clipboard suggestion chip. Its text is the clipboard text |
| `LANGUAGE_SWITCH_KEY` | `language_switch_key` | The language-switch key. Its text is the active language |
| `THEME_INDICATOR` | `theme_indicator` | An element whose text is the active theme name |

## Keyboard selection on iOS
iOS has no command to select a keyboard. The `select_keyboard` step uses the globe key. It finds
the system globe key (`Next keyboard`) first. If the keyboard draws its own globe key, set
`accessibilityIdentifier = "next_keyboard_key"` on that key. See ADR-0010.
