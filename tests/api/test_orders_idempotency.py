"""Layer 1 API tests: Order lifecycle, atomic ledger, and Idempotency-Key semantics."""

from __future__ import annotations

import pytest

from qa_framework.api_client import AegisApiClient
from sut.config import SutSettings

pytestmark = pytest.mark.api


def test_order_hold_cancel_and_refund_conservation(api_client: AegisApiClient) -> None:
    token, _ = api_client.register_and_get_token(email="orders@aegispay.dev")
    dep = api_client.deposit(token, amount_cents=25_000, reference="seed-topup")
    assert dep.status_code == 200
    assert dep.json()["balance_cents"] == 25_000

    created = api_client.create_order(
        token,
        recipient="cloud-provider@infra.dev",
        amount_cents=10_000,
        currency="USD",
        memo="Monthly compute",
    )
    assert created.status_code == 201
    order_id = created.json()["id"]
    assert created.json()["status"] == "PENDING"
    assert created.headers.get("X-Idempotency-Replayed") == "false"

    summary_after_hold = api_client.get_account(token).json()
    assert summary_after_hold["balance_cents"] == 15_000
    assert summary_after_hold["pending_orders_cents"] == 10_000

    cancelled = api_client.cancel_order(token, order_id)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    summary_after_cancel = api_client.get_account(token).json()
    assert summary_after_cancel["balance_cents"] == 25_000
    assert summary_after_cancel["pending_orders_cents"] == 0

    # Double cancellation is rejected as 409 Conflict
    assert api_client.cancel_order(token, order_id).status_code == 409


def test_insufficient_funds_rejected_without_mutating_balance(api_client: AegisApiClient) -> None:
    token, _ = api_client.register_and_get_token(email="lowbal@aegispay.dev")
    api_client.deposit(token, amount_cents=1_000)

    resp = api_client.create_order(token, recipient="merchant@acme.io", amount_cents=1_001)
    assert resp.status_code == 422
    assert api_client.get_account(token).json()["balance_cents"] == 1_000


def test_settled_order_cannot_be_cancelled(
    api_client: AegisApiClient, sut_settings: SutSettings
) -> None:
    cust_token, _ = api_client.register_and_get_token(email="cust.settle@aegispay.dev")
    admin_token, _ = api_client.register_and_get_token(
        email="adm.settle@aegispay.dev",
        role="admin",
        admin_provision_key=sut_settings.admin_provision_key,
    )
    api_client.deposit(cust_token, amount_cents=10_000)
    order_id = api_client.create_order(
        cust_token, recipient="supplier@acme.io", amount_cents=4_000
    ).json()["id"]

    assert api_client.settle_order(admin_token, order_id).status_code == 200
    assert api_client.cancel_order(cust_token, order_id).status_code == 409
    assert api_client.settle_order(admin_token, order_id).status_code == 409


def test_idempotency_key_replay_and_conflict(api_client: AegisApiClient) -> None:
    token, _ = api_client.register_and_get_token(email="idem@aegispay.dev")
    api_client.deposit(token, amount_cents=50_000)

    first = api_client.create_order(
        token,
        recipient="merchant@acme.io",
        amount_cents=15_000,
        currency="USD",
        memo="Order #1",
        idempotency_key="idem-key-001",
    )
    assert first.status_code == 201
    assert first.headers.get("X-Idempotency-Replayed") == "false"

    # Replay with exact same payload returns cached order without double-debiting
    replay = api_client.create_order(
        token,
        recipient="merchant@acme.io",
        amount_cents=15_000,
        currency="USD",
        memo="Order #1",
        idempotency_key="idem-key-001",
    )
    assert replay.status_code == 201
    assert replay.headers.get("X-Idempotency-Replayed") == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert api_client.get_account(token).json()["balance_cents"] == 35_000

    # Reusing same key with modified amount must fail with 409 Conflict
    conflict = api_client.create_order(
        token,
        recipient="merchant@acme.io",
        amount_cents=16_000,
        currency="USD",
        memo="Order #1",
        idempotency_key="idem-key-001",
    )
    assert conflict.status_code == 409
    assert api_client.get_account(token).json()["balance_cents"] == 35_000


def test_blank_idempotency_key_rejected_with_422(api_client: AegisApiClient) -> None:
    token, _ = api_client.register_and_get_token(email="blankidem@aegispay.dev")
    api_client.deposit(token, amount_cents=5_000)
    resp = api_client.create_order(
        token,
        recipient="merchant@acme.io",
        amount_cents=1_000,
        idempotency_key="   ",
    )
    assert resp.status_code == 422
