import subprocess

import pytest

from verdict.device_state import adb as adb_module
from verdict.device_state.adb import AdbError, SubprocessAdb


def test_tests_cannot_reach_the_real_adb():
    with pytest.raises(AssertionError, match="adb without --run-device"):
        SubprocessAdb().devices()


@pytest.fixture
def recorded(monkeypatch):
    # Undo the autouse guard for these tests only; subprocess.run is replaced with a fake.
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        out = b"List of devices attached\nR5CX\tdevice\nemulator-5554\toffline\n\n"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr=b"")

    monkeypatch.undo()
    monkeypatch.setattr(adb_module.subprocess, "run", fake_run)
    return calls


def test_devices_parses_the_list_without_a_serial(recorded):
    assert SubprocessAdb(serial="R5CX").devices() == [("R5CX", "device"), ("emulator-5554", "offline")]
    assert recorded == [["adb", "devices"]]


def test_shell_adds_the_serial(recorded):
    SubprocessAdb(serial="R5CX").shell("am get-current-user")
    assert recorded[0][:4] == ["adb", "-s", "R5CX", "shell"]


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(
        adb_module.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"no devices"),
    )
    with pytest.raises(AdbError, match="exited 1: no devices"):
        SubprocessAdb().shell("true")
