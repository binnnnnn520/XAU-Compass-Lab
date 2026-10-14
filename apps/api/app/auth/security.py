from __future__ import annotations

import base64
from datetime import timedelta
import hashlib
import hmac
import json
import os
import secrets
from typing import Any
from uuid import UUID

from app.auth.models import User
from app.database import utcnow


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310_000
TOKEN_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=7)
TOKEN_TTL = ACCESS_TOKEN_TTL


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _token_secret() -> bytes:
    return os.getenv("AUTH_TOKEN_SECRET", "phase3-auth-local-development-secret").encode("utf-8")


def _json_b64(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64encode(encoded)


def _sign(unsigned_token: str) -> str:
    signature = hmac.new(_token_secret(), unsigned_token.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(signature)


def _create_token(user: User, *, token_type: str, ttl: timedelta) -> str:
    issued_at = utcnow()
    expires_at = issued_at + ttl
    roles = [role.name for role in user.roles]
    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "roles": roles,
        "typ": token_type,
        "jti": secrets.token_urlsafe(16),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    unsigned = f"{_json_b64(header)}.{_json_b64(payload)}"
    return f"{unsigned}.{_sign(unsigned)}"


def create_access_token(user: User) -> str:
    return _create_token(user, token_type="access", ttl=ACCESS_TOKEN_TTL)


def create_refresh_token(user: User) -> str:
    return _create_token(user, token_type="refresh", ttl=REFRESH_TOKEN_TTL)


def _verify_token(token: str, *, expected_type: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_raw, payload_raw, signature = parts
    unsigned = f"{header_raw}.{payload_raw}"
    if not hmac.compare_digest(_sign(unsigned), signature):
        return None

    try:
        header = json.loads(_b64decode(header_raw))
        payload = json.loads(_b64decode(payload_raw))
    except (ValueError, TypeError):
        return None

    if header.get("alg") != TOKEN_ALGORITHM:
        return None
    if payload.get("typ") != expected_type:
        return None
    if int(payload.get("exp", 0)) < int(utcnow().timestamp()):
        return None
    try:
        UUID(str(payload["sub"]))
    except (KeyError, ValueError, TypeError):
        return None
    return payload


def verify_access_token(token: str) -> dict[str, Any] | None:
    return _verify_token(token, expected_type="access")


def verify_refresh_token(token: str) -> dict[str, Any] | None:
    return _verify_token(token, expected_type="refresh")
