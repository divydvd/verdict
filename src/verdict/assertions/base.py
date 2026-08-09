from __future__ import annotations

from typing import Protocol, runtime_checkable

from verdict.core.models import AssertionResult, RunContext
from verdict.plugins.registry import Registry


@runtime_checkable
class Assertion(Protocol):
    """Common interface for all assertions, generic and `domains/ime`
    alike. See docs/architecture.md §6.3.
    """

    name: str

    def check(self, ctx: RunContext) -> AssertionResult: ...


assertion_registry: Registry[Assertion] = Registry(kind="assertion")
