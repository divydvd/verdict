import pytest

from verdict.core.exceptions import VerdictError
from verdict.core.models import UiNode
from verdict.device_driver.fake import FakeDeviceDriver
from verdict.evidence.collector import EvidenceCollector


def test_capture_screenshot(tmp_path):
    driver = FakeDeviceDriver()
    collector = EvidenceCollector(driver, tmp_path)

    ref = collector.capture("screenshot", seq=0)

    assert ref is not None
    assert ref.kind == "screenshot"
    assert ref.path.exists()


def test_capture_hierarchy_writes_xml_file(tmp_path):
    driver = FakeDeviceDriver()
    driver.set_hierarchy(UiNode(text="hi"))
    collector = EvidenceCollector(driver, tmp_path)

    ref = collector.capture("hierarchy", seq=3)

    assert ref is not None
    assert ref.path == tmp_path / "hierarchy-3.xml"
    assert ref.path.read_text() == "<fake/>"


def test_capture_logcat(tmp_path):
    driver = FakeDeviceDriver()
    collector = EvidenceCollector(driver, tmp_path)

    ref = collector.capture("logcat", seq=0)

    assert ref is not None
    assert ref.kind == "logcat"
    assert ref.path.exists()


def test_capture_bugreport_none_when_driver_returns_none(tmp_path):
    class _NoBugreportDriver(FakeDeviceDriver):
        def collect_bugreport(self):
            return None

    collector = EvidenceCollector(_NoBugreportDriver(), tmp_path)

    assert collector.capture("bugreport", seq=0) is None


def test_capture_unknown_kind_raises(tmp_path):
    driver = FakeDeviceDriver()
    collector = EvidenceCollector(driver, tmp_path)

    with pytest.raises(VerdictError, match="Unknown evidence kind"):
        collector.capture("video", seq=0)


def test_capture_all_skips_none_results(tmp_path):
    class _NoBugreportDriver(FakeDeviceDriver):
        def collect_bugreport(self):
            return None

    collector = EvidenceCollector(_NoBugreportDriver(), tmp_path)

    refs = collector.capture_all(["screenshot", "bugreport"], seq=0)

    assert [ref.kind for ref in refs] == ["screenshot"]
