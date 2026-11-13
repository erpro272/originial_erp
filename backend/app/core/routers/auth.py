"""Auth endpoints. The refresh token lives in an httpOnly cookie, never in JS."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response

from app.core.auth import CurrentPrincipal, TenantDB
from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.core.schemas import LoginRequest, MeResponse, SwitchCompanyRequest, TokenResponse
from app.core.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "erp_refresh"
COOKIE_PATH = "/api/auth"


def _respond(response: Response, tokens: svc.IssuedTokens) -> TokenResponse:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=s.refresh_token_ttl_seconds,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(access_token=tokens.access_token, expires_in=s.access_token_ttl_seconds)


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> TokenResponse:
    ip = request.client.host if request.client else "unknown"
    tokens = await svc.login(body.email, body.password, body.tenant_id, ip)
    return _respond(response, tokens)


@router.post("/refresh")
async def refresh(
    response: Response, erp_refresh: Annotated[str | None, Cookie()] = None
) -> TokenResponse:
    if not erp_refresh:
        raise Unauthorized("Not signed in.")
    return _respond(response, await svc.refresh(erp_refresh))


@router.post("/switch-company")
async def switch_company(
    body: SwitchCompanyRequest, principal: CurrentPrincipal, response: Response
) -> TokenResponse:
    return _respond(response, await svc.switch_company(principal.user_id, body.tenant_id))


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


@router.post("/logout-all", status_code=204)
async def logout_all(principal: CurrentPrincipal, db: TenantDB, response: Response) -> None:
    await svc.logout_everywhere(db, principal.user_id)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


@router.get("/me")
async def me(principal: CurrentPrincipal, db: TenantDB) -> MeResponse:
    return await svc.me(db, principal.user_id, principal.tenant_id)
