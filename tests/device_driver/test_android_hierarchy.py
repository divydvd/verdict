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


# The shape of a real uiautomator2 dump: one top-level node for each window.
# The IME window is last, so a parser that keeps only the first window (the
# status bar) cannot find the keyboard or the app's text field.
MULTI_WINDOW_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
        package="com.android.systemui" content-desc="" bounds="[0,0][1080,80]">
    <node index="0" text="" resource-id="com.android.systemui:id/status_bar"
          class="android.widget.FrameLayout" content-desc="" bounds="[0,0][1080,80]" />
  </node>
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
        package="bha.keys.smartype.debug" content-desc="" bounds="[0,0][1080,2340]">
    <node index="0" text="helllo" resource-id="text_field" class="android.widget.EditText"
          content-desc="" bounds="[40,400][1040,520]" />
  </node>
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
        package="com.android.systemui" content-desc="" bounds="[0,2205][1080,2340]" />
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout"
        package="bha.keys.smartype.debug" content-desc="" bounds="[0,1301][1080,2340]">
    <node index="0" text="" resource-id="keyboard_view" class="android.view.View"
          content-desc="" bounds="[0,1301][1080,2205]" />
  </node>
</hierarchy>
"""


def test_parse_hierarchy_xml_keeps_every_window():
    root = parse_hierarchy_xml(MULTI_WINDOW_XML)

    assert root is not None
    assert root.class_name == "hierarchy"
    assert root.resource_id is None and root.bounds is None
    assert [window.bounds for window in root.children] == [
        (0, 0, 1080, 80),
        (0, 0, 1080, 2340),
        (0, 2205, 1080, 2340),
        (0, 1301, 1080, 2340),
    ]


def test_ime_and_app_lookups_work_on_a_multi_window_dump():
    from verdict.core.models import RunContext
    from verdict.device_driver.fake import FakeDeviceDriver
    from verdict.domains.ime.assertions import KeyboardVisibleAssertion, TextInsertedAssertion

    driver = FakeDeviceDriver()
    driver.set_hierarchy(parse_hierarchy_xml(MULTI_WINDOW_XML))
    ctx = RunContext(
        session_id="s1",
        run_id="r1",
        scenario_name="scenario",
        driver=driver,
        evidence_dir=driver.evidence_dir,
    )

    assert KeyboardVisibleAssertion().check(ctx).passed
    assert TextInsertedAssertion("helllo").check(ctx).passed


class _DroppedU2Device:
    """A u2 device whose server connection is lost: every dump fails."""

    class _Adb:
        def shell(self, command: str) -> str:
            return ""

    adb_device = _Adb()

    def stop_uiautomator(self, wait: bool = True) -> None:
        pass

    def start_uiautomator(self) -> None:
        pass

    def dump_hierarchy(self) -> str:
        import uiautomator2 as u2

        raise u2.exceptions.HTTPError("connection lost")


def test_android_dump_keeps_a_connection_error_after_the_retries(monkeypatch, tmp_path):
    import uiautomator2 as u2

    import verdict.device_driver.android as android_module

    monkeypatch.setattr(android_module.u2, "connect", lambda *args: _DroppedU2Device())
    driver = android_module.AndroidUiautomator2Driver(evidence_dir=tmp_path, sleep=lambda _: None)
    with pytest.raises(u2.exceptions.HTTPError):
        driver.dump_hierarchy()
