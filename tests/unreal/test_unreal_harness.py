"""Layer 4 Unreal Engine Gauntlet CLI, C++ reference test, and FPS/crash log regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from qa_framework.integrations.jira_reporter import (
    DefectTicketSpec,
    JiraConfig,
    JiraDefectClient,
    compute_defect_fingerprint,
    infer_priority,
)
from qa_framework.unreal.gauntlet import (
    GauntletConfig,
    UnrealPerformanceBudget,
    build_gauntlet_command,
    parse_unreal_automation_log,
)

pytestmark = pytest.mark.unreal

SAMPLE_PASSING_UE5_LOG = "\n".join(
    [
        "LogInit: Display: Running Gauntlet automation suite AegisGauntletTest",
        (
            "LogAutomationController: Display: Test Completed. Result={Passed} "
            "Name={LedgerHealthEndpoint} Path={AegisPay.Smoke.LedgerHealthEndpoint}"
        ),
        (
            "LogAutomationController: Display: Test Completed. Result={Passed} "
            "Name={WalletWidgetRender} Path={AegisPay.Smoke.WalletWidgetRender}"
        ),
        "LogFPSChart: Display: AvgFPS=62.40 P95FrameTimeMs=15.80 PeakMemoryMB=2140.5",
    ]
)

SAMPLE_REGRESSED_UE5_LOG = "\n".join(
    [
        (
            "LogAutomationController: Display: Test Completed. Result={Passed} "
            "Name={LedgerHealthEndpoint} Path={AegisPay.Smoke.LedgerHealthEndpoint}"
        ),
        (
            "LogAutomationController: Error: Test Completed. Result={Failed} "
            "Name={CheckoutStress} Path={AegisPay.Smoke.CheckoutStress}"
        ),
        (
            "LogOutputDevice: Error: Ensure condition failed: Balance >= 0 "
            "[File:LedgerClient.cpp] [Line:142]"
        ),
        "LogWindows: Error: Fatal error: Unhandled Exception: EXCEPTION_ACCESS_VIOLATION",
        "LogFPSChart: Display: AvgFPS=41.20 P95FrameTimeMs=27.40 PeakMemoryMB=4620.0",
    ]
)


def test_gauntlet_cli_builder_for_win64_and_linux() -> None:
    win_cmd = build_gauntlet_command(
        GauntletConfig(
            ue_root="C:/UnrealEngine/UE_5.4",
            uproject_path="C:/Projects/AegisClient/AegisClient.uproject",
            platform="Win64",
        )
    )
    assert win_cmd[0].endswith("RunUAT.bat")
    assert "RunUnreal" in win_cmd
    assert "-nullrhi" in win_cmd
    assert "-test=AegisGauntletTest" in win_cmd

    linux_cmd = build_gauntlet_command(
        GauntletConfig(
            ue_root="/opt/unreal/UE_5.4",
            uproject_path="/src/AegisClient.uproject",
            platform="Linux",
            null_rhi=False,
        )
    )
    assert linux_cmd[0].endswith("RunUAT.sh")
    assert "-nullrhi" not in linux_cmd


def test_unreal_log_parser_passes_healthy_telemetry() -> None:
    report = parse_unreal_automation_log(
        SAMPLE_PASSING_UE5_LOG,
        budget=UnrealPerformanceBudget(
            min_avg_fps=55.0,
            max_p95_frame_time_ms=18.0,
            max_peak_memory_mb=4096.0,
        ),
    )
    assert report.is_healthy is True
    assert len(report.tests) == 2
    assert report.avg_fps == 62.40
    assert report.p95_frame_time_ms == 15.80
    assert report.ensure_failures == ()
    assert report.fatal_errors == ()
    assert report.budget_violations == ()


def test_unreal_regression_detects_ensure_fatal_fps_and_files_jira_dry_run() -> None:
    report = parse_unreal_automation_log(SAMPLE_REGRESSED_UE5_LOG)
    assert report.is_healthy is False
    assert any(not t.passed and t.name == "CheckoutStress" for t in report.tests)
    assert len(report.ensure_failures) == 1
    assert len(report.fatal_errors) == 1
    assert len(report.budget_violations) == 3

    excerpt = f"{report.fatal_errors[0]}\nViolations: {'; '.join(report.budget_violations)}"
    spec = DefectTicketSpec(
        fingerprint=compute_defect_fingerprint("AegisPay.Smoke.CheckoutStress", excerpt),
        layer="Layer 4: Unreal (Gauntlet/Log)",
        sublayer="UE5 Gauntlet & Perf Gate",
        nodeid="AegisPay.Smoke.CheckoutStress",
        priority=infer_priority("Layer 4: Unreal (Gauntlet/Log)", excerpt),
        summary="[UE5][Gauntlet] Fatal/FPS regression in CheckoutStress",
        reproduction_cmd="RunUAT.bat RunUnreal -test=AegisGauntletTest -runtest=AegisPay.Smoke",
        environment={"platform": "Win64", "min_fps": "55.0"},
        failure_excerpt=excerpt,
    )
    assert spec.priority == "Highest"

    jira = JiraDefectClient(
        JiraConfig(
            base_url="https://example.atlassian.net",
            user_email="qa@aegispay.dev",
            api_token="mock-token",
        )
    )
    try:
        res = jira.submit_defect(spec, dry_run=True)
        assert res.status == "dry_run"
        assert "highest" in str(res.payload["fields"]["priority"]["name"]).lower()
    finally:
        jira.close()


def test_unreal_cpp_reference_spec_present_and_valid() -> None:
    cpp_path = (
        Path(__file__).resolve().parents[2]
        / "qa_framework"
        / "unreal"
        / "cpp"
        / "AegisPayGauntletTests.cpp"
    )
    text = cpp_path.read_text(encoding="utf-8")
    assert "IMPLEMENT_SIMPLE_AUTOMATION_TEST" in text
    assert "FAegisPayLedgerHealthTest" in text
    assert "AegisPay.Smoke.LedgerHealthEndpoint" in text
