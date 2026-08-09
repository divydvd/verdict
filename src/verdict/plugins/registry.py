from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """Name -> factory registry for one plugin capability (drivers,
    assertions, report renderers, LLM providers, evidence collectors,
    performance collectors). See docs/architecture.md §7.

    Built-ins register themselves at import time. External plugins
    register via the `verdict.plugins` importlib.metadata entry-point
    group (wired up in Phase 2+ once there's a second real plugin to
    discover) — no custom plugin-loading protocol invented.
    """

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._factories: dict[str, Callable[..., T]] = {}

    def register(self, name: str, factory: Callable[..., T]) -> None:
        if name in self._factories:
            raise ValueError(f"{self._kind} '{name}' is already registered")
        self._factories[name] = factory

    def get(self, name: str, *args: object, **kwargs: object) -> T:
        try:
            factory = self._factories[name]
        except KeyError:
            available = ", ".join(sorted(self._factories)) or "(none registered)"
            raise KeyError(f"No {self._kind} registered as '{name}'. Available: {available}") from None
        return factory(*args, **kwargs)

    def list(self) -> list[str]:
        return sorted(self._factories)
