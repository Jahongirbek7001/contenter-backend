from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.passwords import hash_password, verify_password
from app.domain.admin.service import create_admin
from app.main import create_app
from app.models import TrendTemplate
from app.models.enums import AdminRole

PASSWORD = "correct-horse-battery"
NEW_TREND = {
    "slug": "test-trend",
    "title_uz": "Sinov trendi",
    "title_ru": "Тестовый тренд",
    "category": "lifestyle",
    "audience": "all",
    "badge": "new",
    "prompt_skeleton": "Odam quyosh botayotgan sohilda kameraga qarab yuradi.",
    "first_frame_instructions": "Keep the face exactly as in the selfie, vertical 9:16.",
    "music_prompt": "iliq, gitara",
    "sort_order": 999,
    "is_active": False,
}


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app(cors_origins=["http://localhost:3000"])
    app.state.session_factory = session_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    async with session_factory() as session, session.begin():
        await session.execute(delete(TrendTemplate).where(TrendTemplate.slug == "test-trend"))


async def _admin(
    session_factory: async_sessionmaker[AsyncSession], email: str, role: AdminRole
) -> None:
    async with session_factory() as session, session.begin():
        await create_admin(session, email, PASSWORD, role)


async def _login(client: AsyncClient, email: str) -> None:
    response = await client.post("/admin/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def test_password_hash_round_trip() -> None:
    stored = hash_password("s3cret-password")
    assert stored.startswith("scrypt$")
    assert verify_password("s3cret-password", stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password("anything", "not-a-hash")


async def test_create_admin_rejects_short_password(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="at least"):
            await create_admin(session, "a@b.uz", "short", AdminRole.ADMIN)


async def test_login_sets_http_only_cookie_and_me_works(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(session_factory, "Owner@Example.uz", AdminRole.OWNER)

    response = await client.post(
        "/admin/auth/login", json={"email": " owner@example.UZ ", "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json() == {"email": "owner@example.uz", "role": "owner"}
    cookie = response.headers["set-cookie"]
    assert "admin_session=" in cookie
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    me = await client.get("/admin/auth/me")
    assert me.json()["email"] == "owner@example.uz"


async def test_login_rejects_wrong_password_and_unknown_email(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(session_factory, "admin@example.uz", AdminRole.ADMIN)

    wrong = await client.post(
        "/admin/auth/login", json={"email": "admin@example.uz", "password": "nope-nope-nope"}
    )
    unknown = await client.post(
        "/admin/auth/login", json={"email": "ghost@example.uz", "password": PASSWORD}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_logout_ends_session(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(session_factory, "admin@example.uz", AdminRole.ADMIN)
    await _login(client, "admin@example.uz")
    token = client.cookies["admin_session"]

    assert (await client.post("/admin/auth/logout")).status_code == 204
    client.cookies.set("admin_session", token)
    assert (await client.get("/admin/auth/me")).status_code == 401


async def test_trends_require_login(client: AsyncClient) -> None:
    assert (await client.get("/admin/trends")).status_code == 401


async def test_seeded_trends_are_listed_in_order(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(session_factory, "admin@example.uz", AdminRole.ADMIN)
    await _login(client, "admin@example.uz")

    trends = (await client.get("/admin/trends")).json()

    assert len(trends) == 20
    assert trends[0]["slug"] == "registon-oqshomi"
    active = {trend["slug"] for trend in trends if trend["is_active"]}
    assert active == {"registon-oqshomi", "chopon-toglar", "chimyonda-qor", "kino-qahramoni"}


async def test_editor_creates_and_updates_trend(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(session_factory, "admin@example.uz", AdminRole.ADMIN)
    await _login(client, "admin@example.uz")

    created = await client.post("/admin/trends", json=NEW_TREND)
    assert created.status_code == 201
    trend_id = created.json()["id"]
    duplicate = await client.post("/admin/trends", json=NEW_TREND)
    assert duplicate.status_code == 409

    updated = await client.patch(
        f"/admin/trends/{trend_id}", json={"is_active": True, "badge": "hot", "music_prompt": None}
    )
    assert updated.status_code == 200
    body = updated.json()
    assert (body["is_active"], body["badge"], body["music_prompt"]) == (True, "hot", None)
    assert body["title_uz"] == "Sinov trendi"


async def test_update_rejects_null_for_required_field(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(session_factory, "admin@example.uz", AdminRole.ADMIN)
    await _login(client, "admin@example.uz")
    trend_id = (await client.get("/admin/trends")).json()[0]["id"]

    response = await client.patch(f"/admin/trends/{trend_id}", json={"title_uz": None})

    assert response.status_code == 422


async def test_support_role_is_read_only(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(session_factory, "support@example.uz", AdminRole.SUPPORT)
    await _login(client, "support@example.uz")

    assert (await client.get("/admin/trends")).status_code == 200
    assert (await client.post("/admin/trends", json=NEW_TREND)).status_code == 403
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(TrendTemplate)
            .where(TrendTemplate.slug == "test-trend")
        )
    assert count == 0


async def test_create_rejects_bad_slug_and_category(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(session_factory, "admin@example.uz", AdminRole.ADMIN)
    await _login(client, "admin@example.uz")

    bad_slug = await client.post("/admin/trends", json={**NEW_TREND, "slug": "Bad Slug"})
    bad_category = await client.post("/admin/trends", json={**NEW_TREND, "category": "x"})

    assert bad_slug.status_code == bad_category.status_code == 422
