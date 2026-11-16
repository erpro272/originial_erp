from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.auth import Principal, TenantDB, require
from app.core.permissions import Permission
from app.dashboard import service
from app.dashboard.schemas import DashboardOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


Owner = Annotated[Principal, Depends(require(Permission.DASHBOARD_READ))]


@router.get("", response_model=DashboardOut)
async def overview(
    db: TenantDB,
    _: Owner,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> DashboardOut:
    """The owner's consolidated view for a date range (default: this week and next)."""
    return await service.overview(db, date_from, date_to)
