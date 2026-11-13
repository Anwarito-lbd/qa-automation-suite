"""ADB device-health, package-smoke, memory, and logcat diagnostic harness."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from sut.mobile_bridge import DeterministicMobileBridge

FATAL_LOGCAT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"FATAL EXCEPTION", re.IGNORECASE),
    re.compile(r"ANR in\s+", re.IGNORECASE),
    re.compile(r"Process .* has died", re.IGNORECASE),
    re.compile(r"StrictMode policy violation", re.IGNORECASE),
)


@dataclass(frozen=True)
class AdbHealthReport:
    """Structured device health & smoke check telemetry."""

    device_state: str
    sdk_version: int
    device_model: str
    package_installed: bool
    cold_start_ms: int
    total_pss_kb: int
    fatal_logcat_lines: tuple[str, ...]


class AdbBridge:
    """Executes ADB diagnostics against either a real emulator or DeterministicMobileBridge."""

    def __init__(
        self,
        *,
        mode: str = "mock",
        device_serial: str = "emulator-5554",
        mock_bridge: DeterministicMobileBridge | None = None,
    ) -> None:
        self._mode = mode
        self._device_serial = device_serial
        self._mock_bridge = mock_bridge

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        if self._mode == "mock":
            if self._mock_bridge is None:
                raise RuntimeError("mock_bridge is required when mode='mock'")
            return self._mock_bridge.adb_command(args)

        cmd = ["adb", "-s", self._device_serial, *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        return proc.returncode, proc.stdout, proc.stderr

    def get_device_state(self) -> str:
        code, out, err = self._run(["get-state"])
        if code != 0:
            raise RuntimeError(f"adb get-state failed: {err.strip()}")
        return out.strip()

    def get_sdk_version(self) -> int:
        code, out, err = self._run(["shell", "getprop", "ro.build.version.sdk"])
        if code != 0:
            raise RuntimeError(f"adb getprop sdk failed: {err.strip()}")
        return int(out.strip())

    def get_device_model(self) -> str:
        code, out, err = self._run(["shell", "getprop", "ro.product.model"])
        if code != 0:
            raise RuntimeError(f"adb getprop model failed: {err.strip()}")
        return out.strip()

    def is_package_installed(self, package: str) -> bool:
        code, out, _ = self._run(["shell", "pm", "list", "packages", package])
        if code != 0:
            return False
        return f"package:{package}" in out

    def cold_start_activity(self, package: str, activity: str) -> int:
        code, out, err = self._run(["shell", "am", "start", "-W", "-n", f"{package}/{activity}"])
        if code != 0:
            raise RuntimeError(f"adb am start failed: {err.strip()}")
        match = re.search(r"TotalTime:\s*(\d+)", out)
        if not match:
            raise RuntimeError(f"Could not parse TotalTime from am start output:\n{out}")
        return int(match.group(1))

    def get_meminfo_pss_kb(self, package: str) -> int:
        code, out, err = self._run(["shell", "dumpsys", "meminfo", package])
        if code != 0:
            raise RuntimeError(f"adb dumpsys meminfo failed: {err.strip()}")
        match = re.search(r"TOTAL PSS:\s*(\d+)", out)
        if not match:
            raise RuntimeError(f"Could not parse TOTAL PSS from dumpsys meminfo:\n{out}")
        return int(match.group(1))

    def scan_logcat_for_fatal_errors(self) -> tuple[str, ...]:
        code, out, err = self._run(["logcat", "-d", "-v", "threadtime"])
        if code != 0:
            raise RuntimeError(f"adb logcat failed: {err.strip()}")
        hits: list[str] = []
        for line in out.splitlines():
            if any(pattern.search(line) for pattern in FATAL_LOGCAT_PATTERNS):
                hits.append(line)
        return tuple(hits)

    def collect_health_report(self, *, package: str, activity: str) -> AdbHealthReport:
        return AdbHealthReport(
            device_state=self.get_device_state(),
            sdk_version=self.get_sdk_version(),
            device_model=self.get_device_model(),
            package_installed=self.is_package_installed(package),
            cold_start_ms=self.cold_start_activity(package, activity),
            total_pss_kb=self.get_meminfo_pss_kb(package),
            fatal_logcat_lines=self.scan_logcat_for_fatal_errors(),
        )
