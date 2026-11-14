"""Unreal Engine Gauntlet CLI command builder and UE5 automation/FPS log parser.

Note: Runs deterministically against UE5 automation log streams without requiring a
local 50 GB Unreal Engine editor installation in CI. When `UE_ROOT` is configured,
`build_gauntlet_command` emits the exact `RunUAT` / `RunUnreal` invocation for
self-hosted Unreal build agents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TEST_COMPLETED_RE = re.compile(
    r"LogAutomationController:.*Test Completed\. Result=\{(?P<result>Passed|Failed)\} "
    r"Name=\{(?P<name>[^}]+)\} Path=\{(?P<path>[^}]+)\}"
)
FPS_CHART_RE = re.compile(
    r"LogFPSChart:.*AvgFPS=(?P<avg_fps>\d+(?:\.\d+)?)\s+"
    r"P95FrameTimeMs=(?P<p95_ms>\d+(?:\.\d+)?)\s+"
    r"PeakMemoryMB=(?P<peak_mb>\d+(?:\.\d+)?)"
)
ENSURE_RE = re.compile(r"LogOutputDevice: Error:\s*Ensure condition failed:.*", re.IGNORECASE)
FATAL_RE = re.compile(r"(Fatal error:|Unhandled Exception:).*", re.IGNORECASE)


@dataclass(frozen=True)
class GauntletConfig:
    """Configuration for launching an Unreal Engine Gauntlet automation run."""

    ue_root: str
    uproject_path: str
    platform: str = "Win64"
    configuration: str = "Development"
    test_suite: str = "AegisGauntletTest"
    automation_filter: str = "AegisPay.Smoke"
    null_rhi: bool = True
    log_path: str = "reports/unreal-gauntlet.log"
    artifact_dir: str = "reports/unreal-artifacts"


@dataclass(frozen=True)
class UnrealPerformanceBudget:
    """Frame-time, FPS, and memory regression thresholds for UE5 QA gates."""

    min_avg_fps: float = 55.0
    max_p95_frame_time_ms: float = 18.0
    max_peak_memory_mb: float = 4096.0


@dataclass(frozen=True)
class UnrealTestResult:
    """Single Unreal Automation Controller test outcome."""

    name: str
    test_path: str
    passed: bool


@dataclass(frozen=True)
class UnrealTelemetryReport:
    """Parsed UE5 automation test results, crash/ensure diagnostics, and FPS metrics."""

    tests: tuple[UnrealTestResult, ...]
    avg_fps: float | None
    p95_frame_time_ms: float | None
    peak_memory_mb: float | None
    ensure_failures: tuple[str, ...]
    fatal_errors: tuple[str, ...]
    budget_violations: tuple[str, ...]

    @property
    def is_healthy(self) -> bool:
        return (
            bool(self.tests)
            and all(t.passed for t in self.tests)
            and not self.ensure_failures
            and not self.fatal_errors
            and not self.budget_violations
        )


def build_gauntlet_command(cfg: GauntletConfig) -> list[str]:
    """Build the Unreal AutomationTool (RunUAT) Gauntlet execution command."""
    uat_exe = (
        f"{cfg.ue_root}/Engine/Build/BatchFiles/RunUAT.bat"
        if cfg.platform.startswith("Win")
        else f"{cfg.ue_root}/Engine/Build/BatchFiles/RunUAT.sh"
    )
    cmd = [
        uat_exe,
        "RunUnreal",
        f"-project={cfg.uproject_path}",
        f"-platform={cfg.platform}",
        f"-configuration={cfg.configuration}",
        f"-test={cfg.test_suite}",
        f"-runtest={cfg.automation_filter}",
        "-unattended",
        "-nop4",
        f"-log={cfg.log_path}",
        f"-artifactoutput={cfg.artifact_dir}",
    ]
    if cfg.null_rhi:
        cmd.append("-nullrhi")
    return cmd


def parse_unreal_automation_log(
    log_text: str,
    *,
    budget: UnrealPerformanceBudget | None = None,
) -> UnrealTelemetryReport:
    """Parse UE5 automation log lines and evaluate performance/stability gates."""
    limits = budget or UnrealPerformanceBudget()
    tests: list[UnrealTestResult] = []
    ensure_failures: list[str] = []
    fatal_errors: list[str] = []
    avg_fps: float | None = None
    p95_ms: float | None = None
    peak_mb: float | None = None

    for line in log_text.splitlines():
        test_match = TEST_COMPLETED_RE.search(line)
        if test_match:
            tests.append(
                UnrealTestResult(
                    name=test_match.group("name"),
                    test_path=test_match.group("path"),
                    passed=test_match.group("result") == "Passed",
                )
            )
            continue

        fps_match = FPS_CHART_RE.search(line)
        if fps_match:
            avg_fps = float(fps_match.group("avg_fps"))
            p95_ms = float(fps_match.group("p95_ms"))
            peak_mb = float(fps_match.group("peak_mb"))
            continue

        if ENSURE_RE.search(line):
            ensure_failures.append(line.strip())
        elif FATAL_RE.search(line):
            fatal_errors.append(line.strip())

    violations: list[str] = []
    if avg_fps is not None and avg_fps < limits.min_avg_fps:
        violations.append(f"AvgFPS {avg_fps:.2f} below minimum {limits.min_avg_fps:.2f}")
    if p95_ms is not None and p95_ms > limits.max_p95_frame_time_ms:
        violations.append(
            f"P95FrameTimeMs {p95_ms:.2f} exceeds budget {limits.max_p95_frame_time_ms:.2f}"
        )
    if peak_mb is not None and peak_mb > limits.max_peak_memory_mb:
        violations.append(
            f"PeakMemoryMB {peak_mb:.1f} exceeds budget {limits.max_peak_memory_mb:.1f}"
        )

    return UnrealTelemetryReport(
        tests=tuple(tests),
        avg_fps=avg_fps,
        p95_frame_time_ms=p95_ms,
        peak_memory_mb=peak_mb,
        ensure_failures=tuple(ensure_failures),
        fatal_errors=tuple(fatal_errors),
        budget_violations=tuple(violations),
    )
