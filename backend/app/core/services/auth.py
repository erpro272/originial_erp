"""Login, token refresh and the /me view."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.db import get_sessionmaker, set_tenant
from app.core.errors import Forbidden, TooManyRequests, Unauthorized
from app.core.models import Membership, Tenant, User
from app.core.permissions import ROLE_PERMISSIONS, Role
from app.core.redis import get_redis
from app.core.schemas import CompanyOut, MeResponse
from app.core.security import (
    InvalidTokenError,
    create_token,
    decode_token,
    verify_password,
)

LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 15 * 60


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str


async def _bind_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Lets the memberships/tenants RLS policies show this user's own rows."""
    await session.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})


async def _companies(session: AsyncSession, user_id: uuid.UUID) -> list[CompanyOut]:
    rows = await session.execute(
        select(Tenant.id, Tenant.name, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == user_id, Membership.is_active, Tenant.is_active)
        .order_by(Tenant.name)
    )
    return [CompanyOut(id=r.id, name=r.name, role=Role(r.role)) for r in rows]


async def _rate_limit(key: str) -> None:
    redis = get_redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, LOGIN_WINDOW_SECONDS)
    if count > LOGIN_MAX_ATTEMPTS:
        raise TooManyRequests("Too many sign-in attempts. Try again in 15 minutes.")


def _issue(user: User, company: CompanyOut) -> IssuedTokens:
    role = company.role.value
    return IssuedTokens(
        access_token=create_token(user_id=user.id, tenant_id=company.id, role=role, typ="access"),
        refresh_token=create_token(
            user_id=user.id, tenant_id=company.id, role=role, typ="refresh", ver=user.token_version
        ),
    )


async def login(email: str, password: str, tenant_id: uuid.UUID | None, client_ip: str) -> IssuedTokens:
    email = email.strip().lower()
    await _rate_limit(f"login:{client_ip}:{email}")
    async with get_sessionmaker()() as session, session.begin():
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not verify_password(password, user.password_hash if user else None) or user is None:
            raise Unauthorized("Email or password is incorrect.")
        if not user.is_active:
            raise Unauthorized("This account is disabled.")
        await _bind_user(session, user.id)
        companies = await _companies(session, user.id)
        if not companies:
            raise Forbidden("Your account is not a member of any active company.")
        if tenant_id is None:
            if len(companies) > 1:
                raise Forbidden(
                    "Choose a company to sign in to.",
                    details={"companies": [c.model_dump(mode="json") for c in companies]},
                )
            company = companies[0]
        else:
            match = [c for c in companies if c.id == tenant_id]
            if not match:
                raise Forbidden("You are not a member of that company.")
            company = match[0]
        await set_tenant(session, company.id)
        await audit.record(session, actor_id=user.id, action="login", entity_type="user", entity_id=user.id)
        tokens = _issue(user, company)
    await get_redis().delete(f"login:{client_ip}:{email}")
    return tokens


async def refresh(refresh_token: str) -> IssuedTokens:
    try:
        claims = decode_token(refresh_token, "refresh")
    except InvalidTokenError as exc:
        raise Unauthorized("Session expired. Please sign in again.") from exc
    return await _reissue(claims.user_id, claims.tenant_id, token_version=claims.ver)


async def _reissue(user_id: uuid.UUID, tenant_id: uuid.UUID, token_version: int | None) -> IssuedTokens:
    """Re-check the user and the membership on every refresh (role changes apply)."""
    async with get_sessionmaker()() as session, session.begin():
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            raise Unauthorized("Session expired. Please sign in again.")
        if token_version is not None and token_version != user.token_version:
            raise Unauthorized("Session expired. Please sign in again.")
        await _bind_user(session, user.id)
        match = [c for c in await _companies(session, user.id) if c.id == tenant_id]
        if not match:
            raise Forbidden("You are not a member of that company.")
        return _issue(user, match[0])


async def logout_everywhere(session: AsyncSession, user_id: uuid.UUID) -> None:
    user = await session.get(User, user_id)
    if user is not None:
        user.token_version += 1
        await audit.record(
            session, actor_id=user_id, action="logout_all", entity_type="user", entity_id=user_id
        )


async def me(session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID) -> MeResponse:
    user = await session.get(User, user_id)
    if user is None:
        raise Unauthorized("Not authenticated")
    companies = await _companies(session, user_id)
    current = next((c for c in companies if c.id == tenant_id), None)
    if current is None:
        raise Forbidden("You are no longer a member of this company.")
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=current.role,
        company=current,
        companies=companies,
        permissions=sorted(ROLE_PERMISSIONS[current.role]),
    )
