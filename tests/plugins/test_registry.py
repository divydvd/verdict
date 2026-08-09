import pytest

from verdict.plugins.registry import Registry


def test_register_and_get():
    registry: Registry[str] = Registry(kind="widget")
    registry.register("greeting", lambda name: f"hello {name}")
    assert registry.get("greeting", "world") == "hello world"


def test_register_duplicate_name_raises():
    registry: Registry[int] = Registry(kind="widget")
    registry.register("one", lambda: 1)
    with pytest.raises(ValueError):
        registry.register("one", lambda: 2)


def test_get_unknown_name_raises_with_available_list():
    registry: Registry[int] = Registry(kind="widget")
    registry.register("one", lambda: 1)
    with pytest.raises(KeyError, match="one"):
        registry.get("missing")


def test_list_returns_sorted_names():
    registry: Registry[int] = Registry(kind="widget")
    registry.register("zeta", lambda: 1)
    registry.register("alpha", lambda: 2)
    assert registry.list() == ["alpha", "zeta"]
