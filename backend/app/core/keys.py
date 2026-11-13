"""Per-tenant data keys: create, load (unwrap) and cache ``TenantCipher`` objects."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import KeyProvider, TenantCipher, get_key_provider, new_data_key
from app.core.models import TenantKey

# Unwrapped DEKs cached per process. Small (32 bytes each) and never logged.
_cache: dict[uuid.UUID, TenantCipher] = {}


async def create_tenant_key(
    session: AsyncSession, tenant_id: uuid.UUID, provider: KeyProvider | None = None
) -> None:
    """Generate and store a wrapped DEK. Session must already be bound to ``tenant_id``."""
    provider = provider or get_key_provider()
    wrapped = provider.wrap(new_data_key(), tenant_id)
    session.add(TenantKey(tenant_id=tenant_id, version=1, wrapped_key=wrapped, is_active=True))
    await session.flush()


async def get_cipher(session: AsyncSession, tenant_id: uuid.UUID) -> TenantCipher:
    """Return the tenant's cipher. RLS guarantees only the bound tenant's key is readable."""
    if (cached := _cache.get(tenant_id)) is not None:
        return cached
    row = (
        await session.execute(select(TenantKey).where(TenantKey.tenant_id == tenant_id, TenantKey.is_active))
    ).scalar_one()
    cipher = TenantCipher(tenant_id, get_key_provider().unwrap(row.wrapped_key, tenant_id))
    _cache[tenant_id] = cipher
    return cipher


def clear_cache() -> None:
    _cache.clear()
