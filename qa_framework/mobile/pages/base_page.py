"""Base Page Object with explicit waits and semantic element actions."""

from __future__ import annotations

from qa_framework.mobile.driver import Locator, MobileDriver, MobileElement


class BasePage:
    """Shared base class for Android UIAutomator2 Page Objects."""

    def __init__(self, driver: MobileDriver) -> None:
        self._driver = driver

    def wait_visible(self, locator: Locator, *, timeout_seconds: float = 3.0) -> MobileElement:
        return self._driver.wait_for_element(locator, timeout_seconds=timeout_seconds)

    def tap(self, locator: Locator) -> None:
        self.wait_visible(locator).click()

    def type_text(self, locator: Locator, text: str) -> None:
        self.wait_visible(locator).send_keys(text)

    def get_text(self, locator: Locator) -> str:
        return self.wait_visible(locator).text

    def is_visible(self, locator: Locator) -> bool:
        try:
            return self._driver.find_element(locator).is_displayed()
        except LookupError:
            return False
