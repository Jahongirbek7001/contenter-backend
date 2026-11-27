from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.ratelimit import RateLimiter
from app.domain.admin.service import create_admin
from app.main import create_app
from app.models.enums import AdminRole

PASSWORD = "correct-horse-battery"
SessionFactory = async_sessionmaker[AsyncSession]


@dataclass
class FakeRedis:
    counts: dict[str, int] = field(default_factory=dict)

    async def incr(self, name: str) -> int:
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.counts[name]

    async def expire(self, name: str, time: int) -> bool:
        return True


@pytest.fixture
async def http(session_factory: SessionFactory) -> AsyncIterator[AsyncClient]:
    app = create_app(cors_origins=[])
    app.state.session_factory = session_factory
    app.state.limiter = RateLimiter(cast(Redis, FakeRedis()))
    async with session_factory() as session, session.begin():
        await create_admin(session, "admin@example.uz", PASSWORD, AdminRole.ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def login(http: AsyncClient, password: str = PASSWORD) -> int:
    response = await http.post(
        "/admin/auth/login", json={"email": "admin@example.uz", "password": password}
    )
    return response.status_code


@pytest.fixture
async def restore_catalog(session_factory: SessionFactory) -> AsyncIterator[None]:
    """Seeded prices and packs are shared by every test: put them back afterwards."""
    async with session_factory() as session:
        prices = (
            await session.execute(text("SELECT id, credits, is_active FROM product_prices"))
        ).all()
        packs = (await session.execute(text("SELECT id, title_uz, price_stars FROM packs"))).all()
    yield
    async with session_factory() as session, session.begin():
        await session.execute(text("DELETE FROM packs WHERE code = 'mega'"))
        for price_id, credits, active in prices:
            await session.execute(
                text("UPDATE product_prices SET credits = :c, is_active = :a WHERE id = :i"),
                {"c": credits, "a": active, "i": price_id},
            )
        for pack_id, title, stars in packs:
            await session.execute(
                text("UPDATE packs SET title_uz = :t, price_stars = :s WHERE id = :i"),
                {"t": title, "s": stars, "i": pack_id},
            )


@pytest.mark.usefixtures("restore_catalog")
async def test_prices_and_packs_are_editable(http: AsyncClient) -> None:
    assert await login(http) == 200
    prices = (await http.get("/admin/catalog/prices")).json()
    trend = next(row for row in prices if row["product"] == "trend")
    packs = (await http.get("/admin/catalog/packs")).json()
    start = next(pack for pack in packs if pack["code"] == "start")

    cheaper = await http.patch(f"/admin/catalog/prices/{trend['id']}", json={"credits": 3})
    off_bot = await http.patch(f"/admin/catalog/packs/{start['id']}", json={"price_stars": None})
    renamed = await http.patch(
        f"/admin/catalog/packs/{start['id']}", json={"title_uz": "Boshlang'ich"}
    )
    created = await http.post(
        "/admin/catalog/packs",
        json={
            "code": "mega",
            "title_uz": "Mega",
            "title_ru": "Mega",
            "price_uzs": 999_999,
            "credits": 200,
            "bonus_credits": 20,
        },
    )
    duplicate = await http.post(
        "/admin/catalog/packs",
        json={"code": "mega", "title_uz": "x", "title_ru": "x", "price_uzs": 1000, "credits": 1},
    )
    public = (await http.get("/api/packs")).json()

    assert cheaper.json()["credits"] == 3
    assert off_bot.json()["price_stars"] is None
    assert renamed.json()["price_stars"] is None  # unset fields stay as they were
    assert created.status_code == 201 and created.json()["price_stars"] is None
    assert duplicate.status_code == 409
    assert "mega" in [pack["code"] for pack in public]


async def test_dashboard_reports_the_period(http: AsyncClient) -> None:
    assert await login(http) == 200
    body = (await http.get("/admin/dashboard", params={"days": 7})).json()
    assert len(body["days"]) == 7
    assert body["totals"]["generations"] == 0
    assert body["uzs_per_usd"] == "12000"


async def test_admin_login_is_limited(http: AsyncClient) -> None:
    statuses = [await login(http, "wrong-password") for _ in range(11)]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


async def test_limiter_fails_open_without_redis() -> None:
    assert await RateLimiter(None).allow("k", 0, 60) is True
