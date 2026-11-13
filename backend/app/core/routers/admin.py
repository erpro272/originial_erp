"""Audit log, tenant settings and per-user preferences."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.auth import CurrentPrincipal, Principal, TenantDB, require
from app.core.permissions import Permission
from app.core.schemas import AuditEntryOut, JsonValue, JsonValueIn, Page
from app.core.services import audit_query, kv

router = APIRouter(tags=["admin"])


@router.get("/audit-log")
async def audit_log(
    db: TenantDB,
    _: Annotated[Principal, Depends(require(Permission.AUDIT_READ))],
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditEntryOut]:
    rows, total = await audit_query.list_entries(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return Page[AuditEntryOut](
        items=[AuditEntryOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/settings/{key}")
async def get_setting(
    key: str, db: TenantDB, _: Annotated[Principal, Depends(require(Permission.SETTINGS_READ))]
) -> JsonValue:
    return JsonValue(key=key, value=await kv.get_setting(db, key))


@router.put("/settings/{key}")
async def put_setting(
    key: str,
    body: JsonValueIn,
    db: TenantDB,
    principal: Annotated[Principal, Depends(require(Permission.SETTINGS_WRITE))],
) -> JsonValue:
    return JsonValue(key=key, value=await kv.put_setting(db, principal.user_id, key, body.value))


@router.get("/me/preferences/{key}")
async def get_preference(key: str, db: TenantDB, principal: CurrentPrincipal) -> JsonValue:
    value = await kv.get_preference(db, principal.user_id, key)
    return JsonValue(key=key, value=value or {})


@router.put("/me/preferences/{key}")
async def put_preference(key: str, body: JsonValueIn, db: TenantDB, principal: CurrentPrincipal) -> JsonValue:
    return JsonValue(key=key, value=await kv.put_preference(db, principal.user_id, key, body.value))
