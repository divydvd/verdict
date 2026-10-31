from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from verdict.core.models import (
    Direction,
    KeyInput,
    Platform,
    RecordingHandle,
    Selector,
    UiHierarchy,
)


@runtime_checkable
class InputDriver(Protocol):
    """Universal input primitives. Applies across mobile, desktop, and web —
    selector semantics differ per platform, but the operations themselves
    don't. See docs/adr/0007-layered-device-driver-protocols.md.
    """

    def tap(self, x: int, y: int) -> None: ...

    def tap_selector(self, selector: Selector) -> None: ...

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None: ...

    def scroll(self, direction: Direction, selector: Selector | None = None) -> None:
        """Scroll in `direction`. The meaning depends on `selector`:

        - No selector: swipe the screen. `direction` is the direction of the
          finger, so UP shows the content below.
        - With a selector: scroll that element. `direction` is the content to
          show, so DOWN shows the content below and RIGHT the content to the
          right.
        """
        ...

    def type_text(self, text: str) -> None: ...

    def type_keys(self, text: str, interval_ms: int = 150) -> None:
        """Send `text` one character at a time as real key input, with a
        pause of `interval_ms` after each character. Unlike `type_text`
        (which can paste the whole string), this drives the keyboard's
        key-event path, so key-driven behaviour such as autocorrect runs.
        """
        ...

    def press_key(self, key: KeyInput) -> None:
        """Press one key: a `KeyEvent`, or any platform key code
        (for Android, a number or a name such as `KEYCODE_POUND`)."""
        ...

    def screenshot(self) -> Path: ...

    def dump_hierarchy(self) -> UiHierarchy: ...

    def wait_for(self, selector: Selector, timeout_ms: int) -> bool: ...


@runtime_checkable
class AppLifecycleDriver(Protocol):
    """Mobile-app lifecycle operations. Not implemented by non-app-based
    platforms (e.g. a future Web driver would implement a different
    lifecycle protocol — navigate/clear_cookies — instead of this one).
    """

    def install(self, path: str) -> None: ...

    def uninstall(self, package: str) -> None: ...

    def launch(self, package: str, activity: str | None = None) -> None: ...

    def clear_data(self, package: str) -> None: ...


@runtime_checkable
class DiagnosticsDriver(Protocol):
    """Log/recording/bugreport collection. Semantics adapt per platform
    (logcat vs. browser console vs. OS event log); collect_bugreport is
    optional since it has no cross-platform equivalent.
    """

    def collect_logs(self, since: datetime | None = None) -> Path: ...

    def start_recording(self) -> RecordingHandle: ...

    def stop_recording(self, handle: RecordingHandle) -> Path: ...

    def collect_bugreport(self) -> Path | None: ...


@runtime_checkable
class KeyboardDriver(Protocol):
    """Selects the active on-screen keyboard. An optional capability: it is
    not part of `DeviceDriver`. See docs/adr/0010-keyboard-selection-capability.md.
    """

    def select_keyboard(self, name: str) -> None:
        """Make the keyboard `name` the active keyboard, then check it.

        `name` is platform-specific: the IME id on Android
        (`package/.Service`), and the name in the globe-key list on iOS.
        Raises `DriverError` (or `ElementNotFoundError`) when the keyboard
        is not available or does not become active.
        """
        ...


@runtime_checkable
class DeviceDriver(InputDriver, AppLifecycleDriver, DiagnosticsDriver, Protocol):
    """Composition of all three capability protocols. Android's
    implementation satisfies this in full; other platforms may implement
    only a subset of the constituent protocols (see ADR-0007).
    """

    platform: Platform
