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


def _baseline_and_test(tmp_path):
    from tests.device_state.fake_adb import PLAY, TARGET, FakePhone
    from verdict.device_state.baseline import prepare_private_folder, take_baseline

    phone = FakePhone()
    folder = prepare_private_folder(tmp_path / "ev")
    take_baseline(phone, TARGET, PLAY, folder)
    phone.run_candidate_test(code=100)
    return phone, folder


def test_restore_command_prints_table_and_deletes_backups(tmp_path, monkeypatch):
    phone, folder = _baseline_and_test(tmp_path)
    monkeypatch.setattr(cli, "SubprocessAdb", lambda serial: phone)
    result = CliRunner().invoke(
        cli.main, ["restore", "bha.keys.smartype.debug", "--dir", str(folder), "--result", "FAIL"]
    )
    assert result.exit_code == 0, result.output
    assert "| item | baseline | final | equal |" in result.output
    assert "| font_scale | 1.0 | 1.0 | yes |" in result.output
    assert "backups deleted" in result.output
    assert not (folder / "app-data.tar").exists()
    assert (folder / "baseline.json").exists()


def test_restore_command_exits_1_and_keeps_backups_on_a_difference(tmp_path, monkeypatch):
    phone, folder = _baseline_and_test(tmp_path)
    phone.builds[b"pretest-apk"] = (100, "something-else")
    monkeypatch.setattr(cli, "SubprocessAdb", lambda serial: phone)
    result = CliRunner().invoke(
        cli.main, ["restore", "bha.keys.smartype.debug", "--dir", str(folder), "--result", "FAIL"]
    )
    assert result.exit_code == 1, result.output
    assert "| no |" in result.output
    assert (folder / "app-data.tar").exists()


def test_restore_command_blocks_when_adb_fails(tmp_path, monkeypatch):
    phone, folder = _baseline_and_test(tmp_path)
    phone.fail_on = {"tar -xf"}
    monkeypatch.setattr(cli, "SubprocessAdb", lambda serial: phone)
    result = CliRunner().invoke(
        cli.main, ["restore", "bha.keys.smartype.debug", "--dir", str(folder), "--result", "PASS"]
    )
    assert result.exit_code == 2
    assert "BLOCKED: the restore stopped" in result.output


def test_restore_command_reports_apk_probe_failure_and_keeps_backups(tmp_path, monkeypatch):
    from verdict.device_state.adb import AdbError

    phone, folder = _baseline_and_test(tmp_path)
    original_pull = phone.pull
    pulls = 0

    def interrupted_pull(remote, local):
        nonlocal pulls
        pulls += 1
        if pulls == 1:
            local.write_bytes(b"partial")
            raise AdbError("APK read interrupted")
        original_pull(remote, local)

    monkeypatch.setattr(phone, "pull", interrupted_pull)
    monkeypatch.setattr(cli, "SubprocessAdb", lambda serial: phone)
    result = CliRunner().invoke(
        cli.main, ["restore", "bha.keys.smartype.debug", "--dir", str(folder), "--result", "FAIL"]
    )
    assert result.exit_code == 2, result.output
    assert "BLOCKED: the restore stopped" in result.output
    assert "APK read interrupted" in result.output
    assert not any(c.startswith("install") or "tar -xf" in c for c in phone.commands)
    assert (folder / "app-data.tar").exists() and (folder / "pretest.apk").exists()
    assert not (folder / "final-check.apk").exists()


def test_restore_command_blocks_when_adb_fails_in_the_preflight(tmp_path, monkeypatch):
    from verdict.device_state.adb import AdbError

    phone, folder = _baseline_and_test(tmp_path)

    def broken_devices():
        raise AdbError("`adb devices` failed: no server")

    phone.devices = broken_devices
    monkeypatch.setattr(cli, "SubprocessAdb", lambda serial: phone)
    result = CliRunner().invoke(
        cli.main, ["restore", "bha.keys.smartype.debug", "--dir", str(folder), "--result", "FAIL"]
    )
    assert result.exit_code == 2, result.output
    assert "BLOCKED: the preflight check failed" in result.output


def test_run_command_reports_blocked_when_the_device_connection_drops(tmp_path, monkeypatch):
    # verdict#10: a dead uiautomator2 server gives RemoteDisconnected.
    import http.client

    class _DroppingDriver(FakeDeviceDriver):
        def wait_for(self, selector, timeout_ms=5000):
            raise http.client.RemoteDisconnected("Remote end closed connection without response")

    scenario_path = _write_scenario(
        tmp_path,
        steps=[{"action": "wait_for", "selector": {"description": "x"}, "timeout_ms": 10}],
    )
    monkeypatch.setattr(cli, "AndroidUiautomator2Driver", lambda serial=None: _DroppingDriver())

    result = CliRunner().invoke(cli.main, ["run", str(scenario_path), "--output-dir", str(tmp_path / "out")])

    assert result.exit_code == 2
    assert "BLOCKED" in result.output
    assert "RemoteDisconnected" in result.output
    assert not isinstance(result.exception, http.client.RemoteDisconnected)


def test_run_command_writes_the_report_when_a_hierarchy_assertion_is_blocked(tmp_path, monkeypatch):
    # A lost connection during the dump of a hierarchy assertion is BLOCKED, and
    # the report keeps the steps that ran before it.
    import json

    import uiautomator2 as u2

    class _DroppingDriver(FakeDeviceDriver):
        def dump_hierarchy(self):
            raise u2.exceptions.HTTPError("connection lost")

    driver = _DroppingDriver()
    driver.set_hierarchy(UiNode(resource_id="text_field"))
    scenario_path = _write_scenario(
        tmp_path,
        steps=[
            {"action": "launch", "package": "bha.keys.smartype.debug"},
            {"action": "assert", "assertion": "keyboard_visible"},
        ],
    )
    monkeypatch.setattr(cli, "AndroidUiautomator2Driver", lambda serial=None: driver)
    out = tmp_path / "out"

    result = CliRunner().invoke(cli.main, ["run", str(scenario_path), "--output-dir", str(out)])

    assert result.exit_code == 2, result.output
    assert "cli-scenario: BLOCKED (1 attempt(s))" in result.output
    report = json.loads((out / "report.json").read_text())
    assert report["blocked"] is True
    events = report["timeline"]["events"]
    assert [event["passed"] for event in events] == [True, False]
    assert events[1]["error"].startswith("BLOCKED: the device connection failed: HTTPError")
    assert "**Result:** BLOCKED" in (out / "report.md").read_text()
