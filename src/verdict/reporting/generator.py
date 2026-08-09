"""Report Generator orchestrator. See docs/architecture.md §6.7."""

from __future__ import annotations

from pathlib import Path

from verdict.reporting.base import report_renderer_registry
from verdict.scenario_engine.runner import ScenarioResult

DEFAULT_FORMATS = ("json", "markdown", "html")


class ReportGenerator:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def generate(
        self, result: ScenarioResult, formats: tuple[str, ...] = DEFAULT_FORMATS
    ) -> dict[str, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        for name in formats:
            renderer = report_renderer_registry.get(name)
            content = renderer.render(result)
            path = self.output_dir / f"report.{renderer.extension}"
            path.write_text(content)
            paths[name] = path
        return paths
