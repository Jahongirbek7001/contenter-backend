from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.admin.service import create_admin
from app.domain.credits.service import get_balance, grant_bonus, release_hold, settle_hold
from app.domain.generations.start import start_spoken_generation
from app.domain.talking.script import Script
from app.main import create_app
from app.media.store import LocalMediaStore
from app.models import Generation, ScriptStyle, User
from app.models.enums import AdminRole, GenerationStatus, Language, Product, Resolution

PASSWORD = "correct-horse-battery"
SessionFactory = async_sessionmaker[AsyncSession]
SCRIPT = Script("idea", ("one", "two", "three"), "bible")


@dataclass
class FakeArq:
    jobs: list[tuple[str, int, str]] = field(default_factory=list)

    async def enqueue_job(self, name: str, generation_id: int, _job_id: str) -> None:
        self.jobs.append((name, generation_id, _job_id))


@dataclass
class Env:
    http: AsyncClient
    store: LocalMediaStore
    arq: FakeArq


@pytest.fixture
async def env(session_factory: SessionFactory, tmp_path: Path) -> AsyncIterator[Env]:
    app = create_app(cors_origins=[])
    store, arq = LocalMediaStore(tmp_path), FakeArq()
    app.state.session_factory = session_factory
    app.state.media_store = store
    app.state.arq = arq
    async with session_factory() as session, session.begin():
        for role in (AdminRole.ADMIN, AdminRole.SUPPORT):
            await create_admin(session, f"{role.value}@example.uz", PASSWORD, role)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield Env(http, store, arq)


async def login(env: Env, role: AdminRole = AdminRole.ADMIN) -> None:
    response = await env.http.post(
        "/admin/auth/login", json={"email": f"{role.value}@example.uz", "password": PASSWORD}
    )
    assert response.status_code == 200


async def spoken(
    factory: SessionFactory, env: Env, credits: int, outcome: GenerationStatus
) -> tuple[int, int]:
    """A finished 720p series (9 ⚡) for a new customer; returns (user id, generation id)."""
    async with factory() as session, session.begin():
        user = User(telegram_id=9300)
        session.add(user)
        await session.flush()
        await grant_bonus(session, user.id, credits, "seed")
        style_id = await session.scalar(select(ScriptStyle.id).where(ScriptStyle.slug == "pov"))
        assert style_id is not None
        generation = await start_spoken_generation(
            session,
            env.store,
            user,
            product=Product.SERIES,
            resolution=Resolution.P720,
            style_id=style_id,
            language=Language.RU,
            script_json=SCRIPT.to_json(),
            idea=SCRIPT.idea,
            photo=b"\xff\xd8jpeg",
            mime_type="image/jpeg",
            subtitles=True,
            contact_text="@shop",
        )
        generation.status = outcome
        if outcome is GenerationStatus.SUCCEEDED:
            await settle_hold(session, generation.id)
            generation.output_media_key = f"outputs/{generation.id}.mp4"
            await env.store.save(generation.output_media_key, b"\x00\x00\x00\x18ftypmp42video")
        else:
            await release_hold(session, generation.id)
        return user.id, generation.id


async def available(factory: SessionFactory, user_id: int) -> int:
    async with factory() as session:
        return (await get_balance(session, user_id)).available


async def test_detail_shows_script_and_plays_stored_video(
    env: Env, session_factory: SessionFactory
) -> None:
    await login(env, AdminRole.SUPPORT)
    _, generation_id = await spoken(session_factory, env, 9, GenerationStatus.SUCCEEDED)

    detail = (await env.http.get(f"/admin/generations/{generation_id}")).json()
    video = await env.http.get(detail["video_url"], headers={"Range": "bytes=0-3"})
    listed = (await env.http.get("/admin/generations")).json()

    assert detail["script_lines"] == ["one", "two", "three"]
    assert (detail["style_title"], detail["contact_text"]) == ("🎭 POV monolog", "@shop")
    assert (detail["can_refund"], detail["can_rerun"], detail["refunded"]) == (True, False, False)
    assert video.status_code == 206
    assert video.headers["cache-control"] == "private, no-store"
    assert listed[0]["style_title"] == "🎭 POV monolog"


async def test_video_needs_an_admin_session(env: Env, session_factory: SessionFactory) -> None:
    _, generation_id = await spoken(session_factory, env, 9, GenerationStatus.SUCCEEDED)
    response = await env.http.get(f"/admin/generations/{generation_id}/video.mp4")
    assert response.status_code == 401


async def test_refund_gives_credits_back_once(env: Env, session_factory: SessionFactory) -> None:
    await login(env)
    user_id, generation_id = await spoken(session_factory, env, 9, GenerationStatus.SUCCEEDED)
    assert await available(session_factory, user_id) == 0

    first = await env.http.post(f"/admin/generations/{generation_id}/refund")
    second = await env.http.post(f"/admin/generations/{generation_id}/refund")

    assert first.status_code == 200
    assert (first.json()["refunded"], first.json()["can_refund"]) == (True, False)
    assert (second.status_code, second.json()["detail"]) == (409, "already_refunded")
    assert await available(session_factory, user_id) == 9


async def test_failed_generation_is_not_refundable(
    env: Env, session_factory: SessionFactory
) -> None:
    await login(env)
    _, generation_id = await spoken(session_factory, env, 9, GenerationStatus.FAILED)
    response = await env.http.post(f"/admin/generations/{generation_id}/refund")
    assert (response.status_code, response.json()["detail"]) == (409, "not_spent")


async def test_rerun_holds_credits_and_queues_a_copy(
    env: Env, session_factory: SessionFactory
) -> None:
    await login(env)
    user_id, generation_id = await spoken(session_factory, env, 9, GenerationStatus.BLOCKED)

    response = await env.http.post(f"/admin/generations/{generation_id}/rerun")

    assert response.status_code == 201
    new_id = response.json()["id"]
    assert env.arq.jobs == [("spoken_generation", new_id, f"generation:{new_id}")]
    assert await available(session_factory, user_id) == 0
    async with session_factory() as session:
        copy = await session.get(Generation, new_id)
    assert copy is not None
    assert (copy.source_generation_id, copy.contact_text) == (generation_id, "@shop")
    assert copy.status is GenerationStatus.PENDING
    # The copy has not failed, so it cannot be re-run again.
    again = await env.http.post(f"/admin/generations/{new_id}/rerun")
    assert (again.status_code, again.json()["detail"]) == (409, "not_failed")


async def test_rerun_needs_the_photo_and_enough_credits(
    env: Env, session_factory: SessionFactory
) -> None:
    await login(env)
    _, poor = await spoken(session_factory, env, 9, GenerationStatus.FAILED)
    async with session_factory() as session, session.begin():
        generation = await session.get(Generation, poor)
        assert generation is not None
        user = await session.get(User, generation.user_id)
        assert user is not None
        user.telegram_id = 9301  # free the telegram id for the next customer

    spend = await env.http.post(f"/admin/generations/{poor}/rerun")
    assert spend.status_code == 201  # the 9 ⚡ came back when it failed
    broke = await env.http.post(f"/admin/generations/{poor}/rerun")
    assert broke.status_code == 402

    _, expired = await spoken(session_factory, env, 9, GenerationStatus.FAILED)
    async with session_factory() as session:
        generation = await session.get(Generation, expired)
        assert generation is not None and generation.input_media_key is not None
    await env.store.delete(generation.input_media_key)
    gone = await env.http.post(f"/admin/generations/{expired}/rerun")
    assert (gone.status_code, gone.json()["detail"]) == (409, "photo_expired")


async def test_support_cannot_refund_or_rerun(env: Env, session_factory: SessionFactory) -> None:
    await login(env, AdminRole.SUPPORT)
    _, generation_id = await spoken(session_factory, env, 9, GenerationStatus.SUCCEEDED)
    assert (await env.http.post(f"/admin/generations/{generation_id}/refund")).status_code == 403
    assert (await env.http.post(f"/admin/generations/{generation_id}/rerun")).status_code == 403
