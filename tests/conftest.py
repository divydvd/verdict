"""Keep the test suite away from a real phone unless the run opts in.

Tests marked ``requires_device`` run only with ``--run-device``. In all other
code, the guard blocks every way to start ``adb`` and blocks a uiautomator2
connection. ``pytest_configure`` installs the guard before collection, so it
also covers module import time, ``pytest_configure`` hooks of later plugins,
and fixtures of every scope. The guard allows device access only while the
setup, call, or teardown of a ``requires_device`` test runs with
``--run-device``.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

pytest_plugins = ["pytester"]

_ADB_NAMES = frozenset({"adb", "adb.exe"})
_SHELL_SEPARATORS = re.compile(r"[;|&()<>`\s]+")
_EXEC_FUNCTIONS = (
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "posix_spawn", "posix_spawnp",
)
_U2_CONNECT_FUNCTIONS = ("connect", "connect_usb", "connect_adb_wifi", "connect_wifi")

_device_access_allowed = False
_restore: list[tuple[Any, str, Any]] = []


class RealDeviceAccessError(AssertionError):
    pass


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


def _string_tokens(text: str) -> list[str]:
    try:
        words = shlex.split(text)
    except ValueError:
        words = text.split()
    return [token for word in words for token in _SHELL_SEPARATORS.split(word) if token]


def _command_tokens(command: Any) -> list[str]:
    if isinstance(command, (str, bytes, os.PathLike)):
        return _string_tokens(os.fsdecode(command))
    if isinstance(command, (list, tuple)):
        return [token for part in command for token in _command_tokens(part)]
    return []


def _is_adb_command(*commands: Any) -> bool:
    return any(
        os.path.basename(token) in _ADB_NAMES
        for command in commands
        for token in _command_tokens(command)
    )


def _check(*commands: Any) -> None:
    if not _device_access_allowed and _is_adb_command(*commands):
        raise RealDeviceAccessError(f"test tried to run adb without --run-device: {commands!r}")


def _patch(owner: Any, name: str, make_wrapper: Callable[[Any], Any]) -> None:
    original = getattr(owner, name, None)
    if original is None:
        return
    _restore.append((owner, name, original))
    setattr(owner, name, make_wrapper(original))


def _guard_execute_child(original: Any) -> Any:
    # Popen.__init__ calls _execute_child with the final argv (for shell=True,
    # [shell, "-c", command]). Patching it covers run, call, check_output,
    # os.popen, asyncio, and code that imported Popen before this hook ran.
    def wrapper(self: Any, args: Any, executable: Any, *rest: Any, **kwargs: Any) -> Any:
        _check(args, executable)
        return original(self, args, executable, *rest, **kwargs)

    return wrapper


def _guard_function(original: Any) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        _check(*args)
        return original(*args, **kwargs)

    return wrapper


def _guard_connect(original: Any) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _device_access_allowed:
            raise RealDeviceAccessError("test tried to open a real uiautomator2 connection")
        return original(*args, **kwargs)

    return wrapper


def pytest_configure(config: pytest.Config) -> None:
    _patch(subprocess.Popen, "_execute_child", _guard_execute_child)
    _patch(os, "system", _guard_function)
    for name in _EXEC_FUNCTIONS:
        _patch(os, name, _guard_function)
    try:
        import uiautomator2
    except ImportError:
        return
    for name in _U2_CONNECT_FUNCTIONS:
        _patch(uiautomator2, name, _guard_connect)


def pytest_unconfigure(config: pytest.Config) -> None:
    while _restore:
        owner, name, original = _restore.pop()
        setattr(owner, name, original)


def _allows_device(item: pytest.Item) -> bool:
    return "requires_device" in item.keywords and bool(item.config.getoption("--run-device"))


@contextmanager
def _device_window(item: pytest.Item) -> Iterator[None]:
    global _device_access_allowed
    previous = _device_access_allowed
    _device_access_allowed = _allows_device(item)
    try:
        yield
    finally:
        _device_access_allowed = previous


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Iterator[None]:
    with _device_window(item):
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    with _device_window(item):
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Iterator[None]:
    with _device_window(item):
        yield
