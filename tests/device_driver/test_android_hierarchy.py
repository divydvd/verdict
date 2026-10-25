import pytest

from verdict.core.exceptions import DriverError
from verdict.device_driver.android_hierarchy import dump_with_retry, parse_hierarchy_xml

SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" content-desc=""
        bounds="[0,0][1080,2280]">
    <node index="0" text="" resource-id="com.example:id/text_field" class="android.widget.EditText"
          content-desc="" bounds="[40,100][1040,200]" />
    <node index="1" text="" resource-id="" class="android.widget.ImageView"
          content-desc="ai_suggestion_chip" bounds="[40,300][400,360]" />
  </node>
</hierarchy>
"""


def test_parse_hierarchy_xml_builds_tree():
    root = parse_hierarchy_xml(SAMPLE_XML)

    assert root is not None
    assert root.class_name == "android.widget.FrameLayout"
    assert root.bounds == (0, 0, 1080, 2280)
    assert len(root.children) == 2
    assert root.children[0].resource_id == "com.example:id/text_field"
    assert root.children[1].content_desc == "ai_suggestion_chip"
    assert root.children[1].bounds == (40, 300, 400, 360)


def test_parse_hierarchy_xml_blank_attrs_become_none():
    root = parse_hierarchy_xml(SAMPLE_XML)
    assert root is not None
    assert root.text is None
    assert root.resource_id is None


def test_parse_hierarchy_xml_empty_hierarchy_returns_none():
    root = parse_hierarchy_xml("<hierarchy rotation='0'></hierarchy>")
    assert root is None


_GOOD_XML = '<hierarchy><node resource-id="keyboard_view" bounds="[0,0][10,10]" /></hierarchy>'


class _Transient(Exception):
    pass


def _dumper(outputs):
    queue = list(outputs)

    def dump():
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return dump


def test_dump_with_retry_returns_first_good_dump_without_pause():
    sleeps: list[float] = []
    hierarchy = dump_with_retry(
        _dumper([_GOOD_XML]), attempts=3, pause_s=0.25, sleep=sleeps.append, retry_on=(_Transient,)
    )
    assert hierarchy.root is not None
    assert sleeps == []


def test_dump_with_retry_retries_error_empty_and_bad_xml():
    sleeps: list[float] = []
    hierarchy = dump_with_retry(
        _dumper([_Transient("busy"), "<hierarchy></hierarchy>", "<hierarchy", _GOOD_XML]),
        attempts=4,
        pause_s=0.25,
        sleep=sleeps.append,
        retry_on=(_Transient,),
    )
    assert hierarchy.root is not None
    assert hierarchy.root.resource_id == "keyboard_view"
    assert sleeps == [0.25, 0.25, 0.25]


def test_dump_with_retry_returns_empty_hierarchy_after_last_attempt():
    hierarchy = dump_with_retry(
        _dumper(["<hierarchy></hierarchy>"] * 2),
        attempts=2,
        pause_s=0,
        sleep=lambda _: None,
        retry_on=(_Transient,),
    )
    assert hierarchy.root is None


def test_dump_with_retry_raises_driver_error_when_every_dump_fails():
    with pytest.raises(DriverError, match="2 attempt"):
        dump_with_retry(
            _dumper([_Transient("a"), _Transient("b")]),
            attempts=2,
            pause_s=0,
            sleep=lambda _: None,
            retry_on=(_Transient,),
        )


def test_dump_with_retry_does_not_hide_unexpected_errors():
    with pytest.raises(KeyError):
        dump_with_retry(
            _dumper([KeyError("bug")]), attempts=3, pause_s=0, sleep=lambda _: None, retry_on=(_Transient,)
        )
