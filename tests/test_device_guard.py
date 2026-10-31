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
        ["env", "A=1", "echo", "ios"],
        ["echo", "IOS", "ios.exe"],
        ("echo", "ios"),
        iter(["echo", "--platform", "ios"]),
    ],
    ids=["verdict-run", "env", "case", "tuple", "iterator"],
)
def test_ios_as_an_argument_in_an_argument_list_is_not_blocked(fake_ios_tools, command):
    result = subprocess.run(command, check=False, capture_output=True)
    assert result.returncode == 0
    assert list(fake_ios_tools.iterdir()) == []


@pytest.mark.parametrize(
    "command",
    [
        "echo verdict run --platform ios",
        "echo ios | cat",
        "true > ios",
        'echo "$(ios list)"',
        "echo `ios list`",
        "{ ios list; }",
        "if true; then ios list; fi",
        "! ios list",
        "(ios list)",
        "while false; do ios list; done",
        "case x in x) ios list;; esac",
        "f() { ios list; }; f",
        "i\\os list",
        "'i''os' list",
        "IOS list",
        "/usr/local/bin/ios.exe list",
    ],
)
def test_shell_strings_with_the_word_ios_fail_closed(fake_ios_tools, command):
    _assert_ios_is_blocked(command, fake_ios_tools, shell=True, tool=None)
    _assert_ios_is_blocked(["sh", "-c", command], fake_ios_tools, tool=None)
    _assert_ios_is_blocked(["bash", "-ec", command], fake_ios_tools, tool=None)
    with pytest.raises(RealDeviceAccessError):
        os.system(command)


@pytest.mark.parametrize(
    ("command", "executables"),
    [
        (["verdict", "run", "--platform", "ios"], ["verdict"]),
        (["sudo", "-E", "env", "A=1", "ios", "list"], ["ios"]),
        (["bash", "-c", "FOO=1 /usr/local/bin/ios list"], ["bash"]),
        ("ios list", []),
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


def _assert_ios_is_blocked(command, fake_ios_tools, tool="ios", **kwargs):
    match = f"run {tool} without --run-device" if tool else "without --run-device"
    with pytest.raises(RealDeviceAccessError, match=match):
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
    assert guard._device_tool_in(command) == "ios"
    assert guard._device_tool_in(shlex.join(command)) == "ios"


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


def _iterator_of(command):
    return (word for word in command)


@pytest.mark.parametrize(
    "call",
    [
        lambda: subprocess.run(_iterator_of(["ios", "list"]), check=False),
        lambda: subprocess.run(_iterator_of(["xcrun", "simctl", "list"]), check=False),
        lambda: subprocess.Popen(map(str, ["adb", "devices"])),
        lambda: os.posix_spawnp("true", _iterator_of(["sh", "-c", "ios list"]), dict(os.environ)),
    ],
    ids=["generator-ios", "generator-xcrun", "map-adb", "spawn-generator"],
)
def test_an_iterator_command_is_checked(fake_ios_tools, call):
    with pytest.raises(RealDeviceAccessError):
        call()
    assert list(fake_ios_tools.iterdir()) == []


def test_an_iterator_command_still_runs_after_the_check(tmp_path):
    marker = tmp_path / "ran"
    result = subprocess.run(_iterator_of(["touch", str(marker)]), check=False)
    assert result.returncode == 0
    assert marker.exists()
    pid = os.posix_spawnp("true", _iterator_of(["true"]), dict(os.environ))
    assert os.waitpid(pid, 0)[1] == 0


@pytest.mark.parametrize(
    "command",
    [
        ["ADB", "devices"],
        ["XCRUN", "simctl", "list"],
        ["/usr/bin/XcodeBuild", "-version"],
        ["IDEVICE_ID", "-l"],
        ["IOS", "list"],
        "XCRUN simctl list",
        "Ios.Exe list",
    ],
)
def test_tool_names_ignore_the_case(command):
    assert guard._device_tool_in(command) is not None
    with pytest.raises(RealDeviceAccessError):
        subprocess.run(command, shell=isinstance(command, str), check=False)


@pytest.mark.parametrize(
    "command",
    [
        ["ios-deploy", "--detect"],
        ["iproxy", "8100", "8100"],
        ["simctl", "list"],
        ["/Applications/Xcode.app/Contents/Developer/usr/bin/simctl", "list"],
        ["/usr/local/bin/ios-deploy", "--id", "UDID"],
        "iproxy 8100 8100 &",
        "/Applications/Xcode.app/Contents/Developer/usr/bin/simctl list",
    ],
)
def test_ios_deploy_iproxy_and_simctl_are_blocked(command):
    with pytest.raises(RealDeviceAccessError):
        subprocess.run(command, shell=isinstance(command, str), check=False)


@pytest.mark.parametrize(
    "command",
    [
        ["ios list"],
        ("ios list",),
        ["true", "ios list"],
        ["echo start; ios list"],
        ("{ ios list; }",),
        ["XCRUN simctl list"],
    ],
    ids=["list", "tuple", "second-item", "separator", "brace-tuple", "tool-case"],
)
def test_shell_true_checks_each_item_as_shell_text(fake_ios_tools, command):
    with pytest.raises(RealDeviceAccessError):
        subprocess.run(command, shell=True, check=False, capture_output=True)
    assert list(fake_ios_tools.iterdir()) == []


@pytest.mark.parametrize(
    ("argv", "executable"),
    [
        (["alias", "-c", 'echo "$(ios list)"'], "/bin/sh"),
        (["alias", "-ec", "ios list"], "/bin/sh"),
        (["true", "list"], "ios"),
        (["true", "devices"], "/usr/bin/adb"),
    ],
    ids=["sh-c", "sh-ec", "ios", "adb-path"],
)
def test_popen_checks_the_executable_argument(fake_ios_tools, argv, executable):
    with pytest.raises(RealDeviceAccessError):
        subprocess.run(argv, executable=executable, check=False, capture_output=True)
    assert list(fake_ios_tools.iterdir()) == []


def test_popen_with_a_harmless_executable_still_runs():
    result = subprocess.run(
        ["alias", "-c", "echo ok"], executable="/bin/sh", capture_output=True, check=True
    )
    assert result.stdout == b"ok\n"


@pytest.mark.parametrize(
    "call",
    [
        lambda env: os.posix_spawn("/bin/sh", ["alias", "-c", 'echo "$(ios list)"'], env),
        lambda env: os.posix_spawnp("sh", ["alias", "-c", "ios list"], env),
        lambda env: os.posix_spawnp("ios", ["true", "list"], env),
        lambda env: os.spawnv(os.P_WAIT, "/bin/sh", ["alias", "-c", "ios list"]),
        lambda env: os.spawnve(os.P_WAIT, "/bin/sh", ["alias", "-c", "ios list"], env),
        lambda env: os.spawnl(os.P_WAIT, "/bin/sh", "alias", "-c", "ios list"),
        lambda env: os.spawnlpe(os.P_WAIT, "sh", "alias", "-c", "ios list", env),
        lambda env: os.spawnvp(os.P_WAIT, "ios", ["true", "list"]),
    ],
    ids=["posix_spawn", "posix_spawnp", "posix_spawnp-ios", "spawnv", "spawnve", "spawnl",
         "spawnlpe", "spawnvp-ios"],
)
def test_os_spawn_checks_the_program_path_with_the_arguments(fake_ios_tools, call):
    with pytest.raises(RealDeviceAccessError):
        call(dict(os.environ))
    assert list(fake_ios_tools.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("execv", ("/bin/sh", ["alias", "-c", "ios list"])),
        ("execve", ("/bin/sh", ["alias", "-c", "ios list"], {})),
        ("execvp", ("ios", ["true", "list"])),
        ("execvpe", ("sh", ["alias", "-ec", "ios list"], {})),
        ("execl", ("/bin/sh", "alias", "-c", "ios list")),
        ("execle", ("/bin/sh", "alias", "-c", "ios list", {})),
        ("execlp", ("ios", "true", "list")),
        ("execlpe", ("sh", "alias", "-c", "ios list", {})),
    ],
)
def test_os_exec_checks_the_program_path_with_the_arguments(name, args):
    # A real os.exec* call would replace this process, so a fake original takes its place.
    calls = []

    def original(*call_args):
        calls.append(call_args)

    original.__name__ = name
    with pytest.raises(RealDeviceAccessError):
        guard._guard_function(original)(*args)
    assert calls == []


def test_os_exec_wrapper_passes_a_harmless_call_through():
    calls = []

    def execv(*call_args):
        calls.append(call_args)

    guard._guard_function(execv)("/bin/sh", iter(["alias", "-c", "echo ok"]))
    assert calls == [("/bin/sh", ["alias", "-c", "echo ok"])]


@pytest.mark.parametrize(
    "host",
    [
        "127.1",
        "127.0.1",
        "2130706433",
        "0x7f000001",
        "0x7f.1",
        "017700000001",
        "0177.0.0.1",
        "::ffff:127.0.0.1",
        "::ffff:7f00:1",
        "::ffff:0.0.0.0",
        "0",
        "LOCALHOST",
        "localhost.",
    ],
)
def test_other_loopback_forms_are_blocked(host):
    assert guard._is_loopback_host(host)
    url = f"http://[{host}]:4723/status" if ":" in host else f"http://{host}:4723/status"
    with pytest.raises(RealDeviceAccessError, match="loopback URL"):
        urllib.request.urlopen(url)


@pytest.mark.parametrize("host", ["10.0.0.2", "1", "::ffff:10.0.0.2", "example.com", "1.2.3.4"])
def test_other_hosts_are_not_loopback(host):
    assert not guard._is_loopback_host(host)
