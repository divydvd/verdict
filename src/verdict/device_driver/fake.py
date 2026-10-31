from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from verdict.core.exceptions import DriverError, ElementNotFoundError
from verdict.core.models import (
    Direction,
    KeyInput,
    Platform,
    RecordingHandle,
    Selector,
    UiHierarchy,
    UiNode,
    normalize_key,
)


@dataclass
class FakeDeviceDriver:
    """In-memory `DeviceDriver` for unit tests — no emulator/device required.

    Satisfies the full protocol (verified via `isinstance` against
    `DeviceDriver` in tests). UI state is a plain `UiNode` tree that test
    code sets up via `set_hierarchy()` to simulate screen transitions;
    every call is recorded on the corresponding `*_calls` list so tests can
    assert on driver interaction without a real device.
    """

    platform: Platform = Platform.ANDROID
    evidence_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="verdict-fake-")))

    _hierarchy: UiNode | None = field(default=None, init=False, repr=False)
    _log_content: str = field(default="", init=False, repr=False)
    installed_packages: set[str] = field(default_factory=set, init=False)
    current_package: str | None = field(default=None, init=False)
    cleared_data: list[str] = field(default_factory=list, init=False)
    tap_calls: list[tuple[int, int]] = field(default_factory=list, init=False)
    swipe_calls: list[tuple[int, int, int, int, int]] = field(default_factory=list, init=False)
    scroll_calls: list[tuple[Direction, Selector | None]] = field(default_factory=list, init=False)
    typed_text: list[str] = field(default_factory=list, init=False)
    typed_keys: list[tuple[str, int]] = field(default_factory=list, init=False)
    pressed_keys: list[KeyInput] = field(default_factory=list, init=False)
    screenshots_taken: list[Path] = field(default_factory=list, init=False)
    logs_collected: list[Path] = field(default_factory=list, init=False)
    bugreports_collected: list[Path] = field(default_factory=list, init=False)
    available_keyboards: set[str] | None = None
    """The keyboards that `select_keyboard` accepts. None accepts all names."""
    active_keyboard: str | None = None
    selected_keyboards: list[str] = field(default_factory=list, init=False)
    _active_recording: RecordingHandle | None = field(default=None, init=False, repr=False)
    _recordings_stopped: list[RecordingHandle] = field(default_factory=list, init=False)

    def set_hierarchy(self, root: UiNode | None) -> None:
        """Test-setup hook: replace the current fake UI tree."""
        self._hierarchy = root

    def set_logs(self, content: str) -> None:
        """Test-setup hook: content returned by the next collect_logs() call."""
        self._log_content = content

    def tap(self, x: int, y: int) -> None:
        self.tap_calls.append((x, y))

    def tap_selector(self, selector: Selector) -> None:
        hierarchy = self.dump_hierarchy()
        node = hierarchy.find(selector)
        if node is None:
            raise ElementNotFoundError(f"No element matching {selector!r}")
        x, y = self._center(node)
        self.tap_calls.append((x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipe_calls.append((x1, y1, x2, y2, duration_ms))

    def scroll(self, direction: Direction, selector: Selector | None = None) -> None:
        self.scroll_calls.append((direction, selector))

    def type_text(self, text: str) -> None:
        self.typed_text.append(text)

    def type_keys(self, text: str, interval_ms: int = 150) -> None:
        self.typed_keys.append((text, interval_ms))

    def press_key(self, key: KeyInput) -> None:
        self.pressed_keys.append(normalize_key(key))

    def select_keyboard(self, name: str) -> None:
        if self.available_keyboards is not None and name not in self.available_keyboards:
            raise DriverError(f"select_keyboard: no keyboard '{name}'")
        self.selected_keyboards.append(name)
        self.active_keyboard = name

    def screenshot(self) -> Path:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"screenshot-{len(self.screenshots_taken)}.png"
        path.write_bytes(b"")
        self.screenshots_taken.append(path)
        return path

    def dump_hierarchy(self) -> UiHierarchy:
        root = self._hierarchy
        return UiHierarchy(raw_xml="<fake/>", root=root)

    def wait_for(self, selector: Selector, timeout_ms: int) -> bool:
        return self.dump_hierarchy().find(selector) is not None

    def install(self, path: str) -> None:
        self.installed_packages.add(path)

    def uninstall(self, package: str) -> None:
        self.installed_packages.discard(package)
        if self.current_package == package:
            self.current_package = None

    def launch(self, package: str, activity: str | None = None) -> None:
        self.current_package = package

    def clear_data(self, package: str) -> None:
        self.cleared_data.append(package)

    def collect_logs(self, since: datetime | None = None) -> Path:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"logs-{len(self.logs_collected)}.txt"
        path.write_text(self._log_content)
        self.logs_collected.append(path)
        return path

    def start_recording(self) -> RecordingHandle:
        handle = RecordingHandle(recording_id=str(uuid.uuid4()), started_at=datetime.now(UTC))
        self._active_recording = handle
        return handle

    def stop_recording(self, handle: RecordingHandle) -> Path:
        if self._active_recording is None or self._active_recording.recording_id != handle.recording_id:
            raise ValueError(f"No active recording with id {handle.recording_id}")
        self._active_recording = None
        self._recordings_stopped.append(handle)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"recording-{handle.recording_id}.mp4"
        path.write_bytes(b"")
        return path

    def collect_bugreport(self) -> Path | None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"bugreport-{len(self.bugreports_collected)}.zip"
        path.write_bytes(b"")
        self.bugreports_collected.append(path)
        return path

    @staticmethod
    def _center(node: UiNode) -> tuple[int, int]:
        if node.bounds is None:
            return (0, 0)
        left, top, right, bottom = node.bounds
        return ((left + right) // 2, (top + bottom) // 2)
