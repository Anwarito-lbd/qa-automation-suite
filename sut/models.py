"""Pydantic v2 request and response schemas for AegisPay SUT."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
CONTROL_CHARS_REGEX = re.compile(r"[\x00-\x1f\x7f]")


class UserRole(StrEnum):
    CUSTOMER = "customer"
    ANALYST = "analyst"
    ADMIN = "admin"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class CurrencyCode(StrEnum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


def _reject_control_chars(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if CONTROL_CHARS_REGEX.search(cleaned):
        raise ValueError(f"{field_name} must not contain control characters")
    return cleaned


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=5, max_length=120)
    full_name: str = Field(..., min_length=2, max_length=80)
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = Field(default=UserRole.CUSTOMER)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        cleaned = _reject_control_chars(value, "email").lower()
        if not EMAIL_REGEX.match(cleaned):
            raise ValueError("Invalid email address format")
        return cleaned

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        cleaned = _reject_control_chars(value, "full_name")
        if len(cleaned) < 2:
            raise ValueError("full_name must be at least 2 characters")
        return cleaned


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _reject_control_chars(value, "email").lower()


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    balance_cents: int
    created_at: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class DepositRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: int = Field(..., gt=0, le=10_000_000)
    reference: str = Field(default="manual-topup", min_length=1, max_length=64)

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        cleaned = _reject_control_chars(value, "reference")
        if not cleaned:
            raise ValueError("reference must not be blank")
        return cleaned


class AccountSummaryResponse(BaseModel):
    user_id: str
    email: str
    role: UserRole
    balance_cents: int
    total_deposited_cents: int
    pending_orders_cents: int
    settled_orders_cents: int


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str = Field(..., min_length=2, max_length=80)
    amount_cents: int = Field(..., gt=0, le=5_000_000)
    currency: CurrencyCode = Field(default=CurrencyCode.USD)
    memo: str = Field(default="", max_length=140)

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, value: str) -> str:
        cleaned = _reject_control_chars(value, "recipient")
        if len(cleaned) < 2:
            raise ValueError("recipient must be at least 2 characters")
        return cleaned

    @field_validator("memo")
    @classmethod
    def validate_memo(cls, value: str) -> str:
        return _reject_control_chars(value, "memo")


class OrderResponse(BaseModel):
    id: str
    user_id: str
    recipient: str
    amount_cents: int
    currency: CurrencyCode
    memo: str
    status: OrderStatus
    idempotency_key: str | None
    created_at: str
    updated_at: str


class AuditLogEntry(BaseModel):
    id: int
    actor_id: str
    action: str
    target_id: str
    detail: str
    created_at: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    users_count: int
    orders_count: int
