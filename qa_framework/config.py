"""Configuration for the Multi-Layer QA Automation Framework."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QAExecutionConfig:
    """Runtime execution settings for API, Web, and Mobile QA layers."""

    mobile_mode: str = "mock"  # "mock" (deterministic CI bridge) or "appium" (real Appium/ADB)
    appium_server_url: str = "http://127.0.0.1:4723"
    android_device_serial: str = "emulator-5554"
    android_app_package: str = "com.aegispay.wallet"
    android_main_activity: str = ".MainActivity"
    cold_start_budget_ms: int = 2000
    memory_pss_budget_kb: int = 250_000

    @classmethod
    def from_env(cls) -> QAExecutionConfig:
        return cls(
            mobile_mode=os.getenv("QA_MOBILE_MODE", "mock").strip().lower(),
            appium_server_url=os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723").rstrip("/"),
            android_device_serial=os.getenv("ANDROID_DEVICE_SERIAL", "emulator-5554"),
            android_app_package=os.getenv("ANDROID_APP_PACKAGE", "com.aegispay.wallet"),
            android_main_activity=os.getenv("ANDROID_MAIN_ACTIVITY", ".MainActivity"),
        )
