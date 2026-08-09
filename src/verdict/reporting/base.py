from __future__ import annotations

from typing import Protocol, runtime_checkable

from verdict.plugins.registry import Registry
from verdict.scenario_engine.runner import ScenarioResult


@runtime_checkable
class ReportRenderer(Protocol):
    """Common interface for all report renderers. See docs/architecture.md §6.7."""

    name: str
    extension: str

    def render(self, result: ScenarioResult) -> str: ...


report_renderer_registry: Registry[ReportRenderer] = Registry(kind="report renderer")
