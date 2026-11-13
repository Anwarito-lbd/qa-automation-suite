"""TransferOrderActivity Page Object for AegisPay Android."""

from __future__ import annotations

from qa_framework.mobile.driver import Locator
from qa_framework.mobile.pages.base_page import BasePage


class TransferOrderPage(BasePage):
    RECIPIENT_INPUT = Locator("accessibility id", "transfer-recipient-input")
    AMOUNT_CENTS_INPUT = Locator("id", "com.aegispay.wallet:id/input_amount_cents")
    MEMO_INPUT = Locator("accessibility id", "transfer-memo-input")
    IDEMPOTENCY_INPUT = Locator("id", "com.aegispay.wallet:id/input_idempotency_key")
    SUBMIT_BTN = Locator("accessibility id", "transfer-submit-btn")
    BACK_BTN = Locator("id", "com.aegispay.wallet:id/btn_back_dashboard")
    ERROR_TEXT = Locator("id", "com.aegispay.wallet:id/txt_transfer_error")

    def submit_transfer(
        self,
        *,
        recipient: str,
        amount_cents: int,
        memo: str = "",
        idempotency_key: str = "",
    ) -> None:
        self.type_text(self.RECIPIENT_INPUT, recipient)
        self.type_text(self.AMOUNT_CENTS_INPUT, str(amount_cents))
        self.type_text(self.MEMO_INPUT, memo)
        self.type_text(self.IDEMPOTENCY_INPUT, idempotency_key)
        self.tap(self.SUBMIT_BTN)

    def read_error(self) -> str:
        return self.get_text(self.ERROR_TEXT)

    def go_back(self) -> None:
        self.tap(self.BACK_BTN)
