"""Keep the test suite away from a real phone unless the run opts in.

Tests marked ``requires_device`` run only with ``--run-device``. In all other
code, the guard blocks these actions on an Android or iOS device:

- Start ``adb`` or an iOS tool: ``xcode-select``, ``xcodebuild``, ``xcrun``
  (this covers ``xcrun devicectl`` and ``xcrun simctl``), ``appium``, ``ffmpeg``,
  every ``idevice*`` tool, ``pymobiledevice3``, ``go-ios``, and ``tidevice``. The
  guard finds these names in every word of the command, as for ``adb``.
- Start ``ios`` (the go-ios executable). The word ``ios`` is also a normal
  argument (``verdict run --platform ios``), so the guard blocks it only in
  the executable position of a command.
- Open a uiautomator2 connection or an Appium ``WebDriver`` session.
- Open a URL on a loopback host (``localhost``, ``127.0.0.0/8``, ``::1``,
  ``0.0.0.0``) with ``urllib.request.urlopen``. The ``verdict doctor ios``
  probe uses this call for ``<appium-url>/status``. A local Appium server or
  a WebDriverAgent port forward always uses a loopback host. The guard does
  not patch ``ios_doctor.urllib_get``, because ``run_ios_doctor`` keeps a
  reference to it as a default argument. A remote host does not go to a
  local device, so the guard does not block it.

``pytest_configure`` installs the guard before collection, so it also covers
module import time, ``pytest_configure`` hooks of later plugins, and fixtures
of every scope. The guard allows device access only while the setup, call, or
teardown of a ``requires_device`` test runs with ``--run-device``.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest

pytest_plugins = ["pytester"]

_DEVICE_TOOL_NAMES = frozenset(
    {
        "adb",
        "adb.exe",
        "xcode-select",
        "xcodebuild",
        "xcrun",
        "appium",
        "ffmpeg",
        "pymobiledevice3",
        "go-ios",
        "tidevice",
    }
)
_DEVICE_TOOL_PREFIXES = ("idevice",)
_EXECUTABLE_ONLY_NAMES = frozenset({"ios", "ios.exe"})


@dataclass(frozen=True)
class _Wrapper:
    # The options of a command that runs another command, such as env or sudo.
    flags: str = ""
    values: str = ""
    optional_values: str = ""
    long_flags: frozenset[str] = frozenset()
    long_values: frozenset[str] = frozenset()
    operands: int = 0


# An option that is not in this table makes the guard fail closed. env -S is
# not in the table, because its value is a second command line.
_WRAPPERS = {
    "env": _Wrapper(
        flags="i0v",
        values="uC",
        long_flags=frozenset({"ignore-environment", "null", "debug"}),
        long_values=frozenset({"unset", "chdir"}),
    ),
    "sudo": _Wrapper(
        flags="AbEeHiKklnPSsVv",
        values="CDgpRrTtUu",
        long_flags=frozenset(
            {
                "askpass", "background", "bell", "edit", "login", "non-interactive",
                "preserve-env", "preserve-groups", "remove-timestamp", "reset-timestamp",
                "set-home", "shell", "stdin",
            }
        ),
        long_values=frozenset(
            {
                "chdir", "chroot", "close-from", "command-timeout", "group", "other-user",
                "prompt", "role", "type", "user",
            }
        ),
    ),
    "nice": _Wrapper(values="n", long_values=frozenset({"adjustment"})),
    "timeout": _Wrapper(
        flags="v",
        values="ks",
        long_flags=frozenset({"foreground", "preserve-status", "verbose"}),
        long_values=frozenset({"kill-after", "signal"}),
        operands=1,
    ),
    "xargs": _Wrapper(
        flags="0oprtx",
        values="adEILnPs",
        optional_values="eil",
        long_flags=frozenset(
            {"eof", "exit", "interactive", "no-run-if-empty", "null", "open-tty", "replace",
             "verbose", "max-lines"}
        ),
        long_values=frozenset(
            {"arg-file", "delimiter", "max-args", "max-chars", "max-procs", "process-slot-var"}
        ),
    ),
    "stdbuf": _Wrapper(values="ioe", long_values=frozenset({"input", "output", "error"})),
    "time": _Wrapper(
        flags="alpqv",
        values="fo",
        long_flags=frozenset({"append", "portability", "quiet", "verbose"}),
        long_values=frozenset({"format", "output"}),
    ),
    "caffeinate": _Wrapper(flags="dimsu", values="tw"),
    "exec": _Wrapper(flags="cl", values="a"),
    "command": _Wrapper(flags="pVv"),
    "nohup": _Wrapper(),
    "builtin": _Wrapper(),
    "setsid": _Wrapper(flags="cfw"),
}
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_SHELL_SEPARATORS = re.compile(r"[;|&()<>`\s]+")
_SHELL_PUNCTUATION = ";&|()<>`\n"
_SHELL_LONG_VALUES = frozenset({"rcfile", "init-file"})
_REDIRECTIONS = frozenset({"<", ">", ">>", "<<", "<<<", "<>", ">&", "<&", "&>", ">|"})
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
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
        help=(
            "run tests marked requires_device on a real Android or iOS device "
            "(needs a device grant)"
        ),
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-device"):
        return
    skip = pytest.mark.skip(
        reason="device test: pass --run-device to run it on a real Android or iOS device"
    )
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


def _shell_words(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=_SHELL_PUNCTUATION)
    lexer.whitespace_split = True
    # A newline separates two commands, so it is an operator and not whitespace.
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return text.split()


def _is_operator(word: str) -> bool:
    return bool(word) and all(char in _SHELL_PUNCTUATION for char in word)


def _operator_effect(word: str) -> tuple[bool, bool]:
    # Return (starts a new command, the next word is a redirection target).
    # shlex joins adjacent operators, for example ";>". Such a token starts a
    # new command and also redirects. This fails closed.
    if word in _REDIRECTIONS:
        return False, True
    redirects = ("<" in word or ">" in word) and "(" not in word
    return True, redirects


def _is_fd_prefix(word: str, words: list[str], index: int) -> bool:
    # "2>/dev/null" splits into "2", ">", "/dev/null".
    return (
        (word.isdigit() or re.fullmatch(r"\{[A-Za-z_][A-Za-z0-9_]*\}", word) is not None)
        and index < len(words)
        and _is_operator(words[index])
        and _operator_effect(words[index])[1]
    )


def _wrapped_command_start(wrapper: _Wrapper, words: list[str], index: int) -> int | None:
    # Return the index of the wrapped command, or None if an option is unknown.
    while index < len(words):
        word = words[index]
        if word == "--":
            index += 1
            break
        if word == "-":
            index += 1
            continue
        if _is_operator(word):
            break
        if word.startswith("--"):
            option, has_value, _ = word[2:].partition("=")
            if option in wrapper.long_values:
                index += 1 if has_value else 2
            elif option in wrapper.long_flags:
                index += 1
            else:
                return None
            continue
        if word.startswith("-") and len(word) > 1:
            if wrapper is _WRAPPERS["nice"] and word[1:].isdigit():
                index += 1
                continue
            step = 1
            for position, char in enumerate(word[1:], start=1):
                if char in wrapper.optional_values:
                    break
                if char in wrapper.values:
                    if position == len(word) - 1:
                        step = 2
                    break
                if char not in wrapper.flags:
                    return None
            index += step
            continue
        break
    return index + wrapper.operands


def _shell_script(args: list[str]) -> str | None:
    # Return the command string of "sh -c SCRIPT", also for groups such as -ec.
    has_c = False
    index = 0
    while index < len(args):
        word = args[index]
        if word == "--":
            index += 1
            break
        if len(word) < 2 or word[0] not in "-+":
            break
        if word.startswith("--"):
            index += 2 if word[2:] in _SHELL_LONG_VALUES else 1
            continue
        group = word[1:]
        if word[0] == "-" and "c" in group:
            has_c = True
        index += 2 if ("o" in group or "O" in group) else 1
    if has_c and index < len(args):
        return args[index]
    return None


def _executable_words(words: list[str]) -> Iterator[str]:
    # Yield each word that a shell runs as a program: the first word of every
    # command, after redirections, environment assignments, and wrappers such
    # as env or sudo. If a wrapper option is unknown, yield all later words.
    at_start = True
    index = 0
    while index < len(words):
        word = words[index]
        index += 1
        if _is_operator(word):
            new_command, redirects = _operator_effect(word)
            at_start = at_start or new_command
            if redirects and index < len(words) and not _is_operator(words[index]):
                index += 1
            continue
        if not at_start or _is_fd_prefix(word, words, index) or _ENV_ASSIGNMENT.match(word):
            continue
        name = os.path.basename(word)
        wrapper = _WRAPPERS.get(name)
        if wrapper is not None:
            start = _wrapped_command_start(wrapper, words, index)
            if start is None:
                yield from (
                    token
                    for later in words[index:]
                    if not _is_operator(later)
                    for token in _string_tokens(later)
                )
                return
            index = start
            continue
        yield word
        at_start = False
        if name in _SHELLS:
            script = _shell_script(words[index:])
            if script is not None:
                yield from _executable_words(_shell_words(script))


def _command_executables(command: Any) -> list[str]:
    if isinstance(command, (str, bytes, os.PathLike)):
        return list(_executable_words(_shell_words(os.fsdecode(command))))
    if isinstance(command, (list, tuple)):
        words = [os.fsdecode(part) for part in command if isinstance(part, (str, bytes, os.PathLike))]
        return list(_executable_words(words))
    return []


def _is_device_tool(name: str) -> bool:
    return name in _DEVICE_TOOL_NAMES or name.startswith(_DEVICE_TOOL_PREFIXES)


def _device_tool_in(*commands: Any) -> str | None:
    for command in commands:
        for token in _command_tokens(command):
            name = os.path.basename(token)
            if _is_device_tool(name):
                return name
    for command in commands:
        for word in _command_executables(command):
            name = os.path.basename(word)
            if name in _EXECUTABLE_ONLY_NAMES:
                return name
    return None


def _check(*commands: Any) -> None:
    if _device_access_allowed:
        return
    tool = _device_tool_in(*commands)
    if tool is not None:
        raise RealDeviceAccessError(
            f"test tried to run {tool} without --run-device: {commands!r}"
        )


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


def _guard_appium_init(original: Any) -> Any:
    # appium.webdriver.Remote is the WebDriver class, so this also covers Remote.
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> None:
        if not _device_access_allowed:
            raise RealDeviceAccessError("test tried to open a real Appium session")
        original(self, *args, **kwargs)

    return wrapper


def _url_host(url: Any) -> str | None:
    if isinstance(url, urllib.request.Request):
        url = url.full_url
    if isinstance(url, bytes):
        url = url.decode(errors="replace")
    if not isinstance(url, str):
        return None
    try:
        return urllib.parse.urlsplit(url).hostname
    except ValueError:
        return None


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _guard_urlopen(original: Any) -> Any:
    def wrapper(url: Any, *args: Any, **kwargs: Any) -> Any:
        if not _device_access_allowed and _is_loopback_host(_url_host(url)):
            raise RealDeviceAccessError(
                f"test tried to open a loopback URL (Appium server) without --run-device: {url!r}"
            )
        return original(url, *args, **kwargs)

    return wrapper


def pytest_configure(config: pytest.Config) -> None:
    _patch(subprocess.Popen, "_execute_child", _guard_execute_child)
    _patch(os, "system", _guard_function)
    for name in _EXEC_FUNCTIONS:
        _patch(os, name, _guard_function)
    _patch(urllib.request, "urlopen", _guard_urlopen)
    try:
        from appium.webdriver.webdriver import WebDriver
    except ImportError:
        pass
    else:
        _patch(WebDriver, "__init__", _guard_appium_init)
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
