"""Pure helpers that turn text into per-key `adb shell input` commands.

Kept free of uiautomator2/adbutils so the mapping is unit-testable without a device.
"""

from __future__ import annotations

import shlex

from verdict.core.exceptions import DriverError

# Characters that `input text` handles badly (it drops a space, and `#` can
# start a shell comment) go through a key event instead.
_CHAR_KEYCODES: dict[str, str] = {
    " ": "KEYCODE_SPACE",
    "\n": "KEYCODE_ENTER",
    "\t": "KEYCODE_TAB",
    "#": "KEYCODE_POUND",
    "*": "KEYCODE_STAR",
    "@": "KEYCODE_AT",
}


def key_input_command(char: str) -> str:
    """Return the `adb shell` command that sends one character as a real key input."""
    if len(char) != 1:
        raise DriverError(f"expected one character, got {char!r}")
    keycode = _CHAR_KEYCODES.get(char)
    if keycode is not None:
        return f"input keyevent {keycode}"
    if not (char.isascii() and char.isprintable()):
        raise DriverError(
            f"type_keys supports printable ASCII, space, newline, and tab only; got {char!r}"
        )
    return f"input text {shlex.quote(char)}"


def key_input_commands(text: str) -> list[str]:
    """One command for each character of `text`. Validates all characters first."""
    return [key_input_command(char) for char in text]
