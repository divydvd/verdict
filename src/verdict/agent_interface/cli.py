"""Thin CLI wiring parser -> runner -> reporting. See docs/architecture.md §6.9, §9."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

import click

# Importing domains.ime registers its actions/assertions (docs/architecture.md
# §3.8). scenario_engine deliberately stays domain-agnostic, so this wiring
# has to happen somewhere above it -- the CLI entry point is that place.
import verdict.domains.ime  # noqa: F401
from verdict.core.exceptions import VerdictError
from verdict.device_driver.android import AndroidUiautomator2Driver
from verdict.device_driver.base import DeviceDriver
from verdict.device_state.adb import Adb, AdbError, SubprocessAdb
from verdict.device_state.baseline import (
    Baseline,
    BlockedError,
    preflight,
    prepare_private_folder,
    take_baseline,
)
from verdict.device_state.restore import (
    RestoreReport,
    TestResult,
    delete_backups,
    load_baseline,
    restore,
)
from verdict.reporting.generator import DEFAULT_FORMATS, ReportGenerator
from verdict.scenario_engine.parser import parse_scenario
from verdict.scenario_engine.runner import ScenarioResult, run_scenario

DriverFactory = Callable[[str | None], DeviceDriver]


def _default_driver_factory(serial: str | None) -> DeviceDriver:
    return AndroidUiautomator2Driver(serial=serial)


def execute_run(
    scenario_path: Path,
    variables: dict[str, str],
    output_dir: Path,
    formats: tuple[str, ...],
    device: str | None,
    driver_factory: DriverFactory = _default_driver_factory,
) -> ScenarioResult:
    """Parse, run, and report on a scenario. Split out from the `run` click
    command so tests can inject a `driver_factory` (e.g. FakeDeviceDriver)
    without a real device/emulator attached.
    """
    spec = parse_scenario(scenario_path, variables)
    driver = driver_factory(device)
    result = run_scenario(spec, driver, session_id=str(uuid.uuid4()))
    ReportGenerator(output_dir).generate(result, formats=formats)
    return result


def _parse_variable(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise click.BadParameter(f"expected KEY=VALUE, got {raw!r}")
    key, value = raw.split("=", 1)
    return key, value


@click.group()
def main() -> None:
    """Verdict: agentic mobile testing platform CLI."""


@main.command()
@click.argument("scenario_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--var",
    "-e",
    "variables",
    multiple=True,
    metavar="KEY=VALUE",
    help="Override/define a scenario variable. May be passed multiple times.",
)
@click.option(
    "--device", "-s", default=None, help="adb serial; defaults to the only connected device."
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("verdict-report"),
    show_default=True,
    help="Directory to write report.{json,md,html} into.",
)
@click.option(
    "--formats",
    default=",".join(DEFAULT_FORMATS),
    show_default=True,
    help="Comma-separated subset of: json,markdown,html.",
)
def run(
    scenario_path: Path,
    variables: tuple[str, ...],
    device: str | None,
    output_dir: Path,
    formats: str,
) -> None:
    """Run SCENARIO_PATH against a connected Android device/emulator."""
    var_dict = dict(_parse_variable(v) for v in variables)
    format_tuple = tuple(f.strip() for f in formats.split(",") if f.strip())

    try:
        result = execute_run(scenario_path, var_dict, output_dir, format_tuple, device)
    except VerdictError as exc:
        raise click.ClickException(str(exc)) from exc

    status = "PASSED" if result.passed else "FAILED"
    click.echo(f"{result.timeline.scenario_name}: {status} ({result.attempts} attempt(s))")
    click.echo(f"Report written to {output_dir}")
    if not result.passed:
        raise SystemExit(1)


AdbFactory = Callable[[str | None], Adb]


def _baseline_summary(baseline: Baseline, folder: Path) -> list[str]:
    state = baseline.state
    lines = [f"Baseline of {baseline.package} saved in {folder}"]
    for name, version in state.packages.items():
        lines.append(f"  package {name}: {version.version_name} ({version.version_code})")
    if baseline.package not in state.packages:
        lines.append(f"  {baseline.package} is not installed: no APK pull, no app-data backup")
    if state.apk_sha256:
        lines.append(f"  pretest APK SHA-256: {state.apk_sha256[:12]}")
    for key, value in {**state.keyboard, **state.display}.items():
        lines.append(f"  {key}: {value}")
    if baseline.app_data_tar:
        lines.append(f"  app data: {len(state.app_data_sha256)} file(s) backed up with checksums")
    if baseline.ime_enabled_by_verdict:
        lines.append(f"  enabled for the test: {baseline.ime_enabled_by_verdict}")
    return lines


def execute_baseline(
    package: str,
    folder: Path,
    prefix: str | None,
    device: str | None,
    adb_factory: AdbFactory | None = None,
) -> tuple[Baseline, Path]:
    adb = (adb_factory or SubprocessAdb)(device)
    resolved = prepare_private_folder(folder)
    preflight(adb, device)
    return take_baseline(adb, package, prefix or package, resolved), resolved


@main.command()
@click.argument("package")
@click.option(
    "--dir",
    "folder",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Private evidence folder (mode 700, outside any git repo) for the backups.",
)
@click.option(
    "--packages-prefix",
    default=None,
    help="Record every package with this prefix, and never select one of their keyboards. "
    "Default: PACKAGE.",
)
@click.option("--device", "-s", default=None, help="adb serial of the one connected phone.")
def baseline(package: str, folder: Path, packages_prefix: str | None, device: str | None) -> None:
    """Record the phone's state for PACKAGE before a device test.

    Exit 0: saved. Exit 2: BLOCKED (the reason is printed); the phone is unchanged,
    or its keyboard is set back.
    """
    try:
        result, resolved = execute_baseline(package, folder, packages_prefix, device)
    except BlockedError as exc:
        click.echo(f"BLOCKED: {exc}")
        raise SystemExit(2) from exc
    except VerdictError as exc:
        raise click.ClickException(str(exc)) from exc
    for line in _baseline_summary(result, resolved):
        click.echo(line)


def execute_restore(
    package: str,
    folder: Path,
    result: TestResult,
    device: str | None,
    adb_factory: AdbFactory | None = None,
) -> RestoreReport:
    baseline = load_baseline(folder, package)
    adb = (adb_factory or SubprocessAdb)(device)
    try:
        preflight(adb, device, check_lock=False)
    except (AdbError, OSError) as exc:
        raise BlockedError(f"the preflight check failed: {exc}") from exc
    try:
        return restore(adb, baseline, folder, result)
    except (AdbError, VerdictError, OSError) as exc:
        raise BlockedError(f"the restore stopped; finish it by hand from the skill: {exc}") from exc


@main.command(name="restore")
@click.argument("package")
@click.option(
    "--dir",
    "folder",
    required=True,
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="The evidence folder that `verdict baseline` used.",
)
@click.option(
    "--result",
    required=True,
    type=click.Choice(["PASS", "FAIL", "BLOCKED"]),
    help="PASS keeps the tested build. FAIL or BLOCKED installs the pretest APK (never a downgrade).",
)
@click.option("--keep-backup", is_flag=True, help="Keep the backup files after a good check.")
@click.option("--device", "-s", default=None, help="adb serial of the one connected phone.")
def restore_command(
    package: str, folder: Path, result: TestResult, keep_backup: bool, device: str | None
) -> None:
    """Put the phone back to the baseline of PACKAGE after a device test.

    Exit 0: equal to the baseline (expected differences allowed). Exit 1: a difference
    stays. Exit 2: BLOCKED (the reason is printed).
    """
    try:
        report = execute_restore(package, folder, result, device)
    except BlockedError as exc:
        click.echo(f"BLOCKED: {exc}")
        raise SystemExit(2) from exc
    except VerdictError as exc:
        raise click.ClickException(str(exc)) from exc
    for note in report.notes:
        click.echo(f"- {note}")
    click.echo("| item | baseline | final | equal |\n| --- | --- | --- | --- |")
    for row in report.rows:
        click.echo(f"| {row.item} | {row.baseline} | {row.final} | {row.status} |")
    if not report.equal:
        click.echo("Restore check: a difference stays. The backups are kept.")
        raise SystemExit(1)
    if not keep_backup:
        delete_backups(folder)
    click.echo("Restore check: equal to the baseline" + ("." if keep_backup else "; backups deleted."))
