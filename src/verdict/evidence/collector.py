from __future__ import annotations

from pathlib import Path

from verdict.core.exceptions import VerdictError
from verdict.core.models import EvidenceRef
from verdict.device_driver.base import DeviceDriver


class EvidenceCollector:
    """Captures evidence artifacts from a `DeviceDriver` and correlates
    them under a per-run evidence directory. Called by the Scenario
    Engine runner at step boundaries and on failure (§6.4).
    """

    def __init__(self, driver: DeviceDriver, evidence_dir: Path) -> None:
        self._driver = driver
        self._evidence_dir = evidence_dir

    def capture(self, kind: str, seq: int) -> EvidenceRef | None:
        if kind == "screenshot":
            return EvidenceRef(kind=kind, path=self._driver.screenshot())
        if kind == "hierarchy":
            hierarchy = self._driver.dump_hierarchy()
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self._evidence_dir / f"hierarchy-{seq}.xml"
            path.write_text(hierarchy.raw_xml)
            return EvidenceRef(kind=kind, path=path)
        if kind == "logcat":
            return EvidenceRef(kind=kind, path=self._driver.collect_logs())
        if kind == "bugreport":
            bugreport_path = self._driver.collect_bugreport()
            return EvidenceRef(kind=kind, path=bugreport_path) if bugreport_path is not None else None
        raise VerdictError(f"Unknown evidence kind '{kind}'")

    def capture_all(self, kinds: list[str], seq: int) -> list[EvidenceRef]:
        refs: list[EvidenceRef] = []
        for kind in kinds:
            ref = self.capture(kind, seq)
            if ref is not None:
                refs.append(ref)
        return refs
