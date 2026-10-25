from __future__ import annotations

import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import adbutils
import uiautomator2 as u2

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
from verdict.device_driver.android_hierarchy import parse_hierarchy_xml
from verdict.device_driver.android_keys import input_failed, key_input_commands, keyevent_command

# Maps our platform-neutral Selector field names onto uiautomator2's
# UiSelector kwarg names (see uiautomator2._selector.Selector.__fields).
_SELECTOR_FIELD_MAP = {
    "resource_id": "resourceId",
    "text": "text",
    "description": "description",
    "class_name": "className",
}


def _to_u2_kwargs(selector: Selector) -> dict[str, str]:
    kwargs: dict[str, str] = {}
    for our_field, u2_field in _SELECTOR_FIELD_MAP.items():
        value = getattr(selector, our_field)
        if value is not None:
            kwargs[u2_field] = value
    return kwargs


@dataclass
class AndroidUiautomator2Driver:
    """`DeviceDriver` implementation for Android — see ADR-0002.

    InputDriver operations go through `uiautomator2` (element selection,
    waits, gestures, text input). AppLifecycleDriver/DiagnosticsDriver
    operations go through the underlying `adbutils.AdbDevice`
    (`self._device.adb_device`) — install/uninstall/clear-data, logcat,
    screen recording, and bugreports have no IME-specific behaviour and
    don't benefit from the uiautomator2 layer.
    """

    serial: str | None = None
    evidence_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="verdict-android-")))
    platform: Platform = field(default=Platform.ANDROID, init=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    _device: u2.Device = field(init=False, repr=False)
    _adb: adbutils.AdbDevice = field(init=False, repr=False)
    _active_recording: tuple[RecordingHandle, Path] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._device = u2.connect(self.serial) if self.serial else u2.connect()
        self._adb = self._device.adb_device

    def _ui_object(self, selector: Selector) -> Any:
        return self._device(**_to_u2_kwargs(selector))

    # -- InputDriver -----------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        self._device.click(x, y)

    def tap_selector(self, selector: Selector) -> None:
        obj = self._ui_object(selector)
        if not obj.exists:
            raise ElementNotFoundError(f"No element matching {selector!r}")
        obj.click()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._device.swipe(x1, y1, x2, y2, duration=duration_ms / 1000)

    def scroll(self, direction: Direction, selector: Selector | None = None) -> None:
        if selector is None:
            self._device.swipe_ext(direction.value)
            return
        obj = self._ui_object(selector)
        axis = obj.scroll.horiz if direction in (Direction.LEFT, Direction.RIGHT) else obj.scroll.vert
        action = axis.forward if direction in (Direction.DOWN, Direction.RIGHT) else axis.backward
        action()

    def type_text(self, text: str) -> None:
        self._device.send_keys(text)

    def type_keys(self, text: str, interval_ms: int = 150) -> None:
        # One `adb shell input` call per character: a single long `input text`
        # call races and drops characters (SmarType testing doc, caveat 1).
        for command in key_input_commands(text):
            self._shell_input(command)
            self.sleep(interval_ms / 1000)

    def press_key(self, key: KeyInput) -> None:
        try:
            normalized = normalize_key(key)
        except ValueError as exc:
            raise DriverError(str(exc)) from exc
        if isinstance(normalized, KeyEvent):
            self._device.press(normalized.value)
            return
        self._shell_input(keyevent_command(normalized))

    def _shell_input(self, command: str) -> None:
        output = str(self._adb.shell(command))
        if input_failed(output):
            raise DriverError(f"`{command}` failed: {output.strip()}")

    def screenshot(self) -> Path:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"screenshot-{uuid.uuid4().hex}.png"
        self._device.screenshot(filename=str(path))
        return path

    def dump_hierarchy(self) -> UiHierarchy:
        raw_xml = self._device.dump_hierarchy()
        return UiHierarchy(raw_xml=raw_xml, root=parse_hierarchy_xml(raw_xml))

    def wait_for(self, selector: Selector, timeout_ms: int) -> bool:
        return bool(self._ui_object(selector).wait(timeout=timeout_ms / 1000))

    # -- AppLifecycleDriver ------------------------------------------------

    def install(self, path: str) -> None:
        self._adb.install(path)

    def uninstall(self, package: str) -> None:
        self._adb.uninstall(package)

    def launch(self, package: str, activity: str | None = None) -> None:
        self._device.app_start(package, activity)

    def clear_data(self, package: str) -> None:
        self._adb.app_clear(package)

    # -- DiagnosticsDriver ---------------------------------------------------

    def collect_logs(self, since: datetime | None = None) -> Path:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"logcat-{uuid.uuid4().hex}.txt"
        output = self._adb.shell("logcat -d -v time")
        path.write_text(output)
        return path

    def start_recording(self) -> RecordingHandle:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"recording-{uuid.uuid4().hex}.mp4"
        handle = RecordingHandle(recording_id=uuid.uuid4().hex, started_at=datetime.now(UTC))
        self._adb.start_recording(str(path))
        self._active_recording = (handle, path)
        return handle

    def stop_recording(self, handle: RecordingHandle) -> Path:
        if self._active_recording is None or self._active_recording[0].recording_id != handle.recording_id:
            raise DriverError(f"No active recording with id {handle.recording_id}")
        self._adb.stop_recording()
        _, path = self._active_recording
        self._active_recording = None
        return path

    def collect_bugreport(self) -> Path | None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        local_path = self.evidence_dir / f"bugreport-{uuid.uuid4().hex}.zip"
        try:
            output = self._adb.shell("bugreportz")
        except adbutils.AdbError:
            return None
        if not output.startswith("OK:"):
            return None
        remote_path = output.split("OK:", 1)[1].strip()
        self._adb.sync.pull(remote_path, str(local_path))
        return local_path
