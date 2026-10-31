import os
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
import uiautomator2

_ROOT_CONFTEST = Path(__file__).parent / "conftest.py"


def _active_guard():
    # The conftest module that pytest loaded; its patches and error class are live.
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path and Path(path).resolve() == _ROOT_CONFTEST.resolve():
            return module
    raise LookupError("tests/conftest.py is not loaded")


guard = _active_guard()
RealDeviceAccessError = guard.RealDeviceAccessError


@pytest.mark.parametrize(
    "args",
    [["adb", "devices"], ["/usr/local/bin/adb", "shell", "input", "keyevent", "3"], "adb devices"],
)
def test_subprocess_run_cannot_start_adb(args):
    with pytest.raises(AssertionError, match="adb|uiautomator2"):
        subprocess.run(args, capture_output=True, check=False)


def test_subprocess_popen_cannot_start_adb():
    with pytest.raises(AssertionError, match="adb|uiautomator2"):
        subprocess.Popen(["adb", "devices"])


def test_uiautomator2_connect_is_blocked():
    with pytest.raises(AssertionError, match="adb|uiautomator2"):
        uiautomator2.connect()


def test_other_commands_still_run():
    result = subprocess.run(["true"], check=False)
    assert result.returncode == 0


def test_device_tests_are_skipped_without_opt_in(pytester):
    pytester.makeconftest(_ROOT_CONFTEST.read_text())
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.requires_device
        def test_on_phone():
            raise AssertionError("must not run")
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(skipped=1)


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    """Put a fake ``adb`` first on PATH. It writes a marker file if it ever starts."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    marker = tmp_path / "adb-started"
    script = bin_dir / "adb"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/bin{os.pathsep}/usr/bin")
    return marker


@pytest.mark.parametrize(
    "call",
    [
        lambda: subprocess.run(["sh", "-c", "adb devices"], check=False),
        lambda: subprocess.run("/usr/bin/env adb devices", shell=True, check=False),
        lambda: subprocess.run("true; adb devices", shell=True, check=False),
        lambda: os.system("adb devices"),
        lambda: os.popen("adb devices").read(),
    ],
    ids=["sh-c", "shell-env", "shell-separator", "os-system", "os-popen"],
)
def test_adb_inside_a_shell_command_is_blocked(fake_adb, call):
    with pytest.raises(RealDeviceAccessError):
        call()
    assert not fake_adb.exists()


def test_os_spawn_functions_are_blocked(fake_adb):
    # os.exec* use the same wrapper. A failed check there would replace this process.
    with pytest.raises(RealDeviceAccessError):
        os.spawnvp(os.P_WAIT, "adb", ["adb", "devices"])
    with pytest.raises(RealDeviceAccessError):
        os.posix_spawnp("adb", ["adb", "devices"], dict(os.environ))
    assert not fake_adb.exists()


def test_non_adb_shell_command_still_runs(fake_adb):
    assert subprocess.run("true", shell=True, check=False).returncode == 0
    assert subprocess.run(["sh", "-c", "true"], check=False).returncode == 0
    assert os.system("true") == 0


def _run_inner_suite(pytester, test_source):
    pytester.makeconftest(_ROOT_CONFTEST.read_text())
    pytester.makepyfile(test_source)
    # A separate process: the guard of this outer run must not hide a gap in the inner run.
    return pytester.runpytest_subprocess("-p", "no:cacheprovider")


def test_adb_at_module_import_is_blocked(pytester, fake_adb):
    result = _run_inner_suite(
        pytester,
        """
        import subprocess

        subprocess.run(["adb", "devices"], check=False)

        def test_placeholder():
            pass
        """,
    )
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*RealDeviceAccessError*"])
    assert not fake_adb.exists()


def test_adb_in_session_scoped_fixture_is_blocked(pytester, fake_adb):
    result = _run_inner_suite(
        pytester,
        """
        import subprocess

        import pytest

        @pytest.fixture(scope="session")
        def phone():
            subprocess.run(["adb", "devices"], check=False)

        def test_uses_phone(phone):
            pass
        """,
    )
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*RealDeviceAccessError*"])
    assert not fake_adb.exists()


class _FakeConfig:
    def __init__(self, run_device):
        self._run_device = run_device

    def getoption(self, name):
        assert name == "--run-device"
        return self._run_device


class _FakeItem:
    def __init__(self, keywords, run_device):
        self.keywords = keywords
        self.config = _FakeConfig(run_device)


@pytest.mark.parametrize(
    ("keywords", "run_device", "allowed"),
    [
        ({"requires_device": True}, True, True),
        ({"requires_device": True}, False, False),
        ({}, True, False),
        ({}, False, False),
    ],
)
def test_device_access_is_allowed_only_for_opted_in_device_tests(keywords, run_device, allowed):
    assert guard._allows_device(_FakeItem(keywords, run_device)) is allowed


_IOS_TOOLS = (
    "xcode-select",
    "xcodebuild",
    "xcrun",
    "appium",
    "ffmpeg",
    "idevice_id",
    "ideviceinstaller",
    "idevicesyslog",
    "pymobiledevice3",
    "go-ios",
    "ios",
    "tidevice",
)


@pytest.fixture
def fake_ios_tools(tmp_path, monkeypatch):
    """Put fake iOS tools first on PATH. Each one writes a marker file if it ever starts."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    markers = tmp_path / "started"
    markers.mkdir()
    for name in _IOS_TOOLS:
        script = bin_dir / name
        script.write_text(f"#!/bin/sh\ntouch '{markers / name}'\n")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/bin{os.pathsep}/usr/bin")
    return markers


@pytest.mark.parametrize("tool", _IOS_TOOLS)
@pytest.mark.parametrize(
    "call",
    [
        lambda tool: subprocess.run([tool, "--version"], check=False),
        lambda tool: subprocess.run(f"{tool} --version", shell=True, check=False),
        lambda tool: subprocess.run(["sh", "-c", f"true && {tool} list"], check=False),
        lambda tool: subprocess.run(f"FOO=1 /usr/bin/env {tool} list", shell=True, check=False),
        lambda tool: os.system(f"{tool} --version"),
        lambda tool: os.popen(f"{tool} --version").read(),
        lambda tool: os.spawnvp(os.P_WAIT, tool, [tool, "--version"]),
    ],
    ids=["run-list", "run-shell", "sh-c", "env", "os-system", "os-popen", "os-spawnvp"],
)
def test_ios_tools_are_blocked_without_run_device(fake_ios_tools, tool, call):
    with pytest.raises(RealDeviceAccessError, match=f"run {tool} without --run-device"):
        call(tool)
    assert list(fake_ios_tools.iterdir()) == []


def test_xcrun_subcommands_are_blocked(fake_ios_tools):
    for command in (["xcrun", "devicectl", "list", "devices"], ["xcrun", "simctl", "list"]):
        with pytest.raises(RealDeviceAccessError):
            subprocess.run(command, check=False)
    assert list(fake_ios_tools.iterdir()) == []


@pytest.mark.parametrize("tool", _IOS_TOOLS)
def test_ios_tools_run_inside_the_device_window(fake_ios_tools, monkeypatch, tool):
    monkeypatch.setattr(guard, "_device_access_allowed", True)
    assert subprocess.run([tool, "--version"], check=False).returncode == 0
    assert (fake_ios_tools / tool).exists()


def test_ios_tools_run_in_an_opted_in_device_test(pytester, fake_ios_tools):
    pytester.makeconftest(_ROOT_CONFTEST.read_text())
    pytester.makepyfile(
        f"""
        import subprocess

        import pytest

        TOOLS = {list(_IOS_TOOLS)!r}

        @pytest.mark.requires_device
        def test_on_phone():
            for tool in TOOLS:
                assert subprocess.run([tool, "--version"], check=False).returncode == 0

        def test_not_on_phone():
            with pytest.raises(AssertionError, match="without --run-device"):
                subprocess.run(["xcrun", "devicectl", "list", "devices"], check=False)
        """
    )
    # The tools on PATH are the fake scripts, so no real tool starts.
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "--run-device")
    result.assert_outcomes(passed=2)
    assert sorted(path.name for path in fake_ios_tools.iterdir()) == sorted(_IOS_TOOLS)


@pytest.mark.parametrize(
    "command",
    [
        ["echo", "verdict", "run", "--platform", "ios"],
        "echo verdict run --platform ios",
        "echo ios | cat",
        ["sh", "-c", "echo ios > /dev/null"],
        "true > ios",
    ],
)
def test_ios_as_an_argument_is_not_blocked(fake_ios_tools, tmp_path, monkeypatch, command):
    monkeypatch.chdir(tmp_path)
    shell = isinstance(command, str)
    result = subprocess.run(command, shell=shell, check=False, capture_output=True)
    assert result.returncode == 0
    assert list(fake_ios_tools.iterdir()) == []


@pytest.mark.parametrize(
    ("command", "executables"),
    [
        (["verdict", "run", "--platform", "ios"], ["verdict"]),
        ("cd /tmp && ios list; echo ios", ["cd", "ios", "echo"]),
        ("sudo -E env A=1 ios list | grep ios", ["ios", "grep"]),
        (["bash", "-c", "FOO=1 /usr/local/bin/ios list"], ["bash", "/usr/local/bin/ios"]),
        ("cat < ios", ["cat"]),
    ],
)
def test_executable_words_find_only_programs(command, executables):
    assert guard._command_executables(command) == executables


def test_appium_remote_is_blocked():
    from appium import webdriver

    with pytest.raises(RealDeviceAccessError, match="Appium session"):
        webdriver.Remote("http://127.0.0.1:4723")


def test_appium_webdriver_class_is_blocked():
    from appium.webdriver.webdriver import WebDriver

    with pytest.raises(RealDeviceAccessError, match="Appium session"):
        WebDriver("http://10.0.0.2:4723")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:4723/status",
        "http://localhost:4723/status",
        "http://[::1]:4723/status",
        "http://0.0.0.0:4723/status",
        "http://127.0.0.2:8100/status",
    ],
)
def test_appium_status_probe_is_blocked(url):
    from verdict.device_state import ios_doctor

    with pytest.raises(RealDeviceAccessError, match="loopback URL"):
        ios_doctor.urllib_get(url)
    with pytest.raises(RealDeviceAccessError, match="loopback URL"):
        urllib.request.urlopen(urllib.request.Request(url))


def test_doctor_default_probe_is_blocked():
    from verdict.device_state import ios_doctor

    with pytest.raises(RealDeviceAccessError):
        ios_doctor.check_appium_server("http://127.0.0.1:4723", ios_doctor.urllib_get)


def test_urlopen_without_a_loopback_host_is_not_blocked():
    with urllib.request.urlopen("data:,hello") as response:
        assert response.read() == b"hello"
    assert not guard._is_loopback_host("10.0.0.2")
    assert not guard._is_loopback_host("example.com")


def test_doctor_ffmpeg_version_check_is_blocked(fake_ios_tools):
    with pytest.raises(RealDeviceAccessError, match="run ffmpeg without --run-device"):
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=False)
    with pytest.raises(RealDeviceAccessError, match="run ffmpeg without --run-device"):
        subprocess.run("echo start; /opt/homebrew/bin/ffmpeg -version", shell=True, check=False)
    assert list(fake_ios_tools.iterdir()) == []


def _assert_ios_is_blocked(command, fake_ios_tools, **kwargs):
    with pytest.raises(RealDeviceAccessError, match="run ios without --run-device"):
        subprocess.run(command, check=False, capture_output=True, **kwargs)
    assert list(fake_ios_tools.iterdir()) == []


@pytest.mark.parametrize(
    "command",
    ["true\nios list", "echo start\n\nios list", "true;\nios list"],
)
def test_a_newline_separates_shell_commands(fake_ios_tools, command):
    _assert_ios_is_blocked(command, fake_ios_tools, shell=True)
    _assert_ios_is_blocked(["sh", "-c", command], fake_ios_tools)


@pytest.mark.parametrize(
    "command",
    [
        ["env", "-u", "VERDICT_GUARD_UNUSED", "ios", "list"],
        ["env", "-iu", "NAME", "-C", "/tmp", "A=1", "ios", "list"],
        ["env", "--unset", "NAME", "--chdir=/tmp", "ios", "list"],
        ["env", "-", "ios", "list"],
        ["sudo", "-u", "root", "-g", "wheel", "ios", "list"],
        ["sudo", "-Eu", "root", "--", "ios", "list"],
        ["nice", "-n", "5", "ios", "list"],
        ["nice", "-10", "ios", "list"],
        ["timeout", "-s", "KILL", "5", "ios", "list"],
        ["timeout", "--kill-after", "1", "5", "ios", "list"],
        ["xargs", "-n", "1", "-I", "{}", "ios", "list"],
        ["stdbuf", "-o", "L", "ios", "list"],
        ["exec", "-a", "name", "ios", "list"],
        ["env", "-S", "ios list"],
        ["sudo", "--unknown-option", "value", "ios", "list"],
        ["timeout", "-z", "5", "ios", "list"],
    ],
)
def test_wrapper_options_with_values_do_not_hide_the_executable(command):
    assert "ios" in guard._command_executables(command)
    assert "ios" in guard._command_executables(shlex.join(command))


def test_wrapper_option_with_a_value_is_blocked(fake_ios_tools):
    _assert_ios_is_blocked(["env", "-u", "VERDICT_GUARD_UNUSED", "ios", "list"], fake_ios_tools)


@pytest.mark.parametrize(
    "command",
    [
        "2>/dev/null ios list",
        "2>&1 ios list",
        "true; >/dev/null ios list",
        "true;>/dev/null ios list",
        "{fd}>/dev/null ios list",
        "</dev/null 2>/dev/null ios list",
    ],
)
def test_a_numbered_redirection_before_the_command_is_blocked(fake_ios_tools, command):
    _assert_ios_is_blocked(command, fake_ios_tools, shell=True)


@pytest.mark.parametrize(
    "command",
    [
        ["sh", "-ec", "ios list"],
        ["sh", "-ce", "ios list"],
        ["bash", "-xec", "ios list"],
        ["bash", "-o", "pipefail", "-c", "ios list"],
        ["bash", "--norc", "-ec", "ios list"],
        ["sh", "-c", "-e", "ios list"],
    ],
)
def test_combined_shell_options_with_c_are_blocked(fake_ios_tools, command):
    _assert_ios_is_blocked(command, fake_ios_tools)
