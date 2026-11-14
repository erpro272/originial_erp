import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import create_token
from tests.conftest import PASSWORD, login


async def test_login_single_company_and_me(client: AsyncClient, tenants) -> None:
    r = await client.post("/auth/login", json={"email": "Planner@Demo.example ", "password": PASSWORD})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    set_cookie = r.headers["set-cookie"].lower()
    assert "erp_refresh=" in set_cookie and "httponly" in set_cookie
    assert "samesite=strict" in set_cookie and "path=/api/auth" in set_cookie
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    body = me.json()
    assert body["role"] == "planner"
    assert body["company"]["id"] == str(tenants["demo"])
    assert "audit.read" not in body["permissions"]


@pytest.mark.parametrize(
    ("email", "password"),
    [("planner@demo.example", "wrong"), ("nobody@demo.example", PASSWORD)],
)
async def test_bad_credentials_same_message(client: AsyncClient, email: str, password: str) -> None:
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Email or password is incorrect."


async def test_each_demo_user_belongs_to_one_company(client: AsyncClient, tenants) -> None:
    """One company per website: no user is asked to pick a company."""
    for email in ("owner@demo.example", "owner@second.example"):
        me = (await client.get("/auth/me", headers=await login(client, email))).json()
        assert len(me["companies"]) == 1
    assert me["company"]["id"] == str(tenants["second"])


async def test_cannot_sign_in_to_foreign_company(client: AsyncClient, tenants) -> None:
    r = await client.post(
        "/auth/login",
        json={
            "email": "planner@demo.example",
            "password": PASSWORD,
            "tenant_id": str(tenants["second"]),
        },
    )
    assert r.status_code == 403


async def test_refresh_via_cookie_and_logout(client: AsyncClient) -> None:
    await login(client, "planner@demo.example")
    r = await client.post("/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]
    await client.post("/auth/logout")
    client.cookies.clear()
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_logout_all_revokes_refresh_tokens(client: AsyncClient) -> None:
    h = await login(client, "accountant@demo.example")
    old_cookie = client.cookies.get("erp_refresh")
    assert (await client.post("/auth/logout-all", headers=h)).status_code == 204
    client.cookies.set("erp_refresh", old_cookie, path="/api/auth")
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_missing_bad_expired_and_wrong_type_tokens(client: AsyncClient, tenants) -> None:
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/auth/me", headers={"Authorization": "Bearer junk"})).status_code == 401
    s = get_settings()
    expired = jwt.encode(
        {
            "iss": s.jwt_issuer,
            "sub": str(uuid.uuid4()),
            "tid": str(tenants["demo"]),
            "role": "owner",
            "typ": "access",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        s.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})).status_code == 401
    forged = jwt.encode({"sub": "x"}, "not-the-secret-but-long-enough-for-hs256!!", algorithm="HS256")
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    refresh_as_access = create_token(
        user_id=uuid.uuid4(), tenant_id=tenants["demo"], role="owner", typ="refresh"
    )
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {refresh_as_access}"})
    assert r.status_code == 401


async def test_login_rate_limited(client: AsyncClient) -> None:
    for _ in range(10):
        await client.post("/auth/login", json={"email": "planner@demo.example", "password": "x"})
    r = await client.post("/auth/login", json={"email": "planner@demo.example", "password": PASSWORD})
    assert r.status_code == 429


async def test_validation_error_shape(client: AsyncClient) -> None:
    r = await client.post("/auth/login", json={"email": "not-an-email", "password": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
