"""Layer 2 Playwright Web E2E Tests: Auth, Validation, Ledger, Accessibility & Responsive."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Page,
    expect,
    sync_playwright,
)

pytestmark = pytest.mark.web


@pytest.fixture(scope="module")
def browser_instance() -> Generator[Browser, None, None]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def _attach_hygiene_listeners(page: Page) -> tuple[list[str], list[str]]:
    console_errors: list[str] = []
    page_errors: list[str] = []

    def on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error":
            console_errors.append(msg.text)

    def on_page_error(exc: Exception) -> None:
        page_errors.append(str(exc))

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    return console_errors, page_errors


def _new_desktop_page(browser: Browser) -> tuple[BrowserContext, Page, list[str], list[str]]:
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    console_errors, page_errors = _attach_hygiene_listeners(page)
    return context, page, console_errors, page_errors


def test_web_registration_login_and_invalid_credentials_alert(
    browser_instance: Browser, live_server_url: str
) -> None:
    context, page, console_errors, page_errors = _new_desktop_page(browser_instance)
    try:
        page.goto(live_server_url, wait_until="networkidle")

        # Switch to registration tab and create user
        page.get_by_test_id("tab-register").click()
        page.get_by_test_id("reg-name").fill("Ada Lovelace")
        page.get_by_test_id("reg-email").fill("ada.web@aegispay.dev")
        page.get_by_test_id("reg-password").fill("QuantumPass123!")
        page.get_by_test_id("register-submit").click()

        expect(page.get_by_test_id("nav-user-pill")).to_contain_text("Ada Lovelace (customer)")
        expect(page.get_by_test_id("metric-balance")).to_have_text("$0.00")

        # Sign out and verify invalid password alert
        page.get_by_test_id("logout-btn").click()
        expect(page.get_by_test_id("login-form")).to_be_visible()

        page.get_by_test_id("login-email").fill("ada.web@aegispay.dev")
        page.get_by_test_id("login-password").fill("WrongPass!")
        page.get_by_test_id("login-submit").click()
        expect(page.get_by_test_id("alert-banner")).to_contain_text("Invalid email or password")

        # Valid sign-in succeeds
        page.get_by_test_id("login-password").fill("QuantumPass123!")
        page.get_by_test_id("login-submit").click()
        expect(page.get_by_test_id("nav-user-pill")).to_contain_text("Ada Lovelace")

        unexpected = [err for err in console_errors if "status of 401" not in err]
        assert unexpected == []
        assert page_errors == []
    finally:
        context.close()


def test_web_form_validation_and_insufficient_funds(
    browser_instance: Browser, live_server_url: str
) -> None:
    context, page, console_errors, page_errors = _new_desktop_page(browser_instance)
    try:
        page.goto(live_server_url, wait_until="networkidle")
        page.get_by_test_id("tab-register").click()
        page.get_by_test_id("reg-name").fill("Grace Hopper")
        page.get_by_test_id("reg-email").fill("grace.val@aegispay.dev")
        page.get_by_test_id("reg-password").fill("CompilerPass123!")
        page.get_by_test_id("register-submit").click()
        expect(page.get_by_test_id("metric-balance")).to_have_text("$0.00")

        # Client-side validation rejects non-positive deposit
        page.get_by_test_id("deposit-amount").fill("0")
        page.get_by_test_id("deposit-submit").click()
        expect(page.get_by_test_id("alert-banner")).to_contain_text("greater than $0.00")

        # Server-side validation rejects order exceeding balance
        page.get_by_test_id("order-recipient").fill("merchant@acme.io")
        page.get_by_test_id("order-amount").fill("75.00")
        page.get_by_test_id("order-submit").click()
        expect(page.get_by_test_id("alert-banner")).to_contain_text("Insufficient funds")

        unexpected = [err for err in console_errors if "status of 422" not in err]
        assert unexpected == []
        assert page_errors == []
    finally:
        context.close()


def test_web_full_deposit_order_cancel_workflow_and_desktop_screenshot(
    browser_instance: Browser, live_server_url: str, screenshot_dir: Path
) -> None:
    context, page, console_errors, page_errors = _new_desktop_page(browser_instance)
    try:
        page.goto(live_server_url, wait_until="networkidle")
        page.get_by_test_id("tab-register").click()
        page.get_by_test_id("reg-name").fill("Anwar QA")
        page.get_by_test_id("reg-email").fill("anwar.e2e@aegispay.dev")
        page.get_by_test_id("reg-password").fill("StaffEngPass123!")
        page.get_by_test_id("register-submit").click()

        # Deposit $500.00
        page.get_by_test_id("deposit-amount").fill("500.00")
        page.get_by_test_id("deposit-ref").fill("wire-e2e-001")
        page.get_by_test_id("deposit-submit").click()
        expect(page.get_by_test_id("metric-balance")).to_have_text("$500.00")
        expect(page.get_by_test_id("metric-deposited")).to_have_text("$500.00")

        # Submit order for $125.50
        page.get_by_test_id("order-recipient").fill("cloud-compute@aws.internal")
        page.get_by_test_id("order-amount").fill("125.50")
        page.get_by_test_id("order-memo").fill("GPU CI cluster #42")
        page.get_by_test_id("order-idem").fill("e2e-idem-42")
        page.get_by_test_id("order-submit").click()

        expect(page.get_by_test_id("metric-balance")).to_have_text("$374.50")
        expect(page.get_by_test_id("metric-pending")).to_have_text("$125.50")
        expect(page.get_by_test_id("orders-tbody")).to_contain_text("cloud-compute@aws.internal")
        expect(page.get_by_test_id("orders-tbody")).to_contain_text("PENDING")

        # Capture real Desktop Playwright screenshot of verified live dashboard state
        desktop_shot = screenshot_dir / "playwright-e2e.png"
        page.screenshot(path=str(desktop_shot), full_page=True)
        assert desktop_shot.exists() and desktop_shot.stat().st_size > 10_000

        # Cancel the pending order and verify full refund
        cancel_btn = page.locator("[data-testid^='cancel-order-']").first
        cancel_btn.click()
        expect(page.get_by_test_id("metric-balance")).to_have_text("$500.00")
        expect(page.get_by_test_id("metric-pending")).to_have_text("$0.00")
        expect(page.get_by_test_id("orders-tbody")).to_contain_text("CANCELLED")

        assert console_errors == []
        assert page_errors == []
    finally:
        context.close()


def test_web_mobile_390x844_responsive_and_accessibility_audit(
    browser_instance: Browser, live_server_url: str, screenshot_dir: Path
) -> None:
    context = browser_instance.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    console_errors, page_errors = _attach_hygiene_listeners(page)
    try:
        page.goto(live_server_url, wait_until="networkidle")

        # Accessibility landmarks & label-control association audit
        a11y_audit = page.evaluate(
            """() => {
                const hasHeader = Boolean(document.querySelector('header'));
                const hasMain = Boolean(document.querySelector('main'));
                const hasNav = Boolean(document.querySelector('nav'));
                const inputs = Array.from(document.querySelectorAll('input, select'));
                const unlabeled = inputs.filter(el => {
                    const id = el.getAttribute('id');
                    return !id || !document.querySelector(`label[for="${id}"]`);
                }).map(el => el.id || el.name);
                const overflowPx = document.documentElement.scrollWidth - window.innerWidth;
                return { hasHeader, hasMain, hasNav, unlabeled, overflowPx };
            }"""
        )
        assert a11y_audit["hasHeader"] is True
        assert a11y_audit["hasMain"] is True
        assert a11y_audit["hasNav"] is True
        assert a11y_audit["unlabeled"] == []
        assert a11y_audit["overflowPx"] <= 0

        # Register & populate dashboard on mobile viewport 390x844
        page.get_by_test_id("tab-register").click()
        page.get_by_test_id("reg-name").fill("Mobile QA")
        page.get_by_test_id("reg-email").fill("mobile.web@aegispay.dev")
        page.get_by_test_id("reg-password").fill("MobilePass123!")
        page.get_by_test_id("register-submit").click()

        page.get_by_test_id("deposit-amount").fill("250.00")
        page.get_by_test_id("deposit-submit").click()
        expect(page.get_by_test_id("metric-balance")).to_have_text("$250.00")

        page.get_by_test_id("order-recipient").fill("transit@city.gov")
        page.get_by_test_id("order-amount").fill("42.00")
        page.get_by_test_id("order-submit").click()
        expect(page.get_by_test_id("metric-balance")).to_have_text("$208.00")

        mobile_overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert mobile_overflow <= 0

        mobile_shot = screenshot_dir / "playwright-mobile-390x844.png"
        page.screenshot(path=str(mobile_shot), full_page=True)
        assert mobile_shot.exists() and mobile_shot.stat().st_size > 10_000

        assert console_errors == []
        assert page_errors == []
    finally:
        context.close()
