import pytest

import verdict.device_driver.android as android_module
from verdict.core.models import Selector
from verdict.device_driver.android import AndroidUiautomator2Driver


class _FakeObject:
    def __init__(self, log: list[object], bounds: list[dict[str, int]]) -> None:
        self.log = log
        self.bounds = bounds
        self.exists = True

    @property
    def info(self) -> dict[str, object]:
        value = self.bounds.pop(0) if len(self.bounds) > 1 else self.bounds[0]
        return {"bounds": value}

    def click(self) -> None:
        self.log.append("click")


class _FakeAdb:
    def shell(self, command: str) -> str:
        return ""


class _FakeU2Device:
    def __init__(self, log: list[object], bounds: list[dict[str, int]]) -> None:
        self.adb_device = _FakeAdb()
        self.log = log
        self.obj = _FakeObject(log, bounds)

    def __call__(self, **kwargs: str) -> _FakeObject:
        return self.obj

    # The driver can restart the uiautomator2 server at start (verdict#12).
    def stop_uiautomator(self, wait: bool = True) -> None:
        pass

    def start_uiautomator(self) -> None:
        pass

    def app_start(self, package: str, activity: str | None = None) -> None:
        self.log.append("launch")


def _bounds(top: int) -> dict[str, int]:
    return {"left": 0, "top": top, "right": 100, "bottom": top + 50}


@pytest.fixture
def make_driver(monkeypatch, tmp_path):
    def make(bounds: list[dict[str, int]]) -> tuple[AndroidUiautomator2Driver, list[object]]:
        log: list[object] = []
        monkeypatch.setattr(android_module.u2, "connect", lambda *args: _FakeU2Device(log, bounds))
        driver = AndroidUiautomator2Driver(evidence_dir=tmp_path, sleep=lambda s: log.append(s))
        return driver, log

    return make


FIELD = Selector(resource_id="text_field")


def test_first_tap_waits_until_the_element_stops_moving(make_driver):
    driver, log = make_driver([_bounds(2400), _bounds(2103), _bounds(2103)])
    driver.tap_selector(FIELD)
    assert log == [1.5, 0.25, 0.25, "click"]


def test_only_the_first_tap_after_a_launch_waits(make_driver):
    driver, log = make_driver([_bounds(2103)])
    driver.tap_selector(FIELD)
    log.clear()
    driver.tap_selector(FIELD)
    assert log == ["click"]

    driver.launch("bha.keys.smartype.debug")
    driver.tap_selector(FIELD)
    assert log == ["click", "launch", 1.5, 0.25, "click"]


def test_settle_stops_after_the_check_limit(make_driver):
    moving = [_bounds(top) for top in range(100, 120)]
    driver, log = make_driver(moving)
    driver.tap_selector(FIELD)
    assert log == [1.5] + [0.25] * driver.tap_settle_checks + ["click"]
