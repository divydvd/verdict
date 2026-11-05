import pytest

import verdict.device_driver.android as android_module
from verdict.core.exceptions import DriverError
from verdict.core.models import KeyEvent
from verdict.device_driver.android import AndroidUiautomator2Driver


class _FakeAdb:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.output = ""

    def shell(self, command: str) -> str:
        self.commands.append(command)
        return self.output


class _FakeU2Device:
    def __init__(self) -> None:
        self.adb_device = _FakeAdb()
        self.pressed: list[str] = []
        self.server_calls: list[str] = []

    def stop_uiautomator(self, wait: bool = True) -> None:
        self.server_calls.append(f"stop wait={wait}")

    def start_uiautomator(self) -> None:
        self.server_calls.append("start")

    def press(self, key: str) -> None:
        self.pressed.append(key)


@pytest.fixture
def driver(monkeypatch, tmp_path):
    monkeypatch.setattr(android_module.u2, "connect", lambda *args: _FakeU2Device())
    sleeps: list[float] = []
    drv = AndroidUiautomator2Driver(evidence_dir=tmp_path, sleep=sleeps.append)
    drv.recorded_sleeps = sleeps  # type: ignore[attr-defined]
    drv._adb.commands.clear()
    return drv


def test_type_keys_sends_one_adb_call_per_character_with_pause(driver):
    driver.type_keys("hi #", interval_ms=150)
    assert driver._adb.commands == [
        "input text h",
        "input text i",
        "input keyevent KEYCODE_SPACE",
        "input keyevent KEYCODE_POUND",
    ]
    assert driver.recorded_sleeps == [0.15] * 4


def test_type_keys_sends_nothing_when_text_has_unsupported_character(driver):
    with pytest.raises(DriverError):
        driver.type_keys("caf\u00e9")
    assert driver._adb.commands == []


def test_press_key_keeps_uiautomator2_path_for_named_keys(driver):
    driver.press_key(KeyEvent.ENTER)
    driver.press_key("back")
    assert driver._device.pressed == ["enter", "back"]
    assert driver._adb.commands == []


def test_press_key_sends_any_key_code_through_input_keyevent(driver):
    driver.press_key("KEYCODE_POUND")
    driver.press_key(62)
    driver.press_key("dpad_left")
    assert driver._adb.commands == [
        "input keyevent KEYCODE_POUND",
        "input keyevent 62",
        "input keyevent KEYCODE_DPAD_LEFT",
    ]


def test_press_key_raises_when_device_rejects_key_code(driver):
    driver._adb.output = "Error: Unknown keycode: KEYCODE_NOPE"
    with pytest.raises(DriverError, match="Unknown keycode"):
        driver.press_key("NOPE")


def test_press_key_rejects_invalid_key_before_adb(driver):
    with pytest.raises(DriverError):
        driver.press_key("POUND; reboot")
    assert driver._adb.commands == []


def test_driver_start_uses_the_supported_server_lifecycle_without_shell_kills(monkeypatch, tmp_path):
    device = _FakeU2Device()
    monkeypatch.setattr(android_module.u2, "connect", lambda *args: device)
    AndroidUiautomator2Driver(evidence_dir=tmp_path)
    assert device.adb_device.commands == []
    assert device.server_calls == ["stop wait=True", "start"]


@pytest.mark.parametrize("operation", ["stop_uiautomator", "start_uiautomator"])
def test_driver_start_reports_server_lifecycle_failure(monkeypatch, tmp_path, operation):
    device = _FakeU2Device()
    monkeypatch.setattr(android_module.u2, "connect", lambda *args: device)

    def fail(*args, **kwargs):
        raise ConnectionError("server connection lost")

    monkeypatch.setattr(device, operation, fail)
    with pytest.raises(ConnectionError, match="server connection lost"):
        AndroidUiautomator2Driver(evidence_dir=tmp_path)
    assert device.adb_device.commands == []
    assert device.server_calls == ([] if operation == "stop_uiautomator" else ["stop wait=True"])
