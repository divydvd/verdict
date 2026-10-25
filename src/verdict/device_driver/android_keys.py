"""Pure helpers that turn text into per-key `adb shell input` commands.

Kept free of uiautomator2/adbutils so the mapping is unit-testable without a device.
"""

from __future__ import annotations

import re
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


_KEYCODE_NAME = re.compile(r"KEYCODE_[A-Z0-9_]+")


def keyevent_command(key: int | str) -> str:
    """Return the `adb shell` command for one Android key code: a number
    (`18`) or a name with or without the `KEYCODE_` prefix (`POUND`)."""
    if isinstance(key, int):
        if key < 0:
            raise DriverError(f"key code must be 0 or more, got {key}")
        return f"input keyevent {key}"
    name = key.strip().upper()
    if not name.startswith("KEYCODE_"):
        name = f"KEYCODE_{name}"
    if not _KEYCODE_NAME.fullmatch(name):
        raise DriverError(f"invalid Android key code name {key!r}")
    return f"input keyevent {name}"


def input_failed(output: str) -> bool:
    """`adb shell input` exits 0 for an unknown key code; it prints an error instead."""
    return "Exception" in output or "Error" in output


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
