from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.admin.service import create_admin
from app.domain.bonuses import broadcast_campaign
from app.domain.credits.service import get_balance
from app.domain.payments.orders import record_stars_payment
from app.domain.settings import WELCOME_BONUS, set_setting
from app.domain.users import Profile, display_name, get_or_create_user
from app.main import create_app
from app.models import BonusCampaign, Pack, User
from app.models.enums import AdminRole, Language

PASSWORD = "correct-horse-battery"
SessionFactory = async_sessionmaker[AsyncSession]
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)


@dataclass
class FakeArq:
    jobs: list[tuple[Any, ...]] = field(default_factory=list)

    async def enqueue_job(self, name: str, *args: Any, **_: Any) -> None:
        self.jobs.append((name, *args))


@dataclass
class Env:
    http: AsyncClient
    arq: FakeArq
    factory: SessionFactory


@pytest.fixture
async def env(session_factory: SessionFactory) -> AsyncIterator[Env]:
    app = create_app(cors_origins=[])
    arq = FakeArq()
    app.state.session_factory = session_factory
    app.state.arq = arq
    async with session_factory() as session, session.begin():
        await create_admin(session, "admin@example.uz", PASSWORD, AdminRole.ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        login = await http.post(
            "/admin/auth/login", json={"email": "admin@example.uz", "password": PASSWORD}
        )
        assert login.status_code == 200
        yield Env(http, arq, session_factory)


async def customer(
    factory: SessionFactory, telegram_id: int, profile: Profile | None = None
) -> int:
    async with factory() as session, session.begin():
        lookup = await get_or_create_user(session, telegram_id, "uz", profile=profile)
        return lookup.user.id


async def available(factory: SessionFactory, user_id: int) -> int:
    async with factory() as session:
        return (await get_balance(session, user_id)).available


async def test_profile_is_kept_fresh_and_searchable(env: Env) -> None:
    user_id = await customer(env.factory, 501, Profile("Aziz", "Karimov", "aziz"))
    await customer(env.factory, 501, Profile("Aziz", "Karimov", "aziz_new"))
    await customer(env.factory, 502)

    by_name = (await env.http.get("/admin/customers", params={"q": "aziz kar"})).json()
    by_username = (await env.http.get("/admin/customers", params={"q": "@aziz_new"})).json()
    by_id = (await env.http.get("/admin/customers", params={"q": "502"})).json()

    assert [row["id"] for row in by_name] == [user_id]
    assert by_name[0]["name"] == "Aziz Karimov"
    assert by_username[0]["username"] == "aziz_new"
    assert by_id[0]["name"] == "502"


def test_display_name_falls_back_to_username_then_id() -> None:
    assert display_name(User(telegram_id=7, username="ali")) == "@ali"
    assert display_name(User(telegram_id=7)) == "7"


async def test_welcome_gift_is_given_to_new_customers_only(env: Env) -> None:
    old = await customer(env.factory, 600)
    saved = await env.http.put("/admin/settings", json={"welcome_bonus": 2})
    too_much = await env.http.put("/admin/settings", json={"welcome_bonus": 999})
    unknown = await env.http.put("/admin/settings", json={"nope": 1})

    async with env.factory() as session, session.begin():
        lookup = await get_or_create_user(session, 601, "ru")
        again = await get_or_create_user(session, 600, "ru")

    assert saved.json()["welcome_bonus"] == 2
    assert too_much.status_code == 422 and unknown.status_code == 422
    assert (lookup.welcome_bonus, again.welcome_bonus) == (2, 0)
    assert await available(env.factory, lookup.user.id) == 2
    assert await available(env.factory, old) == 0


async def test_single_bonus_is_announced_and_only_positive(env: Env) -> None:
    user_id = await customer(env.factory, 700)

    gift = await env.http.post(
        f"/admin/customers/{user_id}/credits",
        json={"amount": 3, "note": "uzr", "kind": "bonus", "notify": True},
    )
    negative = await env.http.post(
        f"/admin/customers/{user_id}/credits",
        json={"amount": -1, "note": "xato", "kind": "bonus"},
    )

    assert gift.status_code == 200
    assert gift.json()["ledger"][0]["kind"] == "bonus"
    assert negative.status_code == 422
    assert env.arq.jobs == [("bonus_notice", user_id, 3)]


@dataclass
class FakeSender:
    unreachable: set[int]
    sent: list[tuple[int, str]] = field(default_factory=list)

    async def send(self, chat_id: int, text: str) -> bool:
        if chat_id in self.unreachable:
            return False
        self.sent.append((chat_id, text))
        return True


def render(campaign: BonusCampaign, language: Language, balance: int) -> str:
    return f"{language.value}:{campaign.credits}:{balance}"


async def test_campaign_credits_the_segment_once_and_announces_it(env: Env) -> None:
    buyer = await customer(env.factory, 801)
    quiet = await customer(env.factory, 802)
    blocked = await customer(env.factory, 803)
    async with env.factory() as session, session.begin():
        user = await session.get(User, buyer)
        pack_id = await session.scalar(select(Pack.id).where(Pack.code == "start"))
        assert user is not None and pack_id is not None
        await record_stars_payment(session, user, pack_id, "charge", 210, NOW)
        blocked_user = await session.get(User, blocked)
        assert blocked_user is not None
        blocked_user.is_blocked = True

    sizes = (await env.http.get("/admin/bonuses/segments")).json()
    created = await env.http.post(
        "/admin/bonuses/campaigns",
        json={"credits": 2, "segment": "all", "message_uz": "Bayram!", "message_ru": ""},
    )
    campaign_id = created.json()["id"]
    sender = FakeSender(unreachable={802})
    delivered = await broadcast_campaign(env.factory, sender, render, campaign_id, NOW, interval=0)
    again = await broadcast_campaign(env.factory, sender, render, campaign_id, NOW, interval=0)
    listed = (await env.http.get("/admin/bonuses/campaigns")).json()

    assert sizes == {"all": 2, "buyers": 1, "non_buyers": 1, "active_30d": 1}
    assert created.status_code == 201 and created.json()["recipients"] == 2
    assert env.arq.jobs == [("campaign_broadcast", campaign_id)]
    assert (delivered, again) == (1, 0)
    assert sender.sent == [(801, "uz:2:7")]
    assert listed[0]["sent"] == 1 and listed[0]["finished_at"] is not None
    assert await available(env.factory, quiet) == 2
    assert await available(env.factory, blocked) == 0


async def test_customer_page_lists_payments(env: Env) -> None:
    user_id = await customer(env.factory, 900, Profile("Dilnoza", None, None))
    async with env.factory() as session, session.begin():
        user = await session.get(User, user_id)
        pack_id = await session.scalar(select(Pack.id).where(Pack.code == "popular"))
        assert user is not None and pack_id is not None
        await record_stars_payment(session, user, pack_id, "charge-9", 625, NOW)

    detail = (await env.http.get(f"/admin/customers/{user_id}")).json()

    assert detail["name"] == "Dilnoza"
    assert [(p["provider"], p["amount"], p["credits"]) for p in detail["payments"]] == [
        ("stars", 625, 16)
    ]


async def test_support_cannot_give_gifts(env: Env, session_factory: SessionFactory) -> None:
    async with session_factory() as session, session.begin():
        await create_admin(session, "support@example.uz", PASSWORD, AdminRole.SUPPORT)
        await set_setting(session, WELCOME_BONUS, 0)
    await env.http.post(
        "/admin/auth/login", json={"email": "support@example.uz", "password": PASSWORD}
    )
    response = await env.http.post(
        "/admin/bonuses/campaigns", json={"credits": 1, "segment": "all"}
    )
    assert response.status_code == 403
