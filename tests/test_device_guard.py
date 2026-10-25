import os
import subprocess
import sys
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
