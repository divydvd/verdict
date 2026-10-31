"""Readiness checks for iOS device tests (`verdict doctor ios`). See ADR-0009.

Each check starts host tools through an injectable `CommandRunner`, so the
tests need no Xcode, Appium, or device. The external commands are:
`xcode-select`, `xcodebuild`, `appium`, `xcrun devicectl`, `xcrun simctl`,
and `idevice_id`. The Appium check also sends one HTTP GET to `/status`.
"""

from __future__ import annotations

import http.client
import importlib
import json
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from verdict.core.exceptions import VerdictError

IOS_EXTRA_INSTALL = "pip install -e '.[ios]'"
_COMMAND_LINE_TOOLS = "CommandLineTools"
_XCODE_SELECT_FIX = (
    "Install Xcode from the App Store. Then run: "
    "sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
)
_DEVICE_FIX = (
    "Connect the iPhone with a cable and trust this Mac, "
    "or boot a Simulator: xcrun simctl boot <UDID>"
)


class IosExtraMissingError(VerdictError):
    """The `ios` extra (the Appium client) is not installed."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def output(self) -> str:
        return f"{self.stdout}\n{self.stderr}"


# Runs a command and returns its result. Raises OSError when the program is not found.
CommandRunner = Callable[[Sequence[str]], CommandResult]
# Sends a GET request and returns the HTTP status. Raises OSError when the server does not answer.
HttpGet = Callable[[str], int]
ModuleImporter = Callable[[str], object]


def subprocess_runner(command: Sequence[str]) -> CommandResult:
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(returncode=124, stderr=f"timeout after {exc.timeout} s")
    return CommandResult(done.returncode, done.stdout, done.stderr)


def urllib_get(url: str) -> int:
    with urllib.request.urlopen(url, timeout=5) as response:
        return int(response.status)


def ios_extra_installed(import_module: ModuleImporter = importlib.import_module) -> bool:
    """Return True if the Appium client of the `ios` extra imports."""
    try:
        import_module("appium.webdriver")
    except ImportError:
        return False
    return True


class CheckStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str
    fix: str | None = None


def _run(runner: CommandRunner, command: Sequence[str]) -> CommandResult | None:
    try:
        return runner(command)
    except OSError:
        return None


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def check_xcode(runner: CommandRunner) -> Check:
    selected = _run(runner, ["xcode-select", "-p"])
    if selected is None or selected.returncode != 0:
        return Check("xcode", CheckStatus.FAIL, "xcode-select found no developer folder", _XCODE_SELECT_FIX)
    path = selected.stdout.strip()
    if _COMMAND_LINE_TOOLS in path:
        return Check(
            "xcode",
            CheckStatus.FAIL,
            f"only the Command Line Tools are selected ({path}); the full Xcode is necessary",
            _XCODE_SELECT_FIX,
        )
    version = _run(runner, ["xcodebuild", "-version"])
    if version is None or version.returncode != 0:
        reason = _first_line(version.output) if version else "xcodebuild is not found"
        return Check(
            "xcode",
            CheckStatus.FAIL,
            f"xcodebuild -version failed: {reason}",
            "Accept the license: sudo xcodebuild -license accept. Then run: "
            "sudo xcodebuild -runFirstLaunch",
        )
    return Check("xcode", CheckStatus.OK, f"{_first_line(version.stdout)} ({path})")


def check_appium(runner: CommandRunner) -> list[Check]:
    version = _run(runner, ["appium", "--version"])
    if version is None or version.returncode != 0:
        return [
            Check("appium", CheckStatus.FAIL, "appium is not on PATH", "npm i -g appium"),
            Check(
                "xcuitest driver",
                CheckStatus.FAIL,
                "appium is not on PATH",
                "Install appium, then run: appium driver install xcuitest",
            ),
        ]
    appium = Check("appium", CheckStatus.OK, f"appium {_first_line(version.stdout)}")
    drivers = _run(runner, ["appium", "driver", "list", "--installed"])
    # Appium writes the driver list to stderr.
    if drivers is None or drivers.returncode != 0 or "xcuitest" not in drivers.output.lower():
        return [
            appium,
            Check(
                "xcuitest driver",
                CheckStatus.FAIL,
                "the xcuitest driver is not installed",
                "appium driver install xcuitest",
            ),
        ]
    return [appium, Check("xcuitest driver", CheckStatus.OK, "installed")]


def check_appium_server(appium_url: str, http_get: HttpGet) -> Check:
    url = appium_url.rstrip("/") + "/status"
    try:
        status = http_get(url)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return Check(
            "appium server",
            CheckStatus.WARN,
            f"no answer at {url}: {exc}",
            "Start the server in a different terminal: appium",
        )
    if status != 200:
        return Check(
            "appium server",
            CheckStatus.WARN,
            f"{url} gave HTTP {status}",
            "Start the server in a different terminal: appium",
        )
    return Check("appium server", CheckStatus.OK, f"answers at {url}")


def _devicectl_devices(runner: CommandRunner) -> dict[str, str] | None:
    with tempfile.TemporaryDirectory(prefix="verdict-doctor-") as folder:
        output = Path(folder) / "devices.json"
        result = _run(
            runner, ["xcrun", "devicectl", "list", "devices", "--json-output", str(output)]
        )
        if result is None or result.returncode != 0 or not output.exists():
            return None
        try:
            data: Any = json.loads(output.read_text())
        except (OSError, ValueError):
            return None
    devices: dict[str, str] = {}
    for device in data.get("result", {}).get("devices", []):
        udid = device.get("hardwareProperties", {}).get("udid")
        if not udid or device.get("connectionProperties", {}).get("tunnelState") == "unavailable":
            continue
        devices[udid] = device.get("deviceProperties", {}).get("name", "iPhone")
    return devices


def _idevice_devices(runner: CommandRunner) -> dict[str, str] | None:
    result = _run(runner, ["idevice_id", "-l"])
    if result is None or result.returncode != 0:
        return None
    return {line.strip(): "iPhone" for line in result.stdout.splitlines() if line.strip()}


def _booted_simulators(runner: CommandRunner) -> dict[str, str]:
    result = _run(runner, ["xcrun", "simctl", "list", "devices", "booted", "-j"])
    if result is None or result.returncode != 0:
        return {}
    try:
        data: Any = json.loads(result.stdout)
    except ValueError:
        return {}
    return {
        sim["udid"]: f"{sim.get('name', 'Simulator')} (Simulator)"
        for sims in data.get("devices", {}).values()
        for sim in sims
        if sim.get("udid") and sim.get("state") == "Booted"
    }


def check_device(runner: CommandRunner, device: str | None) -> Check:
    real = _devicectl_devices(runner)
    if real is None:
        real = _idevice_devices(runner) or {}
    found = {**real, **_booted_simulators(runner)}
    listed = ", ".join(f"{name} {udid}" for udid, name in found.items())
    if device is not None:
        if device in found:
            return Check("device", CheckStatus.OK, f"{found[device]} {device}")
        seen = f"; found: {listed}" if found else "; found no device"
        return Check("device", CheckStatus.FAIL, f"{device} is not connected or booted{seen}", _DEVICE_FIX)
    if not found:
        return Check(
            "device", CheckStatus.FAIL, "found no iPhone and no booted Simulator", _DEVICE_FIX
        )
    return Check("device", CheckStatus.OK, listed)


def check_ios_extra(import_module: ModuleImporter) -> Check:
    if ios_extra_installed(import_module):
        return Check("ios extra", CheckStatus.OK, "the Appium client imports")
    return Check(
        "ios extra", CheckStatus.FAIL, "the Appium client is not installed", IOS_EXTRA_INSTALL
    )


def run_ios_doctor(
    device: str | None,
    appium_url: str,
    runner: CommandRunner = subprocess_runner,
    http_get: HttpGet = urllib_get,
    import_module: ModuleImporter = importlib.import_module,
) -> list[Check]:
    """Run all iOS readiness checks and return one `Check` for each."""
    return [
        check_xcode(runner),
        *check_appium(runner),
        check_appium_server(appium_url, http_get),
        check_device(runner, device),
        check_ios_extra(import_module),
    ]


def doctor_passed(checks: Sequence[Check]) -> bool:
    """Return True if no required check failed. A WARN does not stop a run."""
    return all(check.status is not CheckStatus.FAIL for check in checks)
