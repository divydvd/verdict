"""A small `adb` subprocess wrapper for the device-state commands (baseline, restore).

These commands copy files and pipe binary data (APKs, tar backups), so they call the
`adb` binary directly. They map 1:1 onto the adb steps of a manual device test.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

from verdict.core.exceptions import DriverError


class AdbError(DriverError):
    """An adb command failed or timed out."""


class Adb(Protocol):
    def devices(self) -> list[tuple[str, str]]: ...

    def shell(self, command: str) -> str: ...

    def exec_out_to_file(self, command: str, path: Path) -> None: ...

    def pull(self, remote: str, local: Path) -> None: ...

    def push(self, local: Path, remote: str) -> None: ...

    def install(self, apk: Path) -> None: ...

    def uninstall(self, package: str) -> None: ...


@dataclass
class SubprocessAdb:
    serial: str | None = None
    adb_path: str = "adb"
    timeout_s: float = 300.0

    def _run(
        self,
        args: list[str],
        stdout: IO[bytes] | None = None,
        use_serial: bool = True,
    ) -> str:
        prefix = [self.adb_path]
        if use_serial and self.serial:
            prefix += ["-s", self.serial]
        try:
            proc = subprocess.run(
                prefix + args,
                stdout=stdout if stdout is not None else subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdbError(f"`adb {args[0]}` failed: {exc}") from exc
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace").strip()
            raise AdbError(f"`adb {' '.join(args)}` exited {proc.returncode}: {stderr}")
        return "" if stdout is not None else proc.stdout.decode(errors="replace")

    def devices(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for line in self._run(["devices"], use_serial=False).splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                found.append((parts[0], parts[1]))
        return found

    def shell(self, command: str) -> str:
        return self._run(["shell", command])

    def exec_out_to_file(self, command: str, path: Path) -> None:
        with path.open("wb") as handle:
            self._run(["exec-out", command], stdout=handle)

    def pull(self, remote: str, local: Path) -> None:
        self._run(["pull", remote, str(local)])

    def push(self, local: Path, remote: str) -> None:
        self._run(["push", str(local), remote])

    def install(self, apk: Path) -> None:
        if "Success" not in self._run(["install", "-r", str(apk)]):
            raise AdbError(f"`adb install -r {apk.name}` did not report Success")

    def uninstall(self, package: str) -> None:
        if "Success" not in self._run(["uninstall", package]):
            raise AdbError(f"`adb uninstall {package}` did not report Success")
