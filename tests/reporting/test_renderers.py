from pathlib import Path

from verdict.reporting.renderers.html import HtmlRenderer
from verdict.reporting.renderers.json import JsonRenderer
from verdict.reporting.renderers.markdown import MarkdownRenderer
from verdict.scenario_engine.runner import ScenarioResult

GOLDEN_DIR = Path(__file__).parent / "golden"


def _golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text()


def test_json_renderer_matches_golden(fixed_result: ScenarioResult):
    assert JsonRenderer().render(fixed_result) + "\n" == _golden("report.json")


def test_markdown_renderer_matches_golden(fixed_result: ScenarioResult):
    assert MarkdownRenderer().render(fixed_result) + "\n" == _golden("report.md")


def test_html_renderer_matches_golden(fixed_result: ScenarioResult):
    assert HtmlRenderer().render(fixed_result) + "\n" == _golden("report.html")


def test_markdown_renderer_omits_error_line_when_passed(fixed_result: ScenarioResult):
    rendered = MarkdownRenderer().render(fixed_result)
    passed_step_section = rendered.split("### [FAIL]")[0]
    assert "**Error:**" not in passed_step_section


def test_html_renderer_uses_video_tag_for_recording_evidence():
    from datetime import UTC, datetime

    from verdict.core.models import EvidenceRef, Timeline, TimelineEvent

    timeline = Timeline(
        run_id="r",
        scenario_name="s",
        events=[
            TimelineEvent(
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                step_id="0:tap",
                action="tap",
                passed=True,
                evidence_refs=[EvidenceRef(kind="recording", path=Path("/evidence/0.mp4"))],
            )
        ],
    )
    result = ScenarioResult(passed=True, attempts=1, timeline=timeline)
    rendered = HtmlRenderer().render(result)
    assert '<video src="/evidence/0.mp4" controls></video>' in rendered
