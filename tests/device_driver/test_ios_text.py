import pytest

from tests.device_driver.fake_appium import FakeAppiumSession, make_driver
from verdict.core.models import RunContext, Selector
from verdict.domains.ime.assertions import TextInsertedAssertion

FIELD = Selector(resource_id="text_field")


def _ctx(driver):
    return RunContext(
        session_id="ios-text",
        run_id="ios-text",
        scenario_name="ios-text",
        driver=driver,
        evidence_dir=driver.evidence_dir,
    )


@pytest.mark.parametrize(
    "attributes, actual",
    [
        ('value="keep \U0001f382 " placeholderValue="Type here"', "keep \U0001f382 "),
        ('value="Type here" placeholderValue="Type here" label="Message"', ""),
        ('value="" label="Message"', ""),
        ('label="Message"', ""),
    ],
)
def test_ios_field_read_keeps_unicode_and_empty_field_semantics(tmp_path, attributes, actual):
    session = FakeAppiumSession(
        '<AppiumAUT><XCUIElementTypeTextField type="XCUIElementTypeTextField" '
        f'name="text_field" {attributes}/></AppiumAUT>'
    )
    driver, _ = make_driver(tmp_path, session)
    assert driver.get_text(FIELD) == actual
    result = TextInsertedAssertion("\U0001f382").check(_ctx(driver))
    assert result.passed == ("\U0001f382" in actual)
    assert repr(actual) in result.message
    assert not TextInsertedAssertion("Message").check(_ctx(driver)).passed
    assert not TextInsertedAssertion("Type here").check(_ctx(driver)).passed


def test_missing_ios_field_fails_without_fabricating_empty_text(tmp_path):
    driver, _ = make_driver(tmp_path, FakeAppiumSession("<AppiumAUT/>"))
    assert driver.get_text(FIELD) is None
    assert not TextInsertedAssertion("").check(_ctx(driver)).passed


def test_ios_text_transport_error_propagates(tmp_path, monkeypatch):
    driver, session = make_driver(tmp_path)

    def fail(*args):
        raise ConnectionError("offline")

    monkeypatch.setattr(session, "execute_script", fail)
    with pytest.raises(ConnectionError, match="offline"):
        TextInsertedAssertion("\U0001f382").check(_ctx(driver))
