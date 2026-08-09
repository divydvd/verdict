import pytest

from verdict.assertions.base import assertion_registry


@pytest.fixture(autouse=True)
def _isolated_assertion_registry():
    """Assertions registered by a test must not leak into later tests —
    Registry.register() raises on duplicate names, so without this,
    registering the same test-only assertion name twice across test
    functions would fail.
    """
    backup = dict(assertion_registry._factories)
    try:
        yield
    finally:
        assertion_registry._factories.clear()
        assertion_registry._factories.update(backup)
