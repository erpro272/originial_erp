import contextlib

from fastapi import APIRouter
from sqlalchemy import text

from app.ai.service import get_ai_client
from app.core.db import get_engine
from app.core.redis import get_redis
from app.core.schemas import HealthOut
from app.core.storage import get_storage

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> HealthOut:
    db = redis_ok = False
    with contextlib.suppress(Exception):  # health reports problems, never raises
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        db = True
    with contextlib.suppress(Exception):
        redis_ok = bool(await get_redis().ping())
    storage = await get_storage().ping()
    ok = db and redis_ok and storage
    return HealthOut(
        status="ok" if ok else "degraded",
        database=db,
        redis=redis_ok,
        storage=storage,
        ai_mode=get_ai_client().mode,
    )
