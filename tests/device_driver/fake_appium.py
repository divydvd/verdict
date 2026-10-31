"""A fake Appium session for the iOS driver tests. It records each call."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from verdict.device_driver.ios_appium import IosAppiumDriver

FIXTURE_XML = (Path(__file__).parent / "fixtures" / "xcuitest_source.xml").read_text()


class FakeElement:
    def __init__(self, calls: list[tuple[Any, ...]], element_id: str = "el-1") -> None:
        self.calls = calls
        self.id = element_id

    def click(self) -> None:
        self.calls.append(("click", self.id))

    def send_keys(self, text: str) -> None:
        self.calls.append(("send_keys", text))


class _SwitchTo:
    def __init__(self, calls: list[tuple[Any, ...]]) -> None:
        self.active_element = FakeElement(calls, "focused")


class FakeAppiumSession:
    def __init__(self, page_source: str = FIXTURE_XML) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.page_sources = [page_source]
        self.elements: dict[tuple[str, str], list[FakeElement]] = {}
        self.missing_reads = 0
        self.syslog: list[dict[str, Any]] = []
        self.recording = b"fake-mp4"
        self.switch_to = _SwitchTo(self.calls)

    @property
    def page_source(self) -> str:
        source = self.page_sources.pop(0) if len(self.page_sources) > 1 else self.page_sources[0]
        self.calls.append(("page_source",))
        return source

    def add_element(self, by: str, value: str, element_id: str = "el-1") -> FakeElement:
        element = FakeElement(self.calls, element_id)
        self.elements.setdefault((by, value), []).append(element)
        return element

    def execute(self, driver_command: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("execute", driver_command, params))
        return None

    def execute_script(self, script: str, *args: Any) -> Any:
        self.calls.append(("script", script, *args))
        return None

    def find_elements(self, by: str, value: str | None = None) -> list[Any]:
        self.calls.append(("find", by, value))
        if self.missing_reads > 0:
            self.missing_reads -= 1
            return []
        return list(self.elements.get((by, value or ""), []))

    def get_screenshot_as_png(self) -> bytes:
        return b"\x89PNG fake"

    def get_log(self, log_type: str) -> list[dict[str, Any]]:
        self.calls.append(("get_log", log_type))
        return self.syslog

    def start_recording_screen(self, **options: Any) -> Any:
        self.calls.append(("start_recording",))
        return None

    def stop_recording_screen(self, **options: Any) -> Any:
        self.calls.append(("stop_recording",))
        return base64.b64encode(self.recording)

    def quit(self) -> None:
        self.calls.append(("quit",))


def make_driver(
    tmp_path: Path, session: FakeAppiumSession | None = None, **kwargs: Any
) -> tuple[IosAppiumDriver, FakeAppiumSession]:
    fake = session or FakeAppiumSession()
    kwargs.setdefault("sleep", lambda seconds: None)
    driver = IosAppiumDriver(session_factory=lambda: fake, evidence_dir=tmp_path, **kwargs)
    return driver, fake
