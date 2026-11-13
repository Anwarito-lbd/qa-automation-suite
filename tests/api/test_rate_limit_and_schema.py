"""Layer 1 API tests: Sliding-window rate limiting and OpenAPI schema invariants."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from qa_framework.api_client import AegisApiClient
from sut.app import create_app
from sut.config import SutSettings

pytestmark = pytest.mark.api


class FakeClock:
    def __init__(self, initial: float = 100.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_sliding_window_rate_limit_and_deterministic_recovery() -> None:
    clock = FakeClock()
    settings = SutSettings(
        db_path=":memory:",
        rate_limit_max_requests=3,
        rate_limit_window_seconds=10.0,
        pbkdf2_iterations=1_000,
    )
    app = create_app(settings=settings, clock=clock)
    try:
        with TestClient(app) as client:
            api = AegisApiClient(client)
            api.register(email="rl@aegispay.dev", full_name="RL User", password="Password123!")

            for expected_remaining in (2, 1, 0):
                resp = api.login(email="rl@aegispay.dev", password="Password123!")
                assert resp.status_code == 200
                assert resp.headers["X-RateLimit-Limit"] == "3"
                assert resp.headers["X-RateLimit-Remaining"] == str(expected_remaining)

            blocked = api.login(email="rl@aegispay.dev", password="Password123!")
            assert blocked.status_code == 429
            assert int(blocked.headers["Retry-After"]) >= 1

            # Advance deterministic clock past 10s window
            clock.advance(10.5)
            recovered = api.login(email="rl@aegispay.dev", password="Password123!")
            assert recovered.status_code == 200
            assert recovered.headers["X-RateLimit-Remaining"] == "2"
    finally:
        app.state.db.close()


def test_openapi_schema_and_health_telemetry(api_client: AegisApiClient) -> None:
    schema_resp = api_client._client.get("/openapi.json")
    assert schema_resp.status_code == 200
    spec = schema_resp.json()
    expected_paths = {
        "/health",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/accounts/me",
        "/api/v1/accounts/deposit",
        "/api/v1/orders",
        "/api/v1/orders/{order_id}",
        "/api/v1/orders/{order_id}/cancel",
        "/api/v1/admin/orders/{order_id}/settle",
        "/api/v1/audit/logs",
    }
    assert expected_paths.issubset(set(spec["paths"].keys()))

    health_before = api_client._client.get("/health").json()
    assert health_before["status"] == "ok"
    assert health_before["users_count"] == 0
    assert health_before["orders_count"] == 0

    token, _ = api_client.register_and_get_token(email="health@aegispay.dev")
    api_client.deposit(token, amount_cents=5_000)
    api_client.create_order(token, recipient="peer@aegispay.dev", amount_cents=1_500)

    health_after = api_client._client.get("/health").json()
    assert health_after["users_count"] == 1
    assert health_after["orders_count"] == 1
