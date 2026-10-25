import pytest

from verdict.core.exceptions import DriverError
from verdict.device_driver.android_keys import key_input_command, key_input_commands


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
