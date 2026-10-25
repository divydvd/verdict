import pytest

import verdict.device_driver.android as android_module
from verdict.core.exceptions import DriverError
from verdict.device_driver.android import AndroidUiautomator2Driver


class _FakeAdb:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def shell(self, command: str) -> str:
        self.commands.append(command)
        return ""


class _FakeU2Device:
    def __init__(self) -> None:
        self.adb_device = _FakeAdb()


@pytest.fixture
def driver(monkeypatch, tmp_path):
    monkeypatch.setattr(android_module.u2, "connect", lambda *args: _FakeU2Device())
    sleeps: list[float] = []
    drv = AndroidUiautomator2Driver(evidence_dir=tmp_path, sleep=sleeps.append)
    drv.recorded_sleeps = sleeps  # type: ignore[attr-defined]
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
