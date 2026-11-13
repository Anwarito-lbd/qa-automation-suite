"""Shared pytest fixtures across Layer 1 (API/Property), Layer 2 (Web E2E), and Layer 3 (Mobile)."""

from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qa_framework.api_client import AegisApiClient
from qa_framework.config import QAExecutionConfig
from qa_framework.mobile.adb import AdbBridge
from qa_framework.mobile.driver import HttpAppiumBackend, MobileDriver, MockAppiumBackend
from sut.app import create_app
from sut.config import SutSettings
from sut.mobile_bridge import DeterministicMobileBridge


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def qa_config() -> QAExecutionConfig:
    return QAExecutionConfig.from_env()


@pytest.fixture()
def sut_settings() -> SutSettings:
    return SutSettings(db_path=":memory:", rate_limit_max_requests=200, pbkdf2_iterations=1_000)


@pytest.fixture()
def sut_app(sut_settings: SutSettings) -> Generator[FastAPI, None, None]:
    app = create_app(settings=sut_settings)
    yield app
    app.state.db.close()


@pytest.fixture()
def api_client(sut_app: FastAPI) -> Generator[AegisApiClient, None, None]:
    with TestClient(sut_app) as client:
        yield AegisApiClient(client)


@pytest.fixture()
def live_server_url() -> Generator[str, None, None]:
    """Start a real isolated uvicorn server on an ephemeral localhost port for Playwright E2E."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = str(Path(tmpdir) / "e2e_sut.sqlite3")
        settings = SutSettings(
            db_path=db_file,
            rate_limit_max_requests=500,
            pbkdf2_iterations=1_000,
        )
        app = create_app(settings=settings)
        port = _free_tcp_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)

        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 10.0
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Timed out waiting for uvicorn E2E server to start")
            time.sleep(0.05)

        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=5.0)
            app.state.db.close()


@pytest.fixture()
def mobile_bridge(sut_app: FastAPI) -> DeterministicMobileBridge:
    return DeterministicMobileBridge(sut_app)


@pytest.fixture()
def adb_bridge(qa_config: QAExecutionConfig, mobile_bridge: DeterministicMobileBridge) -> AdbBridge:
    return AdbBridge(
        mode=qa_config.mobile_mode,
        device_serial=qa_config.android_device_serial,
        mock_bridge=mobile_bridge,
    )


@pytest.fixture()
def mobile_driver(
    qa_config: QAExecutionConfig, mobile_bridge: DeterministicMobileBridge
) -> Generator[MobileDriver, None, None]:
    backend = (
        HttpAppiumBackend(qa_config.appium_server_url)
        if qa_config.mobile_mode == "appium"
        else MockAppiumBackend(mobile_bridge)
    )
    caps = {
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:deviceName": qa_config.android_device_serial,
        "appium:appPackage": qa_config.android_app_package,
        "appium:appActivity": qa_config.android_main_activity,
    }
    driver = MobileDriver(backend=backend, capabilities=caps)
    try:
        yield driver
    finally:
        driver.quit()


@pytest.fixture()
def screenshot_dir() -> Path:
    custom = os.getenv("QA_SCREENSHOT_DIR")
    target = Path(custom) if custom else Path(__file__).resolve().parent.parent / "docs" / "images"
    target.mkdir(parents=True, exist_ok=True)
    return target
