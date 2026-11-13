"""Deterministic SQLite ledger repository with atomic transactions and idempotency."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sut.models import (
    AccountSummaryResponse,
    AuditLogEntry,
    CurrencyCode,
    OrderResponse,
    OrderStatus,
    UserResponse,
    UserRole,
)


class DomainError(Exception):
    """Base domain exception."""


class DuplicateEmailError(DomainError):
    """Raised when attempting to register an existing email."""


class InvalidCredentialsError(DomainError):
    """Raised when login credentials fail verification."""


class NotFoundError(DomainError):
    """Raised when a requested resource does not exist."""


class ForbiddenError(DomainError):
    """Raised when an actor lacks ownership or role permission."""


class InsufficientFundsError(DomainError):
    """Raised when an account balance cannot cover an order amount."""


class InvalidStateTransitionError(DomainError):
    """Raised on illegal order state transitions."""


class IdempotencyConflictError(DomainError):
    """Raised when an Idempotency-Key is reused with a mismatched payload."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class LedgerDatabase:
    """Thread-safe SQLite repository for users, orders, ledger entries, and idempotency."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            if db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('customer', 'analyst', 'admin')),
                balance_cents INTEGER NOT NULL DEFAULT 0 CHECK(balance_cents >= 0),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                recipient TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                currency TEXT NOT NULL CHECK(currency IN ('USD', 'EUR', 'GBP')),
                memo TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING', 'SETTLED', 'CANCELLED')),
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ledger_entries (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                order_id TEXT,
                entry_type TEXT NOT NULL CHECK(
                    entry_type IN ('DEPOSIT', 'ORDER_HOLD', 'ORDER_RELEASE', 'ORDER_SETTLE')
                ),
                delta_cents INTEGER NOT NULL,
                balance_after_cents INTEGER NOT NULL CHECK(balance_after_cents >= 0),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS idempotency_records (
                user_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, endpoint, idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_id TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    def _row_to_user(self, row: sqlite3.Row) -> UserResponse:
        return UserResponse(
            id=str(row["id"]),
            email=str(row["email"]),
            full_name=str(row["full_name"]),
            role=UserRole(str(row["role"])),
            balance_cents=int(row["balance_cents"]),
            created_at=str(row["created_at"]),
        )

    def _row_to_order(self, row: sqlite3.Row) -> OrderResponse:
        return OrderResponse(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            recipient=str(row["recipient"]),
            amount_cents=int(row["amount_cents"]),
            currency=CurrencyCode(str(row["currency"])),
            memo=str(row["memo"]),
            status=OrderStatus(str(row["status"])),
            idempotency_key=str(row["idempotency_key"]) if row["idempotency_key"] else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _record_audit(self, actor_id: str, action: str, target_id: str, detail: str) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_logs (actor_id, action, target_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (actor_id, action, target_id, detail, _utc_now_iso()),
        )

    def create_user(
        self,
        *,
        email: str,
        full_name: str,
        password_hash: str,
        role: UserRole,
    ) -> UserResponse:
        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._conn.execute(
                    "SELECT id FROM users WHERE email = ?", (email,)
                ).fetchone()
                if existing is not None:
                    raise DuplicateEmailError(f"Email {email} is already registered")

                self._conn.execute(
                    """
                    INSERT INTO users
                    (id, email, full_name, password_hash, role, balance_cents, created_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (user_id, email, full_name, password_hash, role.value, now),
                )
                self._record_audit(user_id, "USER_REGISTER", user_id, f"role={role.value}")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            assert row is not None
            return self._row_to_user(row)

    def get_user_credentials(self, email: str) -> tuple[UserResponse, str] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row is None:
                return None
            return self._row_to_user(row), str(row["password_hash"])

    def get_user_by_id(self, user_id: str) -> UserResponse | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._row_to_user(row) if row is not None else None

    def deposit(
        self,
        *,
        user_id: str,
        amount_cents: int,
        reference: str,
        max_deposit_cents: int,
    ) -> AccountSummaryResponse:
        if amount_cents <= 0 or amount_cents > max_deposit_cents:
            raise ValueError(f"Deposit must be between 1 and {max_deposit_cents} cents")

        now = _utc_now_iso()
        entry_id = f"ldg_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                user_row = self._conn.execute(
                    "SELECT * FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                if user_row is None:
                    raise NotFoundError(f"User {user_id} not found")

                new_balance = int(user_row["balance_cents"]) + amount_cents
                self._conn.execute(
                    "UPDATE users SET balance_cents = ? WHERE id = ?",
                    (new_balance, user_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO ledger_entries
                    (id, user_id, order_id, entry_type, delta_cents,
                     balance_after_cents, created_at)
                    VALUES (?, ?, NULL, 'DEPOSIT', ?, ?, ?)
                    """,
                    (entry_id, user_id, amount_cents, new_balance, now),
                )
                self._record_audit(
                    user_id,
                    "ACCOUNT_DEPOSIT",
                    user_id,
                    f"amount_cents={amount_cents},ref={reference}",
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

        return self.get_account_summary(user_id)

    def get_account_summary(self, user_id: str) -> AccountSummaryResponse:
        with self._lock:
            user_row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if user_row is None:
                raise NotFoundError(f"User {user_id} not found")

            dep_row = self._conn.execute(
                """
                SELECT COALESCE(SUM(delta_cents), 0) AS total
                FROM ledger_entries
                WHERE user_id = ? AND entry_type = 'DEPOSIT'
                """,
                (user_id,),
            ).fetchone()
            pending_row = self._conn.execute(
                """
                SELECT COALESCE(SUM(amount_cents), 0) AS total
                FROM orders
                WHERE user_id = ? AND status = 'PENDING'
                """,
                (user_id,),
            ).fetchone()
            settled_row = self._conn.execute(
                """
                SELECT COALESCE(SUM(amount_cents), 0) AS total
                FROM orders
                WHERE user_id = ? AND status = 'SETTLED'
                """,
                (user_id,),
            ).fetchone()

            return AccountSummaryResponse(
                user_id=str(user_row["id"]),
                email=str(user_row["email"]),
                role=UserRole(str(user_row["role"])),
                balance_cents=int(user_row["balance_cents"]),
                total_deposited_cents=int(dep_row["total"]) if dep_row else 0,
                pending_orders_cents=int(pending_row["total"]) if pending_row else 0,
                settled_orders_cents=int(settled_row["total"]) if settled_row else 0,
            )

    def create_order(
        self,
        *,
        user_id: str,
        recipient: str,
        amount_cents: int,
        currency: CurrencyCode,
        memo: str,
        idempotency_key: str | None,
        request_hash: str,
    ) -> tuple[OrderResponse, int, bool]:
        """Create an order atomically, honoring optional Idempotency-Key.

        Returns `(order, status_code, replayed_from_cache)`.
        """
        endpoint = "POST:/api/v1/orders"
        now = _utc_now_iso()
        order_id = f"ord_{uuid.uuid4().hex[:12]}"
        entry_id = f"ldg_{uuid.uuid4().hex[:12]}"

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if idempotency_key is not None:
                    idem_row = self._conn.execute(
                        """
                        SELECT request_hash, status_code, response_json
                        FROM idempotency_records
                        WHERE user_id = ? AND endpoint = ? AND idempotency_key = ?
                        """,
                        (user_id, endpoint, idempotency_key),
                    ).fetchone()
                    if idem_row is not None:
                        if str(idem_row["request_hash"]) != request_hash:
                            raise IdempotencyConflictError(
                                "Idempotency-Key reused with a different request payload"
                            )
                        cached_payload: dict[str, Any] = json.loads(str(idem_row["response_json"]))
                        cached_order = OrderResponse.model_validate(cached_payload)
                        cached_status = int(idem_row["status_code"])
                        self._conn.execute("COMMIT")
                        return cached_order, cached_status, True

                user_row = self._conn.execute(
                    "SELECT * FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                if user_row is None:
                    raise NotFoundError(f"User {user_id} not found")

                current_balance = int(user_row["balance_cents"])
                if current_balance < amount_cents:
                    raise InsufficientFundsError(
                        f"Insufficient funds: available={current_balance}, required={amount_cents}"
                    )

                new_balance = current_balance - amount_cents
                self._conn.execute(
                    "UPDATE users SET balance_cents = ? WHERE id = ?",
                    (new_balance, user_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO orders
                    (id, user_id, recipient, amount_cents, currency, memo, status, idempotency_key,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
                    """,
                    (
                        order_id,
                        user_id,
                        recipient,
                        amount_cents,
                        currency.value,
                        memo,
                        idempotency_key,
                        now,
                        now,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO ledger_entries
                    (id, user_id, order_id, entry_type, delta_cents,
                     balance_after_cents, created_at)
                    VALUES (?, ?, ?, 'ORDER_HOLD', ?, ?, ?)
                    """,
                    (entry_id, user_id, order_id, -amount_cents, new_balance, now),
                )
                self._record_audit(
                    user_id,
                    "ORDER_CREATE",
                    order_id,
                    f"amount_cents={amount_cents},currency={currency.value}",
                )

                order_row = self._conn.execute(
                    "SELECT * FROM orders WHERE id = ?", (order_id,)
                ).fetchone()
                assert order_row is not None
                order = self._row_to_order(order_row)

                if idempotency_key is not None:
                    self._conn.execute(
                        """
                        INSERT INTO idempotency_records
                        (user_id, endpoint, idempotency_key, request_hash,
                         status_code, response_json, created_at)
                        VALUES (?, ?, ?, ?, 201, ?, ?)
                        """,
                        (
                            user_id,
                            endpoint,
                            idempotency_key,
                            request_hash,
                            order.model_dump_json(),
                            now,
                        ),
                    )

                self._conn.execute("COMMIT")
                return order, 201, False
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def list_orders(self, *, user_id: str, include_all: bool = False) -> list[OrderResponse]:
        with self._lock:
            if include_all:
                rows = self._conn.execute(
                    "SELECT * FROM orders ORDER BY created_at DESC, id DESC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                    (user_id,),
                ).fetchall()
            return [self._row_to_order(r) for r in rows]

    def get_order(self, *, order_id: str, actor_id: str, actor_role: UserRole) -> OrderResponse:
        with self._lock:
            row = self._conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"Order {order_id} not found")
            if str(row["user_id"]) != actor_id and actor_role not in (
                UserRole.ADMIN,
                UserRole.ANALYST,
            ):
                raise ForbiddenError("Cannot access another user's order")
            return self._row_to_order(row)

    def cancel_order(self, *, order_id: str, actor_id: str, actor_role: UserRole) -> OrderResponse:
        now = _utc_now_iso()
        entry_id = f"ldg_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                order_row = self._conn.execute(
                    "SELECT * FROM orders WHERE id = ?", (order_id,)
                ).fetchone()
                if order_row is None:
                    raise NotFoundError(f"Order {order_id} not found")

                owner_id = str(order_row["user_id"])
                if owner_id != actor_id and actor_role != UserRole.ADMIN:
                    raise ForbiddenError("Cannot cancel another user's order")

                current_status = OrderStatus(str(order_row["status"]))
                if current_status != OrderStatus.PENDING:
                    raise InvalidStateTransitionError(
                        f"Cannot cancel order in state {current_status.value}"
                    )

                amount_cents = int(order_row["amount_cents"])
                user_row = self._conn.execute(
                    "SELECT balance_cents FROM users WHERE id = ?", (owner_id,)
                ).fetchone()
                assert user_row is not None
                new_balance = int(user_row["balance_cents"]) + amount_cents

                self._conn.execute(
                    "UPDATE users SET balance_cents = ? WHERE id = ?",
                    (new_balance, owner_id),
                )
                self._conn.execute(
                    "UPDATE orders SET status = 'CANCELLED', updated_at = ? WHERE id = ?",
                    (now, order_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO ledger_entries
                    (id, user_id, order_id, entry_type, delta_cents,
                     balance_after_cents, created_at)
                    VALUES (?, ?, ?, 'ORDER_RELEASE', ?, ?, ?)
                    """,
                    (entry_id, owner_id, order_id, amount_cents, new_balance, now),
                )
                self._record_audit(actor_id, "ORDER_CANCEL", order_id, f"refund={amount_cents}")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

            updated = self._conn.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            assert updated is not None
            return self._row_to_order(updated)

    def settle_order(self, *, order_id: str, admin_id: str) -> OrderResponse:
        now = _utc_now_iso()
        entry_id = f"ldg_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                order_row = self._conn.execute(
                    "SELECT * FROM orders WHERE id = ?", (order_id,)
                ).fetchone()
                if order_row is None:
                    raise NotFoundError(f"Order {order_id} not found")

                current_status = OrderStatus(str(order_row["status"]))
                if current_status != OrderStatus.PENDING:
                    raise InvalidStateTransitionError(
                        f"Cannot settle order in state {current_status.value}"
                    )

                owner_id = str(order_row["user_id"])
                user_row = self._conn.execute(
                    "SELECT balance_cents FROM users WHERE id = ?", (owner_id,)
                ).fetchone()
                assert user_row is not None
                balance_after = int(user_row["balance_cents"])

                self._conn.execute(
                    "UPDATE orders SET status = 'SETTLED', updated_at = ? WHERE id = ?",
                    (now, order_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO ledger_entries
                    (id, user_id, order_id, entry_type, delta_cents,
                     balance_after_cents, created_at)
                    VALUES (?, ?, ?, 'ORDER_SETTLE', 0, ?, ?)
                    """,
                    (entry_id, owner_id, order_id, balance_after, now),
                )
                self._record_audit(admin_id, "ORDER_SETTLE", order_id, "status=SETTLED")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

            updated = self._conn.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            assert updated is not None
            return self._row_to_order(updated)

    def list_audit_logs(self, *, limit: int = 100) -> list[AuditLogEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [
                AuditLogEntry(
                    id=int(r["id"]),
                    actor_id=str(r["actor_id"]),
                    action=str(r["action"]),
                    target_id=str(r["target_id"]),
                    detail=str(r["detail"]),
                    created_at=str(r["created_at"]),
                )
                for r in rows
            ]

    def get_counts(self) -> tuple[int, int]:
        with self._lock:
            u = self._conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
            o = self._conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()
            return (int(u["c"]) if u else 0, int(o["c"]) if o else 0)
