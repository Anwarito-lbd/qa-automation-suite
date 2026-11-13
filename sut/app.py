"""FastAPI System Under Test (AegisPay FinTech Ledger & Order Sandbox)."""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sut.config import SutSettings
from sut.database import (
    DuplicateEmailError,
    ForbiddenError,
    IdempotencyConflictError,
    InsufficientFundsError,
    InvalidStateTransitionError,
    LedgerDatabase,
    NotFoundError,
)
from sut.models import (
    AccountSummaryResponse,
    AuditLogEntry,
    CreateOrderRequest,
    DepositRequest,
    HealthResponse,
    LoginRequest,
    OrderResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    UserRole,
)
from sut.rate_limit import SlidingWindowRateLimiter
from sut.security import (
    canonical_payload_hash,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def enforce_rate_limit(request: Request, response: Response) -> None:
    """Apply sliding-window rate limiting using the app's configured limiter."""
    limiter: SlidingWindowRateLimiter = request.app.state.limiter
    client_host = request.client.host if request.client else "testclient"
    key = f"{client_host}:{request.url.path}"
    decision = limiter.check(key)
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Retry later.",
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )


def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> UserResponse:
    """Authenticate Bearer JWT and load the corresponding user from SQLite."""
    cfg: SutSettings = request.app.state.settings
    db: LedgerDatabase = request.app.state.db

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Bearer token",
        )
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = decode_access_token(token, secret=cfg.jwt_secret)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    user_id = str(claims.get("sub", ""))
    user = db.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User referenced by token no longer exists",
        )
    return user


def require_roles(*allowed_roles: UserRole) -> Callable[[UserResponse], UserResponse]:
    """Build a FastAPI dependency enforcing RBAC role membership."""

    def dependency(user: Annotated[UserResponse, Depends(get_current_user)]) -> UserResponse:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' is not authorized for this resource",
            )
        return user

    return dependency


def create_app(
    settings: SutSettings | None = None,
    clock: Callable[[], float] | None = None,
) -> FastAPI:
    """Create a fresh isolated FastAPI SUT instance."""
    cfg = settings or SutSettings()
    db = LedgerDatabase(db_path=cfg.db_path)
    limiter = SlidingWindowRateLimiter(
        max_requests=cfg.rate_limit_max_requests,
        window_seconds=cfg.rate_limit_window_seconds,
        clock=clock or time.monotonic,
    )

    app = FastAPI(
        title="AegisPay Sandbox SUT",
        version="1.0.0",
        description="Deterministic FinTech Order, Auth, and Ledger Sandbox for Multi-Layer QA.",
    )
    app.state.settings = cfg
    app.state.db = db
    app.state.limiter = limiter

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def serve_portal() -> FileResponse:
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Web portal static bundle missing")
        return FileResponse(index_path)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        users_count, orders_count = db.get_counts()
        return HealthResponse(
            status="ok",
            service="aegispay-sut",
            version="1.0.0",
            users_count=users_count,
            orders_count=orders_count,
        )

    @app.post(
        "/api/v1/auth/register",
        response_model=TokenResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(enforce_rate_limit)],
        tags=["auth"],
    )
    def register(
        payload: RegisterRequest,
        x_admin_provision_key: Annotated[str | None, Header()] = None,
    ) -> TokenResponse:
        if payload.role != UserRole.CUSTOMER and (
            not x_admin_provision_key
            or not hmac.compare_digest(x_admin_provision_key, cfg.admin_provision_key)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Elevated role provisioning requires valid X-Admin-Provision-Key",
            )

        pw_hash = hash_password(payload.password, iterations=cfg.pbkdf2_iterations)
        try:
            user = db.create_user(
                email=payload.email,
                full_name=payload.full_name,
                password_hash=pw_hash,
                role=payload.role,
            )
        except DuplicateEmailError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role.value,
            secret=cfg.jwt_secret,
            ttl_seconds=cfg.jwt_ttl_seconds,
        )
        return TokenResponse(access_token=token, user=user)

    @app.post(
        "/api/v1/auth/login",
        response_model=TokenResponse,
        dependencies=[Depends(enforce_rate_limit)],
        tags=["auth"],
    )
    def login(payload: LoginRequest) -> TokenResponse:
        record = db.get_user_credentials(payload.email)
        if record is None or not verify_password(payload.password, record[1]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        user = record[0]
        token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=user.role.value,
            secret=cfg.jwt_secret,
            ttl_seconds=cfg.jwt_ttl_seconds,
        )
        return TokenResponse(access_token=token, user=user)

    @app.get("/api/v1/auth/me", response_model=UserResponse, tags=["auth"])
    def get_me(user: Annotated[UserResponse, Depends(get_current_user)]) -> UserResponse:
        return user

    @app.get("/api/v1/accounts/me", response_model=AccountSummaryResponse, tags=["accounts"])
    def get_account(
        user: Annotated[UserResponse, Depends(get_current_user)],
    ) -> AccountSummaryResponse:
        return db.get_account_summary(user.id)

    @app.post(
        "/api/v1/accounts/deposit",
        response_model=AccountSummaryResponse,
        dependencies=[Depends(enforce_rate_limit)],
        tags=["accounts"],
    )
    def deposit_funds(
        payload: DepositRequest,
        user: Annotated[UserResponse, Depends(get_current_user)],
    ) -> AccountSummaryResponse:
        try:
            return db.deposit(
                user_id=user.id,
                amount_cents=payload.amount_cents,
                reference=payload.reference,
                max_deposit_cents=cfg.max_deposit_cents,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @app.post(
        "/api/v1/orders",
        response_model=OrderResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(enforce_rate_limit)],
        tags=["orders"],
    )
    def create_order(
        payload: CreateOrderRequest,
        response: Response,
        user: Annotated[UserResponse, Depends(get_current_user)],
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> OrderResponse:
        if payload.amount_cents > cfg.max_order_cents:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Order exceeds max_order_cents={cfg.max_order_cents}",
            )

        cleaned_idem: str | None = None
        if idempotency_key is not None:
            cleaned_idem = idempotency_key.strip()
            if not cleaned_idem or len(cleaned_idem) > 128:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Idempotency-Key must be 1..128 non-whitespace characters",
                )

        req_hash = canonical_payload_hash(payload.model_dump(mode="json"))
        try:
            order, code, replayed = db.create_order(
                user_id=user.id,
                recipient=payload.recipient,
                amount_cents=payload.amount_cents,
                currency=payload.currency,
                memo=payload.memo,
                idempotency_key=cleaned_idem,
                request_hash=req_hash,
            )
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except InsufficientFundsError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

        response.status_code = code
        response.headers["X-Idempotency-Replayed"] = "true" if replayed else "false"
        return order

    @app.get("/api/v1/orders", response_model=list[OrderResponse], tags=["orders"])
    def list_orders(
        user: Annotated[UserResponse, Depends(get_current_user)],
        all_users: bool = False,
    ) -> list[OrderResponse]:
        if all_users and user.role not in (UserRole.ADMIN, UserRole.ANALYST):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin or analyst roles can list all users' orders",
            )
        return db.list_orders(user_id=user.id, include_all=all_users)

    @app.get("/api/v1/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
    def get_order(
        order_id: str,
        user: Annotated[UserResponse, Depends(get_current_user)],
    ) -> OrderResponse:
        try:
            return db.get_order(order_id=order_id, actor_id=user.id, actor_role=user.role)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ForbiddenError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    @app.post("/api/v1/orders/{order_id}/cancel", response_model=OrderResponse, tags=["orders"])
    def cancel_order(
        order_id: str,
        user: Annotated[UserResponse, Depends(get_current_user)],
    ) -> OrderResponse:
        try:
            return db.cancel_order(order_id=order_id, actor_id=user.id, actor_role=user.role)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ForbiddenError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except InvalidStateTransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.post(
        "/api/v1/admin/orders/{order_id}/settle",
        response_model=OrderResponse,
        tags=["admin"],
    )
    def settle_order(
        order_id: str,
        admin: Annotated[UserResponse, Depends(require_roles(UserRole.ADMIN))],
    ) -> OrderResponse:
        try:
            return db.settle_order(order_id=order_id, admin_id=admin.id)
        except NotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidStateTransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @app.get("/api/v1/audit/logs", response_model=list[AuditLogEntry], tags=["audit"])
    def get_audit_logs(
        _: Annotated[UserResponse, Depends(require_roles(UserRole.ANALYST, UserRole.ADMIN))],
        limit: int = 100,
    ) -> list[AuditLogEntry]:
        bounded_limit = max(1, min(limit, 500))
        return db.list_audit_logs(limit=bounded_limit)

    return app


app = create_app()
