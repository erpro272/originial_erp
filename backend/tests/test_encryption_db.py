"""Layer 2: per-tenant keys stored wrapped; one tenant can't use another's key."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from app.core import keys
from app.core.crypto import DecryptionError
from app.core.db import tenant_session
from app.core.models import TenantKey


async def test_each_tenant_has_distinct_wrapped_key(tenants) -> None:
    keys.clear_cache()
    async with tenant_session(tenants["demo"]) as s:
        a = await keys.get_cipher(s, tenants["demo"])
        wrapped = (await s.execute(select(TenantKey.wrapped_key))).scalar_one()
        assert len(wrapped) == 2 + 12 + 32 + 16  # version + nonce + key + tag
    async with tenant_session(tenants["second"]) as s:
        b = await keys.get_cipher(s, tenants["second"])
    blob = a.encrypt("123456784417", "bank_account")
    assert a.decrypt(blob, "bank_account") == "123456784417"
    with pytest.raises(DecryptionError):
        b.decrypt(blob, "bank_account")


async def test_cannot_load_another_tenants_key(tenants) -> None:
    keys.clear_cache()
    async with tenant_session(tenants["demo"]) as s:
        with pytest.raises(NoResultFound):  # RLS hides tenant 2's key row
            await keys.get_cipher(s, tenants["second"])
