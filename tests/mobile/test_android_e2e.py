"""Layer 3 Android Appium UIAutomator2 Page Object Model E2E tests."""

from __future__ import annotations

import pytest

from qa_framework.api_client import AegisApiClient
from qa_framework.mobile.adb import AdbBridge
from qa_framework.mobile.driver import MobileDriver
from qa_framework.mobile.pages import LoginPage, TransferOrderPage, WalletDashboardPage

pytestmark = pytest.mark.mobile


def test_android_login_error_and_wallet_transfer_e2e(
    api_client: AegisApiClient,
    mobile_driver: MobileDriver,
    adb_bridge: AdbBridge,
) -> None:
    # Seed user and balance via backend API
    token, _ = api_client.register_and_get_token(
        email="android.e2e@aegispay.dev",
        full_name="Android User",
        password="MobileUserPass123!",
    )
    assert api_client.deposit(token, amount_cents=40_000).status_code == 200

    login_page = LoginPage(mobile_driver)
    dashboard = WalletDashboardPage(mobile_driver)
    transfer_page = TransferOrderPage(mobile_driver)

    # 1. Invalid password triggers inline Android error TextView
    login_page.login("android.e2e@aegispay.dev", "WrongPassword!")
    assert "Invalid email or password" in login_page.read_error()

    # 2. Valid credentials navigate to WalletDashboardActivity with live XML hierarchy
    login_page.login("android.e2e@aegispay.dev", "MobileUserPass123!")
    dashboard.wait_loaded()
    assert dashboard.read_balance() == "$400.00"
    assert dashboard.read_orders_count() == 0
    assert "<hierarchy" in mobile_driver.page_source

    # 3. Create transfer via TransferOrderActivity with Idempotency-Key
    dashboard.open_new_transfer()
    transfer_page.submit_transfer(
        recipient="pos-terminal@store.io",
        amount_cents=8_500,
        memo="Mobile NFC checkout",
        idempotency_key="mob-idem-9001",
    )

    dashboard.wait_loaded()
    assert dashboard.read_balance() == "$315.00"
    assert dashboard.read_orders_count() == 1
    created_order_id = dashboard.read_last_order_id()
    assert created_order_id.startswith("ord_")

    # 4. Cross-layer verification: backend API ledger matches mobile UI state
    api_summary = api_client.get_account(token).json()
    assert api_summary["balance_cents"] == 31_500
    assert api_summary["pending_orders_cents"] == 8_500

    # 5. Idempotency replay protection on duplicate mobile submit
    dashboard.open_new_transfer()
    transfer_page.submit_transfer(
        recipient="pos-terminal@store.io",
        amount_cents=8_500,
        memo="Mobile NFC checkout",
        idempotency_key="mob-idem-9001",
    )
    dashboard.wait_loaded()
    assert dashboard.read_balance() == "$315.00"
    assert dashboard.read_orders_count() == 1

    # 6. Logcat fatal-crash gate must be clean
    assert adb_bridge.scan_logcat_for_fatal_errors() == ()


def test_android_insufficient_funds_error_preserves_session(
    api_client: AegisApiClient,
    mobile_driver: MobileDriver,
) -> None:
    token, _ = api_client.register_and_get_token(
        email="android.low@aegispay.dev",
        password="MobileUserPass123!",
    )
    api_client.deposit(token, amount_cents=2_000)

    login_page = LoginPage(mobile_driver)
    dashboard = WalletDashboardPage(mobile_driver)
    transfer_page = TransferOrderPage(mobile_driver)

    login_page.login("android.low@aegispay.dev", "MobileUserPass123!")
    dashboard.wait_loaded()
    dashboard.open_new_transfer()
    transfer_page.submit_transfer(
        recipient="merchant@acme.io",
        amount_cents=5_000,
        memo="Over-limit",
    )

    assert "Insufficient funds" in transfer_page.read_error()
    transfer_page.go_back()
    dashboard.wait_loaded()
    assert dashboard.read_balance() == "$20.00"
    dashboard.logout()
    assert login_page.is_visible(LoginPage.SUBMIT_BUTTON)
