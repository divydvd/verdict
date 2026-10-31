"""Thin CLI wiring parser -> runner -> reporting. See docs/architecture.md §6.9, §9."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import click

# Importing domains.ime registers its actions/assertions (docs/architecture.md
# §3.8). scenario_engine deliberately stays domain-agnostic, so this wiring
# has to happen somewhere above it -- the CLI entry point is that place.
import verdict.domains.ime  # noqa: F401
from verdict.core.exceptions import VerdictError
from verdict.core.models import Platform, Timeline
from verdict.device_driver.android import CONNECTION_ERRORS, AndroidUiautomator2Driver
from verdict.device_driver.base import DeviceDriver
from verdict.device_driver.ios_appium import (
    DEFAULT_APPIUM_URL,
    IOS_CONNECTION_ERRORS,
    IosAppiumDriver,
)
from verdict.device_state.adb import Adb, AdbError, SubprocessAdb
from verdict.device_state.baseline import (
    Baseline,
    BlockedError,
    preflight,
    prepare_private_folder,
    take_baseline,
)
from verdict.device_state.ios_doctor import (
    IOS_EXTRA_INSTALL,
    IosExtraMissingError,
    doctor_passed,
    ios_extra_installed,
    run_ios_doctor,
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
from verdict.scenario_engine.schema import ScenarioSpec

DriverFactory = Callable[[str | None], DeviceDriver]


def _default_driver_factory(serial: str | None) -> DeviceDriver:
    return AndroidUiautomator2Driver(serial=serial)


def ios_driver_factory(appium_url: str, app_paths: dict[str, str]) -> DriverFactory:
    """Return a factory that opens an Appium session on the iOS device with that UDID."""

    def factory(udid: str | None) -> DeviceDriver:
        if not ios_extra_installed():
            raise IosExtraMissingError(
                f"the `ios` extra is not installed. Install it: {IOS_EXTRA_INSTALL}"
            )
        return IosAppiumDriver(udid=udid, appium_url=appium_url, app_paths=app_paths)

    return factory


def blocked_errors_for(platform: Platform) -> tuple[type[BaseException], ...]:
    """Return the errors that make a run BLOCKED on `platform`."""
    return IOS_CONNECTION_ERRORS if platform is Platform.IOS else CONNECTION_ERRORS


def _close_driver(driver: DeviceDriver) -> None:
    close = getattr(driver, "close", None)
    if callable(close):
        # The session can be gone already (a BLOCKED run). That does not change the result.
        with suppress(Exception):
            close()


def _skipped_result(spec: ScenarioSpec, platform: Platform) -> ScenarioResult:
    # The same result and reason as `run_scenario` gives, but without a driver session.
    supported = ", ".join(p.value for p in spec.platforms or ())
    return ScenarioResult(
        passed=False,
        skipped=True,
        skip_reason=(
            f"the scenario supports only {supported}; the device platform is {platform.value}"
        ),
        attempts=0,
        timeline=Timeline(run_id=str(uuid.uuid4()), scenario_name=spec.name),
    )


def execute_run(
    scenario_path: Path,
    variables: dict[str, str],
    output_dir: Path,
    formats: tuple[str, ...],
    device: str | None,
    driver_factory: DriverFactory = _default_driver_factory,
    platform: Platform = Platform.ANDROID,
) -> ScenarioResult:
    """Parse, run, and report on a scenario. Split out from the `run` click
    command so tests can inject a `driver_factory` (e.g. FakeDeviceDriver)
    without a real device/emulator attached.

    `platform` selects the errors that make the run BLOCKED. If the scenario
    does not support `platform`, the result is SKIPPED and the driver is not
    made. The run closes the driver session at the end, also after an error.
    """
    spec = parse_scenario(scenario_path, variables)
    if not spec.supports(platform):
        result = _skipped_result(spec, platform)
        ReportGenerator(output_dir).generate(result, formats=formats)
        return result
    driver = driver_factory(device)
    try:
        result = run_scenario(
            spec,
            driver,
            session_id=str(uuid.uuid4()),
            blocked_errors=blocked_errors_for(platform),
        )
    finally:
        _close_driver(driver)
    ReportGenerator(output_dir).generate(result, formats=formats)
    return result


def _parse_variable(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise click.BadParameter(f"expected KEY=VALUE, got {raw!r}")
    key, value = raw.split("=", 1)
    return key, value


def _parse_app(raw: str) -> tuple[str, str]:
    bundle_id, path = raw.split("=", 1) if "=" in raw else ("", "")
    if not bundle_id or not path:
        raise click.BadParameter(f"expected BUNDLE_ID=PATH, got {raw!r}")
    return bundle_id, str(Path(path).expanduser().resolve())


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
    "--platform",
    type=click.Choice([Platform.ANDROID.value, Platform.IOS.value]),
    default=Platform.ANDROID.value,
    show_default=True,
    help="The platform of the device.",
)
@click.option(
    "--device",
    "-s",
    default=None,
    help="Android: the adb serial (default: the only connected device). "
    "iOS: the UDID of the iPhone or the Simulator.",
)
@click.option(
    "--appium-url",
    default=DEFAULT_APPIUM_URL,
    show_default=True,
    help="iOS only: the URL of the Appium server.",
)
@click.option(
    "--app",
    "apps",
    multiple=True,
    metavar="BUNDLE_ID=PATH",
    help="iOS only: the .app or .ipa file of a bundle id. clear_data needs it. "
    "May be passed multiple times.",
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
    platform: str,
    device: str | None,
    appium_url: str,
    apps: tuple[str, ...],
    output_dir: Path,
    formats: str,
) -> None:
    """Run SCENARIO_PATH on a connected Android or iOS device.

    Exit 0: PASSED. Exit 1: FAILED. Exit 2: BLOCKED, the device connection
    failed or the `ios` extra is not installed. The report keeps the steps
    before the BLOCKED step. Exit 3: SKIPPED, the scenario does not support
    the platform. The skip reason is printed.
    """
    var_dict = dict(_parse_variable(v) for v in variables)
    format_tuple = tuple(f.strip() for f in formats.split(",") if f.strip())
    target = Platform(platform)
    if target is Platform.IOS:
        app_paths = dict(_parse_app(a) for a in apps)
        factory = ios_driver_factory(appium_url, app_paths)
    else:
        if apps:
            raise click.UsageError("--app applies only to --platform ios.")
        factory = _default_driver_factory
    blocked_errors = blocked_errors_for(target)

    try:
        result = execute_run(
            scenario_path, var_dict, output_dir, format_tuple, device, factory, target
        )
    except IosExtraMissingError as exc:
        click.echo(f"BLOCKED: {exc}", err=True)
        raise SystemExit(2) from exc
    except VerdictError as exc:
        raise click.ClickException(str(exc)) from exc
    except blocked_errors as exc:
        click.echo(f"BLOCKED: the device connection failed: {type(exc).__name__}: {exc}", err=True)
        raise SystemExit(2) from exc

    click.echo(f"{result.timeline.scenario_name}: {result.status} ({result.attempts} attempt(s))")
    click.echo(f"Report written to {output_dir}")
    if result.skipped:
        click.echo(f"SKIPPED: {result.skip_reason}", err=True)
        raise SystemExit(3)
    if result.blocked:
        click.echo(f"BLOCKED: {result.timeline.events[-1].error}", err=True)
        raise SystemExit(2)
    if not result.passed:
        raise SystemExit(1)


@main.group()
def doctor() -> None:
    """Check that this computer is ready for device tests."""


@doctor.command(name="ios")
@click.option("--device", "-s", default=None, help="The UDID of the iPhone or the Simulator to find.")
@click.option(
    "--appium-url",
    default=DEFAULT_APPIUM_URL,
    show_default=True,
    help="The URL of the Appium server.",
)
def doctor_ios(device: str | None, appium_url: str) -> None:
    """Check Xcode, Appium, the XCUITest driver, the device, and the `ios` extra.

    Each check prints one line: OK, WARN, or FAIL. Each WARN and FAIL also
    prints a fix. Exit 0: no required check failed. Exit 2: a required check
    failed.
    """
    checks = run_ios_doctor(device, appium_url)
    for check in checks:
        click.echo(f"{check.status.value:<4} {check.name}: {check.detail}")
        if check.fix:
            click.echo(f"     fix: {check.fix}")
    if not doctor_passed(checks):
        click.echo("iOS is not ready: fix each FAIL line.")
        raise SystemExit(2)
    click.echo("iOS is ready.")


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
    except (BlockedError, OSError) as exc:
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
