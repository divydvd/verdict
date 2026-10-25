import pytest

from verdict.core.exceptions import DriverError
from verdict.device_driver.android_keys import (
    input_failed,
    key_input_command,
    key_input_commands,
    keyevent_command,
)


def test_letters_use_one_input_text_call_each():
    assert key_input_commands("hi") == ["input text h", "input text i"]


@pytest.mark.parametrize(
    ("char", "keycode"),
    [
        (" ", "KEYCODE_SPACE"),
        ("\n", "KEYCODE_ENTER"),
        ("\t", "KEYCODE_TAB"),
        ("#", "KEYCODE_POUND"),
        ("*", "KEYCODE_STAR"),
        ("@", "KEYCODE_AT"),
    ],
)
def test_special_characters_use_key_events(char, keycode):
    assert key_input_command(char) == f"input keyevent {keycode}"


@pytest.mark.parametrize("char", ["'", '"', "$", "&", ";", "|", "`", "\\", "(", "<", "~", "?"])
def test_shell_metacharacters_are_quoted(char):
    command = key_input_command(char)
    assert command.startswith("input text ")
    assert command != f"input text {char}"


def test_single_quote_is_quoted_safely():
    assert key_input_command("'") == "input text ''\"'\"''"


@pytest.mark.parametrize("char", ["é", "😀", "\x00"])
def test_unsupported_characters_raise_before_any_input(char):
    with pytest.raises(DriverError):
        key_input_commands(f"ab{char}")


def test_rejects_multi_character_input():
    with pytest.raises(DriverError):
        key_input_command("ab")


@pytest.mark.parametrize(
    ("key", "command"),
    [
        (18, "input keyevent 18"),
        ("KEYCODE_POUND", "input keyevent KEYCODE_POUND"),
        ("pound", "input keyevent KEYCODE_POUND"),
        ("DPAD_LEFT", "input keyevent KEYCODE_DPAD_LEFT"),
    ],
)
def test_keyevent_command_accepts_number_or_name(key, command):
    assert keyevent_command(key) == command


@pytest.mark.parametrize("key", [-3, "POUND;reboot", "KEYCODE_", "a b"])
def test_keyevent_command_rejects_invalid_keys(key):
    with pytest.raises(DriverError):
        keyevent_command(key)


def test_input_failed_detects_error_output():
    assert input_failed("Error: Unknown keycode: KEYCODE_NOPE")
    assert input_failed("java.lang.IllegalArgumentException: ...")
    assert not input_failed("")
