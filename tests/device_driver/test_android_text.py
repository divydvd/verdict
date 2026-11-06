import http.client

import pytest
import uiautomator2 as u2

from verdict.core.exceptions import DriverError
from verdict.core.models import RunContext, Selector
from verdict.device_driver.android import AndroidUiautomator2Driver
from verdict.domains.ime.assertions import AutocorrectAppliedAssertion, TextInsertedAssertion
from verdict.scenario_engine.runner import run_scenario
from verdict.scenario_engine.schema import ScenarioSpec, StepSpec

FIELD = Selector(resource_id="text_field")
CAKE_TEXT = "keep \U0001f382 "


class _TextObject:
    def __init__(self, text):
        self.text = text

    def get_text(self, timeout=None):
        assert timeout == 0
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


class _TextDevice:
    def __init__(self, text, xml_text):
        self.obj = _TextObject(text)
        self.xml_text = xml_text
        self.adb_device = object()

    def __call__(self, **kwargs):
        assert kwargs == {"resourceId": "text_field"}
        return self.obj

    def stop_uiautomator(self, wait=True):
        pass

    def start_uiautomator(self):
        pass

    def dump_hierarchy(self):
        return f'<hierarchy><node resource-id="text_field" text="{self.xml_text}"/></hierarchy>'


def _driver(monkeypatch, tmp_path, text, xml_text="keep .. "):
    device = _TextDevice(text, xml_text)
    monkeypatch.setattr(u2, "connect", lambda *args: device)
    return AndroidUiautomator2Driver(evidence_dir=tmp_path)


def _ctx(driver):
    return RunContext(
        session_id="unicode",
        run_id="unicode",
        scenario_name="unicode",
        driver=driver,
        evidence_dir=driver.evidence_dir,
    )


def test_text_inserted_preserves_native_emoji_despite_lossy_xml(monkeypatch, tmp_path):
    driver = _driver(monkeypatch, tmp_path, CAKE_TEXT)
    assert driver.dump_hierarchy().find(FIELD).text == "keep .. "
    result = TextInsertedAssertion(CAKE_TEXT).check(_ctx(driver))
    assert result.passed
    assert repr(CAKE_TEXT) in result.message


def test_text_inserted_rejects_hierarchy_false_positive(monkeypatch, tmp_path):
    driver = _driver(monkeypatch, tmp_path, "keep plain ", xml_text=CAKE_TEXT)
    result = TextInsertedAssertion("\U0001f382").check(_ctx(driver))
    assert not result.passed
    assert repr("keep plain ") in result.message


def test_autocorrect_reads_native_unicode_and_rejects_original(monkeypatch, tmp_path):
    driver = _driver(monkeypatch, tmp_path, CAKE_TEXT)
    assert AutocorrectAppliedAssertion("\U0001f382", original=":birthday").check(_ctx(driver)).passed
    driver._device.obj.text = "keep :birthday \U0001f382 "
    assert not AutocorrectAppliedAssertion("\U0001f382", original=":birthday").check(_ctx(driver)).passed


@pytest.mark.parametrize("text", [CAKE_TEXT, "", "a\u0301 \U0001f469\u200d\U0001f4bb "])
def test_get_text_preserves_exact_native_value(monkeypatch, tmp_path, text):
    driver = _driver(monkeypatch, tmp_path, text)
    assert driver.get_text(FIELD) == text


def test_missing_native_field_fails_even_when_xml_has_expected_text(monkeypatch, tmp_path):
    missing = u2.exceptions.UiObjectNotFoundError(-32002, "missing")
    driver = _driver(monkeypatch, tmp_path, missing, xml_text=CAKE_TEXT)
    assert driver.get_text(FIELD) is None
    assert not TextInsertedAssertion(CAKE_TEXT).check(_ctx(driver)).passed
    assert not TextInsertedAssertion("").check(_ctx(driver)).passed


@pytest.mark.parametrize("text", [None, 42])
def test_invalid_native_text_is_an_error_not_a_default(monkeypatch, tmp_path, text):
    driver = _driver(monkeypatch, tmp_path, text, xml_text=CAKE_TEXT)
    with pytest.raises(DriverError, match="text"):
        TextInsertedAssertion(CAKE_TEXT).check(_ctx(driver))


def test_rpc_text_error_is_reported(monkeypatch, tmp_path):
    driver = _driver(monkeypatch, tmp_path, u2.exceptions.RPCError("read failed"))
    with pytest.raises(DriverError, match="read failed"):
        TextInsertedAssertion(CAKE_TEXT).check(_ctx(driver))


@pytest.mark.parametrize(
    "error",
    [ConnectionError("offline"), http.client.HTTPException("offline"), u2.exceptions.DeviceError("offline")],
)
def test_text_connection_errors_propagate(monkeypatch, tmp_path, error):
    driver = _driver(monkeypatch, tmp_path, error)
    with pytest.raises(type(error), match="offline"):
        TextInsertedAssertion(CAKE_TEXT).check(_ctx(driver))


@pytest.mark.parametrize(
    "text, passed, error_part",
    [
        (CAKE_TEXT, True, None),
        ("keep plain ", False, "keep plain"),
        (u2.exceptions.RPCError("read failed"), False, "read failed"),
        (ConnectionError("offline"), False, "BLOCKED: the device connection failed"),
    ],
)
def test_native_text_result_reaches_scenario_report(monkeypatch, tmp_path, text, passed, error_part):
    driver = _driver(monkeypatch, tmp_path, text)
    spec = ScenarioSpec(
        name="unicode-text",
        steps=[StepSpec(action="assert", assertion="text_inserted", args={"text": CAKE_TEXT}, settle_ms=0)],
    )
    result = run_scenario(
        spec, driver, session_id="unicode", blocked_errors=(ConnectionError,)
    )
    assert result.passed is passed
    assert result.attempts == 1
    event = result.timeline.events[0]
    if error_part is None:
        assert event.error is None
        assert repr(CAKE_TEXT) in event.assertion_results[0].message
    else:
        assert error_part in event.error
