import json

from verdict.reporting.generator import ReportGenerator
from verdict.scenario_engine.runner import ScenarioResult


def test_generate_writes_one_file_per_format(tmp_path, fixed_result: ScenarioResult):
    generator = ReportGenerator(tmp_path)

    paths = generator.generate(fixed_result)

    assert set(paths) == {"json", "markdown", "html"}
    assert paths["json"] == tmp_path / "report.json"
    assert paths["markdown"] == tmp_path / "report.md"
    assert paths["html"] == tmp_path / "report.html"
    for path in paths.values():
        assert path.exists()


def test_generate_json_output_is_valid_json(tmp_path, fixed_result: ScenarioResult):
    generator = ReportGenerator(tmp_path)

    paths = generator.generate(fixed_result, formats=("json",))

    data = json.loads(paths["json"].read_text())
    assert data["passed"] is False
    assert data["timeline"]["scenario_name"] == "typo_correction"


def test_generate_respects_requested_formats_subset(tmp_path, fixed_result: ScenarioResult):
    generator = ReportGenerator(tmp_path)

    paths = generator.generate(fixed_result, formats=("markdown",))

    assert set(paths) == {"markdown"}
    assert not (tmp_path / "report.json").exists()
