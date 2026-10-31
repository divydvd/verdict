import pytest

from verdict.core.models import KeyEvent, UiNode
from verdict.device_driver.base import DeviceDriver
from verdict.device_driver.fake import FakeDeviceDriver


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


def test_ios_driver_satisfies_contract(tmp_path):
    from tests.device_driver.fake_appium import make_driver

    driver, _ = make_driver(tmp_path)
    _assert_basic_driver_contract(driver)


@pytest.mark.requires_device
def test_android_driver_satisfies_contract():
    from verdict.device_driver.android import AndroidUiautomator2Driver

    driver = AndroidUiautomator2Driver()
    _assert_basic_driver_contract(driver)
