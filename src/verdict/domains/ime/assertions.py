"""SmarType/IME-specific assertions. See docs/architecture.md §6.3, §3.8."""

from __future__ import annotations

from verdict.assertions.base import assertion_registry
from verdict.core.models import AssertionResult, RunContext, UiNode
from verdict.domains.ime.selectors import (
    AI_SUGGESTION_CHIP,
    CLIPBOARD_SUGGESTION_CHIP,
    KEYBOARD_ROOT,
    LANGUAGE_SWITCH_KEY,
    SUGGESTION_STRIP,
    TEXT_FIELD,
    THEME_INDICATOR,
)


def _all_nodes(root: UiNode | None) -> list[UiNode]:
    if root is None:
        return []
    nodes = [root]
    for child in root.children:
        nodes.extend(_all_nodes(child))
    return nodes


class KeyboardVisibleAssertion:
    name = "keyboard_visible"

    def check(self, ctx: RunContext) -> AssertionResult:
        found = ctx.driver.dump_hierarchy().find(KEYBOARD_ROOT) is not None
        return AssertionResult(
            passed=found, message="keyboard visible" if found else "keyboard not visible"
        )


class AiSuggestionVisibleAssertion:
    name = "ai_suggestion_visible"

    def check(self, ctx: RunContext) -> AssertionResult:
        found = ctx.driver.dump_hierarchy().find(AI_SUGGESTION_CHIP) is not None
        return AssertionResult(
            passed=found,
            message="AI suggestion chip visible" if found else "AI suggestion chip not visible",
        )


class TextInsertedAssertion:
    name = "text_inserted"

    def __init__(self, text: str) -> None:
        self.text = text

    def check(self, ctx: RunContext) -> AssertionResult:
        actual = ctx.driver.get_text(TEXT_FIELD)
        passed = actual is not None and self.text in actual
        return AssertionResult(
            passed=passed, message=f"text field contains {self.text!r} (actual: {actual!r})"
        )


class ClipboardUpdatedAssertion:
    name = "clipboard_updated"

    def __init__(self, text: str) -> None:
        self.text = text

    def check(self, ctx: RunContext) -> AssertionResult:
        node = ctx.driver.dump_hierarchy().find(CLIPBOARD_SUGGESTION_CHIP)
        actual = node.text if node is not None else None
        passed = actual is not None and self.text in actual
        return AssertionResult(
            passed=passed,
            message=f"clipboard suggestion shows {self.text!r} (actual: {actual!r})",
        )


class AutocorrectAppliedAssertion:
    name = "autocorrect_applied"

    def __init__(self, corrected: str, original: str | None = None) -> None:
        self.corrected = corrected
        self.original = original

    def check(self, ctx: RunContext) -> AssertionResult:
        actual = ctx.driver.get_text(TEXT_FIELD)
        if actual is None:
            return AssertionResult(passed=False, message="text field not found")
        applied = self.corrected in actual
        regressed = self.original is not None and self.original in actual
        passed = applied and not regressed
        return AssertionResult(
            passed=passed,
            message=f"text field contains corrected {self.corrected!r} (actual: {actual!r})",
        )


class SuggestionContainsAssertion:
    name = "suggestion_contains"

    def __init__(self, text: str) -> None:
        self.text = text

    def check(self, ctx: RunContext) -> AssertionResult:
        strip = ctx.driver.dump_hierarchy().find(SUGGESTION_STRIP)
        candidates = [node.text for node in _all_nodes(strip) if node.text]
        passed = any(self.text in candidate for candidate in candidates)
        return AssertionResult(
            passed=passed,
            message=f"suggestion strip contains {self.text!r} (candidates: {candidates!r})",
        )


class ClipboardSuggestionShownAssertion:
    name = "clipboard_suggestion_shown"

    def check(self, ctx: RunContext) -> AssertionResult:
        found = ctx.driver.dump_hierarchy().find(CLIPBOARD_SUGGESTION_CHIP) is not None
        return AssertionResult(
            passed=found,
            message="clipboard suggestion shown" if found else "clipboard suggestion not shown",
        )


class ThemeMatchesAssertion:
    name = "theme_matches"

    def __init__(self, theme: str) -> None:
        self.theme = theme

    def check(self, ctx: RunContext) -> AssertionResult:
        node = ctx.driver.dump_hierarchy().find(THEME_INDICATOR)
        actual = node.text if node is not None else None
        passed = actual == self.theme
        return AssertionResult(
            passed=passed, message=f"active theme is {self.theme!r} (actual: {actual!r})"
        )


class LanguageSwitchedAssertion:
    name = "language_switched"

    def __init__(self, language: str) -> None:
        self.language = language

    def check(self, ctx: RunContext) -> AssertionResult:
        node = ctx.driver.dump_hierarchy().find(LANGUAGE_SWITCH_KEY)
        actual = node.text if node is not None else None
        passed = actual == self.language
        return AssertionResult(
            passed=passed, message=f"active language is {self.language!r} (actual: {actual!r})"
        )


assertion_registry.register("keyboard_visible", lambda: KeyboardVisibleAssertion())
assertion_registry.register("ai_suggestion_visible", lambda: AiSuggestionVisibleAssertion())
assertion_registry.register("text_inserted", lambda text: TextInsertedAssertion(text))
assertion_registry.register("clipboard_updated", lambda text: ClipboardUpdatedAssertion(text))
assertion_registry.register(
    "autocorrect_applied",
    lambda corrected, original=None: AutocorrectAppliedAssertion(corrected, original),
)
assertion_registry.register("suggestion_contains", lambda text: SuggestionContainsAssertion(text))
assertion_registry.register(
    "clipboard_suggestion_shown", lambda: ClipboardSuggestionShownAssertion()
)
assertion_registry.register("theme_matches", lambda theme: ThemeMatchesAssertion(theme))
assertion_registry.register("language_switched", lambda language: LanguageSwitchedAssertion(language))
