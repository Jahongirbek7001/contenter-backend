import base64
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.miniapp.deps import MiniAppAuth
from app.api.payments import Gateways
from app.core.telegram_auth import sign_login_widget
from app.domain.admin.service import create_admin
from app.domain.payments.checkout import ClickCheckout, PaymeCheckout
from app.main import create_app
from app.models.enums import AdminRole

BOT_TOKEN = "123456:test-token"
TELEGRAM_ID = 424242
PASSWORD = "correct-horse-battery"
SessionFactory = async_sessionmaker[AsyncSession]


@dataclass
class Env:
    http: AsyncClient
    gateways: Gateways


async def make_env(factory: SessionFactory, gateways: Gateways) -> AsyncIterator[Env]:
    app = create_app(cors_origins=[])
    app.state.session_factory = factory
    app.state.gateways = gateways
    app.state.bot_username = "contentorai_bot"
    app.state.miniapp_auth = MiniAppAuth(bot_token=BOT_TOKEN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield Env(http, gateways)


@pytest.fixture
async def env(session_factory: SessionFactory) -> AsyncIterator[Env]:
    gateways = Gateways(
        site_url="http://site.test",
        payme=PaymeCheckout("payme-merchant", test=True),
        payme_key="key",
        click=ClickCheckout("77", "88"),
        click_secret_key="secret",
    )
    async for value in make_env(session_factory, gateways):
        yield value


def widget(telegram_id: int = TELEGRAM_ID, auth_date: int | None = None) -> dict[str, str]:
    fields = {
        "id": str(telegram_id),
        "first_name": "Aziz",
        "username": "aziz",
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
    }
    return sign_login_widget(fields, BOT_TOKEN)


async def login(env: Env, **extra: str) -> dict[str, object]:
    response = await env.http.post("/site/auth/telegram", json={**widget(), **extra})
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_login_rejects_forged_or_stale_widget_data(env: Env) -> None:
    forged = {**widget(), "id": "1"}
    stale = widget(auth_date=int(time.time()) - 3 * 24 * 3600)

    assert (await env.http.post("/site/auth/telegram", json=forged)).status_code == 401
    assert (await env.http.post("/site/auth/telegram", json=stale)).status_code == 401
    assert (await env.http.get("/site/me")).status_code == 401


async def test_login_sets_a_session_and_shows_balance(env: Env) -> None:
    me = await login(env, language="ru")
    again = (await env.http.get("/site/me")).json()

    assert me["telegram_id"] == TELEGRAM_ID
    assert again["language"] == "ru"
    assert again["available"] == 0
    assert again["providers"] == ["payme", "click"]
    assert again["referral_link"] == f"https://t.me/contentorai_bot?start=ref_{TELEGRAM_ID}"

    assert (await env.http.post("/site/auth/logout")).status_code == 204
    assert (await env.http.get("/site/me")).status_code == 401


async def test_orders_link_to_payme_and_click(env: Env) -> None:
    await login(env)

    payme = (
        await env.http.post("/site/orders", json={"pack_code": "start", "provider": "payme"})
    ).json()
    click = (
        await env.http.post("/site/orders", json={"pack_code": "pro", "provider": "click"})
    ).json()
    stars = await env.http.post("/site/orders", json={"pack_code": "start", "provider": "stars"})
    missing = await env.http.post("/site/orders", json={"pack_code": "nope", "provider": "click"})

    encoded = payme["checkout_url"].removeprefix("https://test.paycom.uz/")
    params = dict(part.split("=", 1) for part in base64.b64decode(encoded).decode().split(";"))
    assert params["m"] == "payme-merchant"
    assert params["ac.order_id"] == str(payme["payment_id"])
    assert params["a"] == str(33_333 * 100)
    assert params["c"] == f"http://site.test/uz/account?payment={payme['payment_id']}"
    query = parse_qs(urlparse(click["checkout_url"]).query)
    assert query["amount"] == ["555555"]
    assert query["transaction_param"] == [str(click["payment_id"])]
    assert stars.status_code == 422
    assert (missing.status_code, missing.json()["detail"]) == (409, "pack_unavailable")
    # Orders nobody started paying are not history yet.
    assert (await env.http.get("/site/payments")).json() == []


async def test_disabled_provider_is_hidden_and_refused(session_factory: SessionFactory) -> None:
    async for env in make_env(session_factory, Gateways(site_url="http://site.test")):
        me = await login(env)
        response = await env.http.post(
            "/site/orders", json={"pack_code": "start", "provider": "payme"}
        )
        assert me["providers"] == []
        assert (response.status_code, response.json()["detail"]) == (503, "provider_disabled")


async def test_promo_codes_from_the_admin_cabinet(
    env: Env, session_factory: SessionFactory
) -> None:
    async with session_factory() as session, session.begin():
        await create_admin(session, "admin@example.uz", PASSWORD, AdminRole.ADMIN)
    await env.http.post(
        "/admin/auth/login", json={"email": "admin@example.uz", "password": PASSWORD}
    )
    created = await env.http.post("/admin/promo-codes", json={"code": "navruz-26", "credits": 3})
    taken = await env.http.post("/admin/promo-codes", json={"code": "NAVRUZ-26", "credits": 1})
    bad = await env.http.post("/admin/promo-codes", json={"code": "no spaces", "credits": 1})
    assert created.status_code == 201 and created.json()["code"] == "NAVRUZ-26"
    assert taken.status_code == 409
    assert bad.status_code == 422

    await login(env)
    redeemed = await env.http.post("/site/promo", json={"code": "navruz-26"})
    twice = await env.http.post("/site/promo", json={"code": "navruz-26"})
    listed = (await env.http.get("/admin/promo-codes")).json()

    assert redeemed.json() == {"credits": 3, "available": 3}
    assert (twice.status_code, twice.json()["detail"]) == (409, "already_used")
    assert listed[0]["redemptions"] == 1
    off = await env.http.patch(
        f"/admin/promo-codes/{created.json()['id']}", json={"is_active": False}
    )
    assert off.json()["is_active"] is False
