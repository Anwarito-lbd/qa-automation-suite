"""Layer 3 ADB device-health, package-smoke, launch-latency, memory & logcat gate."""

from __future__ import annotations

import pytest

from qa_framework.config import QAExecutionConfig
from qa_framework.mobile.adb import AdbBridge
from sut.mobile_bridge import DeterministicMobileBridge

pytestmark = pytest.mark.mobile


def test_adb_device_health_and_package_smoke(
    adb_bridge: AdbBridge, qa_config: QAExecutionConfig
) -> None:
    report = adb_bridge.collect_health_report(
        package=qa_config.android_app_package,
        activity=qa_config.android_main_activity,
    )
    assert report.device_state == "device"
    assert report.sdk_version >= 30
    assert report.package_installed is True
    assert report.cold_start_ms <= qa_config.cold_start_budget_ms
    assert report.total_pss_kb <= qa_config.memory_pss_budget_kb
    assert report.fatal_logcat_lines == ()


def test_adb_logcat_scanner_detects_fatal_exceptions(
    adb_bridge: AdbBridge,
    mobile_bridge: DeterministicMobileBridge,
    qa_config: QAExecutionConfig,
) -> None:
    if qa_config.mobile_mode != "mock":
        pytest.skip("Fault injection test only runs against deterministic mock bridge")

    mobile_bridge.inject_logcat_fault(
        "11-13 00:05:09.111  4812  4812 E AndroidRuntime: FATAL EXCEPTION: main"
    )
    try:
        hits = adb_bridge.scan_logcat_for_fatal_errors()
        assert len(hits) == 1
        assert "FATAL EXCEPTION" in hits[0]
    finally:
        mobile_bridge.inject_logcat_fault(None)
