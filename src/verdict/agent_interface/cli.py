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
