import pytest

from verdict.device_state import adb as adb_module


@pytest.fixture(autouse=True)
def _no_real_adb(monkeypatch):
    """Stop any test from running the real `adb` binary against a connected phone."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to run the real adb; inject a fake instead")

    monkeypatch.setattr(adb_module.SubprocessAdb, "_run", refuse)
