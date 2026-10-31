"""Readiness checks for iOS device tests (`verdict doctor ios`). See ADR-0009.

Each check starts host tools through an injectable `CommandRunner`, so the
tests need no Xcode, Appium, or device. The external commands are:
`xcode-select`, `xcodebuild`, `appium`, `ffmpeg`, `xcrun devicectl`,
`xcrun simctl`, and `idevice_id`. The Appium check also sends one HTTP GET to `/status`.
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
_DEVELOPER_MODE_FIX = (
    "On the iPhone, turn on Settings > Privacy & Security > Developer Mode, then restart it"
)
_WDA_SIGNING_KEYS = ("xcodeOrgId", "xcodeConfigFile", "usePreinstalledWDA")
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
    INFO = "INFO"
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


def _failed(command: Sequence[str], result: CommandResult) -> str:
    # The command started, so it is not missing. Show why it failed.
    reason = _first_line(result.stderr) or _first_line(result.stdout) or "no output"
    return f"`{' '.join(command)}` failed with exit code {result.returncode}: {reason}"


def check_xcode(runner: CommandRunner) -> Check:
    selected = _run(runner, ["xcode-select", "-p"])
    if selected is None:
        return Check("xcode", CheckStatus.FAIL, "xcode-select is missing", _XCODE_SELECT_FIX)
    if selected.returncode != 0:
        return Check(
            "xcode", CheckStatus.FAIL, _failed(["xcode-select", "-p"], selected), _XCODE_SELECT_FIX
        )
    path = selected.stdout.strip()
    if _COMMAND_LINE_TOOLS in path:
        return Check(
            "xcode",
            CheckStatus.FAIL,
            f"only the Command Line Tools are selected ({path}); the full Xcode is necessary",
            _XCODE_SELECT_FIX,
        )
    version = _run(runner, ["xcodebuild", "-version"])
    if version is None:
        return Check("xcode", CheckStatus.FAIL, "xcodebuild is missing", _XCODE_SELECT_FIX)
    if version.returncode != 0:
        return Check(
            "xcode",
            CheckStatus.FAIL,
            _failed(["xcodebuild", "-version"], version),
            "Accept the license: sudo xcodebuild -license accept. Then run: "
            "sudo xcodebuild -runFirstLaunch",
        )
    return Check("xcode", CheckStatus.OK, f"{_first_line(version.stdout)} ({path})")


def check_appium(runner: CommandRunner) -> list[Check]:
    version = _run(runner, ["appium", "--version"])
    if version is None or version.returncode != 0:
        detail = (
            "appium is missing from PATH"
            if version is None
            else _failed(["appium", "--version"], version)
        )
        fix = "npm i -g appium" if version is None else "Repair the appium install: npm i -g appium"
        return [
            Check("appium", CheckStatus.FAIL, detail, fix),
            Check(
                "xcuitest driver",
                CheckStatus.FAIL,
                "cannot check without a working appium",
                "Install appium, then run: appium driver install xcuitest",
            ),
        ]
    appium = Check("appium", CheckStatus.OK, f"appium {_first_line(version.stdout)}")
    list_command = ["appium", "driver", "list", "--installed"]
    drivers = _run(runner, list_command)
    if drivers is None or drivers.returncode != 0:
        detail = "appium is missing from PATH" if drivers is None else _failed(list_command, drivers)
        return [
            appium,
            Check(
                "xcuitest driver",
                CheckStatus.FAIL,
                detail,
                "Run `appium driver list --installed` and repair the error",
            ),
        ]
    # Appium writes the driver list to stderr.
    if "xcuitest" not in drivers.output.lower():
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


@dataclass(frozen=True)
class IosDevice:
    udid: str
    name: str
    simulator: bool = False
    developer_mode: str | None = None
    """`enabled` or `disabled` from devicectl. None when devicectl does not report it."""


def devicectl_device_connected(device: dict[str, Any]) -> bool:
    """Return True if a `devicectl list devices` entry is connected now.

    The field names and values come from Apple and Appium documentation. They
    are not checked against real devicectl output, because this Mac has no
    Xcode. A paired device that is not connected must not count.
    """
    connection = device.get("connectionProperties", {})
    tunnel = connection.get("tunnelState")
    if tunnel == "connected":
        return True
    return (
        connection.get("pairingState") == "paired"
        and bool(connection.get("transportType"))
        and tunnel not in ("disconnected", "unavailable")
    )


def _devicectl_devices(runner: CommandRunner) -> list[IosDevice] | None:
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
    devices: list[IosDevice] = []
    for device in data.get("result", {}).get("devices", []):
        udid = device.get("hardwareProperties", {}).get("udid")
        if not udid or not devicectl_device_connected(device):
            continue
        properties = device.get("deviceProperties", {})
        devices.append(
            IosDevice(
                udid=udid,
                name=properties.get("name", "iPhone"),
                developer_mode=properties.get("developerModeStatus"),
            )
        )
    return devices


def _idevice_devices(runner: CommandRunner) -> list[IosDevice] | None:
    result = _run(runner, ["idevice_id", "-l"])
    if result is None or result.returncode != 0:
        return None
    return [IosDevice(line.strip(), "iPhone") for line in result.stdout.splitlines() if line.strip()]


def _booted_simulators(runner: CommandRunner) -> list[IosDevice]:
    result = _run(runner, ["xcrun", "simctl", "list", "devices", "booted", "-j"])
    if result is None or result.returncode != 0:
        return []
    try:
        data: Any = json.loads(result.stdout)
    except ValueError:
        return []
    return [
        IosDevice(sim["udid"], f"{sim.get('name', 'Simulator')} (Simulator)", simulator=True)
        for sims in data.get("devices", {}).values()
        for sim in sims
        if sim.get("udid") and sim.get("state") == "Booted"
    ]


def find_devices(runner: CommandRunner) -> list[IosDevice]:
    """Return the connected iPhones and the booted Simulators."""
    real = _devicectl_devices(runner)
    if real is None:
        real = _idevice_devices(runner) or []
    return [*real, *_booted_simulators(runner)]


def check_device(devices: Sequence[IosDevice], device: str | None) -> Check:
    listed = ", ".join(f"{found.name} {found.udid}" for found in devices)
    if device is not None:
        match = next((found for found in devices if found.udid == device), None)
        if match is not None:
            return Check("device", CheckStatus.OK, f"{match.name} {device}")
        seen = f"; found: {listed}" if devices else "; found no device"
        return Check("device", CheckStatus.FAIL, f"{device} is not connected or booted{seen}", _DEVICE_FIX)
    if not devices:
        return Check(
            "device", CheckStatus.FAIL, "found no iPhone and no booted Simulator", _DEVICE_FIX
        )
    return Check("device", CheckStatus.OK, listed)


def _targets(devices: Sequence[IosDevice], device: str | None) -> list[IosDevice]:
    return [found for found in devices if device is None or found.udid == device]


def _no_real_device(name: str, targets: Sequence[IosDevice]) -> Check:
    if targets:
        return Check(name, CheckStatus.OK, "not necessary for a Simulator")
    return Check(name, CheckStatus.WARN, "found no iPhone to check", _DEVICE_FIX)


def check_developer_mode(devices: Sequence[IosDevice], device: str | None) -> list[Check]:
    targets = _targets(devices, device)
    real = [found for found in targets if not found.simulator]
    if not real:
        return [_no_real_device("developer mode", targets)]
    checks = []
    for found in real:
        label = f"{found.name} {found.udid}"
        if found.developer_mode == "enabled":
            checks.append(Check("developer mode", CheckStatus.OK, f"enabled on {label}"))
        elif found.developer_mode == "disabled":
            checks.append(
                Check(
                    "developer mode",
                    CheckStatus.FAIL,
                    f"disabled on {label}",
                    _DEVELOPER_MODE_FIX,
                )
            )
        else:
            checks.append(
                Check(
                    "developer mode",
                    CheckStatus.WARN,
                    f"devicectl did not report it for {label}",
                    _DEVELOPER_MODE_FIX,
                )
            )
    return checks


def _effective(capabilities: dict[str, Any], key: str) -> Any:
    """Return the last value in insertion order for `key` or `appium:key`."""
    value = None
    for name, item in capabilities.items():
        if name in (key, f"appium:{key}"):
            value = item
    return value


def _given(capabilities: dict[str, Any], key: str) -> bool:
    return _effective(capabilities, key) not in (None, "", False)


def check_wda_signing(
    devices: Sequence[IosDevice], device: str | None, capabilities: dict[str, Any]
) -> Check:
    targets = _targets(devices, device)
    if all(found.simulator for found in targets):
        return _no_real_device("wda signing", targets)
    given = [key for key in _WDA_SIGNING_KEYS if _given(capabilities, key)]
    if given:
        return Check("wda signing", CheckStatus.OK, f"given: appium:{', appium:'.join(given)}")
    if _given(capabilities, "updatedWDABundleId"):
        # A new bundle id only renames WDA. It does not give a team or an identity.
        return Check(
            "wda signing",
            CheckStatus.WARN,
            "only appium:updatedWDABundleId is given; it does not sign WDA. It needs a "
            "provisioning profile for that bundle id, or a team id",
            "Also give your Apple team id: --capability appium:xcodeOrgId=TEAMID, "
            "or give appium:xcodeConfigFile",
        )
    return Check(
        "wda signing",
        CheckStatus.WARN,
        "no appium:xcodeOrgId, appium:xcodeConfigFile, or appium:usePreinstalledWDA is given",
        "Give your Apple team id: --capability appium:xcodeOrgId=TEAMID "
        '--capability "appium:xcodeSigningId=Apple Development"',
    )


def check_ffmpeg(runner: CommandRunner) -> Check:
    result = _run(runner, ["ffmpeg", "-version"])
    if result is None:
        return Check(
            "ffmpeg",
            CheckStatus.WARN,
            "ffmpeg is missing from PATH; screen recording on a real iPhone needs it",
            "brew install ffmpeg",
        )
    if result.returncode != 0:
        return Check(
            "ffmpeg",
            CheckStatus.WARN,
            _failed(["ffmpeg", "-version"], result),
            "Repair the ffmpeg install: brew reinstall ffmpeg",
        )
    return Check("ffmpeg", CheckStatus.OK, _first_line(result.stdout))


def check_ui_automation() -> Check:
    return Check(
        "ui automation",
        CheckStatus.INFO,
        "Verdict cannot read this setting",
        "On the iPhone, turn on Settings > Developer > Enable UI Automation",
    )


def check_ios_extra(import_module: ModuleImporter) -> Check:
    if ios_extra_installed(import_module):
        return Check("ios extra", CheckStatus.OK, "the Appium client imports")
    return Check(
        "ios extra", CheckStatus.FAIL, "the Appium client is not installed", IOS_EXTRA_INSTALL
    )


def run_ios_doctor(
    device: str | None,
    appium_url: str,
    capabilities: dict[str, Any] | None = None,
    runner: CommandRunner = subprocess_runner,
    http_get: HttpGet = urllib_get,
    import_module: ModuleImporter = importlib.import_module,
) -> list[Check]:
    """Run all iOS readiness checks and return one `Check` for each."""
    devices = find_devices(runner)
    return [
        check_xcode(runner),
        *check_appium(runner),
        check_appium_server(appium_url, http_get),
        check_ffmpeg(runner),
        check_device(devices, device),
        *check_developer_mode(devices, device),
        check_wda_signing(devices, device, capabilities or {}),
        check_ui_automation(),
        check_ios_extra(import_module),
    ]


def doctor_passed(checks: Sequence[Check]) -> bool:
    """Return True if no required check failed. A WARN or an INFO does not stop a run."""
    return all(check.status is not CheckStatus.FAIL for check in checks)
