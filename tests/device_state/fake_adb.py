"""A scripted in-memory phone for the device-state tests. No adb, no phone."""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

from verdict.device_state.adb import AdbError

TARGET = "bha.keys.smartype.debug"
PLAY = "bha.keys.smartype"
TARGET_IME = f"{TARGET}/bha.keys.smartype.FlorisImeService"
GBOARD = "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"
SAMSUNG = "com.samsung.android.honeyboard/.service.HoneyBoardService"


def make_tar(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@dataclass
class FakePhone:
    devices_list: list[tuple[str, str]] = field(default_factory=lambda: [("R5CX", "device")])
    user: str = "0"
    window: str = "mDreamingLockscreen=false"
    packages: dict[str, tuple[int, str]] = field(
        default_factory=lambda: {PLAY: (90, "1.9"), TARGET: (100, "2.0-debug+abc1234")}
    )
    secure: dict[str, str] = field(
        default_factory=lambda: {
            "default_input_method": TARGET_IME,
            "enabled_input_methods": f"{TARGET_IME}:{GBOARD}",
            "selected_input_method_subtype": "-1",
        }
    )
    system: dict[str, str] = field(
        default_factory=lambda: {"font_scale": "1.0", "accelerometer_rotation": "1", "user_rotation": "0"}
    )
    global_: dict[str, str] = field(default_factory=lambda: {"stay_on_while_plugged_in": "0"})
    night: str = "no"
    all_imes: list[str] = field(default_factory=lambda: [TARGET_IME, GBOARD, SAMSUNG])
    apk_paths: list[str] = field(default_factory=lambda: ["/data/app/~~x/base.apk"])
    apk_bytes: bytes = b"pretest-apk"
    app_files: dict[str, bytes] = field(
        default_factory=lambda: {"./shared_prefs/a.xml": b"<a/>", "./files/b.db": b"db"}
    )
    tar_override: bytes | None = None
    fail_on: set[str] = field(default_factory=set)
    commands: list[str] = field(default_factory=list)

    def devices(self) -> list[tuple[str, str]]:
        return list(self.devices_list)

    def _enabled(self) -> list[str]:
        value = self.secure["enabled_input_methods"]
        return [part.split(";")[0] for part in value.split(":") if part]

    def shell(self, command: str) -> str:
        self.commands.append(command)
        for fragment in self.fail_on:
            if fragment in command:
                raise AdbError(f"scripted failure: {command}")
        words = command.split()
        if command == "am get-current-user":
            return f"{self.user}\n"
        if command == "dumpsys window":
            return self.window
        if words[:3] == ["pm", "list", "packages"]:
            return "".join(f"package:{name}\n" for name in self.packages)
        if words[:2] == ["dumpsys", "package"]:
            code, name = self.packages[words[2]]
            return f"    versionCode={code} minSdk=26 targetSdk=35\n    versionName={name}\n"
        if words[:2] == ["pm", "path"]:
            return "".join(f"package:{path}\n" for path in self.apk_paths)
        if words[:2] == ["settings", "get"]:
            table = {"secure": self.secure, "system": self.system, "global": self.global_}[words[2]]
            return table.get(words[3], "null") + "\n"
        if command == "cmd uimode night":
            return f"Night mode: {self.night}\n"
        if command == "ime list -s":
            return "".join(f"{ime}\n" for ime in self._enabled())
        if command == "ime list -a -s":
            return "".join(f"{ime}\n" for ime in self.all_imes)
        if words[:2] == ["ime", "enable"]:
            enabled = self._enabled()
            if words[2] not in enabled:
                self.secure["enabled_input_methods"] = ":".join([*enabled, words[2]])
            return ""
        if words[:2] == ["ime", "disable"]:
            enabled = [ime for ime in self._enabled() if ime != words[2]]
            self.secure["enabled_input_methods"] = ":".join(enabled)
            return ""
        if words[:2] == ["ime", "set"]:
            self.secure["default_input_method"] = words[2]
            return ""
        if words[:2] == ["am", "force-stop"]:
            return ""
        if words[:1] == ["run-as"] and "sha256sum" in command:
            import hashlib

            return "".join(
                f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                for name, data in sorted(self.app_files.items())
            )
        raise AssertionError(f"unexpected adb shell command: {command}")

    def exec_out_to_file(self, command: str, path: Path) -> None:
        self.commands.append(f"exec-out {command}")
        data = self.tar_override if self.tar_override is not None else make_tar(self.app_files)
        path.write_bytes(data)

    def pull(self, remote: str, local: Path) -> None:
        self.commands.append(f"pull {remote}")
        local.write_bytes(self.apk_bytes)
