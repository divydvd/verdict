"""Record a phone's state before a device test, so that `restore` can put it back.

Follows the baseline steps of SmarType's `smartype-device-test` skill: packages and
versions, a pull of the installed APK, keyboard and display settings, then (for an
installed app) a keyboard switch, a force-stop, and an app-data tar backup with checksums.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from verdict.core.exceptions import VerdictError
from verdict.device_state.adb import Adb, AdbError

BASELINE_FILE = "baseline.json"
PRETEST_APK = "pretest.apk"
APP_DATA_TAR = "app-data.tar"
APP_DATA_SHA256 = "app-data.sha256"
OUTPUT_FILES = (BASELINE_FILE, PRETEST_APK, APP_DATA_TAR, APP_DATA_SHA256)

KEYBOARD_SETTINGS = ("default_input_method", "enabled_input_methods", "selected_input_method_subtype")
DISPLAY_SETTINGS = {
    "font_scale": "system",
    "accelerometer_rotation": "system",
    "user_rotation": "system",
    "stay_on_while_plugged_in": "global",
}
NIGHT_MODE = "night_mode"

_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+")
_LOCKED = re.compile(
    r"\b(mDreamingLockscreen|mShowingLockscreen|isStatusBarKeyguard|mKeyguardShowing)=true\b"
)


class BlockedError(VerdictError):
    """The device test cannot go on. Report BLOCKED with this reason."""


class PackageVersion(BaseModel):
    version_code: int
    version_name: str


class DeviceState(BaseModel):
    packages: dict[str, PackageVersion]
    keyboard: dict[str, str]
    display: dict[str, str]
    apk_sha256: str | None = None
    app_data_sha256: dict[str, str] = Field(default_factory=dict)


class Baseline(BaseModel):
    package: str
    packages_prefix: str
    created_at: datetime
    state: DeviceState
    pretest_apk: str | None = None
    app_data_tar: str | None = None
    ime_enabled_by_verdict: str | None = None


def check_package_name(name: str) -> str:
    if not _PACKAGE.fullmatch(name):
        raise VerdictError(f"invalid package name {name!r}")
    return name


def prepare_private_folder(folder: Path) -> Path:
    """Create the evidence folder with mode 700. Refuse a folder inside a git
    work tree (backups must never be committed) or one with an old baseline."""
    folder = folder.expanduser().resolve()
    for parent in (folder, *folder.parents):
        if (parent / ".git").exists():
            raise VerdictError(f"{folder} is inside the git work tree {parent}; use a folder outside it")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.stat().st_uid != os.getuid():
        raise VerdictError(f"{folder} is not owned by the current user")
    folder.chmod(0o700)
    # An old file or a symlink at an output path could be overwritten or followed.
    if old := [n for n in OUTPUT_FILES if os.path.lexists(folder / n)]:
        raise VerdictError(f"{folder} already has {', '.join(old)}; restore or use a new folder")
    return folder


def preflight(adb: Adb, serial: str | None, check_lock: bool = True) -> None:
    devices = adb.devices()
    if not devices:
        raise BlockedError("no phone is connected")
    if len(devices) > 1:
        raise BlockedError(f"{len(devices)} devices are connected; exactly one phone is allowed")
    found_serial, state = devices[0]
    if serial is not None and found_serial != serial:
        raise BlockedError("the connected device is not the one given with --device")
    if found_serial.startswith("emulator-"):
        raise BlockedError("the connected device is an emulator; use the phone")
    if state != "device":
        raise BlockedError(f"the phone is in the {state!r} state, not 'device'")
    user = adb.shell("am get-current-user").strip()
    if user != "0":
        raise BlockedError(f"the current user is {user!r}, not 0")
    if check_lock and _LOCKED.search(adb.shell("dumpsys window")):
        raise BlockedError("the phone is locked")


def in_family(package_or_ime: str, prefix: str) -> bool:
    package = package_or_ime.split("/", 1)[0]
    return package == prefix or package.startswith(prefix + ".")


def read_packages(adb: Adb, prefix: str) -> dict[str, PackageVersion]:
    packages: dict[str, PackageVersion] = {}
    for line in adb.shell(f"pm list packages {shlex.quote(prefix)}").splitlines():
        name = line.strip().removeprefix("package:")
        if not in_family(name, prefix):
            continue
        dump = adb.shell(f"dumpsys package {shlex.quote(name)}")
        code = re.search(r"versionCode=(\d+)", dump)
        version = re.search(r"versionName=(\S+)", dump)
        if code is None or version is None:
            raise AdbError(f"cannot read the version of {name}")
        packages[name] = PackageVersion(version_code=int(code.group(1)), version_name=version.group(1))
    return dict(sorted(packages.items()))


def read_settings(adb: Adb) -> tuple[dict[str, str], dict[str, str]]:
    keyboard = {key: adb.shell(f"settings get secure {key}").strip() for key in KEYBOARD_SETTINGS}
    display = {
        key: adb.shell(f"settings get {namespace} {key}").strip()
        for key, namespace in DISPLAY_SETTINGS.items()
    }
    display[NIGHT_MODE] = adb.shell("cmd uimode night").strip().rsplit(":", 1)[-1].strip()
    return keyboard, display


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pull_apk(adb: Adb, package: str, dest: Path) -> str:
    paths = [line.strip().removeprefix("package:") for line in adb.shell(
        f"pm path {shlex.quote(package)}").splitlines() if line.strip()]
    if len(paths) != 1:
        raise BlockedError(f"{package} has {len(paths)} APK files; only a single APK is supported")
    adb.pull(paths[0], dest)
    dest.chmod(0o600)
    return sha256_file(dest)


def read_app_data_checksums(adb: Adb, package: str) -> tuple[str, dict[str, str]]:
    # No remote pipe: a pipe would hide a failed `find`/`sha256sum` (adb gives the last exit code).
    raw = adb.shell(f"run-as {shlex.quote(package)} find . -type f -exec sha256sum {{}} +")
    checksums: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise AdbError(f"unexpected checksum line for {package}")
        checksums[parts[1]] = parts[0]
    return "".join(f"{checksums[p]}  {p}\n" for p in sorted(checksums)), checksums


def select_other_keyboard(adb: Adb, prefix: str, baseline: Baseline, folder: Path) -> None:
    """Select an enabled keyboard outside the package family. If there is none,
    enable one first and save its id, so that restore can disable it again."""
    enabled = [ime.strip() for ime in adb.shell("ime list -s").splitlines() if ime.strip()]
    others = [ime for ime in enabled if not in_family(ime, prefix)]
    if not others:
        every = [ime.strip() for ime in adb.shell("ime list -a -s").splitlines() if ime.strip()]
        others = [ime for ime in every if not in_family(ime, prefix)]
        if not others:
            raise BlockedError("no other keyboard is installed")
        baseline.ime_enabled_by_verdict = others[0]
        save_baseline(folder, baseline)
        adb.shell(f"ime enable {shlex.quote(others[0])}")
    adb.shell(f"ime set {shlex.quote(others[0])}")


def put_keyboard_back(adb: Adb, baseline: Baseline) -> None:
    default = baseline.state.keyboard.get("default_input_method", "null")
    if default != "null":
        adb.shell(f"ime set {shlex.quote(default)}")
    if baseline.ime_enabled_by_verdict:
        adb.shell(f"ime disable {shlex.quote(baseline.ime_enabled_by_verdict)}")


def save_baseline(folder: Path, baseline: Baseline) -> None:
    path = folder / BASELINE_FILE
    path.write_text(baseline.model_dump_json(indent=2))
    path.chmod(0o600)


def _backup_app_data(adb: Adb, package: str, folder: Path) -> dict[str, str]:
    tar_path = folder / APP_DATA_TAR
    adb.exec_out_to_file(f"run-as {shlex.quote(package)} tar -cf - .", tar_path)
    tar_path.chmod(0o600)
    if tar_path.stat().st_size == 0 or not tarfile.is_tarfile(tar_path):
        raise BlockedError(f"the app-data backup of {package} is not a tar file")
    raw, checksums = read_app_data_checksums(adb, package)
    sha_path = folder / APP_DATA_SHA256
    sha_path.write_text(raw)
    sha_path.chmod(0o600)
    with tarfile.open(tar_path) as archive:
        files = [m.name for m in archive.getmembers() if m.isfile() or m.islnk()]
    names = {name if name.startswith("./") else f"./{name}" for name in files}
    if names != set(checksums):
        raise BlockedError(f"the tar has {len(names)} file(s), the checksums {len(checksums)}")
    return checksums


def take_baseline(adb: Adb, package: str, prefix: str, folder: Path) -> Baseline:
    check_package_name(package)
    check_package_name(prefix)
    if not in_family(package, prefix):
        raise VerdictError(f"{package} is not in the --packages-prefix family {prefix}")
    packages = read_packages(adb, prefix)
    installed = package in packages
    keyboard, display = read_settings(adb)
    apk_sha = pull_apk(adb, package, folder / PRETEST_APK) if installed else None
    baseline = Baseline(
        package=package,
        packages_prefix=prefix,
        created_at=datetime.now(UTC),
        state=DeviceState(packages=packages, keyboard=keyboard, display=display, apk_sha256=apk_sha),
        pretest_apk=PRETEST_APK if installed else None,
    )
    save_baseline(folder, baseline)
    if not installed:
        return baseline

    try:
        if in_family(keyboard["default_input_method"], package):
            select_other_keyboard(adb, prefix, baseline, folder)
        adb.shell(f"am force-stop {shlex.quote(package)}")
        baseline.state.app_data_sha256 = _backup_app_data(adb, package, folder)
        baseline.app_data_tar = APP_DATA_TAR
        save_baseline(folder, baseline)
    except (AdbError, BlockedError, OSError, tarfile.TarError) as exc:
        put_keyboard_back(adb, baseline)
        raise BlockedError(f"the baseline failed, keyboard set back: {exc}") from exc
    return baseline
