from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import create_app
from app.models import Pack


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app(cors_origins=["http://localhost:3000"])
    app.state.session_factory = session_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.json() == {"status": "ok"}


async def test_packs_lists_active_packs_in_sort_order(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.get("/api/packs")

    assert response.status_code == 200
    codes = [pack["code"] for pack in response.json()]
    assert codes == ["trial", "start", "popular", "pro"]
    assert set(response.json()[0]) == {
        "code",
        "title_uz",
        "title_ru",
        "price_uzs",
        "credits",
        "bonus_credits",
        "is_one_time",
    }


async def test_packs_hides_inactive_packs(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(update(Pack).where(Pack.code == "trial").values(is_active=False))
    try:
        response = await client.get("/api/packs")
        assert "trial" not in [pack["code"] for pack in response.json()]
    finally:
        async with session_factory() as session, session.begin():
            await session.execute(update(Pack).where(Pack.code == "trial").values(is_active=True))
