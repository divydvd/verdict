import pytest

from verdict.core.exceptions import ElementNotFoundError
from verdict.core.models import Direction, KeyEvent, Platform, Selector, UiNode
from verdict.device_driver.base import DeviceDriver
from verdict.device_driver.fake import FakeDeviceDriver


def test_satisfies_device_driver_protocol():
    assert isinstance(FakeDeviceDriver(), DeviceDriver)


def test_default_platform_is_android():
    assert FakeDeviceDriver().platform == Platform.ANDROID


def test_tap_records_call():
    driver = FakeDeviceDriver()
    driver.tap(10, 20)
    assert driver.tap_calls == [(10, 20)]


def test_tap_selector_finds_node_and_taps_center():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="btn", bounds=(0, 0, 100, 50)))
    driver.tap_selector(Selector(resource_id="btn"))
    assert driver.tap_calls == [(50, 25)]


def test_tap_selector_missing_raises():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="other"))
    with pytest.raises(ElementNotFoundError):
        driver.tap_selector(Selector(resource_id="btn"))


def test_swipe_and_scroll_record_calls():
    driver = FakeDeviceDriver()
    driver.swipe(0, 0, 100, 100, duration_ms=200)
    driver.scroll(Direction.DOWN)
    assert driver.swipe_calls == [(0, 0, 100, 100, 200)]
    assert driver.scroll_calls == [(Direction.DOWN, None)]


def test_type_text_and_press_key_record_calls():
    driver = FakeDeviceDriver()
    driver.type_text("hello")
    driver.press_key(KeyEvent.ENTER)
    assert driver.typed_text == ["hello"]
    assert driver.pressed_keys == [KeyEvent.ENTER]


def test_screenshot_writes_file_and_tracks_it():
    driver = FakeDeviceDriver()
    path = driver.screenshot()
    assert path.exists()
    assert driver.screenshots_taken == [path]


def test_dump_hierarchy_reflects_set_hierarchy():
    driver = FakeDeviceDriver()
    assert driver.dump_hierarchy().root is None
    node = UiNode(text="hi")
    driver.set_hierarchy(node)
    assert driver.dump_hierarchy().root == node


def test_wait_for_true_when_present_false_when_absent():
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(text="hi"))
    assert driver.wait_for(Selector(text="hi"), timeout_ms=100) is True
    assert driver.wait_for(Selector(text="bye"), timeout_ms=100) is False


def test_install_launch_uninstall_lifecycle():
    driver = FakeDeviceDriver()
    driver.install("app.apk")
    driver.launch("bha.keys.smartype")
    assert "app.apk" in driver.installed_packages
    assert driver.current_package == "bha.keys.smartype"
    driver.uninstall("bha.keys.smartype")
    assert driver.current_package is None


def test_clear_data_records_package():
    driver = FakeDeviceDriver()
    driver.clear_data("bha.keys.smartype")
    assert driver.cleared_data == ["bha.keys.smartype"]


def test_collect_logs_and_bugreport_write_files():
    driver = FakeDeviceDriver()
    logs = driver.collect_logs()
    bugreport = driver.collect_bugreport()
    assert logs.exists()
    assert bugreport is not None
    assert bugreport.exists()


def test_recording_lifecycle():
    driver = FakeDeviceDriver()
    handle = driver.start_recording()
    path = driver.stop_recording(handle)
    assert path.exists()


def test_stop_recording_with_unknown_handle_raises():
    driver = FakeDeviceDriver()
    other = FakeDeviceDriver().start_recording()
    with pytest.raises(ValueError):
        driver.stop_recording(other)
