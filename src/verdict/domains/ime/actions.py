"""SmarType/IME-specific step actions. See docs/architecture.md §6.2, §3.8.

Each action is implemented purely in terms of the existing `DeviceDriver`
protocol (tap/swipe/type_text/dump_hierarchy) rather than adding new driver
methods — keeping ADR-0007's protocol surface stable while still letting a
domain bundle introduce new step vocabulary.
"""

from __future__ import annotations

from itertools import pairwise

from verdict.core.exceptions import ElementNotFoundError, VerdictError
from verdict.core.models import AssertionResult, RunContext, UiNode
from verdict.device_driver.base import DeviceDriver
from verdict.domains.ime.selectors import SUGGESTION_STRIP
from verdict.scenario_engine.runner import register_action_handler
from verdict.scenario_engine.schema import StepSpec, register_action


def _center(node: UiNode) -> tuple[int, int]:
    if node.bounds is None:
        return (0, 0)
    left, top, right, bottom = node.bounds
    return ((left + right) // 2, (top + bottom) // 2)


def _do_trigger_autocorrect(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> AssertionResult | None:
    """Commits the word currently being typed the same way a user would —
    by typing a trailing space, which is what fires SmarType's autocorrect
    (see CLAUDE.md "Autocorrect Feature" §Commit Flows).
    """
    driver.type_text(" ")
    return None


def _do_select_suggestion(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> AssertionResult | None:
    strip = driver.dump_hierarchy().find(SUGGESTION_STRIP)
    if strip is None:
        raise ElementNotFoundError("suggestion strip not visible")

    text = step.args.get("text")
    if text is not None:
        matches = [child for child in strip.children if child.text == text]
        if not matches:
            raise ElementNotFoundError(f"no suggestion with text {text!r}")
        target = matches[0]
    else:
        index = int(step.args.get("index", 0))
        if index >= len(strip.children):
            raise ElementNotFoundError(
                f"suggestion index {index} out of range ({len(strip.children)} suggestions)"
            )
        target = strip.children[index]

    x, y = _center(target)
    driver.tap(x, y)
    return None


def _do_swipe_type(driver: DeviceDriver, step: StepSpec, ctx: RunContext) -> AssertionResult | None:
    """Glide/gesture typing: decomposes a path of points into a series of
    swipes over the keyboard, reusing `DeviceDriver.swipe` for each segment.
    """
    points = step.args.get("points")
    if not points or len(points) < 2:
        raise VerdictError("swipe_type requires args.points with at least 2 [x, y] pairs")
    duration_ms = int(step.args.get("duration_ms", 300))
    for (x1, y1), (x2, y2) in pairwise(points):
        driver.swipe(int(x1), int(y1), int(x2), int(y2), duration_ms)
    return None


register_action("trigger_autocorrect")
register_action_handler("trigger_autocorrect", _do_trigger_autocorrect)

register_action("select_suggestion")
register_action_handler("select_suggestion", _do_select_suggestion)

register_action("swipe_type")
register_action_handler("swipe_type", _do_swipe_type)
