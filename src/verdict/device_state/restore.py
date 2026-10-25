"""Put a phone back to its `baseline` state after a device test.

Follows the restore steps of SmarType's `smartype-device-test` skill, with one owner
decision for the APK: after a PASS the tested build stays installed; after FAIL or
BLOCKED the pretest APK goes back, but never as a downgrade.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from verdict.core.exceptions import VerdictError
from verdict.device_state.adb import Adb
from verdict.device_state.baseline import (
    APP_DATA_SHA256,
    APP_DATA_TAR,
    BASELINE_FILE,
    DISPLAY_SETTINGS,
    KEYBOARD_SETTINGS,
    NIGHT_MODE,
    PRETEST_APK,
    Baseline,
    DeviceState,
    PackageVersion,
    in_family,
    pull_apk,
    read_app_data_checksums,
    read_packages,
    read_settings,
    select_other_keyboard,
)

TestResult = Literal["PASS", "FAIL", "BLOCKED"]
Status = Literal["yes", "no", "expected"]
FINAL_APK = "final-check.apk"
STAGING_ROOT = "/data/local/tmp"


@dataclass
class Row:
    item: str
    baseline: str
    final: str
    status: Status


@dataclass
class RestoreReport:
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def equal(self) -> bool:
        return all(row.status != "no" for row in self.rows)


def load_baseline(folder: Path, package: str) -> Baseline:
    path = folder.expanduser().resolve() / BASELINE_FILE
    if not path.is_file():
        raise VerdictError(f"no {BASELINE_FILE} in {folder}; run `verdict baseline` first")
    baseline = Baseline.model_validate_json(path.read_text())
    if baseline.package != package:
        raise VerdictError(f"the baseline in {folder} is for {baseline.package}, not {package}")
    return baseline


def ime_ids(value: str) -> set[str]:
    if value.strip() in ("", "null"):
        return set()
    return {part.split(";", 1)[0] for part in value.strip().split(":") if part}


def _put_setting(adb: Adb, namespace: str, key: str, value: str) -> None:
    if value == "null":
        adb.shell(f"settings delete {namespace} {key}")
    else:
        adb.shell(f"settings put {namespace} {key} {shlex.quote(value)}")


def _safe_data_path(path: str) -> str:
    parts = path.split("/")
    if parts[0] != "." or len(parts) < 2 or any(part in ("", ".", "..") for part in parts[1:]):
        raise VerdictError("an app-data path is not a plain relative path; it was not deleted")
    return path


def extract_backup(adb: Adb, package: str, tar: Path) -> None:
    """Push the tar to a new mode-700 staging folder that only the shell user can
    read, and extract it with a redirect on the phone. A stdin pipe through adb
    fails on some phones. The staging folder is always deleted."""
    staging = f"{STAGING_ROOT}/verdict-restore-{secrets.token_hex(8)}"
    remote = f"{staging}/{APP_DATA_TAR}"
    adb.shell(f"mkdir -m 700 {staging}")
    try:
        adb.push(tar, remote)
        adb.shell(f"chmod 600 {remote}")
        adb.shell(f"run-as {shlex.quote(package)} tar -xf - < {remote}")
    finally:
        adb.shell(f"rm -rf -- {staging}")


def restore_app_data(adb: Adb, baseline: Baseline, folder: Path) -> int:
    """Extract the backup, then delete each file that is not in the baseline list,
    one exact path at a time. Return the number of deleted files."""
    package = shlex.quote(baseline.package)
    adb.shell(f"am force-stop {package}")
    extract_backup(adb, baseline.package, folder / APP_DATA_TAR)
    _, now = read_app_data_checksums(adb, baseline.package)
    extra = sorted(set(now) - set(baseline.state.app_data_sha256))
    for path in extra:
        adb.shell(f"run-as {package} rm -f -- {shlex.quote(_safe_data_path(path))}")
    return len(extra)


def set_display(adb: Adb, display: dict[str, str]) -> None:
    for key, namespace in DISPLAY_SETTINGS.items():
        _put_setting(adb, namespace, key, display[key])
    adb.shell(f"cmd uimode night {shlex.quote(display[NIGHT_MODE])}")


def set_keyboards(adb: Adb, keyboard: dict[str, str]) -> None:
    """Make the enabled keyboards, the default, and the subtype equal the baseline."""
    want = ime_ids(keyboard["enabled_input_methods"])
    have = {line.strip() for line in adb.shell("ime list -s").splitlines() if line.strip()}
    for ime in sorted(want - have):
        adb.shell(f"ime enable {shlex.quote(ime)}")
    if keyboard["default_input_method"] != "null":
        adb.shell(f"ime set {shlex.quote(keyboard['default_input_method'])}")
    for ime in sorted(have - want):
        adb.shell(f"ime disable {shlex.quote(ime)}")
    _put_setting(adb, "secure", "selected_input_method_subtype", keyboard["selected_input_method_subtype"])


def put_apk_back(
    adb: Adb, baseline: Baseline, folder: Path, result: TestResult, report: RestoreReport
) -> set[str]:
    """Apply the APK rule. Return the items that may differ from the baseline."""
    package, before = baseline.package, baseline.state.packages.get(baseline.package)
    now = read_packages(adb, baseline.packages_prefix).get(package)
    tested_build = {f"package {package}", "apk_sha256"}
    if now is not None and result == "PASS":
        report.notes.append("PASS: the tested build stays installed")
        return tested_build | ({"app data"} if before is None else set())
    if before is None:
        if now is not None:
            adb.uninstall(package)
            report.notes.append(f"{package} was not installed before the test: uninstalled")
        return set()
    if now is not None and now.version_code > before.version_code:
        report.notes.append("the pretest APK has a lower version code: no downgrade, the tested build stays")
        return tested_build
    adb.install(folder / PRETEST_APK)
    report.notes.append("the pretest APK is installed again")
    return set()


def read_app_data_if_needed(adb: Adb, baseline: Baseline) -> dict[str, str]:
    wanted = baseline.app_data_tar is not None or baseline.state.apk_sha256 is None
    if wanted and baseline.package in read_packages(adb, baseline.packages_prefix):
        return read_app_data_checksums(adb, baseline.package)[1]
    return {}


def read_final_state(
    adb: Adb, baseline: Baseline, folder: Path, app_data: dict[str, str]
) -> DeviceState:
    packages = read_packages(adb, baseline.packages_prefix)
    keyboard, display = read_settings(adb)
    state = DeviceState(packages=packages, keyboard=keyboard, display=display)
    if baseline.package in packages:
        try:
            state.apk_sha256 = pull_apk(adb, baseline.package, folder / FINAL_APK)
        finally:
            (folder / FINAL_APK).unlink(missing_ok=True)
        state.app_data_sha256 = app_data
    return state


def _version(value: PackageVersion | None) -> str:
    return "not installed" if value is None else f"{value.version_name} ({value.version_code})"


def _data_summary(checksums: dict[str, str]) -> str:
    digest = hashlib.sha256(json.dumps(checksums, sort_keys=True).encode()).hexdigest()
    return f"{len(checksums)} file(s), digest {digest[:12]}" if checksums else "0 file(s)"


def compare(before: DeviceState, after: DeviceState, expected: set[str]) -> list[Row]:
    """Compare names, versions, settings, and counts only, never app-data content."""
    rows: list[Row] = []

    def add(item: str, old: str, new: str) -> None:
        status: Status = "yes" if old == new else "expected" if item in expected else "no"
        rows.append(Row(item, old, new, status))

    for name in sorted(set(before.packages) | set(after.packages)):
        add(f"package {name}", _version(before.packages.get(name)), _version(after.packages.get(name)))
    add("apk_sha256", (before.apk_sha256 or "-")[:12], (after.apk_sha256 or "-")[:12])
    for key in KEYBOARD_SETTINGS:
        old, new = before.keyboard.get(key, "null"), after.keyboard.get(key, "null")
        if key == "enabled_input_methods":
            old, new = ":".join(sorted(ime_ids(old))), ":".join(sorted(ime_ids(new)))
        add(key, old, new)
    for key in (*DISPLAY_SETTINGS, NIGHT_MODE):
        add(key, before.display.get(key, "null"), after.display.get(key, "null"))
    add("app data", _data_summary(before.app_data_sha256), _data_summary(after.app_data_sha256))
    return rows


def restore(adb: Adb, baseline: Baseline, folder: Path, result: TestResult) -> RestoreReport:
    report = RestoreReport()
    state, package = baseline.state, baseline.package
    folder = folder.expanduser().resolve()
    default = state.keyboard["default_input_method"]
    keyboard_is_target = in_family(default, package)
    if keyboard_is_target:
        current = adb.shell("settings get secure default_input_method").strip()
        if in_family(current, package):
            select_other_keyboard(adb, baseline.packages_prefix)
    elif default != "null":
        adb.shell(f"ime enable {shlex.quote(default)}")
        adb.shell(f"ime set {shlex.quote(default)}")
    expected = put_apk_back(adb, baseline, folder, result, report)
    installed = package in read_packages(adb, baseline.packages_prefix)
    if baseline.app_data_tar and installed:
        deleted = restore_app_data(adb, baseline, folder)
        report.notes.append(f"app data extracted; {deleted} file(s) not in the baseline deleted")
    set_display(adb, state.display)
    # Read the app data before the keyboard step: when the package is the baseline
    # keyboard, its start writes its own files and would give a false difference.
    app_data = read_app_data_if_needed(adb, baseline)
    set_keyboards(adb, state.keyboard)
    final = read_final_state(adb, baseline, folder, app_data)
    report.rows = compare(state, final, expected)
    return report


def delete_backups(folder: Path) -> None:
    for name in (PRETEST_APK, APP_DATA_TAR, APP_DATA_SHA256):
        (folder.expanduser().resolve() / name).unlink(missing_ok=True)
