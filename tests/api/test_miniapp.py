import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.miniapp.deps import MiniAppAuth
from app.core.telegram_auth import InitDataError, sign_init_data, validate_init_data
from app.domain.credits.service import grant_bonus
from app.main import create_app
from app.models import TrendTemplate, User

BOT_TOKEN = "123456:test-token"
TELEGRAM_ID = 555001


class MemoryStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, key: str, data: bytes) -> None:
        self.files[key] = data

    async def load(self, key: str) -> bytes:
        return self.files[key]

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)


@dataclass
class FakeArq:
    jobs: list[tuple[str, int, str]] = field(default_factory=list)

    async def enqueue_job(self, name: str, generation_id: int, _job_id: str) -> None:
        self.jobs.append((name, generation_id, _job_id))


@dataclass
class Env:
    http: AsyncClient
    arq: FakeArq
    store: MemoryStore


def init_data(telegram_id: int = TELEGRAM_ID, auth_date: int | None = None, **extra: str) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": telegram_id, "first_name": "Test", "language_code": "ru"}),
        **extra,
    }
    return sign_init_data(fields, BOT_TOKEN)


def auth(value: str | None = None) -> dict[str, str]:
    return {"Authorization": f"tma {value or init_data()}"}


@pytest.fixture
async def env(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Env]:
    app = create_app(cors_origins=["http://localhost:3000"])
    arq, store = FakeArq(), MemoryStore()
    app.state.session_factory = session_factory
    app.state.arq = arq
    app.state.media_store = store
    app.state.miniapp_auth = MiniAppAuth(bot_token=BOT_TOKEN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield Env(http, arq, store)


def test_init_data_signature_and_expiry() -> None:
    user = validate_init_data(init_data(start_param="ref_42"), BOT_TOKEN)
    assert (user.telegram_id, user.language_code, user.start_param) == (TELEGRAM_ID, "ru", "ref_42")
    with pytest.raises(InitDataError, match="signature"):
        validate_init_data(init_data(), "other:token")
    with pytest.raises(InitDataError, match="signature"):
        validate_init_data(init_data().replace("Test", "Evil"), BOT_TOKEN)
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(init_data(auth_date=int(time.time()) - 2 * 86400), BOT_TOKEN)


async def test_requests_without_init_data_are_rejected(env: Env) -> None:
    assert (await env.http.get("/miniapp/me")).status_code == 401
    assert (await env.http.get("/miniapp/me", headers=auth("bad"))).status_code == 401


async def test_me_creates_user_from_telegram(
    env: Env, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await env.http.get("/miniapp/me", headers=auth())

    assert response.status_code == 200
    assert response.json() == {
        "language": "ru",
        "available": 0,
        "held": 0,
        "rules_accepted": False,
        "trend_price": 2,
    }
    async with session_factory() as session:
        assert await session.scalar(select(User.id).where(User.telegram_id == TELEGRAM_ID))


async def test_trends_lists_only_active(env: Env) -> None:
    trends = (await env.http.get("/miniapp/trends", headers=auth())).json()
    assert [trend["slug"] for trend in trends] == [
        "registon-oqshomi",
        "chopon-toglar",
        "chimyonda-qor",
        "kino-qahramoni",
    ]


async def test_language_and_rules_update(env: Env) -> None:
    updated = await env.http.patch("/miniapp/me", headers=auth(), json={"language": "uz"})
    accepted = await env.http.post("/miniapp/rules/accept", headers=auth())

    assert updated.json()["language"] == "uz"
    assert accepted.json()["rules_accepted"] is True


async def _template_id(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        value = await session.scalar(
            select(TrendTemplate.id).where(TrendTemplate.slug == "chimyonda-qor")
        )
    assert value is not None
    return value


async def _post_photo(env: Env, template_id: int) -> tuple[int, dict[str, object]]:
    response = await env.http.post(
        "/miniapp/generations",
        headers=auth(),
        data={"template_id": str(template_id)},
        files={"photo": ("selfie.jpg", b"\xff\xd8jpeg", "image/jpeg")},
    )
    return response.status_code, response.json()


async def test_generation_requires_rules_then_credits(
    env: Env, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    template_id = await _template_id(session_factory)

    status, body = await _post_photo(env, template_id)
    assert (status, body["detail"]) == (
        409,
        {"code": "rules_required", "required": None, "available": None},
    )

    await env.http.post("/miniapp/rules/accept", headers=auth())
    status, body = await _post_photo(env, template_id)
    assert (status, body["detail"]) == (
        402,
        {"code": "insufficient", "required": 2, "available": 0},
    )
    assert env.arq.jobs == []
    assert env.store.files == {}


async def test_generation_is_created_and_queued(
    env: Env, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await env.http.post("/miniapp/rules/accept", headers=auth())
    async with session_factory() as session, session.begin():
        user_id = await session.scalar(select(User.id).where(User.telegram_id == TELEGRAM_ID))
        assert user_id is not None
        await grant_bonus(session, user_id, 4, "test")

    status, body = await _post_photo(env, await _template_id(session_factory))

    assert status == 201
    generation_id = body["id"]
    assert env.arq.jobs == [("trend_generation", generation_id, f"generation:{generation_id}")]
    assert list(env.store.files) == [f"inputs/{generation_id}.jpg"]
    me = (await env.http.get("/miniapp/me", headers=auth())).json()
    assert (me["available"], me["held"]) == (2, 2)
    history = (await env.http.get("/miniapp/generations", headers=auth())).json()
    assert [(item["id"], item["status"], item["trend_title_uz"]) for item in history] == [
        (generation_id, "pending", "Chimyonda qor")
    ]


async def test_dev_user_works_only_when_configured(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app = create_app(cors_origins=[])
    app.state.session_factory = session_factory
    app.state.miniapp_auth = MiniAppAuth(bot_token=BOT_TOKEN, dev_telegram_id=777)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get("/miniapp/me")).status_code == 200
