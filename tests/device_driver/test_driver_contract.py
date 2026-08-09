import shutil
import subprocess

import pytest

from verdict.core.models import KeyEvent, UiNode
from verdict.device_driver.base import DeviceDriver
from verdict.device_driver.fake import FakeDeviceDriver


def _adb_device_attached() -> bool:
    if shutil.which("adb") is None:
        return False
    try:
        result = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=5, check=False
        )
    except OSError:
        return False
    lines = result.stdout.splitlines()[1:]
    return any(line.strip().endswith("device") for line in lines)


def _assert_basic_driver_contract(driver: DeviceDriver) -> None:
    """Minimal behavioural contract every DeviceDriver must satisfy,
    without assuming any particular app is on screen (that's covered by
    the M1.7 domains/ime integration scenarios against a real SmarType
    build).
    """
    assert isinstance(driver, DeviceDriver)
    screenshot_path = driver.screenshot()
    assert screenshot_path.exists()
    hierarchy = driver.dump_hierarchy()
    assert hierarchy.raw_xml
    driver.press_key(KeyEvent.HOME)


def test_fake_driver_satisfies_contract():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(text="root"))
    _assert_basic_driver_contract(driver)


@pytest.mark.requires_device
@pytest.mark.skipif(not _adb_device_attached(), reason="no adb device/emulator attached")
def test_android_driver_satisfies_contract():
    from verdict.device_driver.android import AndroidUiautomator2Driver

    driver = AndroidUiautomator2Driver()
    _assert_basic_driver_contract(driver)
