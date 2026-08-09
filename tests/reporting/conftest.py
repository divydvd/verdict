from datetime import UTC, datetime
from pathlib import Path

import pytest

from verdict.core.models import AssertionResult, EvidenceRef, Timeline, TimelineEvent
from verdict.scenario_engine.runner import ScenarioResult


@pytest.fixture
def fixed_result() -> ScenarioResult:
    timeline = Timeline(
        run_id="run-fixed-1",
        scenario_name="typo_correction",
        events=[
            TimelineEvent(
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                step_id="0:tap",
                action="tap",
                passed=True,
                evidence_refs=[
                    EvidenceRef(kind="screenshot", path=Path("/evidence/0-screenshot.png"))
                ],
            ),
            TimelineEvent(
                timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
                step_id="1:assert",
                action="assert",
                passed=False,
                error="autocorrect not applied",
                assertion_results=[
                    AssertionResult(passed=False, message="autocorrect not applied")
                ],
                evidence_refs=[
                    EvidenceRef(kind="hierarchy", path=Path("/evidence/1-hierarchy.xml"))
                ],
            ),
        ],
    )
    return ScenarioResult(passed=False, attempts=2, timeline=timeline)
