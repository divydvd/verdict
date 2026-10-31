import builtins
import http.client
from datetime import UTC, datetime

import pytest

from tests.device_driver.fake_appium import FakeAppiumSession, make_driver
from verdict.core.exceptions import DriverError, ElementNotFoundError
from verdict.core.models import Direction, KeyEvent, Platform, RecordingHandle, Selector
from verdict.device_driver.base import (
    AppLifecycleDriver,
    DeviceDriver,
    DiagnosticsDriver,
    InputDriver,
)
from verdict.device_driver.ios_appium import (
    BY_ACCESSIBILITY_ID,
    BY_IOS_PREDICATE,
    IOS_CONNECTION_ERRORS,
    IosAppiumDriver,
)


def _actions(call):
    assert call[0] == "execute" and call[1] == "actions"
    (source,) = call[2]["actions"]
    assert source["parameters"] == {"pointerType": "touch"}
    return source["actions"]


def test_driver_satisfies_the_protocols(tmp_path):
    driver, _ = make_driver(tmp_path)
    assert driver.platform is Platform.IOS
    for protocol in (InputDriver, AppLifecycleDriver, DiagnosticsDriver, DeviceDriver):
        assert isinstance(driver, protocol)


def test_tap_sends_a_w3c_touch_action(tmp_path):
    driver, session = make_driver(tmp_path)
    driver.tap(10, 20)
    steps = _actions(session.calls[-1])
    assert [step["type"] for step in steps] == ["pointerMove", "pointerDown", "pause", "pointerUp"]
    assert (steps[0]["x"], steps[0]["y"]) == (10, 20)


def test_swipe_moves_from_start_to_end_in_the_duration(tmp_path):
    driver, session = make_driver(tmp_path)
    driver.swipe(1, 2, 3, 4, duration_ms=500)
    steps = _actions(session.calls[-1])
    assert [step["type"] for step in steps] == ["pointerMove", "pointerDown", "pointerMove", "pointerUp"]
    assert (steps[0]["x"], steps[0]["y"]) == (1, 2)
    assert (steps[2]["x"], steps[2]["y"], steps[2]["duration"]) == (3, 4, 500)


def test_scroll_without_selector_scrolls_the_screen(tmp_path):
    driver, session = make_driver(tmp_path)
    driver.scroll(Direction.DOWN)
    assert session.calls[-1] == ("script", "mobile: scroll", {"direction": "down"})


def test_scroll_with_selector_scrolls_that_element(tmp_path):
    driver, session = make_driver(tmp_path)
    session.add_element(BY_ACCESSIBILITY_ID, "list", "el-9")
    driver.scroll(Direction.UP, Selector(resource_id="list"))
    assert session.calls[-1] == ("script", "mobile: scroll", {"direction": "up", "elementId": "el-9"})


def test_scroll_with_missing_element_raises(tmp_path):
    driver, _ = make_driver(tmp_path)
    with pytest.raises(ElementNotFoundError):
        driver.scroll(Direction.UP, Selector(resource_id="list"))


def test_tap_selector_clicks_the_element(tmp_path):
    driver, session = make_driver(tmp_path)
    session.add_element(BY_ACCESSIBILITY_ID, "sendButton", "el-2")
    driver.tap_selector(Selector(resource_id="sendButton"))
    assert session.calls[-1] == ("click", "el-2")


def test_tap_selector_waits_for_a_late_element(tmp_path):
    sleeps: list[float] = []
    driver, session = make_driver(tmp_path, sleep=sleeps.append, poll_ms=100, tap_wait_ms=1000)
    session.add_element(BY_IOS_PREDICATE, '(label == "Send" OR value == "Send")')
    session.missing_reads = 2
    driver.tap_selector(Selector(text="Send"))
    assert session.calls[-1] == ("click", "el-1")
    assert sleeps == [0.1, 0.1]


def test_tap_selector_raises_when_element_never_shows(tmp_path):
    driver, _ = make_driver(tmp_path, poll_ms=100, tap_wait_ms=300)
    with pytest.raises(ElementNotFoundError):
        driver.tap_selector(Selector(resource_id="missing"))


def test_type_text_sends_keys_to_the_focused_element(tmp_path):
    driver, session = make_driver(tmp_path)
    driver.type_text("hello")
    assert session.calls[-1] == ("send_keys", "hello")


def test_type_keys_sends_one_key_at_a_time_with_a_pause(tmp_path):
    sleeps: list[float] = []
    driver, session = make_driver(tmp_path, sleep=sleeps.append)
    driver.type_keys("abc", interval_ms=200)
    assert [call for call in session.calls if call[0] == "send_keys"] == [
        ("send_keys", "a"),
        ("send_keys", "b"),
        ("send_keys", "c"),
    ]
    assert sleeps == [0.2, 0.2, 0.2]


def test_press_home_uses_press_button(tmp_path):
    driver, session = make_driver(tmp_path)
    driver.press_key(KeyEvent.HOME)
    assert session.calls[-1] == ("script", "mobile: pressButton", {"name": "home"})


@pytest.mark.parametrize(
    ("key", "char"), [(KeyEvent.ENTER, "\n"), (KeyEvent.DELETE, "\b"), (KeyEvent.TAB, "\t"), ("enter", "\n")]
)
def test_press_keyboard_keys_types_the_key(tmp_path, key, char):
    driver, session = make_driver(tmp_path)
    driver.press_key(key)
    assert session.calls[-1] == ("send_keys", char)


def test_press_back_raises_a_clear_error(tmp_path):
    driver, _ = make_driver(tmp_path)
    with pytest.raises(DriverError, match="no back key"):
        driver.press_key(KeyEvent.BACK)


@pytest.mark.parametrize("key", [66, "KEYCODE_POUND"])
def test_press_android_key_code_raises(tmp_path, key):
    driver, _ = make_driver(tmp_path)
    with pytest.raises(DriverError, match="does not support"):
        driver.press_key(key)


def test_press_invalid_key_raises_driver_error(tmp_path):
    driver, _ = make_driver(tmp_path)
    with pytest.raises(DriverError):
        driver.press_key("bad key!")


def test_screenshot_writes_the_png(tmp_path):
    driver, _ = make_driver(tmp_path)
    path = driver.screenshot()
    assert path.parent == tmp_path
    assert path.read_bytes() == b"\x89PNG fake"


def test_dump_hierarchy_parses_the_page_source(tmp_path):
    driver, _ = make_driver(tmp_path)
    hierarchy = driver.dump_hierarchy()
    assert hierarchy.find(Selector(resource_id="sendButton")) is not None


def test_dump_hierarchy_retries_bad_xml(tmp_path):
    session = FakeAppiumSession()
    session.page_sources = ["<AppiumAUT>", session.page_sources[0]]
    driver, _ = make_driver(tmp_path, session=session)
    assert driver.dump_hierarchy().root is not None


def test_dump_hierarchy_raises_after_all_attempts_fail(tmp_path):
    driver, _ = make_driver(tmp_path, session=FakeAppiumSession("<AppiumAUT>"), dump_attempts=2)
    with pytest.raises(DriverError, match="2 attempt"):
        driver.dump_hierarchy()


def test_wait_for_returns_true_when_found_and_false_on_timeout(tmp_path):
    driver, session = make_driver(tmp_path, poll_ms=100)
    session.add_element(BY_ACCESSIBILITY_ID, "sendButton")
    assert driver.wait_for(Selector(resource_id="sendButton"), timeout_ms=500)
    assert not driver.wait_for(Selector(resource_id="missing"), timeout_ms=300)


def test_lifecycle_uses_bundle_id_commands(tmp_path):
    driver, session = make_driver(tmp_path)
    driver.install("/apps/SmarType.app")
    driver.uninstall("com.example.smartype")
    driver.launch("com.example.smartype", activity=".Ignored")
    assert session.calls[-3:] == [
        ("script", "mobile: installApp", {"app": "/apps/SmarType.app"}),
        ("script", "mobile: removeApp", {"bundleId": "com.example.smartype"}),
        ("script", "mobile: activateApp", {"bundleId": "com.example.smartype"}),
    ]


def test_clear_data_uninstalls_and_installs_again(tmp_path):
    driver, session = make_driver(tmp_path, app_paths={"com.example.smartype": "/apps/SmarType.app"})
    driver.clear_data("com.example.smartype")
    assert session.calls[-2:] == [
        ("script", "mobile: removeApp", {"bundleId": "com.example.smartype"}),
        ("script", "mobile: installApp", {"app": "/apps/SmarType.app"}),
    ]


def test_clear_data_without_app_path_raises(tmp_path):
    driver, session = make_driver(tmp_path)
    with pytest.raises(DriverError, match="app_paths"):
        driver.clear_data("com.example.smartype")
    assert not [call for call in session.calls if call[0] == "script"]


def test_collect_logs_writes_syslog_since_a_time(tmp_path):
    driver, session = make_driver(tmp_path)
    since = datetime(2026, 1, 1, tzinfo=UTC)
    since_ms = int(since.timestamp() * 1000)
    session.syslog = [
        {"timestamp": since_ms - 1, "level": "ALL", "message": "old"},
        {"timestamp": since_ms + 1, "level": "ALL", "message": "new"},
    ]
    path = driver.collect_logs(since)
    assert ("get_log", "syslog") in session.calls
    assert path.read_text() == f"{since_ms + 1} ALL new\n"
    assert "old" in driver.collect_logs().read_text()


def test_recording_round_trip(tmp_path):
    driver, session = make_driver(tmp_path)
    handle = driver.start_recording()
    path = driver.stop_recording(handle)
    assert path.read_bytes() == b"fake-mp4"
    assert ("start_recording",) in session.calls and ("stop_recording",) in session.calls


def test_stop_recording_with_unknown_handle_raises(tmp_path):
    driver, _ = make_driver(tmp_path)
    with pytest.raises(DriverError):
        driver.stop_recording(RecordingHandle(recording_id="nope", started_at=datetime.now(UTC)))


def test_collect_bugreport_returns_none(tmp_path):
    driver, _ = make_driver(tmp_path)
    assert driver.collect_bugreport() is None


def test_close_quits_the_session(tmp_path):
    driver, session = make_driver(tmp_path)
    driver.close()
    assert session.calls[-1] == ("quit",)


def test_connection_errors_include_transport_and_session_failures():
    from selenium.common.exceptions import InvalidSessionIdException, NoSuchElementException
    from urllib3.exceptions import MaxRetryError

    assert issubclass(ConnectionRefusedError, IOS_CONNECTION_ERRORS)
    assert issubclass(http.client.RemoteDisconnected, IOS_CONNECTION_ERRORS)
    assert issubclass(MaxRetryError, IOS_CONNECTION_ERRORS)
    assert issubclass(InvalidSessionIdException, IOS_CONNECTION_ERRORS)
    assert not issubclass(NoSuchElementException, IOS_CONNECTION_ERRORS)


def test_missing_appium_client_gives_a_clear_error(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def no_appium(name, *args, **kwargs):
        if name == "appium" or name.startswith("appium."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_appium)
    with pytest.raises(DriverError, match=r"\[ios\]"):
        IosAppiumDriver(evidence_dir=tmp_path)
