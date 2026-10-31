from __future__ import annotations

import base64
import http.client
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from verdict.core.exceptions import DriverError, ElementNotFoundError
from verdict.core.models import (
    Direction,
    KeyEvent,
    KeyInput,
    Platform,
    RecordingHandle,
    Selector,
    UiHierarchy,
    normalize_key,
)
from verdict.device_driver.ios_hierarchy import parse_ios_hierarchy

DEFAULT_APPIUM_URL = "http://127.0.0.1:4723"

# Appium locator strategies (the values of `appium.webdriver.common.appiumby.AppiumBy`).
BY_ACCESSIBILITY_ID = "accessibility id"
BY_CLASS_NAME = "class name"
BY_IOS_PREDICATE = "-ios predicate string"

# The W3C WebDriver command name for pointer actions.
_W3C_ACTIONS = "actions"
_TAP_HOLD_MS = 100

# Characters that XCUITest types as the Return, Delete, and Tab keys.
_KEYBOARD_KEYS = {
    KeyEvent.ENTER: "\n",
    KeyEvent.DELETE: "\b",
    KeyEvent.TAB: "\t",
}


def _optional_connection_errors() -> tuple[type[BaseException], ...]:
    # The Appium client and its transport are optional (the `ios` extra).
    errors: list[type[BaseException]] = []
    try:
        from urllib3.exceptions import HTTPError as Urllib3HTTPError

        errors.append(Urllib3HTTPError)
    except ImportError:
        pass
    try:
        from selenium.common.exceptions import (
            InvalidSessionIdException,
            NoSuchDriverException,
            SessionNotCreatedException,
        )

        errors.extend((InvalidSessionIdException, NoSuchDriverException, SessionNotCreatedException))
    except ImportError:
        pass
    return tuple(errors)


# Errors that mean the Appium server, WebDriverAgent, or the device connection
# failed. They are not test results, so the CLI reports BLOCKED for them.
IOS_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    http.client.HTTPException,
    *_optional_connection_errors(),
)


class AppiumSession(Protocol):
    """The part of an Appium `webdriver.Remote` session that the iOS driver uses."""

    @property
    def page_source(self) -> str: ...

    @property
    def switch_to(self) -> Any: ...

    def execute(self, driver_command: str, params: dict[str, Any] | None = None) -> Any: ...

    def execute_script(self, script: str, *args: Any) -> Any: ...

    def find_elements(self, by: str, value: str | None = None) -> list[Any]: ...

    def get_screenshot_as_png(self) -> bytes: ...

    def get_log(self, log_type: str) -> list[dict[str, Any]]: ...

    def start_recording_screen(self, **options: Any) -> Any: ...

    def stop_recording_screen(self, **options: Any) -> Any: ...

    def quit(self) -> None: ...


def _predicate_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def to_ios_locator(selector: Selector) -> tuple[str, str]:
    """Map a `Selector` to an Appium locator `(strategy, value)` for XCUITest.

    `resource_id` maps to the accessibility id (`name`), `text` to `label` or
    `value`, `description` to `label`, and `class_name` to `type`. A selector
    with only `resource_id` or only `class_name` uses the direct strategy.
    All other selectors use an iOS predicate string.
    """
    fields = {
        name: value
        for name in ("resource_id", "text", "description", "class_name")
        if (value := getattr(selector, name)) is not None
    }
    if set(fields) == {"resource_id"}:
        return BY_ACCESSIBILITY_ID, fields["resource_id"]
    if set(fields) == {"class_name"}:
        return BY_CLASS_NAME, fields["class_name"]
    clauses: list[str] = []
    if "resource_id" in fields:
        clauses.append(f"name == {_predicate_literal(fields['resource_id'])}")
    if "text" in fields:
        literal = _predicate_literal(fields["text"])
        clauses.append(f"(label == {literal} OR value == {literal})")
    if "description" in fields:
        clauses.append(f"label == {_predicate_literal(fields['description'])}")
    if "class_name" in fields:
        clauses.append(f"type == {_predicate_literal(fields['class_name'])}")
    return BY_IOS_PREDICATE, " AND ".join(clauses)


def _pointer_actions(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "actions": [
            {
                "type": "pointer",
                "id": "finger1",
                "parameters": {"pointerType": "touch"},
                "actions": list(steps),
            }
        ]
    }


def _move(x: int, y: int, duration_ms: int = 0) -> dict[str, Any]:
    return {"type": "pointerMove", "duration": duration_ms, "x": x, "y": y, "origin": "viewport"}


_DOWN: dict[str, Any] = {"type": "pointerDown", "button": 0}
_UP: dict[str, Any] = {"type": "pointerUp", "button": 0}


def _pause(duration_ms: int) -> dict[str, Any]:
    return {"type": "pause", "duration": duration_ms}


@dataclass
class IosAppiumDriver:
    """`DeviceDriver` implementation for iOS. See ADR-0009.

    The driver sends all commands to an Appium server with the XCUITest
    driver. WebDriverAgent on the device does the UI operations. Apps are
    identified by their bundle id.

    The Appium client is optional (the `ios` extra). The driver imports it
    only when it opens a real session. Tests give a `session_factory` that
    returns a fake session.
    """

    udid: str | None = None
    appium_url: str = DEFAULT_APPIUM_URL
    capabilities: dict[str, Any] = field(default_factory=dict)
    app_paths: dict[str, str] = field(default_factory=dict)
    """The app file (`.app` or `.ipa`) for each bundle id. `clear_data` needs it."""
    session_factory: Callable[[], AppiumSession] | None = field(default=None, repr=False)
    evidence_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="verdict-ios-")))
    platform: Platform = field(default=Platform.IOS, init=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    poll_ms: int = 250
    tap_wait_ms: int = 5000
    dump_attempts: int = 3

    _session: AppiumSession = field(init=False, repr=False)
    _active_recording: tuple[RecordingHandle, Path] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        factory = self.session_factory or self._open_appium_session
        self._session = factory()

    def _open_appium_session(self) -> AppiumSession:
        try:
            from appium import webdriver
            from appium.options.ios import XCUITestOptions
        except ImportError as exc:
            raise DriverError(
                "The iOS driver needs the Appium client. Install it: pip install -e '.[ios]'"
            ) from exc
        options = XCUITestOptions()
        options.load_capabilities(self.capabilities)
        if self.udid:
            options.udid = self.udid
        return cast(AppiumSession, webdriver.Remote(self.appium_url, options=options))

    def close(self) -> None:
        """Stop the Appium session."""
        self._session.quit()

    def _find(self, selector: Selector) -> Any | None:
        elements = self._session.find_elements(*to_ios_locator(selector))
        return elements[0] if elements else None

    def _find_with_wait(self, selector: Selector, timeout_ms: int) -> Any | None:
        for _ in range(max(1, timeout_ms // self.poll_ms)):
            element = self._find(selector)
            if element is not None:
                return element
            self.sleep(self.poll_ms / 1000)
        return self._find(selector)

    def _send_to_focused(self, text: str) -> None:
        self._session.switch_to.active_element.send_keys(text)

    # -- InputDriver -----------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        self._session.execute(
            _W3C_ACTIONS, _pointer_actions(_move(x, y), _DOWN, _pause(_TAP_HOLD_MS), _UP)
        )

    def tap_selector(self, selector: Selector) -> None:
        element = self._find_with_wait(selector, self.tap_wait_ms)
        if element is None:
            raise ElementNotFoundError(f"No element matching {selector!r}")
        element.click()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._session.execute(
            _W3C_ACTIONS, _pointer_actions(_move(x1, y1), _DOWN, _move(x2, y2, duration_ms), _UP)
        )

    def scroll(self, direction: Direction, selector: Selector | None = None) -> None:
        args: dict[str, Any] = {"direction": direction.value}
        if selector is not None:
            element = self._find(selector)
            if element is None:
                raise ElementNotFoundError(f"No element matching {selector!r}")
            args["elementId"] = element.id
        self._session.execute_script("mobile: scroll", args)

    def type_text(self, text: str) -> None:
        self._send_to_focused(text)

    def type_keys(self, text: str, interval_ms: int = 150) -> None:
        for char in text:
            self._send_to_focused(char)
            self.sleep(interval_ms / 1000)

    def press_key(self, key: KeyInput) -> None:
        try:
            normalized = normalize_key(key)
        except ValueError as exc:
            raise DriverError(str(exc)) from exc
        if normalized is KeyEvent.HOME:
            self._session.execute_script("mobile: pressButton", {"name": "home"})
            return
        if isinstance(normalized, KeyEvent) and normalized in _KEYBOARD_KEYS:
            self._send_to_focused(_KEYBOARD_KEYS[normalized])
            return
        if normalized is KeyEvent.BACK:
            raise DriverError("iOS has no back key. Tap the back button of the app.")
        raise DriverError(f"iOS does not support the key code {normalized!r}.")

    def screenshot(self) -> Path:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"screenshot-{uuid.uuid4().hex}.png"
        path.write_bytes(self._session.get_screenshot_as_png())
        return path

    def dump_hierarchy(self) -> UiHierarchy:
        last_error: ET.ParseError | None = None
        for attempt in range(max(1, self.dump_attempts)):
            if attempt:
                self.sleep(self.poll_ms / 1000)
            try:
                return parse_ios_hierarchy(self._session.page_source)
            except ET.ParseError as exc:
                last_error = exc
        raise DriverError(
            f"hierarchy dump failed after {max(1, self.dump_attempts)} attempt(s): {last_error}"
        ) from last_error

    def wait_for(self, selector: Selector, timeout_ms: int) -> bool:
        return self._find_with_wait(selector, timeout_ms) is not None

    # -- AppLifecycleDriver ------------------------------------------------

    def install(self, path: str) -> None:
        self._session.execute_script("mobile: installApp", {"app": path})

    def uninstall(self, package: str) -> None:
        self._session.execute_script("mobile: removeApp", {"bundleId": package})

    def launch(self, package: str, activity: str | None = None) -> None:
        # iOS apps have no activities. The driver ignores `activity`.
        self._session.execute_script("mobile: activateApp", {"bundleId": package})

    def clear_data(self, package: str) -> None:
        path = self.app_paths.get(package)
        if path is None:
            raise DriverError(
                f"iOS has no clear-data command. Verdict must install {package} again, "
                "but the app file is unknown. Give it in `app_paths`."
            )
        self.uninstall(package)
        self.install(path)

    # -- DiagnosticsDriver ---------------------------------------------------

    def collect_logs(self, since: datetime | None = None) -> Path:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"syslog-{uuid.uuid4().hex}.txt"
        since_ms = since.timestamp() * 1000 if since is not None else None
        lines = [
            f"{entry.get('timestamp', '')} {entry.get('level', '')} {entry.get('message', '')}"
            for entry in self._session.get_log("syslog")
            if since_ms is None or float(entry.get("timestamp", 0)) >= since_ms
        ]
        path.write_text("\n".join(lines) + ("\n" if lines else ""))
        return path

    def start_recording(self) -> RecordingHandle:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"recording-{uuid.uuid4().hex}.mp4"
        handle = RecordingHandle(recording_id=uuid.uuid4().hex, started_at=datetime.now(UTC))
        self._session.start_recording_screen()
        self._active_recording = (handle, path)
        return handle

    def stop_recording(self, handle: RecordingHandle) -> Path:
        if self._active_recording is None or self._active_recording[0].recording_id != handle.recording_id:
            raise DriverError(f"No active recording with id {handle.recording_id}")
        encoded = self._session.stop_recording_screen()
        _, path = self._active_recording
        self._active_recording = None
        path.write_bytes(base64.b64decode(encoded))
        return path

    def collect_bugreport(self) -> Path | None:
        return None
