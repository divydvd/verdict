"""HTML report renderer — embeds screenshot/video evidence inline.
See docs/architecture.md §6.7.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from verdict.reporting.base import report_renderer_registry
from verdict.scenario_engine.runner import ScenarioResult

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)


class HtmlRenderer:
    name = "html"
    extension = "html"

    def render(self, result: ScenarioResult) -> str:
        template = _env.get_template("report.html.j2")
        return template.render(result=result, timeline=result.timeline)


report_renderer_registry.register("html", lambda: HtmlRenderer())
