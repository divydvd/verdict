"""Keep the test suite away from a real phone unless the run opts in.

Tests marked ``requires_device`` run only with ``--run-device``. All other
tests cannot start ``adb`` or open a uiautomator2 connection.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

import pytest

pytest_plugins = ["pytester"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-device",
        action="store_true",
        default=False,
        help="run tests marked requires_device on a real phone (needs a device grant)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-device"):
        return
    skip = pytest.mark.skip(reason="device test: pass --run-device to run it on a real phone")
    for item in items:
        if "requires_device" in item.keywords:
            item.add_marker(skip)


def _is_adb_command(args: Any) -> bool:
    if isinstance(args, (str, bytes, os.PathLike)):
        first = os.fsdecode(args).split()[0] if os.fsdecode(args).split() else ""
    elif args:
        first = os.fsdecode(args[0])
    else:
        return False
    return os.path.basename(first) == "adb"


class RealDeviceAccessError(AssertionError):
    pass


@pytest.fixture(autouse=True)
def _block_real_device(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    if "requires_device" in request.keywords and request.config.getoption("--run-device"):
        return

    def _guard(original: Any) -> Any:
        def wrapper(args: Any, *a: Any, **kw: Any) -> Any:
            if _is_adb_command(args):
                raise RealDeviceAccessError(f"test tried to run adb without --run-device: {args!r}")
            return original(args, *a, **kw)

        return wrapper

    monkeypatch.setattr(subprocess, "run", _guard(subprocess.run))
    monkeypatch.setattr(subprocess, "Popen", _guard(subprocess.Popen))

    def _no_connect(*args: Any, **kwargs: Any) -> Any:
        raise RealDeviceAccessError("test tried to open a real uiautomator2 connection")

    try:
        import uiautomator2
    except ImportError:
        return
    monkeypatch.setattr(uiautomator2, "connect", _no_connect)
