from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.admin.service import create_admin
from app.domain.credits.errors import InsufficientCreditsError
from app.domain.credits.service import adjust_credits, get_balance, grant_bonus
from app.domain.generations.start import UserBlockedError, start_trend_generation
from app.main import create_app
from app.models import User
from app.models.enums import AdminRole

PASSWORD = "correct-horse-battery"
SessionFactory = async_sessionmaker[AsyncSession]


class NullStore:
    async def save(self, key: str, data: bytes) -> None:
        return None

    async def load(self, key: str) -> bytes:
        raise FileNotFoundError(key)

    async def delete(self, key: str) -> None:
        return None


@pytest.fixture
async def client(session_factory: SessionFactory) -> AsyncIterator[AsyncClient]:
    app = create_app(cors_origins=[])
    app.state.session_factory = session_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def login(client: AsyncClient, factory: SessionFactory, role: AdminRole) -> None:
    email = f"{role.value}@example.uz"
    async with factory() as session, session.begin():
        await create_admin(session, email, PASSWORD, role)
    response = await client.post("/admin/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


async def make_user(factory: SessionFactory, telegram_id: int, credits: int = 0) -> int:
    async with factory() as session, session.begin():
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.flush()
        if credits:
            await grant_bonus(session, user.id, credits, "seed")
        return user.id


async def test_adjust_credits_never_goes_below_zero(session_factory: SessionFactory) -> None:
    user_id = await make_user(session_factory, 9001, credits=3)
    async with session_factory() as session, session.begin():
        await adjust_credits(session, user_id, -2, "refund mistake")
        with pytest.raises(InsufficientCreditsError):
            await adjust_credits(session, user_id, -5, "too much")
        with pytest.raises(ValueError, match="zero"):
            await adjust_credits(session, user_id, 0, "nothing")
        assert (await get_balance(session, user_id)).available == 1


async def test_customers_list_shows_balances(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    await login(client, session_factory, AdminRole.SUPPORT)
    first = await make_user(session_factory, 9001, credits=4)
    await make_user(session_factory, 9002)

    rows = (await client.get("/admin/customers")).json()
    found = (await client.get("/admin/customers", params={"telegram_id": 9001})).json()

    assert [row["telegram_id"] for row in rows] == [9002, 9001]
    assert [(row["id"], row["available"], row["generations"]) for row in found] == [(first, 4, 0)]


async def test_editor_adds_credits_with_audit_note(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    await login(client, session_factory, AdminRole.OWNER)
    user_id = await make_user(session_factory, 9001)

    added = await client.post(
        f"/admin/customers/{user_id}/credits", json={"amount": 6, "note": "beta tester"}
    )
    too_much = await client.post(
        f"/admin/customers/{user_id}/credits", json={"amount": -10, "note": "take back"}
    )

    assert added.status_code == 200
    body = added.json()
    assert body["available"] == 6
    assert body["ledger"][0]["kind"] == "adjustment"
    assert body["ledger"][0]["note"] == "owner@example.uz: beta tester"
    assert too_much.status_code == 409


async def test_support_cannot_change_credits_or_block(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    await login(client, session_factory, AdminRole.SUPPORT)
    user_id = await make_user(session_factory, 9001)

    credits = await client.post(
        f"/admin/customers/{user_id}/credits", json={"amount": 5, "note": "please"}
    )
    block = await client.patch(f"/admin/customers/{user_id}", json={"is_blocked": True})

    assert credits.status_code == block.status_code == 403


async def test_blocked_customer_cannot_generate(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    await login(client, session_factory, AdminRole.ADMIN)
    user_id = await make_user(session_factory, 9001, credits=4)

    blocked = await client.patch(f"/admin/customers/{user_id}", json={"is_blocked": True})

    assert blocked.json()["is_blocked"] is True
    async with session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        with pytest.raises(UserBlockedError):
            await start_trend_generation(session, NullStore(), user, 1, b"x", "image/jpeg")


async def test_generations_list_and_stats(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    await login(client, session_factory, AdminRole.SUPPORT)
    user_id = await make_user(session_factory, 9001, credits=4)
    async with session_factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        await start_trend_generation(session, NullStore(), user, 1, b"x", "image/jpeg")

    rows = (await client.get("/admin/generations")).json()
    pending = (await client.get("/admin/generations", params={"status": "pending"})).json()
    stats = (await client.get("/admin/generations/stats")).json()

    assert [(row["telegram_id"], row["trend_title"], row["status"]) for row in rows] == [
        (9001, "Registon oqshomi", "pending")
    ]
    assert len(pending) == 1
    assert stats["total"] == 1
    assert stats["in_progress"] == 1
    detail = (await client.get(f"/admin/customers/{user_id}")).json()
    assert (detail["available"], detail["held"]) == (2, 2)
    assert detail["recent_generations"][0]["trend_title"] == "Registon oqshomi"
