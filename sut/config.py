"""Configuration for the AegisPay FinTech Sandbox SUT."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SutSettings:
    """Immutable configuration settings for a SUT instance."""

    db_path: str = ":memory:"
    jwt_secret: str = "aegispay-deterministic-dev-secret-key-32bytes"
    jwt_ttl_seconds: int = 3600
    admin_provision_key: str = "aegispay-provision-key"
    rate_limit_max_requests: int = 60
    rate_limit_window_seconds: float = 60.0
    max_deposit_cents: int = 10_000_000  # $100,000.00
    max_order_cents: int = 5_000_000  # $50,000.00
    pbkdf2_iterations: int = 12_000
