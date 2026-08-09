"""JSON report renderer — for CI ingestion / further agent processing.
See docs/architecture.md §6.7.
"""

from __future__ import annotations

from verdict.reporting.base import report_renderer_registry
from verdict.scenario_engine.runner import ScenarioResult


class JsonRenderer:
    name = "json"
    extension = "json"

    def render(self, result: ScenarioResult) -> str:
        return result.model_dump_json(indent=2)


report_renderer_registry.register("json", lambda: JsonRenderer())
