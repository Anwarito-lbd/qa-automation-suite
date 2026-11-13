"""WalletDashboardActivity Page Object for AegisPay Android."""

from __future__ import annotations

from qa_framework.mobile.driver import Locator
from qa_framework.mobile.pages.base_page import BasePage


class WalletDashboardPage(BasePage):
    USER_BADGE = Locator("accessibility id", "dashboard-user-badge")
    BALANCE_VALUE = Locator("id", "com.aegispay.wallet:id/txt_balance")
    ORDERS_COUNT = Locator("id", "com.aegispay.wallet:id/txt_orders_count")
    LAST_ORDER_ID = Locator("accessibility id", "dashboard-last-order-id")
    NEW_TRANSFER_BTN = Locator(
        "xpath", "//android.widget.Button[@content-desc='dashboard-new-transfer-btn']"
    )
    REFRESH_BTN = Locator("accessibility id", "dashboard-refresh-btn")
    LOGOUT_BTN = Locator("id", "com.aegispay.wallet:id/btn_logout")

    def wait_loaded(self) -> None:
        self.wait_visible(self.BALANCE_VALUE)

    def read_balance(self) -> str:
        return self.get_text(self.BALANCE_VALUE)

    def read_orders_count(self) -> int:
        return int(self.get_text(self.ORDERS_COUNT))

    def read_last_order_id(self) -> str:
        return self.get_text(self.LAST_ORDER_ID)

    def open_new_transfer(self) -> None:
        self.tap(self.NEW_TRANSFER_BTN)

    def refresh(self) -> None:
        self.tap(self.REFRESH_BTN)

    def logout(self) -> None:
        self.tap(self.LOGOUT_BTN)
