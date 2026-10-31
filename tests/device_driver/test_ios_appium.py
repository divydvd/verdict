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


@pytest.mark.parametrize("direction", list(Direction))
def test_scroll_without_selector_swipes_in_the_finger_direction(tmp_path, direction):
    # Like Android `swipe_ext`: UP moves the finger up and shows the content below.
    driver, session = make_driver(tmp_path)
    driver.scroll(direction)
    assert session.calls[-1] == ("script", "mobile: swipe", {"direction": direction.value})


@pytest.mark.parametrize("direction", list(Direction))
def test_scroll_with_selector_shows_the_content_in_that_direction(tmp_path, direction):
    # Like Android `scroll.forward`: DOWN shows the content below. In
    # `mobile: scroll`, the direction is the content to show.
    driver, session = make_driver(tmp_path)
    session.add_element(BY_ACCESSIBILITY_ID, "list", "el-9")
    driver.scroll(direction, Selector(resource_id="list"))
    assert session.calls[-1] == (
        "script",
        "mobile: scroll",
        {"direction": direction.value, "elementId": "el-9"},
    )


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
    # The base class covers "element not found" too. The driver changes that
    # error into ElementNotFoundError before it leaves the driver.
    assert issubclass(NoSuchElementException, IOS_CONNECTION_ERRORS)
    assert not issubclass(ElementNotFoundError, IOS_CONNECTION_ERRORS)


def test_missing_appium_client_gives_a_clear_error(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def no_appium(name, *args, **kwargs):
        if name == "appium" or name.startswith("appium."):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_appium)
    with pytest.raises(DriverError, match=r"\[ios\]"):
        IosAppiumDriver(evidence_dir=tmp_path)


def test_no_such_element_from_lookup_is_not_found(tmp_path):
    from selenium.common.exceptions import NoSuchElementException

    driver, session = make_driver(tmp_path, poll_ms=100, tap_wait_ms=200)
    session.find_error = NoSuchElementException("none")
    assert not driver.wait_for(Selector(resource_id="x"), timeout_ms=200)
    with pytest.raises(ElementNotFoundError):
        driver.tap_selector(Selector(resource_id="x"))


def test_lost_session_error_is_a_connection_error(tmp_path):
    from selenium.common.exceptions import WebDriverException

    driver, session = make_driver(tmp_path)
    session.find_error = WebDriverException("WDA crashed")
    with pytest.raises(IOS_CONNECTION_ERRORS):
        driver.tap_selector(Selector(resource_id="x"))


def test_stale_element_is_found_again_one_time(tmp_path):
    driver, session = make_driver(tmp_path)
    element = session.add_element(BY_ACCESSIBILITY_ID, "sendButton", "el-2")
    element.stale_clicks = 1
    driver.tap_selector(Selector(resource_id="sendButton"))
    assert session.calls[-1] == ("click", "el-2")
    assert [call[0] for call in session.calls].count("find") == 2


def test_element_stale_two_times_is_not_found(tmp_path):
    driver, session = make_driver(tmp_path)
    element = session.add_element(BY_ACCESSIBILITY_ID, "sendButton", "el-2")
    element.stale_clicks = 2
    with pytest.raises(ElementNotFoundError, match="stale"):
        driver.tap_selector(Selector(resource_id="sendButton"))


def test_stale_element_in_scroll_is_found_again(tmp_path):
    from selenium.common.exceptions import StaleElementReferenceException

    driver, session = make_driver(tmp_path)
    session.add_element(BY_ACCESSIBILITY_ID, "list", "el-9")
    real_script = session.execute_script
    failures = [StaleElementReferenceException("stale")]

    def script(name, *args):
        if failures:
            raise failures.pop()
        return real_script(name, *args)

    session.execute_script = script
    driver.scroll(Direction.DOWN, Selector(resource_id="list"))
    assert session.calls[-1] == ("script", "mobile: scroll", {"direction": "down", "elementId": "el-9"})


def test_wait_checks_again_at_the_deadline(tmp_path):
    sleeps: list[float] = []
    driver, session = make_driver(tmp_path, sleep=sleeps.append, poll_ms=250)
    session.add_element(BY_ACCESSIBILITY_ID, "late")
    session.missing_reads = 2
    assert driver.wait_for(Selector(resource_id="late"), timeout_ms=350)
    assert sleeps == pytest.approx([0.25, 0.1])


def test_zero_timeout_checks_one_time_and_does_not_sleep(tmp_path):
    sleeps: list[float] = []
    driver, session = make_driver(tmp_path, sleep=sleeps.append)
    assert not driver.wait_for(Selector(resource_id="missing"), timeout_ms=0)
    assert sleeps == []
    assert [call[0] for call in session.calls].count("find") == 1


def test_collect_logs_keeps_entries_from_earlier_reads(tmp_path):
    driver, session = make_driver(tmp_path)
    session.syslog = [{"timestamp": 1, "level": "ALL", "message": "first"}]
    assert "first" in driver.collect_logs().read_text()
    session.syslog = [{"timestamp": 2, "level": "ALL", "message": "second"}]
    assert driver.collect_logs().read_text() == "1 ALL first\n2 ALL second\n"
    assert driver.collect_logs(datetime.fromtimestamp(0.002, UTC)).read_text() == "2 ALL second\n"


def _selenium(name):
    from selenium.common import exceptions

    return getattr(exceptions, name)


@pytest.mark.parametrize(
    "name",
    [
        "InvalidElementStateException",
        "ElementNotInteractableException",
        "ElementClickInterceptedException",
        "MoveTargetOutOfBoundsException",
    ],
)
def test_element_errors_in_tap_selector_are_driver_errors(tmp_path, name):
    driver, session = make_driver(tmp_path)
    element = session.add_element(BY_ACCESSIBILITY_ID, "sendButton")
    element.click = lambda: (_ for _ in ()).throw(_selenium(name)("no"))
    with pytest.raises(DriverError) as info:
        driver.tap_selector(Selector(resource_id="sendButton"))
    assert not isinstance(info.value, IOS_CONNECTION_ERRORS)


def test_no_such_element_in_an_action_is_element_not_found(tmp_path):
    driver, session = make_driver(tmp_path)
    element = session.add_element(BY_ACCESSIBILITY_ID, "sendButton")
    element.click = lambda: (_ for _ in ()).throw(_selenium("NoSuchElementException")("gone"))
    with pytest.raises(ElementNotFoundError):
        driver.tap_selector(Selector(resource_id="sendButton"))


def test_invalid_selector_in_lookup_is_a_driver_error(tmp_path):
    driver, session = make_driver(tmp_path)
    session.find_error = _selenium("InvalidSelectorException")("bad predicate")
    with pytest.raises(DriverError) as info:
        driver.wait_for(Selector(text="x"), timeout_ms=0)
    assert not isinstance(info.value, IOS_CONNECTION_ERRORS)


def test_element_error_in_scroll_with_selector_is_a_driver_error(tmp_path):
    driver, session = make_driver(tmp_path)
    session.add_element(BY_ACCESSIBILITY_ID, "list")

    def script(name, *args):
        raise _selenium("InvalidElementStateException")("not scrollable")

    session.execute_script = script
    with pytest.raises(DriverError):
        driver.scroll(Direction.DOWN, Selector(resource_id="list"))


@pytest.mark.parametrize("method", ["type_text", "type_keys"])
def test_element_errors_in_typing_are_driver_errors(tmp_path, method):
    driver, session = make_driver(tmp_path)
    error = _selenium("ElementNotInteractableException")("keyboard hidden")
    session.switch_to.active_element.send_keys = lambda text: (_ for _ in ()).throw(error)
    with pytest.raises(DriverError):
        getattr(driver, method)("ab")


def test_no_focused_element_is_element_not_found(tmp_path):
    driver, session = make_driver(tmp_path)
    error = _selenium("NoSuchElementException")("no focus")
    session.switch_to.active_element.send_keys = lambda text: (_ for _ in ()).throw(error)
    with pytest.raises(ElementNotFoundError):
        driver.press_key(KeyEvent.ENTER)


def test_out_of_bounds_tap_is_a_driver_error(tmp_path):
    driver, session = make_driver(tmp_path)

    def execute(command, params=None):
        raise _selenium("MoveTargetOutOfBoundsException")("outside")

    session.execute = execute
    with pytest.raises(DriverError):
        driver.tap(9999, 9999)
    with pytest.raises(DriverError):
        driver.swipe(0, 0, 9999, 9999)


def test_other_webdriver_errors_pass_through_as_blocked(tmp_path):
    driver, session = make_driver(tmp_path)
    error = _selenium("WebDriverException")("WDA crashed")
    session.switch_to.active_element.send_keys = lambda text: (_ for _ in ()).throw(error)
    with pytest.raises(IOS_CONNECTION_ERRORS) as info:
        driver.type_text("a")
    assert not isinstance(info.value, DriverError)
