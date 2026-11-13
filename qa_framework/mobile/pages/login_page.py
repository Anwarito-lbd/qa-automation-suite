"""LoginActivity Page Object for AegisPay Android."""

from __future__ import annotations

from qa_framework.mobile.driver import Locator
from qa_framework.mobile.pages.base_page import BasePage


class LoginPage(BasePage):
    EMAIL_INPUT = Locator("accessibility id", "login-email-input")
    PASSWORD_INPUT = Locator("id", "com.aegispay.wallet:id/input_password")
    SUBMIT_BUTTON = Locator("accessibility id", "login-submit-btn")
    ERROR_TEXT = Locator("id", "com.aegispay.wallet:id/txt_auth_error")

    def login(self, email: str, password: str) -> None:
        self.type_text(self.EMAIL_INPUT, email)
        self.type_text(self.PASSWORD_INPUT, password)
        self.tap(self.SUBMIT_BUTTON)

    def read_error(self) -> str:
        return self.get_text(self.ERROR_TEXT)
