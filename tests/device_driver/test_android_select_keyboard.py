import pytest

import verdict.device_driver.android as android_module
from verdict.core.exceptions import DriverError
from verdict.device_driver.android import AndroidUiautomator2Driver
from verdict.device_driver.base import KeyboardDriver

SMARTYPE = "bha.keys.smartype.debug/bha.keys.smartype.FlorisImeService"
GBOARD = "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"


class _FakeAdb:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.enabled = [GBOARD, SMARTYPE]
        self.active = GBOARD
        self.set_works = True

    def shell(self, command: str) -> str:
        self.commands.append(command)
        if command == "ime list -s":
            return "\n".join(self.enabled) + "\n"
        if command.startswith("ime set ") and self.set_works:
            self.active = command.removeprefix("ime set ")
            return f"Input method {self.active} selected for user #0\n"
        if command == "settings get secure default_input_method":
            return self.active + "\n"
        return ""


class _FakeU2Device:
    def __init__(self) -> None:
        self.adb_device = _FakeAdb()

    def stop_uiautomator(self, wait: bool = True) -> None: ...

    def start_uiautomator(self) -> None: ...


@pytest.fixture
def driver(monkeypatch, tmp_path):
    monkeypatch.setattr(android_module.u2, "connect", lambda *args: _FakeU2Device())
    drv = AndroidUiautomator2Driver(evidence_dir=tmp_path, sleep=lambda _: None)
    drv._adb.commands.clear()
    return drv


def test_android_driver_is_a_keyboard_driver(driver):
    assert isinstance(driver, KeyboardDriver)


def test_select_keyboard_runs_ime_set_and_checks_the_active_input_method(driver):
    driver.select_keyboard(SMARTYPE)
    assert driver._adb.commands == [
        "ime list -s",
        f"ime set {SMARTYPE}",
        "settings get secure default_input_method",
    ]


def test_select_keyboard_accepts_the_short_ime_id(driver):
    driver._adb.enabled = [GBOARD, "com.example.kb/.Ime"]
    driver.select_keyboard("com.example.kb/.Ime")
    assert driver._adb.commands[1] == "ime set com.example.kb/com.example.kb.Ime"


def test_select_keyboard_fails_when_the_input_method_is_not_on(driver):
    driver._adb.enabled = [GBOARD]
    with pytest.raises(DriverError, match="is not on.*adb shell ime enable"):
        driver.select_keyboard(SMARTYPE)
    assert driver._adb.commands == ["ime list -s"]


def test_select_keyboard_fails_when_the_input_method_does_not_change(driver):
    driver._adb.set_works = False
    with pytest.raises(DriverError, match=f"the active input method is '{GBOARD}'"):
        driver.select_keyboard(SMARTYPE)
