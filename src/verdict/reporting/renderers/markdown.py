"""Markdown report renderer. See docs/architecture.md §6.7."""

from __future__ import annotations

from verdict.core.models import TimelineEvent
from verdict.reporting.base import report_renderer_registry
from verdict.scenario_engine.runner import ScenarioResult


def _render_event(event: TimelineEvent) -> list[str]:
    status = "PASS" if event.passed else "FAIL"
    lines = [f"### [{status}] `{event.step_id}` — {event.action}"]
    if event.error:
        lines.append(f"- **Error:** {event.error}")
    for assertion_result in event.assertion_results:
        mark = "PASS" if assertion_result.passed else "FAIL"
        lines.append(f"- [{mark}] {assertion_result.message}")
    if event.evidence_refs:
        lines.append("- **Evidence:**")
        for ref in event.evidence_refs:
            lines.append(f"  - {ref.kind}: `{ref.path}`")
    lines.append("")
    return lines


class MarkdownRenderer:
    name = "markdown"
    extension = "md"

    def render(self, result: ScenarioResult) -> str:
        timeline = result.timeline
        lines = [
            f"# Scenario: {timeline.scenario_name}",
            "",
            f"**Result:** {'PASSED' if result.passed else 'FAILED'}",
            f"**Attempts:** {result.attempts}",
            f"**Run ID:** {timeline.run_id}",
            "",
            "## Steps",
            "",
        ]
        for event in timeline.events:
            lines.extend(_render_event(event))
        return "\n".join(lines)


report_renderer_registry.register("markdown", lambda: MarkdownRenderer())
