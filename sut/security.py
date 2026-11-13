"""Authentication, password hashing, JWT tokens, and canonical payload hashing."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

import jwt


def hash_password(password: str, *, iterations: int = 12_000) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a 16-byte random salt."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password against a stored PBKDF2-HMAC-SHA256 string."""
    try:
        scheme, iter_str, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False

    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(computed, expected)


def create_access_token(
    *,
    user_id: str,
    email: str,
    role: str,
    secret: str,
    ttl_seconds: int = 3600,
    now: int | None = None,
) -> str:
    """Mint a signed HS256 JWT access token."""
    issued_at = int(time.time()) if now is None else now
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    """Validate and decode an HS256 JWT access token."""
    decoded = jwt.decode(token, secret, algorithms=["HS256"])
    if not isinstance(decoded, dict):
        raise jwt.InvalidTokenError("Malformed JWT payload")
    return decoded


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 digest of a JSON request payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
