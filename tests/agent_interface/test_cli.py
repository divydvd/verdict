from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from verdict.agent_interface import cli
from verdict.assertions.base import assertion_registry
from verdict.core.models import AssertionResult, UiNode
from verdict.device_driver.fake import FakeDeviceDriver


class _PassAssertion:
    name = "cli_always_pass"

    def check(self, ctx):
        return AssertionResult(passed=True, message="ok")


@pytest.fixture(autouse=True)
def _isolated_assertion_registry():
    backup = dict(assertion_registry._factories)
    try:
        yield
    finally:
        assertion_registry._factories.clear()
        assertion_registry._factories.update(backup)


def _write_scenario(tmp_path: Path, **overrides) -> Path:
    spec = {
        "name": "cli-scenario",
        "steps": [
            {"action": "tap", "selector": {"resource_id": "text_field"}},
            {"action": "assert", "assertion": "cli_always_pass"},
        ],
    }
    spec.update(overrides)
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml.safe_dump(spec))
    return path


def _driver_with_text_field() -> FakeDeviceDriver:
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(resource_id="text_field"))
    return driver


def test_execute_run_happy_path_writes_reports(tmp_path):
    assertion_registry.register("cli_always_pass", lambda: _PassAssertion())
    scenario_path = _write_scenario(tmp_path)
    output_dir = tmp_path / "out"

    result = cli.execute_run(
        scenario_path,
        {},
        output_dir,
        ("json", "markdown"),
        device=None,
        driver_factory=lambda serial: _driver_with_text_field(),
    )

    assert result.passed is True
    assert (output_dir / "report.json").exists()
    assert (output_dir / "report.md").exists()
    assert not (output_dir / "report.html").exists()


def test_execute_run_reports_failure(tmp_path):
    scenario_path = _write_scenario(
        tmp_path,
        steps=[{"action": "wait_for", "selector": {"description": "missing"}, "timeout_ms": 10}],
    )
    output_dir = tmp_path / "out"

    result = cli.execute_run(
        scenario_path,
        {},
        output_dir,
        ("json",),
        device=None,
        driver_factory=lambda serial: FakeDeviceDriver(),
    )

    assert result.passed is False


def test_run_command_exits_zero_on_pass(tmp_path, monkeypatch):
    assertion_registry.register("cli_always_pass", lambda: _PassAssertion())
    scenario_path = _write_scenario(tmp_path)
    output_dir = tmp_path / "out"
    monkeypatch.setattr(cli, "AndroidUiautomator2Driver", lambda serial=None: _driver_with_text_field())

    runner = CliRunner()
    result = runner.invoke(cli.main, ["run", str(scenario_path), "--output-dir", str(output_dir)])

    assert result.exit_code == 0
    assert "PASSED" in result.output


def test_run_command_exits_nonzero_on_fail(tmp_path, monkeypatch):
    scenario_path = _write_scenario(
        tmp_path,
        steps=[{"action": "wait_for", "selector": {"description": "missing"}, "timeout_ms": 10}],
    )
    output_dir = tmp_path / "out"
    monkeypatch.setattr(cli, "AndroidUiautomator2Driver", lambda serial=None: FakeDeviceDriver())

    runner = CliRunner()
    result = runner.invoke(cli.main, ["run", str(scenario_path), "--output-dir", str(output_dir)])

    assert result.exit_code == 1
    assert "FAILED" in result.output


def test_run_command_parses_variables(tmp_path, monkeypatch):
    assertion_registry.register("cli_always_pass", lambda: _PassAssertion())
    spec = {
        "name": "cli-scenario-vars",
        "steps": [
            {"action": "launch", "package": "${target_app}"},
            {"action": "assert", "assertion": "cli_always_pass"},
        ],
    }
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml.safe_dump(spec))
    output_dir = tmp_path / "out"
    driver = FakeDeviceDriver()
    monkeypatch.setattr(cli, "AndroidUiautomator2Driver", lambda serial=None: driver)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        [
            "run",
            str(path),
            "-e",
            "target_app=bha.keys.smartype.debug",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert driver.current_package == "bha.keys.smartype.debug"


def test_run_command_rejects_malformed_variable(tmp_path):
    scenario_path = _write_scenario(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli.main, ["run", str(scenario_path), "-e", "not-a-kv-pair"])
    assert result.exit_code != 0


def test_baseline_command_prints_summary(tmp_path, monkeypatch):
    from tests.device_state.fake_adb import PLAY, TARGET, FakePhone

    phone = FakePhone()
    monkeypatch.setattr(cli, "SubprocessAdb", lambda serial: phone)
    folder = tmp_path / "ev"
    result = CliRunner().invoke(
        cli.main, ["baseline", TARGET, "--dir", str(folder), "--packages-prefix", PLAY]
    )
    assert result.exit_code == 0, result.output
    assert f"package {TARGET}: 2.0-debug+abc1234 (100)" in result.output
    assert "app data: 2 file(s) backed up with checksums" in result.output
    assert (folder / "baseline.json").exists()


def test_baseline_command_exits_2_when_blocked(tmp_path, monkeypatch):
    from tests.device_state.fake_adb import FakePhone

    phone = FakePhone(devices_list=[])
    monkeypatch.setattr(cli, "SubprocessAdb", lambda serial: phone)
    result = CliRunner().invoke(
        cli.main, ["baseline", "bha.keys.smartype.debug", "--dir", str(tmp_path / "e")]
    )
    assert result.exit_code == 2
    assert "BLOCKED: no phone is connected" in result.output
