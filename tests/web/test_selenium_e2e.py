"""Layer 2 Selenium WebDriver E2E Tests: Cross-Engine Parity with Playwright."""

from __future__ import annotations

import os
import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

pytestmark = [pytest.mark.web, pytest.mark.selenium]


def _resolve_chrome_binary() -> str | None:
    env_bin = os.getenv("CHROME_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin

    for candidate in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(candidate)
        if found:
            return found

    win_chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if win_chrome.exists():
        return str(win_chrome)

    local_app = os.getenv("LOCALAPPDATA")
    if local_app:
        pw_bins = sorted(
            (Path(local_app) / "ms-playwright").glob("chromium-*/chrome-win64/chrome.exe"),
            reverse=True,
        )
        if pw_bins:
            return str(pw_bins[0])

    linux_pw = sorted(
        (Path.home() / ".cache" / "ms-playwright").glob("chromium-*/chrome-linux*/chrome"),
        reverse=True,
    )
    if linux_pw:
        return str(linux_pw[0])
    return None


@pytest.fixture()
def selenium_driver() -> Generator[webdriver.Chrome, None, None]:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,800")

    chrome_bin = _resolve_chrome_binary()
    if chrome_bin:
        options.binary_location = chrome_bin

    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        driver.quit()


def _by_testid(testid: str) -> tuple[str, str]:
    return (By.CSS_SELECTOR, f'[data-testid="{testid}"]')


def test_selenium_full_auth_deposit_order_cancel_parity(
    selenium_driver: webdriver.Chrome, live_server_url: str
) -> None:
    wait = WebDriverWait(selenium_driver, 10)
    selenium_driver.get(live_server_url)

    # Register fresh account
    wait.until(ec.element_to_be_clickable(_by_testid("tab-register"))).click()
    selenium_driver.find_element(*_by_testid("reg-name")).send_keys("Selenium QA")
    selenium_driver.find_element(*_by_testid("reg-email")).send_keys("sel.e2e@aegispay.dev")
    selenium_driver.find_element(*_by_testid("reg-password")).send_keys("SeleniumPass123!")
    selenium_driver.find_element(*_by_testid("register-submit")).click()

    wait.until(ec.text_to_be_present_in_element(_by_testid("metric-balance"), "$0.00"))

    # Sign out & verify login tab is restored automatically
    selenium_driver.find_element(*_by_testid("logout-btn")).click()
    wait.until(ec.visibility_of_element_located(_by_testid("login-form")))

    # Sign back in
    selenium_driver.find_element(*_by_testid("login-email")).send_keys("sel.e2e@aegispay.dev")
    selenium_driver.find_element(*_by_testid("login-password")).send_keys("SeleniumPass123!")
    selenium_driver.find_element(*_by_testid("login-submit")).click()
    wait.until(ec.text_to_be_present_in_element(_by_testid("nav-user-pill"), "Selenium QA"))

    # Deposit $400.00
    selenium_driver.find_element(*_by_testid("deposit-amount")).send_keys("400.00")
    selenium_driver.find_element(*_by_testid("deposit-submit")).click()
    wait.until(ec.text_to_be_present_in_element(_by_testid("metric-balance"), "$400.00"))

    # Submit order for $110.25
    selenium_driver.find_element(*_by_testid("order-recipient")).send_keys("clearing@partner.io")
    selenium_driver.find_element(*_by_testid("order-amount")).send_keys("110.25")
    selenium_driver.find_element(*_by_testid("order-memo")).send_keys("Selenium parity check")
    selenium_driver.find_element(*_by_testid("order-submit")).click()

    wait.until(ec.text_to_be_present_in_element(_by_testid("metric-balance"), "$289.75"))
    wait.until(ec.text_to_be_present_in_element(_by_testid("orders-tbody"), "PENDING"))

    # Cancel order and assert balance refund
    cancel_btn = wait.until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid^='cancel-order-']"))
    )
    cancel_btn.click()
    wait.until(ec.text_to_be_present_in_element(_by_testid("metric-balance"), "$400.00"))
    wait.until(ec.text_to_be_present_in_element(_by_testid("orders-tbody"), "CANCELLED"))


def test_selenium_mobile_390x844_responsive_layout(
    selenium_driver: webdriver.Chrome, live_server_url: str
) -> None:
    wait = WebDriverWait(selenium_driver, 10)
    selenium_driver.set_window_size(390, 844)
    selenium_driver.get(live_server_url)

    wait.until(ec.visibility_of_element_located(_by_testid("login-form")))
    overflow_auth = int(
        selenium_driver.execute_script(
            "return document.documentElement.scrollWidth - window.innerWidth;"
        )
    )
    assert overflow_auth <= 0

    selenium_driver.find_element(*_by_testid("tab-register")).click()
    selenium_driver.find_element(*_by_testid("reg-name")).send_keys("Sel Mobile")
    selenium_driver.find_element(*_by_testid("reg-email")).send_keys("sel.mob@aegispay.dev")
    selenium_driver.find_element(*_by_testid("reg-password")).send_keys("SelMobPass123!")
    selenium_driver.find_element(*_by_testid("register-submit")).click()

    wait.until(ec.text_to_be_present_in_element(_by_testid("metric-balance"), "$0.00"))
    overflow_dash = int(
        selenium_driver.execute_script(
            "return document.documentElement.scrollWidth - window.innerWidth;"
        )
    )
    assert overflow_dash <= 0
