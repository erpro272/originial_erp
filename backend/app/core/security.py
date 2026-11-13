"""Password hashing (argon2id) and JWT encoding/decoding."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()
# Used to keep login timing similar whether or not the email exists.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    typ: TokenType
    ver: int


def create_token(
    *, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str, typ: TokenType, ver: int = 0
) -> str:
    s = get_settings()
    ttl = s.access_token_ttl_seconds if typ == "access" else s.refresh_token_ttl_seconds
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "iss": s.jwt_issuer,
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role,
        "typ": typ,
        "ver": ver,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256")


class InvalidTokenError(Exception):
    pass


def decode_token(token: str, expected: TokenType) -> TokenClaims:
    s = get_settings()
    try:
        data = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=s.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "tid", "typ"]},
        )
        if data["typ"] != expected:
            raise InvalidTokenError("wrong token type")
        return TokenClaims(
            user_id=uuid.UUID(data["sub"]),
            tenant_id=uuid.UUID(data["tid"]),
            role=data["role"],
            typ=data["typ"],
            ver=int(data.get("ver", 0)),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(str(exc)) from exc
