"""Authentication behind an ``AuthProvider`` interface, plus FastAPI dependencies.

JWT is the current provider. An OIDC provider can implement the same interface and
return the same ``Principal``; nothing downstream changes.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker, set_tenant
from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import Permission, Role, has_permission
from app.core.security import InvalidTokenError, decode_token


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role

    def can(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)


class AuthProvider(Protocol):
    async def authenticate(self, token: str) -> Principal: ...


class JWTAuthProvider:
    async def authenticate(self, token: str) -> Principal:
        try:
            claims = decode_token(token, "access")
            return Principal(claims.user_id, claims.tenant_id, Role(claims.role))
        except (InvalidTokenError, ValueError) as exc:
            raise Unauthorized("Invalid or expired token") from exc


def get_auth_provider() -> AuthProvider:
    return JWTAuthProvider()


_bearer = HTTPBearer(auto_error=False)


async def get_principal(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    provider: Annotated[AuthProvider, Depends(get_auth_provider)],
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthorized("Not authenticated")
    return await provider.authenticate(creds.credentials)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(permission: Permission) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory: ``Depends(require(Permission.AUDIT_READ))``."""

    async def _check(principal: CurrentPrincipal) -> Principal:
        if not principal.can(permission):
            raise Forbidden(f"Your role ({principal.role}) cannot do this ({permission}).")
        return principal

    return _check


async def get_db(principal: CurrentPrincipal, request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request, bound to the caller's tenant (RLS) and user.

    Used with ``scope="function"`` so the commit finishes BEFORE the response is sent:
    a failed commit becomes an error response, never a false success.
    """
    async with get_sessionmaker()() as session, session.begin():
        await set_tenant(session, principal.tenant_id)
        await session.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(principal.user_id)}
        )
        request.state.principal = principal
        yield session


TenantDB = Annotated[AsyncSession, Depends(get_db, scope="function")]
