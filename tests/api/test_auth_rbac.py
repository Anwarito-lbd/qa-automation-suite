"""Layer 1 API contract tests: Authentication, JWT security, and RBAC matrix."""

from __future__ import annotations

import pytest

from qa_framework.api_client import AegisApiClient
from sut.config import SutSettings
from sut.security import create_access_token

pytestmark = pytest.mark.api


def test_register_login_and_me_lifecycle(api_client: AegisApiClient) -> None:
    reg_resp = api_client.register(
        email="Alice.QA@AegisPay.dev",
        full_name="Alice QA",
        password="StrongPassword!123",
    )
    assert reg_resp.status_code == 201
    reg_body = reg_resp.json()
    assert reg_body["token_type"] == "bearer"
    assert reg_body["user"]["email"] == "alice.qa@aegispay.dev"
    assert reg_body["user"]["role"] == "customer"
    assert reg_body["user"]["balance_cents"] == 0

    login_resp = api_client.login(email="alice.qa@aegispay.dev", password="StrongPassword!123")
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    me_resp = api_client.get_me(token)
    assert me_resp.status_code == 200
    assert me_resp.json()["id"] == reg_body["user"]["id"]


def test_duplicate_email_returns_409(api_client: AegisApiClient) -> None:
    first = api_client.register(
        email="dup@aegispay.dev", full_name="First User", password="Password123!"
    )
    assert first.status_code == 201

    second = api_client.register(
        email="DUP@aegispay.dev", full_name="Second User", password="Password123!"
    )
    assert second.status_code == 409


def test_invalid_login_and_malformed_jwt_return_401(
    api_client: AegisApiClient, sut_settings: SutSettings
) -> None:
    api_client.register(email="bob@aegispay.dev", full_name="Bob QA", password="Password123!")

    bad_pw = api_client.login(email="bob@aegispay.dev", password="WrongPassword!")
    assert bad_pw.status_code == 401

    no_hdr = api_client._client.get("/api/v1/auth/me")
    assert no_hdr.status_code == 401

    bad_sig = api_client.get_me("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c3JfZmFrZSJ9.invalidsig")
    assert bad_sig.status_code == 401

    expired = create_access_token(
        user_id="usr_expired",
        email="bob@aegispay.dev",
        role="customer",
        secret=sut_settings.jwt_secret,
        ttl_seconds=10,
        now=1_000_000,
    )
    assert api_client.get_me(expired).status_code == 401


def test_privilege_escalation_requires_provision_key(
    api_client: AegisApiClient, sut_settings: SutSettings
) -> None:
    unauth_admin = api_client.register(
        email="attacker@aegispay.dev",
        full_name="Attacker",
        password="Password123!",
        role="admin",
    )
    assert unauth_admin.status_code == 403

    wrong_key = api_client.register(
        email="attacker2@aegispay.dev",
        full_name="Attacker Two",
        password="Password123!",
        role="analyst",
        admin_provision_key="wrong-key",
    )
    assert wrong_key.status_code == 403

    valid_admin = api_client.register(
        email="admin@aegispay.dev",
        full_name="Admin User",
        password="Password123!",
        role="admin",
        admin_provision_key=sut_settings.admin_provision_key,
    )
    assert valid_admin.status_code == 201
    assert valid_admin.json()["user"]["role"] == "admin"


def test_rbac_matrix_across_customer_analyst_admin(
    api_client: AegisApiClient, sut_settings: SutSettings
) -> None:
    cust1_token, _ = api_client.register_and_get_token(email="cust1@aegispay.dev")
    cust2_token, _ = api_client.register_and_get_token(email="cust2@aegispay.dev")
    analyst_token, _ = api_client.register_and_get_token(
        email="analyst@aegispay.dev",
        role="analyst",
        admin_provision_key=sut_settings.admin_provision_key,
    )
    admin_token, _ = api_client.register_and_get_token(
        email="admin@aegispay.dev",
        role="admin",
        admin_provision_key=sut_settings.admin_provision_key,
    )

    assert api_client.deposit(cust1_token, amount_cents=50_000).status_code == 200
    order_resp = api_client.create_order(
        cust1_token, recipient="vendor@acme.io", amount_cents=12_500
    )
    assert order_resp.status_code == 201
    order_id = order_resp.json()["id"]

    # Customer isolation
    assert api_client.get_order(cust2_token, order_id).status_code == 403
    assert api_client.cancel_order(cust2_token, order_id).status_code == 403
    assert api_client.list_orders(cust2_token, all_users=True).status_code == 403
    assert api_client.get_audit_logs(cust1_token).status_code == 403
    assert api_client.settle_order(cust1_token, order_id).status_code == 403

    # Analyst: read-only audit & global order listing, cannot settle
    assert api_client.get_audit_logs(analyst_token).status_code == 200
    all_orders_resp = api_client.list_orders(analyst_token, all_users=True)
    assert all_orders_resp.status_code == 200
    assert any(o["id"] == order_id for o in all_orders_resp.json())
    assert api_client.settle_order(analyst_token, order_id).status_code == 403

    # Admin: can settle and view audit logs
    settle_resp = api_client.settle_order(admin_token, order_id)
    assert settle_resp.status_code == 200
    assert settle_resp.json()["status"] == "SETTLED"
    assert api_client.get_audit_logs(admin_token).status_code == 200
