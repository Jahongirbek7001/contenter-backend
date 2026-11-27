"""Payme Merchant API and Click SHOP-API, driven over HTTP the way the providers call us."""

import base64
import hashlib
import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.payments import Gateways
from app.domain.credits.service import get_balance
from app.domain.payments.checkout import ClickCheckout, PaymeCheckout
from app.domain.payments.orders import create_site_order
from app.main import create_app
from app.models import Payment, User
from app.models.enums import PaymentProvider, PaymentStatus

SessionFactory = async_sessionmaker[AsyncSession]
PAYME_KEY = "payme-sandbox-key"
CLICK_SECRET = "click-secret"
CLICK_SERVICE = "777"
START_TIYIN = 33_333 * 100
TELEGRAM_IDS = itertools.count(7000)


@dataclass
class FakeArq:
    jobs: list[tuple[Any, ...]] = field(default_factory=list)

    async def enqueue_job(self, name: str, *args: Any, _job_id: str) -> None:
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
    app.state.gateways = Gateways(
        site_url="http://site.test",
        payme=PaymeCheckout("merchant", test=True),
        payme_key=PAYME_KEY,
        click=ClickCheckout(CLICK_SERVICE, "merchant"),
        click_secret_key=CLICK_SECRET,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield Env(http, arq, session_factory)


async def order(
    env: Env, provider: PaymentProvider, pack: str = "start", referrer_id: int | None = None
) -> tuple[int, int]:
    """A new customer's site order; returns (user id, order id)."""
    async with env.factory() as session, session.begin():
        user = User(telegram_id=next(TELEGRAM_IDS), referrer_id=referrer_id)
        session.add(user)
        await session.flush()
        payment = await create_site_order(session, user, pack, provider)
        return user.id, payment.id


async def available(env: Env, user_id: int) -> int:
    async with env.factory() as session:
        return (await get_balance(session, user_id)).available


async def payment(env: Env, payment_id: int) -> Payment:
    async with env.factory() as session:
        found = await session.get(Payment, payment_id)
        assert found is not None
        return found


# --- Payme -------------------------------------------------------------------------------

AUTH = {"Authorization": "Basic " + base64.b64encode(f"Paycom:{PAYME_KEY}".encode()).decode()}


async def rpc(
    env: Env, method: str, *, auth: dict[str, str] = AUTH, **params: Any
) -> dict[str, Any]:
    response = await env.http.post(
        "/payments/payme", json={"id": 1, "method": method, "params": params}, headers=auth
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def account(order_id: int) -> dict[str, str]:
    return {"order_id": str(order_id)}


async def test_payme_rejects_a_wrong_key(env: Env) -> None:
    _, order_id = await order(env, PaymentProvider.PAYME)
    wrong = {"Authorization": "Basic " + base64.b64encode(b"Paycom:nope").decode()}
    body = await rpc(
        env, "CheckPerformTransaction", auth=wrong, amount=START_TIYIN, account=account(order_id)
    )
    assert body["error"]["code"] == -32504


async def test_payme_checks_order_and_amount(env: Env) -> None:
    _, order_id = await order(env, PaymentProvider.PAYME)

    ok = await rpc(env, "CheckPerformTransaction", amount=START_TIYIN, account=account(order_id))
    wrong_amount = await rpc(env, "CheckPerformTransaction", amount=100, account=account(order_id))
    missing = await rpc(env, "CheckPerformTransaction", amount=START_TIYIN, account=account(999))
    unknown = await rpc(env, "ChangePassword", password="x")

    assert ok["result"] == {"allow": True}
    assert wrong_amount["error"]["code"] == -31001
    assert missing["error"]["code"] == -31050
    assert unknown["error"]["code"] == -32601


async def test_payme_full_payment_credits_once_and_notifies(env: Env) -> None:
    inviter, _ = await order(env, PaymentProvider.PAYME)
    user_id, order_id = await order(env, PaymentProvider.PAYME, referrer_id=inviter)
    params: dict[str, Any] = {"id": "payme-tx-1", "time": 1_764_158_400_000, "amount": START_TIYIN}

    created = await rpc(env, "CreateTransaction", **params, account=account(order_id))
    again = await rpc(env, "CreateTransaction", **params, account=account(order_id))
    other = await rpc(
        env, "CreateTransaction", **{**params, "id": "payme-tx-2"}, account=account(order_id)
    )
    performed = await rpc(env, "PerformTransaction", id="payme-tx-1")
    repeated = await rpc(env, "PerformTransaction", id="payme-tx-1")
    checked = await rpc(env, "CheckTransaction", id="payme-tx-1")
    cancel = await rpc(env, "CancelTransaction", id="payme-tx-1", reason=5)
    period: dict[str, Any] = {"from": 0, "to": 2_000_000_000_000}
    statement = await rpc(env, "GetStatement", **period)

    assert created["result"]["state"] == 1
    assert created["result"]["transaction"] == str(order_id)
    assert again["result"] == created["result"]
    assert other["error"]["code"] == -31051
    assert performed["result"]["state"] == 2
    assert repeated["result"] == performed["result"]
    assert checked["result"]["state"] == 2 and checked["result"]["perform_time"] > 0
    assert cancel["error"]["code"] == -31007
    assert [row["id"] for row in statement["result"]["transactions"]] == ["payme-tx-1"]
    assert await available(env, user_id) == 5 + 2
    assert await available(env, inviter) == 2
    assert env.arq.jobs == [("payment_notification", order_id, inviter)]


async def test_payme_cancel_before_perform(env: Env) -> None:
    user_id, order_id = await order(env, PaymentProvider.PAYME)
    await rpc(
        env,
        "CreateTransaction",
        id="tx",
        time=1,
        amount=START_TIYIN,
        account=account(order_id),
    )

    cancelled = await rpc(env, "CancelTransaction", id="tx", reason=3)
    perform = await rpc(env, "PerformTransaction", id="tx")
    missing = await rpc(env, "CheckTransaction", id="nope")

    assert cancelled["result"]["state"] == -1
    assert perform["error"]["code"] == -31008
    assert missing["error"]["code"] == -31003
    stored = await payment(env, order_id)
    assert (stored.status, stored.cancel_reason) == (PaymentStatus.CANCELLED, 3)
    assert await available(env, user_id) == 0


async def test_payme_cancels_a_transaction_older_than_12_hours(env: Env) -> None:
    _, order_id = await order(env, PaymentProvider.PAYME)
    await rpc(
        env,
        "CreateTransaction",
        id="old",
        time=1,
        amount=START_TIYIN,
        account=account(order_id),
    )
    async with env.factory() as session, session.begin():
        stored = await session.get(Payment, order_id)
        assert stored is not None
        stored.provider_created_at = datetime.now(UTC) - timedelta(hours=13)

    perform = await rpc(env, "PerformTransaction", id="old")

    assert perform["error"]["code"] == -31008
    assert (await payment(env, order_id)).cancel_reason == 4


async def test_payme_refuses_a_second_trial(env: Env) -> None:
    user_id, first = await order(env, PaymentProvider.PAYME, pack="trial")
    async with env.factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        second = (await create_site_order(session, user, "trial", PaymentProvider.PAYME)).id
    trial = 7_777 * 100
    await rpc(env, "CreateTransaction", id="t1", time=1, amount=trial, account=account(first))

    refused = await rpc(
        env, "CreateTransaction", id="t2", time=1, amount=trial, account=account(second)
    )

    assert refused["error"]["code"] == -31052


# --- Click -------------------------------------------------------------------------------


def click_form(
    order_id: int, action: int, prepare_id: int | None = None, **extra: str
) -> dict[str, str]:
    form = {
        "click_trans_id": "555",
        "service_id": CLICK_SERVICE,
        "click_paydoc_id": "1",
        "merchant_trans_id": str(order_id),
        "amount": "33333.00",
        "action": str(action),
        "error": "0",
        "error_note": "Success",
        "sign_time": "2026-11-26 12:00:00",
        **extra,
    }
    if prepare_id is not None:
        form["merchant_prepare_id"] = str(prepare_id)
    parts = [form["click_trans_id"], form["service_id"], CLICK_SECRET, form["merchant_trans_id"]]
    if prepare_id is not None:
        parts.append(form["merchant_prepare_id"])
    parts += [form["amount"], form["action"], form["sign_time"]]
    form["sign_string"] = hashlib.md5("".join(parts).encode()).hexdigest()
    return form


async def click(env: Env, path: str, form: dict[str, str]) -> dict[str, Any]:
    response = await env.http.post(f"/payments/click/{path}", data=form)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def test_click_prepare_and_complete_credit_once(env: Env) -> None:
    user_id, order_id = await order(env, PaymentProvider.CLICK)

    prepared = await click(env, "prepare", click_form(order_id, 0))
    completed = await click(
        env, "complete", click_form(order_id, 1, prepared["merchant_prepare_id"])
    )
    again = await click(env, "complete", click_form(order_id, 1, order_id))

    assert (prepared["error"], prepared["merchant_prepare_id"]) == (0, order_id)
    assert (completed["error"], completed["merchant_confirm_id"]) == (0, order_id)
    assert again["error"] == -4
    assert await available(env, user_id) == 5
    assert env.arq.jobs == [("payment_notification", order_id, None)]


async def test_click_rejects_bad_sign_amount_and_unknown_order(env: Env) -> None:
    _, order_id = await order(env, PaymentProvider.CLICK)
    forged = {**click_form(order_id, 0), "sign_string": "0" * 32}

    assert (await click(env, "prepare", forged))["error"] == -1
    assert (await click(env, "prepare", click_form(order_id, 0, amount="1.00")))["error"] == -2
    assert (await click(env, "prepare", click_form(999, 0)))["error"] == -5
    assert (await click(env, "prepare", click_form(order_id, 3)))["error"] == -3


async def test_click_failed_payment_cancels_the_order(env: Env) -> None:
    user_id, order_id = await order(env, PaymentProvider.CLICK)
    await click(env, "prepare", click_form(order_id, 0))

    failed = await click(env, "complete", click_form(order_id, 1, order_id, error="-5017"))
    later = await click(env, "complete", click_form(order_id, 1, order_id))

    assert failed["error"] == -9
    assert later["error"] == -9
    assert (await payment(env, order_id)).status is PaymentStatus.CANCELLED
    assert await available(env, user_id) == 0


def test_empty_merchant_settings_keep_providers_off() -> None:
    from pydantic import SecretStr

    from app.core.config import Settings

    settings = Settings.model_construct(
        site_url="https://contentor.wtf/",
        payme_merchant_id="m",
        payme_key=SecretStr(""),
        payme_test=True,
        click_service_id="",
        click_merchant_id="",
        click_secret_key=None,
    )
    gateways = Gateways.from_settings(settings)
    assert (gateways.payme, gateways.click, gateways.site_url) == (
        None,
        None,
        "https://contentor.wtf",
    )
