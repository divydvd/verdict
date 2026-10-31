import http.client
import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from verdict.agent_interface import cli
from verdict.core.models import Platform, UiNode
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.device_state import ios_doctor
from verdict.device_state.ios_doctor import CommandResult


class _ClosingDriver(FakeDeviceDriver):
    closed: int = 0

    def close(self) -> None:
        self.closed += 1


def _ios_driver() -> _ClosingDriver:
    driver = _ClosingDriver(platform=Platform.IOS)
    driver.set_hierarchy(UiNode(resource_id="field"))
    return driver


def _scenario(tmp_path: Path, **overrides) -> Path:
    spec = {
        "name": "ios-scenario",
        "steps": [{"action": "wait_for", "selector": {"resource_id": "field"}, "timeout_ms": 10}],
    }
    spec.update(overrides)
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml.safe_dump(spec))
    return path


@pytest.fixture
def ios_calls(monkeypatch):
    calls: list[dict] = []
    driver = _ios_driver()

    def fake_ios_driver(**kwargs):
        calls.append(kwargs)
        return driver

    monkeypatch.setattr(cli, "IosAppiumDriver", fake_ios_driver)
    monkeypatch.setattr(
        cli, "AndroidUiautomator2Driver", lambda serial=None: pytest.fail("Android driver used")
    )
    return calls, driver


def test_android_is_the_default_platform(tmp_path, monkeypatch):
    serials = []

    def android(serial=None):
        serials.append(serial)
        driver = FakeDeviceDriver()
        driver.set_hierarchy(UiNode(resource_id="field"))
        return driver

    monkeypatch.setattr(cli, "AndroidUiautomator2Driver", android)
    monkeypatch.setattr(cli, "IosAppiumDriver", lambda **kw: pytest.fail("iOS driver used"))

    result = CliRunner().invoke(
        cli.main, ["run", str(_scenario(tmp_path)), "-s", "emu-1", "-o", str(tmp_path / "out")]
    )

    assert result.exit_code == 0, result.output
    assert serials == ["emu-1"]


def test_platform_ios_selects_the_ios_driver_and_closes_it(tmp_path, ios_calls):
    calls, driver = ios_calls
    app = tmp_path / "SmarType.app"
    app.mkdir()
    ipa = tmp_path / "Other.ipa"
    ipa.write_bytes(b"ipa")

    result = CliRunner().invoke(
        cli.main,
        [
            "run",
            str(_scenario(tmp_path)),
            "--platform",
            "ios",
            "--device",
            "00008110-AAAA",
            "--appium-url",
            "http://127.0.0.1:4800",
            "--app",
            f"bha.keys.smartype={app}",
            "--app",
            f"com.example.other={ipa}",
            "-o",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "PASSED" in result.output
    assert calls == [
        {
            "udid": "00008110-AAAA",
            "appium_url": "http://127.0.0.1:4800",
            "capabilities": {},
            "app_paths": {
                "bha.keys.smartype": str(app.resolve()),
                "com.example.other": str(ipa.resolve()),
            },
        }
    ]
    assert driver.closed == 1


@pytest.mark.parametrize("raw", ["no-equals", "=/apps/A.app", "bha.keys.smartype="])
def test_malformed_app_is_rejected(tmp_path, ios_calls, raw):
    result = CliRunner().invoke(
        cli.main, ["run", str(_scenario(tmp_path)), "--platform", "ios", "--app", raw]
    )
    assert result.exit_code == 2
    assert "BUNDLE_ID=PATH" in result.output
    assert ios_calls[0] == []


@pytest.mark.parametrize(
    "option",
    [
        ["--app", "a.b=/apps/A.app"],
        ["--capability", "appium:xcodeOrgId=TEAM"],
        ["--capabilities-file", "CAPS"],
    ],
)
def test_ios_only_options_are_rejected_on_android(tmp_path, monkeypatch, option):
    monkeypatch.setattr(cli, "AndroidUiautomator2Driver", lambda serial=None: pytest.fail("ran"))
    caps = tmp_path / "caps.json"
    caps.write_text("{}")
    option = [str(caps) if value == "CAPS" else value for value in option]
    result = CliRunner().invoke(cli.main, ["run", str(_scenario(tmp_path)), *option])
    assert result.exit_code == 2
    assert "apply only to --platform ios" in result.output


def test_capabilities_go_to_the_ios_driver(tmp_path, ios_calls):
    caps = tmp_path / "caps.json"
    caps.write_text(
        '{"appium:xcodeOrgId": "FILETEAM", "appium:wdaLocalPort": 8100, "appium:showXcodeLog": false}'
    )
    result = CliRunner().invoke(
        cli.main,
        [
            "run",
            str(_scenario(tmp_path)),
            "--platform",
            "ios",
            "--capabilities-file",
            str(caps),
            "--capability",
            "appium:xcodeOrgId=ABCDE12345",
            "--capability",
            "appium:xcodeSigningId=Apple Development",
            "--capability",
            "appium:showXcodeLog=true",
            "--capability",
            "appium:wdaLaunchTimeout=120000",
            "-o",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert ios_calls[0][0]["capabilities"] == {
        "appium:xcodeOrgId": "ABCDE12345",
        "appium:wdaLocalPort": 8100,
        "appium:showXcodeLog": True,
        "appium:xcodeSigningId": "Apple Development",
        "appium:wdaLaunchTimeout": 120000,
    }


def test_the_ios_driver_factory_passes_the_capabilities(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "IosAppiumDriver", lambda **kw: seen.update(kw) or _ios_driver())
    cli.ios_driver_factory("http://h:1", {}, {"appium:usePreinstalledWDA": True})("UDID")
    assert seen["capabilities"] == {"appium:usePreinstalledWDA": True}


@pytest.mark.parametrize(
    ("content", "message"),
    [("not json", "cannot read"), ("[1, 2]", "must contain a JSON object")],
)
def test_bad_capabilities_file_is_a_usage_error(tmp_path, ios_calls, content, message):
    caps = tmp_path / "caps.json"
    caps.write_text(content)
    result = CliRunner().invoke(
        cli.main,
        ["run", str(_scenario(tmp_path)), "--platform", "ios", "--capabilities-file", str(caps)],
    )
    assert result.exit_code == 2
    assert message in result.output
    assert ios_calls[0] == []


def test_malformed_capability_is_a_usage_error(tmp_path, ios_calls):
    result = CliRunner().invoke(
        cli.main, ["run", str(_scenario(tmp_path)), "--platform", "ios", "--capability", "=x"]
    )
    assert result.exit_code == 2
    assert "expected KEY=VALUE" in result.output


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("appium:showXcodeLog=true", True),
        ("appium:showXcodeLog=false", False),
        ("appium:x=null", None),
        ("appium:wdaLocalPort=8100", 8100),
        ("appium:offset=-5", -5),
        ('appium:processArguments={"args": ["-a"], "scale": 1.5}', {"args": ["-a"], "scale": 1.5}),
        ("appium:list=[1, 2]", [1, 2]),
        ("appium:timeout=17.4", "17.4"),
        ("appium:timeout=1e3", "1e3"),
        ("appium:name=plain text", "plain text"),
        ('appium:quoted="x"', '"x"'),
        ("appium:platformVersion=17.4", "17.4"),
        ("appium:platformVersion=17", "17"),
        ("platformVersion=17", "17"),
        ("appium:xcodeOrgId=5E12345678", "5E12345678"),
        ("appium:xcodeOrgId=1234567890", "1234567890"),
        ("xcodeOrgId=1234567890", "1234567890"),
        ("appium:xcodeSigningId=true", "true"),
        ("appium:udid=00008110", "00008110"),
        ("appium:bundleId=null", "null"),
        ("appium:app=123", "123"),
        ("appium:deviceName=1", "1"),
        ("appium:automationName=false", "false"),
        ("platformName=1", "1"),
        ("appium:updatedWDABundleId=123", "123"),
        ("appium:xcodeConfigFile=1", "1"),
        ("appium:webDriverAgentUrl=8100", "8100"),
        ("appium:xcodeOrgId=NaN", "NaN"),
    ],
)
def test_capability_value_parsing(raw, expected):
    key, value = cli._parse_capability(raw)
    assert key == raw.split("=", 1)[0]
    assert value == expected
    assert type(value) is type(expected)


@pytest.mark.parametrize(
    "raw",
    [
        "appium:x=NaN",
        "appium:x=Infinity",
        "appium:x=-Infinity",
        "appium:x=[1, NaN]",
        'appium:x={"a": {"b": Infinity}}',
        "appium:x=[1e999]",
        'appium:x={"a": [-1e999]}',
    ],
)
def test_non_finite_capability_is_a_usage_error(tmp_path, ios_calls, raw):
    result = CliRunner().invoke(
        cli.main, ["run", str(_scenario(tmp_path)), "--platform", "ios", "--capability", raw]
    )
    assert result.exit_code == 2, result.output
    assert "--capability" in result.output
    assert ios_calls[0] == []


def test_ios_connection_error_in_a_step_is_blocked_and_closes_the_session(tmp_path, monkeypatch):
    class _Dropping(_ClosingDriver):
        def wait_for(self, selector, timeout_ms=5000):
            raise http.client.RemoteDisconnected("WebDriverAgent stopped")

    driver = _Dropping(platform=Platform.IOS)
    monkeypatch.setattr(cli, "IosAppiumDriver", lambda **kw: driver)

    result = CliRunner().invoke(
        cli.main,
        ["run", str(_scenario(tmp_path)), "--platform", "ios", "-o", str(tmp_path / "out")],
    )

    assert result.exit_code == 2, result.output
    assert "BLOCKED: the device connection failed: RemoteDisconnected" in result.output
    assert driver.closed == 1


def test_ios_session_that_does_not_open_is_blocked(tmp_path, monkeypatch):
    def no_server(**kwargs):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(cli, "IosAppiumDriver", no_server)

    result = CliRunner().invoke(cli.main, ["run", str(_scenario(tmp_path)), "--platform", "ios"])

    assert result.exit_code == 2
    assert "BLOCKED: the device connection failed: ConnectionRefusedError" in result.output


def test_unexpected_error_still_closes_the_ios_session(tmp_path, monkeypatch):
    class _Broken(_ClosingDriver):
        def wait_for(self, selector, timeout_ms=5000):
            raise KeyboardInterrupt

    driver = _Broken(platform=Platform.IOS)
    monkeypatch.setattr(cli, "IosAppiumDriver", lambda **kw: driver)

    with pytest.raises(KeyboardInterrupt):
        cli.execute_run(
            _scenario(tmp_path),
            {},
            tmp_path / "out",
            ("json",),
            None,
            cli.ios_driver_factory("http://127.0.0.1:4723", {}),
            Platform.IOS,
        )
    assert driver.closed == 1


def test_missing_ios_extra_is_blocked_with_the_install_command(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ios_extra_installed", lambda: False)
    monkeypatch.setattr(cli, "IosAppiumDriver", lambda **kw: pytest.fail("driver opened"))

    result = CliRunner().invoke(cli.main, ["run", str(_scenario(tmp_path)), "--platform", "ios"])

    assert result.exit_code == 2
    assert "BLOCKED: the `ios` extra is not installed" in result.output
    assert "pip install -e '.[ios]'" in result.output


def test_unsupported_platform_is_skipped_with_exit_3(tmp_path, ios_calls):
    scenario = _scenario(tmp_path, platforms=["android"])

    result = CliRunner().invoke(
        cli.main, ["run", str(scenario), "--platform", "ios", "-o", str(tmp_path / "out")]
    )

    assert result.exit_code == 3, result.output
    assert "ios-scenario: SKIPPED (0 attempt(s))" in result.output
    assert ios_calls[0] == []
    assert "SKIPPED: the scenario supports only android; the device platform is ios" in result.output
    assert (tmp_path / "out" / "report.json").exists()


def test_skip_does_not_make_the_driver(tmp_path):
    def factory(udid):
        raise AssertionError("the driver factory was called")

    result = cli.execute_run(
        _scenario(tmp_path, platforms=["android"]),
        {},
        tmp_path / "out",
        ("json",),
        "00008110-AAAA",
        factory,
        Platform.IOS,
    )

    assert result.skipped is True
    assert result.status == "SKIPPED"


def test_baseline_and_restore_have_no_platform_option(tmp_path):
    for command in (["baseline", "a.b"], ["restore", "a.b"]):
        result = CliRunner().invoke(
            cli.main, [*command, "--dir", str(tmp_path), "--platform", "ios"]
        )
        assert result.exit_code == 2
        assert "No such option" in result.output and "--platform" in result.output


# -- verdict doctor ios --------------------------------------------------------

# A sample `devicectl list devices` entry. It is not real devicectl output (no Xcode here).
_IPHONE = {
    "hardwareProperties": {"udid": "00008110-AAAA"},
    "deviceProperties": {"name": "Divy iPhone", "developerModeStatus": "enabled"},
    "connectionProperties": {
        "pairingState": "paired",
        "tunnelState": "connected",
        "transportType": "wired",
    },
}


def _devicectl_json(*devices):
    return {"result": {"devices": list(devices)}}


def _devicectl_runner(*devices):
    def runner(command):
        if command[:2] == ["xcrun", "devicectl"]:
            Path(command[-1]).write_text(json.dumps(_devicectl_json(*devices)))
            return CommandResult(0)
        if command[:2] == ["xcrun", "simctl"]:
            return CommandResult(0, '{"devices": {}}')
        return _ready_runner([])(command)

    return runner


def _ready_runner(calls: list[list[str]]):
    def runner(command):
        calls.append(list(command))
        match command[:2]:
            case ["xcode-select", "-p"]:
                return CommandResult(0, "/Applications/Xcode.app/Contents/Developer\n")
            case ["xcodebuild", "-version"]:
                return CommandResult(0, "Xcode 16.1\nBuild version 16B40\n")
            case ["appium", "--version"]:
                return CommandResult(0, "2.12.1\n")
            case ["appium", "driver"]:
                return CommandResult(0, "", "- xcuitest@7.28.0 [installed (npm)]\n")
            case ["ffmpeg", "-version"]:
                return CommandResult(0, "ffmpeg version 7.1 Copyright (c) 2000-2024\n")
            case ["xcrun", "devicectl"]:
                Path(command[-1]).write_text(json.dumps(_devicectl_json(_IPHONE)))
                return CommandResult(0)
            case ["xcrun", "simctl"]:
                return CommandResult(
                    0,
                    '{"devices": {"iOS-18-1": [{"udid": "SIM-1", "name": "iPhone 16",'
                    ' "state": "Booted"}]}}',
                )
        raise AssertionError(f"unexpected command {command}")

    return runner


def _invoke_doctor(monkeypatch, runner, http_get=lambda url: 200, importer=lambda name: None, args=()):
    def doctor(device, appium_url, capabilities):
        return ios_doctor.run_ios_doctor(
            device, appium_url, capabilities, runner, http_get, importer
        )

    monkeypatch.setattr(cli, "run_ios_doctor", doctor)
    return CliRunner().invoke(cli.main, ["doctor", "ios", *args])


def test_doctor_passes_when_all_checks_pass(monkeypatch):
    calls: list[list[str]] = []
    result = _invoke_doctor(
        monkeypatch,
        _ready_runner(calls),
        args=["--device", "00008110-AAAA", "--capability", "appium:xcodeOrgId=ABCDE12345"],
    )

    assert result.exit_code == 0, result.output
    assert "OK   xcode: Xcode 16.1 (/Applications/Xcode.app/Contents/Developer)" in result.output
    assert "OK   appium: appium 2.12.1" in result.output
    assert "OK   xcuitest driver: installed" in result.output
    assert "OK   appium server: answers at http://127.0.0.1:4723/status" in result.output
    assert "OK   device: Divy iPhone 00008110-AAAA" in result.output
    assert "OK   ffmpeg: ffmpeg version 7.1" in result.output
    assert "OK   developer mode: enabled on Divy iPhone 00008110-AAAA" in result.output
    assert "OK   wda signing: given: appium:xcodeOrgId" in result.output
    assert "INFO ui automation: Verdict cannot read this setting" in result.output
    assert "fix: On the iPhone, turn on Settings > Developer > Enable UI Automation" in result.output
    assert "OK   ios extra" in result.output
    assert "WARN" not in result.output and "FAIL" not in result.output
    assert "iOS is ready." in result.output
    assert ["idevice_id", "-l"] not in calls


def _with(base, overrides):
    def runner(command):
        for prefix, outcome in overrides.items():
            if tuple(command[: len(prefix)]) == prefix:
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome
        return base(command)

    return runner


@pytest.mark.parametrize(
    ("overrides", "expected", "fix"),
    [
        (
            {("xcode-select",): CommandResult(0, "/Library/Developer/CommandLineTools\n")},
            "FAIL xcode: only the Command Line Tools are selected",
            "sudo xcode-select -s /Applications/Xcode.app/Contents/Developer",
        ),
        (
            {("xcode-select",): FileNotFoundError("xcode-select")},
            "FAIL xcode: xcode-select is missing",
            "Install Xcode from the App Store",
        ),
        (
            {("xcodebuild",): CommandResult(69, "", "You have not agreed to the Xcode license.")},
            "FAIL xcode: `xcodebuild -version` failed with exit code 69: You have not agreed",
            "sudo xcodebuild -license accept",
        ),
        (
            {("appium",): FileNotFoundError("appium")},
            "FAIL appium: appium is missing from PATH",
            "npm i -g appium",
        ),
        (
            {("appium", "driver"): CommandResult(0, "", "- uiautomator2@3.0.0 [installed]\n")},
            "FAIL xcuitest driver: the xcuitest driver is not installed",
            "appium driver install xcuitest",
        ),
    ],
)
def test_doctor_reports_each_failed_tool_check(monkeypatch, overrides, expected, fix):
    result = _invoke_doctor(monkeypatch, _with(_ready_runner([]), overrides))

    assert result.exit_code == 2, result.output
    assert expected in result.output
    assert "fix:" in result.output
    assert fix in result.output
    assert "iOS is not ready" in result.output


def test_doctor_warns_but_passes_when_the_appium_server_does_not_answer(monkeypatch):
    def refused(url):
        raise ConnectionRefusedError("connection refused")

    result = _invoke_doctor(monkeypatch, _ready_runner([]), http_get=refused)

    assert result.exit_code == 0, result.output
    assert "WARN appium server: no answer at http://127.0.0.1:4723/status" in result.output
    assert "fix: Start the server in a different terminal: appium" in result.output


def test_doctor_uses_the_given_appium_url(monkeypatch):
    urls = []
    result = _invoke_doctor(
        monkeypatch,
        _ready_runner([]),
        http_get=lambda url: urls.append(url) or 200,
        args=["--appium-url", "http://10.0.0.2:4800/"],
    )
    assert result.exit_code == 0
    assert urls == ["http://10.0.0.2:4800/status"]


def test_doctor_fails_when_the_given_device_is_not_found(monkeypatch):
    result = _invoke_doctor(monkeypatch, _ready_runner([]), args=["--device", "OTHER"])

    assert result.exit_code == 2
    assert "FAIL device: OTHER is not connected or booted; found: Divy iPhone 00008110-AAAA" in (
        result.output
    )
    assert "xcrun simctl boot <UDID>" in result.output


def test_doctor_finds_a_booted_simulator(monkeypatch):
    result = _invoke_doctor(monkeypatch, _ready_runner([]), args=["--device", "SIM-1"])
    assert result.exit_code == 0
    assert "OK   device: iPhone 16 (Simulator) SIM-1" in result.output


def test_doctor_uses_idevice_id_when_devicectl_fails(monkeypatch):
    calls: list[list[str]] = []
    runner = _with(
        _ready_runner(calls),
        {
            ("xcrun", "devicectl"): CommandResult(72, "", "unable to find utility devicectl"),
            ("xcrun", "simctl"): CommandResult(72, "", "unable to find utility simctl"),
            ("idevice_id",): CommandResult(0, "00008110-BBBB\n"),
        },
    )
    result = _invoke_doctor(monkeypatch, runner, args=["-s", "00008110-BBBB"])

    assert result.exit_code == 0, result.output
    assert "OK   device: iPhone 00008110-BBBB" in result.output


def test_doctor_fails_when_no_device_is_found(monkeypatch):
    runner = _with(
        _ready_runner([]),
        {
            ("xcrun",): FileNotFoundError("xcrun"),
            ("idevice_id",): FileNotFoundError("idevice_id"),
        },
    )
    result = _invoke_doctor(monkeypatch, runner)

    assert result.exit_code == 2
    assert "FAIL device: found no iPhone and no booted Simulator" in result.output


def test_doctor_skips_devices_that_are_not_connected(monkeypatch):
    def runner(command):
        if command[:2] == ["xcrun", "devicectl"]:
            old = {**_IPHONE, "connectionProperties": {"tunnelState": "unavailable"}}
            Path(command[-1]).write_text(json.dumps(_devicectl_json(old)))
            return CommandResult(0)
        if command[:2] == ["xcrun", "simctl"]:
            return CommandResult(0, '{"devices": {}}')
        return _ready_runner([])(command)

    result = _invoke_doctor(monkeypatch, runner)
    assert result.exit_code == 2
    assert "FAIL device: found no iPhone" in result.output


def test_doctor_fails_when_the_ios_extra_does_not_import(monkeypatch):
    def importer(name):
        raise ModuleNotFoundError(name)

    result = _invoke_doctor(monkeypatch, _ready_runner([]), importer=importer)

    assert result.exit_code == 2
    assert "FAIL ios extra: the Appium client is not installed" in result.output
    assert "fix: pip install -e '.[ios]'" in result.output


def test_doctor_on_a_mac_with_only_the_command_line_tools(monkeypatch):
    # The state of a Mac without Xcode, Appium, or a device.
    def runner(command):
        if command[0] == "xcode-select":
            return CommandResult(0, "/Library/Developer/CommandLineTools\n")
        if command[0] == "xcrun":
            return CommandResult(72, "", f"xcrun: error: unable to find utility \"{command[1]}\"")
        raise FileNotFoundError(command[0])

    def refused(url):
        raise ConnectionRefusedError("connection refused")

    result = _invoke_doctor(monkeypatch, runner, http_get=refused)

    assert result.exit_code == 2
    lines = [line.split(":")[0] for line in result.output.splitlines() if not line.startswith(" ")]
    assert lines == [
        "FAIL xcode",
        "FAIL appium",
        "FAIL xcuitest driver",
        "WARN appium server",
        "WARN ffmpeg",
        "FAIL device",
        "WARN developer mode",
        "WARN wda signing",
        "INFO ui automation",
        "OK   ios extra",
        "iOS is not ready",
    ]


@pytest.mark.parametrize(
    ("connection", "connected"),
    [
        ({"pairingState": "paired", "tunnelState": "connected", "transportType": "wired"}, True),
        ({"tunnelState": "connected"}, True),
        ({"pairingState": "paired", "transportType": "localNetwork"}, True),
        ({"pairingState": "paired", "tunnelState": "disconnected"}, False),
        ({"pairingState": "paired", "tunnelState": "unavailable"}, False),
        ({"pairingState": "paired"}, False),
        (
            {"pairingState": "paired", "tunnelState": "disconnected", "transportType": "wired"},
            False,
        ),
        ({"pairingState": "unpaired", "transportType": "wired"}, False),
        ({}, False),
    ],
)
def test_devicectl_device_connected(connection, connected):
    device = {**_IPHONE, "connectionProperties": connection}
    assert ios_doctor.devicectl_device_connected(device) is connected


def test_doctor_does_not_accept_a_paired_iphone_that_is_not_connected(monkeypatch):
    paired = {**_IPHONE, "connectionProperties": {"pairingState": "paired", "tunnelState": "disconnected"}}
    result = _invoke_doctor(monkeypatch, _devicectl_runner(paired), args=["-s", "00008110-AAAA"])
    assert result.exit_code == 2
    assert "FAIL device: 00008110-AAAA is not connected or booted; found no device" in result.output


def test_doctor_fails_when_developer_mode_is_disabled(monkeypatch):
    disabled = {**_IPHONE, "deviceProperties": {"name": "Divy iPhone", "developerModeStatus": "disabled"}}
    result = _invoke_doctor(monkeypatch, _devicectl_runner(disabled))
    assert result.exit_code == 2
    assert "FAIL developer mode: disabled on Divy iPhone 00008110-AAAA" in result.output
    assert "Settings > Privacy & Security > Developer Mode" in result.output


def test_doctor_warns_when_devicectl_does_not_report_developer_mode(monkeypatch):
    unknown = {**_IPHONE, "deviceProperties": {"name": "Divy iPhone"}}
    result = _invoke_doctor(
        monkeypatch,
        _devicectl_runner(unknown),
        args=["--capability", "appium:usePreinstalledWDA=true"],
    )
    assert result.exit_code == 0, result.output
    assert "WARN developer mode: devicectl did not report it for Divy iPhone" in result.output


def test_doctor_warns_when_no_wda_signing_capability_is_given(monkeypatch):
    result = _invoke_doctor(monkeypatch, _devicectl_runner(_IPHONE))
    assert result.exit_code == 0, result.output
    assert "WARN wda signing: no appium:xcodeOrgId" in result.output
    assert "--capability appium:xcodeOrgId=TEAMID" in result.output


@pytest.mark.parametrize(
    "content",
    [
        '{"usePreinstalledWDA": true}',
        '{"appium:xcodeConfigFile": "/signing/wda.xcconfig"}',
        '{"xcodeConfigFile": "/signing/wda.xcconfig"}',
    ],
)
def test_doctor_reads_wda_signing_from_the_capabilities_file(monkeypatch, tmp_path, content):
    caps = tmp_path / "caps.json"
    caps.write_text(content)
    result = _invoke_doctor(
        monkeypatch, _devicectl_runner(_IPHONE), args=["--capabilities-file", str(caps)]
    )
    assert result.exit_code == 0, result.output
    assert "OK   wda signing: given:" in result.output


def test_doctor_needs_no_signing_or_developer_mode_for_a_simulator(monkeypatch):
    result = _invoke_doctor(monkeypatch, _ready_runner([]), args=["-s", "SIM-1"])
    assert result.exit_code == 0, result.output
    assert "OK   developer mode: not necessary for a Simulator" in result.output
    assert "OK   wda signing: not necessary for a Simulator" in result.output


def test_doctor_warns_but_passes_when_ffmpeg_is_missing(monkeypatch):
    runner = _with(_ready_runner([]), {("ffmpeg",): FileNotFoundError("ffmpeg")})
    result = _invoke_doctor(
        monkeypatch, runner, args=["--capability", "appium:xcodeOrgId=ABCDE12345"]
    )
    assert result.exit_code == 0, result.output
    assert "WARN ffmpeg: ffmpeg is missing from PATH" in result.output
    assert "fix: brew install ffmpeg" in result.output


_TIMEOUT = CommandResult(124, "", "timeout after 60 s")


@pytest.mark.parametrize(
    ("overrides", "expected", "absent"),
    [
        (
            {("appium", "--version"): CommandResult(1, "", "Error: Cannot find module 'node:fs'\n")},
            "FAIL appium: `appium --version` failed with exit code 1: Error: Cannot find module",
            "missing",
        ),
        (
            {("appium", "--version"): _TIMEOUT},
            "FAIL appium: `appium --version` failed with exit code 124: timeout after 60 s",
            "missing",
        ),
        (
            {("appium", "driver"): CommandResult(1, "", "Error: EACCES: permission denied\n")},
            (
                "FAIL xcuitest driver: `appium driver list --installed` failed with exit code 1: "
                "Error: EACCES: permission denied"
            ),
            "not installed",
        ),
        (
            {("appium", "driver"): FileNotFoundError("appium")},
            "FAIL xcuitest driver: appium is missing from PATH",
            "not installed",
        ),
        (
            {("xcode-select",): CommandResult(2, "", "xcode-select: error: unable to get active developer directory\n")},
            "FAIL xcode: `xcode-select -p` failed with exit code 2: xcode-select: error: unable",
            "missing",
        ),
        (
            {("xcodebuild",): FileNotFoundError("xcodebuild")},
            "FAIL xcode: xcodebuild is missing",
            "failed",
        ),
    ],
)
def test_doctor_tells_a_failed_tool_from_a_missing_tool(monkeypatch, overrides, expected, absent):
    result = _invoke_doctor(monkeypatch, _with(_ready_runner([]), overrides))

    assert result.exit_code == 2, result.output
    assert expected in result.output
    line = next(line for line in result.output.splitlines() if line.startswith(expected[:10]))
    assert absent not in line


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (CommandResult(1, "", "dyld: Library not loaded: libavcodec.61.dylib\n"),
         "WARN ffmpeg: `ffmpeg -version` failed with exit code 1: dyld: Library not loaded"),
        (_TIMEOUT, "WARN ffmpeg: `ffmpeg -version` failed with exit code 124: timeout after 60 s"),
        (CommandResult(3, "only stdout\n", ""),
         "WARN ffmpeg: `ffmpeg -version` failed with exit code 3: only stdout"),
    ],
)
def test_doctor_reports_a_failed_ffmpeg_with_its_error(monkeypatch, outcome, expected):
    runner = _with(_ready_runner([]), {("ffmpeg",): outcome})
    result = _invoke_doctor(
        monkeypatch, runner, args=["--capability", "appium:xcodeOrgId=ABCDE12345"]
    )
    assert result.exit_code == 0, result.output
    assert expected in result.output
    assert "fix: Repair the ffmpeg install" in result.output


@pytest.mark.parametrize(
    ("name", "kind", "message"),
    [
        ("Missing.app", None, "does not exist"),
        ("SmarType.ipa", "folder", "must be an .app folder or an .ipa file"),
        ("SmarType.app", "file", "must be an .app folder or an .ipa file"),
        ("SmarType.zip", "file", "must be an .app folder or an .ipa file"),
    ],
)
def test_bad_app_path_is_a_usage_error_before_the_driver_is_made(
    tmp_path, ios_calls, name, kind, message
):
    app = tmp_path / name
    if kind == "folder":
        app.mkdir()
    elif kind == "file":
        app.write_text("x")
    result = CliRunner().invoke(
        cli.main,
        ["run", str(_scenario(tmp_path)), "--platform", "ios", "--app", f"bha.keys.smartype={app}"],
    )
    assert result.exit_code == 2, result.output
    assert message in result.output
    assert ios_calls[0] == []


def test_doctor_warns_when_only_updated_wda_bundle_id_is_given(monkeypatch):
    result = _invoke_doctor(
        monkeypatch,
        _devicectl_runner(_IPHONE),
        args=["--capability", "appium:updatedWDABundleId=com.divy.wda"],
    )
    assert result.exit_code == 0, result.output
    assert "WARN wda signing: only appium:updatedWDABundleId is given; it does not sign WDA" in (
        result.output
    )
    assert "provisioning profile" in result.output
    assert "--capability appium:xcodeOrgId=TEAMID" in result.output


def test_doctor_accepts_updated_wda_bundle_id_with_a_team_id(monkeypatch):
    result = _invoke_doctor(
        monkeypatch,
        _devicectl_runner(_IPHONE),
        args=[
            "--capability",
            "appium:updatedWDABundleId=com.divy.wda",
            "--capability",
            "appium:xcodeOrgId=ABCDE12345",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "OK   wda signing: given: appium:xcodeOrgId" in result.output
