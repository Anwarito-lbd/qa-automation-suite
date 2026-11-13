"""Deterministic Android App Contract, Mock Appium UIAutomator2 Engine, and Mock ADB Bridge.

This module implements a W3C WebDriver / UIAutomator2-compatible deterministic mobile
test target backed directly by the live FastAPI + SQLite AegisPay SUT. It renders a real
Android XML View Hierarchy (`<hierarchy>`) evaluated via `xml.etree.ElementTree` so
Page Object Model locators (`accessibility id`, `id`, `xpath`) exercise real structural
tree lookups and mutate real backend ledger state without requiring a physical emulator
in CI.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape

from fastapi import FastAPI
from fastapi.testclient import TestClient


@dataclass
class AndroidWidget:
    """Represents a single Android UIAutomator2 View node."""

    resource_id: str
    class_name: str
    content_desc: str
    text: str = ""
    clickable: bool = False
    enabled: bool = True
    displayed: bool = True
    bounds: str = "[0,0][1080,1920]"


@dataclass
class MockAppiumSession:
    """State for an active deterministic Android UIAutomator2 session."""

    session_id: str
    package_name: str = "com.aegispay.wallet"
    activity: str = ".LoginActivity"
    token: str | None = None
    user_email: str = ""
    balance_cents: int = 0
    orders_count: int = 0
    last_order_id: str = ""
    last_order_status: str = ""
    auth_error: str = ""
    transfer_error: str = ""
    field_values: dict[str, str] = field(default_factory=dict)
    element_registry: dict[str, str] = field(default_factory=dict)
    logcat_lines: list[str] = field(default_factory=list)


class DeterministicMobileBridge:
    """Deterministic Android UIAutomator2 + ADB bridge wired to the live FastAPI SUT."""

    PACKAGE = "com.aegispay.wallet"
    MAIN_ACTIVITY = ".MainActivity"

    def __init__(self, sut_app: FastAPI, device_serial: str = "emulator-5554") -> None:
        self._client = TestClient(sut_app)
        self._device_serial = device_serial
        self._sessions: dict[str, MockAppiumSession] = {}
        self._injected_logcat_fault: str | None = None

    def inject_logcat_fault(self, line: str | None) -> None:
        """Test hook to inject or clear a simulated logcat crash/ANR line."""
        self._injected_logcat_fault = line

    # --- ADB Contract ---

    def adb_command(self, args: list[str]) -> tuple[int, str, str]:
        """Execute a deterministic ADB command and return `(returncode, stdout, stderr)`."""
        joined = " ".join(args)
        if args == ["devices"]:
            return 0, f"List of devices attached\n{self._device_serial}\tdevice\n", ""
        if args == ["get-state"]:
            return 0, "device\n", ""
        if joined == "shell getprop ro.build.version.sdk":
            return 0, "34\n", ""
        if joined == "shell getprop ro.product.model":
            return 0, "sdk_gphone64_x86_64\n", ""
        if joined == f"shell pm list packages {self.PACKAGE}":
            return 0, f"package:{self.PACKAGE}\n", ""
        if joined == f"shell am start -W -n {self.PACKAGE}/{self.MAIN_ACTIVITY}":
            return (
                0,
                (
                    f"Starting: Intent {{ cmp={self.PACKAGE}/{self.MAIN_ACTIVITY} }}\n"
                    "Status: ok\n"
                    "LaunchState: COLD\n"
                    f"Activity: {self.PACKAGE}/.LoginActivity\n"
                    "ThisTime: 312\n"
                    "TotalTime: 312\n"
                    "WaitTime: 318\n"
                    "Complete\n"
                ),
                "",
            )
        if joined == f"shell dumpsys meminfo {self.PACKAGE}":
            return (
                0,
                (
                    "Applications Memory Usage (in Kilobytes):\n"
                    f"Uptime: 18420 Realtime: 18420\n"
                    f"** MEMINFO in pid 4812 [{self.PACKAGE}] **\n"
                    "        TOTAL PSS:   68420            TOTAL RSS:  112400\n"
                ),
                "",
            )
        if args[:1] == ["logcat"]:
            lines = [
                "11-13 00:05:00.101  4812  4812 I AegisPayApp: Application onCreate complete",
                (
                    "11-13 00:05:00.289  4812  4812 I ActivityTaskManager: "
                    "Displayed com.aegispay.wallet/.LoginActivity: +312ms"
                ),
            ]
            for session in self._sessions.values():
                lines.extend(session.logcat_lines)
            if self._injected_logcat_fault:
                lines.append(self._injected_logcat_fault)
            return 0, "\n".join(lines) + "\n", ""

        return 1, "", f"Unsupported mock adb command: {joined}"

    # --- W3C WebDriver / Appium Session Contract ---

    def create_session(self, capabilities: dict[str, Any]) -> dict[str, Any]:
        session_id = f"appium-sess-{uuid.uuid4().hex[:10]}"
        session = MockAppiumSession(
            session_id=session_id,
            package_name=str(capabilities.get("appium:appPackage", self.PACKAGE)),
        )
        session.logcat_lines.append(
            f"11-13 00:05:01.010  4812  4830 I UIAutomator2: Session {session_id} initialized"
        )
        self._sessions[session_id] = session
        return {
            "sessionId": session_id,
            "capabilities": {
                "platformName": "Android",
                "automationName": "UiAutomator2",
                "deviceName": self._device_serial,
                "appPackage": session.package_name,
                "appActivity": session.activity,
            },
        }

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _get_session(self, session_id: str) -> MockAppiumSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown Appium session: {session_id}")
        return session

    def _sync_wallet_state(self, session: MockAppiumSession) -> None:
        if not session.token:
            return
        headers = {"Authorization": f"Bearer {session.token}"}
        acc_resp = self._client.get("/api/v1/accounts/me", headers=headers)
        if acc_resp.status_code == 200:
            acc = acc_resp.json()
            session.balance_cents = int(acc["balance_cents"])
            session.user_email = str(acc["email"])
        ord_resp = self._client.get("/api/v1/orders", headers=headers)
        if ord_resp.status_code == 200:
            orders = ord_resp.json()
            session.orders_count = len(orders)
            if orders:
                session.last_order_id = str(orders[0]["id"])
                session.last_order_status = str(orders[0]["status"])
            else:
                session.last_order_id = "NONE"
                session.last_order_status = "NONE"

    def _widgets_for_session(self, session: MockAppiumSession) -> list[AndroidWidget]:
        if session.activity == ".LoginActivity":
            return [
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/input_email",
                    class_name="android.widget.EditText",
                    content_desc="login-email-input",
                    text=session.field_values.get("input_email", ""),
                    clickable=True,
                    bounds="[48,320][1032,440]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/input_password",
                    class_name="android.widget.EditText",
                    content_desc="login-password-input",
                    text=session.field_values.get("input_password", ""),
                    clickable=True,
                    bounds="[48,470][1032,590]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/btn_sign_in",
                    class_name="android.widget.Button",
                    content_desc="login-submit-btn",
                    text="Sign In",
                    clickable=True,
                    bounds="[48,640][1032,760]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/txt_auth_error",
                    class_name="android.widget.TextView",
                    content_desc="login-error-text",
                    text=session.auth_error,
                    displayed=bool(session.auth_error),
                    bounds="[48,800][1032,880]",
                ),
            ]

        if session.activity == ".WalletDashboardActivity":
            self._sync_wallet_state(session)
            balance_text = f"${session.balance_cents / 100:.2f}"
            return [
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/txt_user_badge",
                    class_name="android.widget.TextView",
                    content_desc="dashboard-user-badge",
                    text=session.user_email,
                    bounds="[48,140][1032,210]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/txt_balance",
                    class_name="android.widget.TextView",
                    content_desc="dashboard-balance-value",
                    text=balance_text,
                    bounds="[48,240][1032,360]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/txt_orders_count",
                    class_name="android.widget.TextView",
                    content_desc="dashboard-orders-count",
                    text=str(session.orders_count),
                    bounds="[48,380][520,460]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/txt_last_order_id",
                    class_name="android.widget.TextView",
                    content_desc="dashboard-last-order-id",
                    text=session.last_order_id,
                    bounds="[540,380][1032,460]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/btn_new_transfer",
                    class_name="android.widget.Button",
                    content_desc="dashboard-new-transfer-btn",
                    text="New Transfer",
                    clickable=True,
                    bounds="[48,520][1032,640]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/btn_refresh_wallet",
                    class_name="android.widget.Button",
                    content_desc="dashboard-refresh-btn",
                    text="Refresh Wallet",
                    clickable=True,
                    bounds="[48,670][1032,790]",
                ),
                AndroidWidget(
                    resource_id=f"{self.PACKAGE}:id/btn_logout",
                    class_name="android.widget.Button",
                    content_desc="dashboard-logout-btn",
                    text="Sign Out",
                    clickable=True,
                    bounds="[48,820][1032,940]",
                ),
            ]

        # .TransferOrderActivity
        return [
            AndroidWidget(
                resource_id=f"{self.PACKAGE}:id/input_recipient",
                class_name="android.widget.EditText",
                content_desc="transfer-recipient-input",
                text=session.field_values.get("input_recipient", ""),
                clickable=True,
                bounds="[48,220][1032,340]",
            ),
            AndroidWidget(
                resource_id=f"{self.PACKAGE}:id/input_amount_cents",
                class_name="android.widget.EditText",
                content_desc="transfer-amount-cents-input",
                text=session.field_values.get("input_amount_cents", ""),
                clickable=True,
                bounds="[48,370][1032,490]",
            ),
            AndroidWidget(
                resource_id=f"{self.PACKAGE}:id/input_memo",
                class_name="android.widget.EditText",
                content_desc="transfer-memo-input",
                text=session.field_values.get("input_memo", ""),
                clickable=True,
                bounds="[48,520][1032,640]",
            ),
            AndroidWidget(
                resource_id=f"{self.PACKAGE}:id/input_idempotency_key",
                class_name="android.widget.EditText",
                content_desc="transfer-idempotency-input",
                text=session.field_values.get("input_idempotency_key", ""),
                clickable=True,
                bounds="[48,670][1032,790]",
            ),
            AndroidWidget(
                resource_id=f"{self.PACKAGE}:id/btn_submit_transfer",
                class_name="android.widget.Button",
                content_desc="transfer-submit-btn",
                text="Send Transfer",
                clickable=True,
                bounds="[48,830][1032,950]",
            ),
            AndroidWidget(
                resource_id=f"{self.PACKAGE}:id/btn_back_dashboard",
                class_name="android.widget.Button",
                content_desc="transfer-back-btn",
                text="Back",
                clickable=True,
                bounds="[48,980][1032,1100]",
            ),
            AndroidWidget(
                resource_id=f"{self.PACKAGE}:id/txt_transfer_error",
                class_name="android.widget.TextView",
                content_desc="transfer-error-text",
                text=session.transfer_error,
                displayed=bool(session.transfer_error),
                bounds="[48,1130][1032,1210]",
            ),
        ]

    def get_page_source(self, session_id: str) -> str:
        """Render the current Android UIAutomator2 XML hierarchy."""
        session = self._get_session(session_id)
        widgets = self._widgets_for_session(session)
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<hierarchy rotation="0" activity="{escape(session.activity)}">',
            (
                f'  <android.widget.FrameLayout package="{escape(session.package_name)}" '
                'bounds="[0,0][1080,1920]">'
            ),
        ]
        for idx, w in enumerate(widgets):
            lines.append(
                f'    <{w.class_name} index="{idx}" '
                f'package="{escape(session.package_name)}" '
                f'class="{escape(w.class_name)}" '
                f'resource-id="{escape(w.resource_id)}" '
                f'content-desc="{escape(w.content_desc)}" '
                f'text="{escape(w.text)}" '
                f'clickable="{str(w.clickable).lower()}" '
                f'enabled="{str(w.enabled).lower()}" '
                f'displayed="{str(w.displayed).lower()}" '
                f'bounds="{escape(w.bounds)}" />'
            )
        lines.append("  </android.widget.FrameLayout>")
        lines.append("</hierarchy>")
        return "\n".join(lines)

    def find_element(self, session_id: str, using: str, value: str) -> str:
        """Locate an element using Appium strategies (`accessibility id`, `id`, `xpath`)."""
        session = self._get_session(session_id)
        xml_str = self.get_page_source(session_id)
        root = ET.fromstring(xml_str)  # noqa: S314 (internal deterministic XML)
        matched_node: ET.Element | None = None

        if using == "accessibility id":
            for node in root.iter():
                if node.attrib.get("content-desc") == value:
                    matched_node = node
                    break
        elif using == "id":
            target_id = value if ":id/" in value else f"{self.PACKAGE}:id/{value}"
            for node in root.iter():
                if node.attrib.get("resource-id") == target_id:
                    matched_node = node
                    break
        elif using == "xpath":
            # Strip leading // for ElementTree relative search if needed
            xpath_query = value.lstrip("/")
            matched_node = root.find(f".//{xpath_query}")
        else:
            raise ValueError(f"Unsupported locator strategy: {using}")

        if matched_node is None:
            raise LookupError(f"NoSuchElementException: using={using!r}, value={value!r}")

        res_id = matched_node.attrib.get("resource-id", "")
        if not res_id:
            raise LookupError(f"Matched element has no resource-id: {value!r}")

        elem_id = f"el-{uuid.uuid4().hex[:8]}"
        session.element_registry[elem_id] = res_id
        return elem_id

    def get_element_text(self, session_id: str, element_id: str) -> str:
        session = self._get_session(session_id)
        res_id = session.element_registry.get(element_id)
        if res_id is None:
            raise LookupError(f"StaleElementReferenceException: {element_id}")
        for w in self._widgets_for_session(session):
            if w.resource_id == res_id:
                return w.text
        raise LookupError(f"Element {res_id} not present on {session.activity}")

    def is_element_displayed(self, session_id: str, element_id: str) -> bool:
        session = self._get_session(session_id)
        res_id = session.element_registry.get(element_id)
        if res_id is None:
            return False
        for w in self._widgets_for_session(session):
            if w.resource_id == res_id:
                return w.displayed
        return False

    def send_keys(self, session_id: str, element_id: str, text: str) -> None:
        session = self._get_session(session_id)
        res_id = session.element_registry.get(element_id)
        if res_id is None:
            raise LookupError(f"StaleElementReferenceException: {element_id}")
        short_id = res_id.split(":id/")[-1]
        session.field_values[short_id] = text

    def click(self, session_id: str, element_id: str) -> None:
        session = self._get_session(session_id)
        res_id = session.element_registry.get(element_id)
        if res_id is None:
            raise LookupError(f"StaleElementReferenceException: {element_id}")
        short_id = res_id.split(":id/")[-1]

        if short_id == "btn_sign_in":
            email = session.field_values.get("input_email", "")
            password = session.field_values.get("input_password", "")
            resp = self._client.post(
                "/api/v1/auth/login", json={"email": email, "password": password}
            )
            if resp.status_code == 200:
                data = resp.json()
                session.token = data["access_token"]
                session.auth_error = ""
                session.activity = ".WalletDashboardActivity"
                self._sync_wallet_state(session)
                session.logcat_lines.append(
                    "11-13 00:05:02.120  4812  4812 I AegisPayAuth: "
                    "Login succeeded -> .WalletDashboardActivity"
                )
            else:
                detail = resp.json().get("detail", "Authentication failed")
                session.auth_error = str(detail)
                session.logcat_lines.append(
                    f"11-13 00:05:02.130  4812  4812 W AegisPayAuth: Login rejected: {detail}"
                )
            return

        if short_id == "btn_new_transfer":
            session.transfer_error = ""
            session.activity = ".TransferOrderActivity"
            return

        if short_id == "btn_refresh_wallet":
            self._sync_wallet_state(session)
            return

        if short_id == "btn_logout":
            session.token = None
            session.user_email = ""
            session.field_values.clear()
            session.activity = ".LoginActivity"
            return

        if short_id == "btn_back_dashboard":
            session.activity = ".WalletDashboardActivity"
            self._sync_wallet_state(session)
            return

        if short_id == "btn_submit_transfer":
            if not session.token:
                session.transfer_error = "Not authenticated"
                return
            recipient = session.field_values.get("input_recipient", "")
            raw_cents = session.field_values.get("input_amount_cents", "0")
            memo = session.field_values.get("input_memo", "")
            idem = session.field_values.get("input_idempotency_key", "").strip()
            try:
                amount_cents = int(raw_cents)
            except ValueError:
                session.transfer_error = "Amount must be an integer in cents"
                return

            headers = {"Authorization": f"Bearer {session.token}"}
            if idem:
                headers["Idempotency-Key"] = idem
            resp = self._client.post(
                "/api/v1/orders",
                headers=headers,
                json={
                    "recipient": recipient,
                    "amount_cents": amount_cents,
                    "currency": "USD",
                    "memo": memo,
                },
            )
            if resp.status_code in (200, 201):
                order = resp.json()
                session.transfer_error = ""
                session.last_order_id = str(order["id"])
                session.last_order_status = str(order["status"])
                session.activity = ".WalletDashboardActivity"
                self._sync_wallet_state(session)
                session.logcat_lines.append(
                    "11-13 00:05:03.410  4812  4812 I AegisPayTransfer: "
                    f"Order {order['id']} submitted"
                )
            else:
                detail = resp.json().get("detail", "Transfer failed")
                session.transfer_error = str(detail)
                session.logcat_lines.append(
                    f"11-13 00:05:03.420  4812  4812 W AegisPayTransfer: Order failed: {detail}"
                )
            return

        raise ValueError(f"Element {short_id} is not clickable")
