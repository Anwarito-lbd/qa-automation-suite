"""Typed API client helper for Layer 1 contract testing and Layer 2/3 test seeding."""

from __future__ import annotations

from typing import Any

import httpx


class AegisApiClient:
    """Thin typed wrapper over httpx / FastAPI TestClient for AegisPay SUT."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @staticmethod
    def auth_headers(token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {token}"}
        if extra:
            headers.update(extra)
        return headers

    def register(
        self,
        *,
        email: str,
        full_name: str,
        password: str,
        role: str = "customer",
        admin_provision_key: str | None = None,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if admin_provision_key is not None:
            headers["X-Admin-Provision-Key"] = admin_provision_key
        return self._client.post(
            "/api/v1/auth/register",
            headers=headers,
            json={
                "email": email,
                "full_name": full_name,
                "password": password,
                "role": role,
            },
        )

    def login(self, *, email: str, password: str) -> httpx.Response:
        return self._client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )

    def get_me(self, token: str) -> httpx.Response:
        return self._client.get("/api/v1/auth/me", headers=self.auth_headers(token))

    def get_account(self, token: str) -> httpx.Response:
        return self._client.get("/api/v1/accounts/me", headers=self.auth_headers(token))

    def deposit(
        self,
        token: str,
        *,
        amount_cents: int,
        reference: str = "qa-seed",
    ) -> httpx.Response:
        return self._client.post(
            "/api/v1/accounts/deposit",
            headers=self.auth_headers(token),
            json={"amount_cents": amount_cents, "reference": reference},
        )

    def create_order(
        self,
        token: str,
        *,
        recipient: str,
        amount_cents: int,
        currency: str = "USD",
        memo: str = "",
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        extra: dict[str, str] = {}
        if idempotency_key is not None:
            extra["Idempotency-Key"] = idempotency_key
        return self._client.post(
            "/api/v1/orders",
            headers=self.auth_headers(token, extra),
            json={
                "recipient": recipient,
                "amount_cents": amount_cents,
                "currency": currency,
                "memo": memo,
            },
        )

    def list_orders(self, token: str, *, all_users: bool = False) -> httpx.Response:
        return self._client.get(
            "/api/v1/orders",
            params={"all_users": str(all_users).lower()},
            headers=self.auth_headers(token),
        )

    def get_order(self, token: str, order_id: str) -> httpx.Response:
        return self._client.get(f"/api/v1/orders/{order_id}", headers=self.auth_headers(token))

    def cancel_order(self, token: str, order_id: str) -> httpx.Response:
        return self._client.post(
            f"/api/v1/orders/{order_id}/cancel",
            headers=self.auth_headers(token),
        )

    def settle_order(self, token: str, order_id: str) -> httpx.Response:
        return self._client.post(
            f"/api/v1/admin/orders/{order_id}/settle",
            headers=self.auth_headers(token),
        )

    def get_audit_logs(self, token: str, *, limit: int = 100) -> httpx.Response:
        return self._client.get(
            "/api/v1/audit/logs",
            params={"limit": limit},
            headers=self.auth_headers(token),
        )

    def register_and_get_token(
        self,
        *,
        email: str,
        full_name: str = "QA Test User",
        password: str = "StrongPass123!",  # noqa: S107
        role: str = "customer",
        admin_provision_key: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        resp = self.register(
            email=email,
            full_name=full_name,
            password=password,
            role=role,
            admin_provision_key=admin_provision_key,
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        return str(body["access_token"]), dict(body["user"])
