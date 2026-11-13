"""Layer 1 Hypothesis Property-Based Fuzzing & Stateful Shadow-Ledger Verification."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, precondition, rule

from qa_framework.api_client import AegisApiClient
from sut.app import create_app
from sut.config import SutSettings

pytestmark = [pytest.mark.api, pytest.mark.property]


@dataclass
class ShadowUser:
    token: str
    email: str
    balance_cents: int = 0
    total_deposited_cents: int = 0
    pending_cents: int = 0
    settled_cents: int = 0


@dataclass
class ShadowOrder:
    order_id: str
    user_idx: int
    amount_cents: int
    status: str  # PENDING | CANCELLED | SETTLED


@settings(max_examples=40, deadline=None)
@given(
    amount_cents=st.one_of(
        st.integers(max_value=0),
        st.integers(min_value=5_000_001, max_value=10_000_000_000),
    ),
    recipient=st.text(min_size=0, max_size=120),
    memo=st.text(min_size=0, max_size=200),
)
def test_fuzz_invalid_order_boundaries_never_500(
    amount_cents: int,
    recipient: str,
    memo: str,
) -> None:
    """Fuzzed out-of-range amounts and arbitrary unicode/control strings must never crash (500)."""
    app = create_app(
        settings=SutSettings(
            db_path=":memory:", rate_limit_max_requests=500, pbkdf2_iterations=1_000
        )
    )
    try:
        with TestClient(app) as client:
            api = AegisApiClient(client)
            token, _ = api.register_and_get_token(email=f"fuzz-{uuid.uuid4().hex[:8]}@aegispay.dev")
            api.deposit(token, amount_cents=100_000)
            resp = api.create_order(
                token,
                recipient=recipient,
                amount_cents=amount_cents,
                memo=memo,
            )
            assert resp.status_code in (400, 422)
            assert api.get_account(token).json()["balance_cents"] == 100_000
    finally:
        app.state.db.close()


@settings(max_examples=40, deadline=None)
@given(
    bad_email=st.one_of(
        st.text(min_size=0, max_size=40).filter(lambda s: "@" not in s or "\x00" in s),
        st.just("user@localhost"),
        st.just("a\n@b.com"),
    ),
    bad_password=st.text(min_size=0, max_size=7),
)
def test_fuzz_registration_validation_never_500(bad_email: str, bad_password: str) -> None:
    """Malformed emails and short/control passwords must cleanly return 422."""
    app = create_app(
        settings=SutSettings(
            db_path=":memory:", rate_limit_max_requests=500, pbkdf2_iterations=1_000
        )
    )
    try:
        with TestClient(app) as client:
            api = AegisApiClient(client)
            resp = api.register(
                email=bad_email,
                full_name="Fuzz User",
                password=bad_password,
            )
            assert resp.status_code == 422
    finally:
        app.state.db.close()


@settings(max_examples=30, deadline=None)
@given(
    recipient=st.sampled_from(
        [
            "merchant@acme.io",
            "'; DROP TABLE orders; --",
            "<script>alert('xss')</script>",
            "vendor-日本語-01",
        ]
    ),
    amount_cents=st.integers(min_value=1, max_value=50_000),
    idem_suffix=st.text(
        alphabet=st.characters(min_codepoint=48, max_codepoint=122),
        min_size=4,
        max_size=24,
    ),
)
def test_property_idempotent_order_replays_preserve_balance(
    recipient: str,
    amount_cents: int,
    idem_suffix: str,
) -> None:
    """Repeated idempotent submissions with identical payload debit the wallet exactly once."""
    app = create_app(
        settings=SutSettings(
            db_path=":memory:", rate_limit_max_requests=500, pbkdf2_iterations=1_000
        )
    )
    try:
        with TestClient(app) as client:
            api = AegisApiClient(client)
            token, _ = api.register_and_get_token(email="prop@aegispay.dev")
            api.deposit(token, amount_cents=100_000)

            idem_key = f"prop-{idem_suffix}"
            r1 = api.create_order(
                token,
                recipient=recipient,
                amount_cents=amount_cents,
                idempotency_key=idem_key,
            )
            r2 = api.create_order(
                token,
                recipient=recipient,
                amount_cents=amount_cents,
                idempotency_key=idem_key,
            )
            assert r1.status_code == 201
            assert r2.status_code == 201
            assert r1.json()["id"] == r2.json()["id"]
            assert r2.headers["X-Idempotency-Replayed"] == "true"
            assert api.get_account(token).json()["balance_cents"] == 100_000 - amount_cents
    finally:
        app.state.db.close()


class LedgerStateMachine(RuleBasedStateMachine):
    """Stateful model-based verification against a Python reference shadow ledger."""

    orders = Bundle("orders")

    def __init__(self) -> None:
        super().__init__()
        self._settings = SutSettings(
            db_path=":memory:",
            rate_limit_max_requests=10_000,
            pbkdf2_iterations=1_000,
        )
        self._app = create_app(settings=self._settings)
        self._client_cm = TestClient(self._app)
        self._raw_client = self._client_cm.__enter__()
        self.api = AegisApiClient(self._raw_client)

        self.admin_token, _ = self.api.register_and_get_token(
            email="stateful-admin@aegispay.dev",
            role="admin",
            admin_provision_key=self._settings.admin_provision_key,
        )
        self.users: list[ShadowUser] = []
        for idx in range(2):
            email = f"stateful-user-{idx}@aegispay.dev"
            token, _ = self.api.register_and_get_token(email=email)
            self.users.append(ShadowUser(token=token, email=email))

    def teardown(self) -> None:
        self._client_cm.__exit__(None, None, None)
        self._app.state.db.close()

    @rule(
        user_idx=st.integers(min_value=0, max_value=1),
        amount_cents=st.integers(min_value=1, max_value=20_000),
    )
    def deposit_funds(self, user_idx: int, amount_cents: int) -> None:
        user = self.users[user_idx]
        resp = self.api.deposit(user.token, amount_cents=amount_cents)
        assert resp.status_code == 200
        user.balance_cents += amount_cents
        user.total_deposited_cents += amount_cents

    @rule(
        target=orders,
        user_idx=st.integers(min_value=0, max_value=1),
        amount_cents=st.integers(min_value=1, max_value=25_000),
    )
    def create_order(self, user_idx: int, amount_cents: int) -> ShadowOrder:
        user = self.users[user_idx]
        resp = self.api.create_order(
            user.token,
            recipient="merchant@stateful.dev",
            amount_cents=amount_cents,
            idempotency_key=f"st-{uuid.uuid4().hex[:10]}",
        )
        if user.balance_cents >= amount_cents:
            assert resp.status_code == 201
            user.balance_cents -= amount_cents
            user.pending_cents += amount_cents
            return ShadowOrder(
                order_id=str(resp.json()["id"]),
                user_idx=user_idx,
                amount_cents=amount_cents,
                status="PENDING",
            )
        assert resp.status_code == 422
        return ShadowOrder(
            order_id="REJECTED", user_idx=user_idx, amount_cents=0, status="CANCELLED"
        )

    @rule(order=orders)
    @precondition(lambda self: True)
    def cancel_order(self, order: ShadowOrder) -> None:
        if order.order_id == "REJECTED":
            return
        user = self.users[order.user_idx]
        resp = self.api.cancel_order(user.token, order.order_id)
        if order.status == "PENDING":
            assert resp.status_code == 200
            assert resp.json()["status"] == "CANCELLED"
            order.status = "CANCELLED"
            user.balance_cents += order.amount_cents
            user.pending_cents -= order.amount_cents
        else:
            assert resp.status_code == 409

    @rule(order=orders)
    def settle_order(self, order: ShadowOrder) -> None:
        if order.order_id == "REJECTED":
            return
        user = self.users[order.user_idx]
        resp = self.api.settle_order(self.admin_token, order.order_id)
        if order.status == "PENDING":
            assert resp.status_code == 200
            assert resp.json()["status"] == "SETTLED"
            order.status = "SETTLED"
            user.pending_cents -= order.amount_cents
            user.settled_cents += order.amount_cents
        else:
            assert resp.status_code == 409

    @invariant()
    def conservation_of_money_and_non_negativity(self) -> None:
        for user in self.users:
            summary = self.api.get_account(user.token).json()
            assert summary["balance_cents"] >= 0
            assert summary["balance_cents"] == user.balance_cents
            assert summary["total_deposited_cents"] == user.total_deposited_cents
            assert summary["pending_orders_cents"] == user.pending_cents
            assert summary["settled_orders_cents"] == user.settled_cents
            assert (
                summary["balance_cents"]
                + summary["pending_orders_cents"]
                + summary["settled_orders_cents"]
                == summary["total_deposited_cents"]
            )


TestLedgerStateMachine = LedgerStateMachine.TestCase
TestLedgerStateMachine.settings = settings(max_examples=25, stateful_step_count=18, deadline=None)
