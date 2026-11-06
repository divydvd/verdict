import pytest

from verdict.assertions.base import assertion_registry
from verdict.core.models import RunContext, Selector, UiNode
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.domains.ime.assertions import (
    AiSuggestionVisibleAssertion,
    AutocorrectAppliedAssertion,
    ClipboardSuggestionShownAssertion,
    ClipboardUpdatedAssertion,
    KeyboardVisibleAssertion,
    LanguageSwitchedAssertion,
    SuggestionContainsAssertion,
    TextInsertedAssertion,
    ThemeMatchesAssertion,
)


def _ctx(driver: FakeDeviceDriver) -> RunContext:
    return RunContext(
        session_id="s1",
        run_id="r1",
        scenario_name="scenario",
        driver=driver,
        evidence_dir=driver.evidence_dir,
    )


def test_ime_assertions_are_registered():
    expected = {
        "keyboard_visible",
        "ai_suggestion_visible",
        "text_inserted",
        "clipboard_updated",
        "autocorrect_applied",
        "suggestion_contains",
        "clipboard_suggestion_shown",
        "theme_matches",
        "language_switched",
    }
    assert expected <= set(assertion_registry.list())


def test_keyboard_visible_true_and_false():
    driver = FakeDeviceDriver()
    assert KeyboardVisibleAssertion().check(_ctx(driver)).passed is False
    driver.set_hierarchy(UiNode(resource_id="keyboard_view"))
    assert KeyboardVisibleAssertion().check(_ctx(driver)).passed is True


def test_ai_suggestion_visible():
    driver = FakeDeviceDriver()
    assert AiSuggestionVisibleAssertion().check(_ctx(driver)).passed is False
    driver.set_hierarchy(UiNode(resource_id="ai_suggestion_chip"))
    assert AiSuggestionVisibleAssertion().check(_ctx(driver)).passed is True


def test_text_inserted_matches_substring():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="text_field", text="hello world"))
    assert TextInsertedAssertion("world").check(_ctx(driver)).passed is True
    assert TextInsertedAssertion("bye").check(_ctx(driver)).passed is False


@pytest.mark.parametrize(
    "actual, expected",
    [
        ("keep \U0001f382 ", "\U0001f382"),
        ("a\u0301 \U0001f469\u200d\U0001f4bb ", "\U0001f469\u200d\U0001f4bb"),
    ],
)
def test_fake_field_text_preserves_unicode(actual, expected):
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="text_field", text=actual))
    assert driver.get_text(Selector(resource_id="text_field")) == actual
    result = TextInsertedAssertion(expected).check(_ctx(driver))
    assert result.passed
    assert repr(actual) in result.message


@pytest.mark.parametrize("actual", [None, ""])
def test_fake_field_without_text_does_not_claim_insertion(actual):
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="text_field", text=actual))
    assert not TextInsertedAssertion("\U0001f382").check(_ctx(driver)).passed


def test_missing_fake_field_fails_even_for_empty_expected_text():
    driver = FakeDeviceDriver()
    assert driver.get_text(Selector(resource_id="text_field")) is None
    assert not TextInsertedAssertion("").check(_ctx(driver)).passed


def test_clipboard_updated():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="clipboard_suggestion_chip", text="copied text"))
    assert ClipboardUpdatedAssertion("copied").check(_ctx(driver)).passed is True
    assert ClipboardUpdatedAssertion("nope").check(_ctx(driver)).passed is False


def test_autocorrect_applied_passes_when_corrected_present():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="text_field", text="I received "))
    result = AutocorrectAppliedAssertion(corrected="received", original="recieved").check(_ctx(driver))
    assert result.passed is True


def test_autocorrect_applied_fails_when_original_still_present():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="text_field", text="I recieved "))
    result = AutocorrectAppliedAssertion(corrected="received", original="recieved").check(_ctx(driver))
    assert result.passed is False


def test_autocorrect_applied_fails_when_text_field_missing():
    driver = FakeDeviceDriver()
    result = AutocorrectAppliedAssertion(corrected="received").check(_ctx(driver))
    assert result.passed is False


def test_suggestion_contains():
    driver = FakeDeviceDriver()
    strip = UiNode(
        resource_id="suggestion_strip",
        children=[UiNode(text="hello"), UiNode(text="world")],
    )
    driver.set_hierarchy(strip)
    assert SuggestionContainsAssertion("wor").check(_ctx(driver)).passed is True
    assert SuggestionContainsAssertion("nope").check(_ctx(driver)).passed is False


def test_clipboard_suggestion_shown():
    driver = FakeDeviceDriver()
    assert ClipboardSuggestionShownAssertion().check(_ctx(driver)).passed is False
    driver.set_hierarchy(UiNode(resource_id="clipboard_suggestion_chip"))
    assert ClipboardSuggestionShownAssertion().check(_ctx(driver)).passed is True


def test_theme_matches():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="theme_indicator", text="dark"))
    assert ThemeMatchesAssertion("dark").check(_ctx(driver)).passed is True
    assert ThemeMatchesAssertion("light").check(_ctx(driver)).passed is False


def test_language_switched():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="language_switch_key", text="ES"))
    assert LanguageSwitchedAssertion("ES").check(_ctx(driver)).passed is True
    assert LanguageSwitchedAssertion("EN").check(_ctx(driver)).passed is False
