import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.credits.errors import InsufficientCreditsError
from app.domain.credits.service import get_balance, grant_bonus
from app.domain.generations.cleanup import delete_expired_photos
from app.domain.generations.start import (
    InvalidPhotoError,
    TemplateUnavailableError,
    start_trend_generation,
)
from app.domain.generations.trend import (
    Outcome,
    RejectReason,
    TrendPipeline,
    parse_plan,
    run_trend_generation,
)
from app.gateway.base import (
    MediaInput,
    MediaResult,
    ProviderBlockedError,
    ProviderFailedError,
    TextResult,
)
from app.gateway.capabilities import VEO_3_1_LITE
from app.gateway.providers.fake import FakeVideoProvider
from app.gateway.registry import VideoProviderRegistry
from app.models import Generation, MusicTrack, TrendTemplate, User
from app.models.enums import GenerationStatus, Language

SessionFactory = async_sessionmaker[AsyncSession]
PHOTO = b"\xff\xd8jpeg"
GOOD_PLAN = json.dumps(
    {
        "photo_ok": True,
        "reject_reason": None,
        "image_prompt": "first frame",
        "video_prompt": "slow dolly in",
    }
)


class MemoryStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, key: str, data: bytes) -> None:
        self.files[key] = data

    async def load(self, key: str) -> bytes:
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)


@dataclass
class ScriptedText:
    """Returns the scripted replies in order; an exception in the list is raised instead."""

    replies: list[str | Exception]
    calls: int = 0

    async def complete(
        self, instructions: str, prompt: str, media: tuple[MediaInput, ...]
    ) -> TextResult:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        return TextResult(text=reply, cost_usd=Decimal("0.01"))


@dataclass
class FakeImage:
    async def compose(self, prompt: str, images: tuple[MediaInput, ...]) -> MediaResult:
        return MediaResult(data=b"png", mime_type="image/png", cost_usd=Decimal("0.07"))


@dataclass
class FakeMusic:
    calls: int = 0

    async def compose(self, prompt: str) -> MediaResult:
        self.calls += 1
        return MediaResult(data=b"mp3", mime_type="audio/mpeg", cost_usd=Decimal("0.04"))


@dataclass
class FakeNotifier:
    results: list[tuple[int, int, int]] = field(default_factory=list)
    failures: list[tuple[Outcome, RejectReason | None]] = field(default_factory=list)

    async def send_trend_result(
        self, chat_id: int, language: Language, video: bytes, generation_id: int, price: int
    ) -> str:
        assert video.startswith(b"composed:")
        self.results.append((chat_id, generation_id, price))
        return f"file-{generation_id}"

    async def send_failure(
        self, chat_id: int, language: Language, outcome: Outcome, reason: RejectReason | None
    ) -> None:
        self.failures.append((outcome, reason))


async def fake_compose(video: bytes, music: bytes | None, seconds: float) -> bytes:
    return b"composed:" + video + b"|" + (music or b"silent")


@dataclass
class Harness:
    pipeline: TrendPipeline
    store: MemoryStore
    notifier: FakeNotifier
    music: FakeMusic
    video: FakeVideoProvider


def make_harness(factory: SessionFactory, text: ScriptedText) -> Harness:
    store = MemoryStore()
    notifier = FakeNotifier()
    music = FakeMusic()
    video = FakeVideoProvider("veo-test", VEO_3_1_LITE)
    pipeline = TrendPipeline(
        session_factory=factory,
        text=text,
        image=FakeImage(),
        music=music,
        videos=VideoProviderRegistry({"vertex": lambda model: video}),
        store=store,
        notifier=notifier,
        compose=fake_compose,
        retry_delay_seconds=0,
    )
    return Harness(pipeline, store, notifier, music, video)


async def active_template_id(factory: SessionFactory, slug: str = "registon-oqshomi") -> int:
    async with factory() as session:
        template_id = await session.scalar(
            select(TrendTemplate.id).where(TrendTemplate.slug == slug)
        )
    assert template_id is not None
    return template_id


async def user_with_credits(factory: SessionFactory, credits: int, telegram_id: int = 7001) -> int:
    async with factory() as session, session.begin():
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.flush()
        if credits:
            await grant_bonus(session, user.id, credits, "test")
        return user.id


async def queue(factory: SessionFactory, store: MemoryStore, user_id: int) -> int:
    template_id = await active_template_id(factory)
    async with factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        generation = await start_trend_generation(
            session, store, user, template_id, PHOTO, "image/jpeg"
        )
        return generation.id


async def load(factory: SessionFactory, generation_id: int) -> Generation:
    async with factory() as session:
        generation = await session.get(Generation, generation_id)
    assert generation is not None
    return generation


async def available(factory: SessionFactory, user_id: int) -> int:
    async with factory() as session:
        return (await get_balance(session, user_id)).available


async def test_success_spends_credits_and_delivers_video(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory, ScriptedText([GOOD_PLAN]))
    user_id = await user_with_credits(session_factory, 5)
    generation_id = await queue(session_factory, harness.store, user_id)
    assert await available(session_factory, user_id) == 3

    outcome = await run_trend_generation(harness.pipeline, generation_id)

    assert outcome is Outcome.SUCCEEDED
    generation = await load(session_factory, generation_id)
    assert generation.status is GenerationStatus.SUCCEEDED
    assert generation.telegram_file_id == f"file-{generation_id}"
    assert generation.cost_usd == Decimal("0.12")  # plan 0.01 + frame 0.07 + music 0.04
    assert await available(session_factory, user_id) == 3
    assert harness.notifier.results == [(7001, generation_id, 2)]
    request = harness.video.requests[0]
    assert (request.duration_seconds, request.audio) == (8, False)
    assert request.first_frame is not None


async def test_music_is_generated_once_per_trend(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory, ScriptedText([GOOD_PLAN]))
    user_id = await user_with_credits(session_factory, 10)

    for _ in range(2):
        generation_id = await queue(session_factory, harness.store, user_id)
        assert await run_trend_generation(harness.pipeline, generation_id) is Outcome.SUCCEEDED

    assert harness.music.calls == 1
    async with session_factory() as session:
        tracks = list(await session.scalars(select(MusicTrack)))
    assert len(tracks) == 1


async def test_rejected_photo_returns_credits(session_factory: SessionFactory) -> None:
    plan = json.dumps({"photo_ok": False, "reject_reason": "minor"})
    harness = make_harness(session_factory, ScriptedText([plan]))
    user_id = await user_with_credits(session_factory, 2)
    generation_id = await queue(session_factory, harness.store, user_id)

    outcome = await run_trend_generation(harness.pipeline, generation_id)

    assert outcome is Outcome.PHOTO_REJECTED
    assert (await load(session_factory, generation_id)).error_code == "photo_rejected:minor"
    assert await available(session_factory, user_id) == 2
    assert harness.notifier.failures == [(Outcome.PHOTO_REJECTED, RejectReason.MINOR)]
    assert harness.video.requests == []


async def test_safety_block_returns_credits(session_factory: SessionFactory) -> None:
    harness = make_harness(
        session_factory, ScriptedText([ProviderBlockedError("prohibited_content")])
    )
    user_id = await user_with_credits(session_factory, 2)
    generation_id = await queue(session_factory, harness.store, user_id)

    assert await run_trend_generation(harness.pipeline, generation_id) is Outcome.BLOCKED
    assert (await load(session_factory, generation_id)).status is GenerationStatus.BLOCKED
    assert await available(session_factory, user_id) == 2


async def test_transient_failure_is_retried(session_factory: SessionFactory) -> None:
    text = ScriptedText([ProviderFailedError("Connection error."), GOOD_PLAN])
    harness = make_harness(session_factory, text)
    user_id = await user_with_credits(session_factory, 2)
    generation_id = await queue(session_factory, harness.store, user_id)

    assert await run_trend_generation(harness.pipeline, generation_id) is Outcome.SUCCEEDED
    assert text.calls == 2


async def test_persistent_failure_returns_credits(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory, ScriptedText([ProviderFailedError("down")]))
    user_id = await user_with_credits(session_factory, 2)
    generation_id = await queue(session_factory, harness.store, user_id)

    assert await run_trend_generation(harness.pipeline, generation_id) is Outcome.FAILED
    assert await available(session_factory, user_id) == 2
    assert harness.notifier.failures == [(Outcome.FAILED, None)]


async def test_duplicate_job_is_ignored(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory, ScriptedText([GOOD_PLAN]))
    user_id = await user_with_credits(session_factory, 2)
    generation_id = await queue(session_factory, harness.store, user_id)

    assert await run_trend_generation(harness.pipeline, generation_id) is Outcome.SUCCEEDED
    assert await run_trend_generation(harness.pipeline, generation_id) is None
    assert len(harness.notifier.results) == 1


async def test_start_requires_credits_and_active_trend(session_factory: SessionFactory) -> None:
    store = MemoryStore()
    user_id = await user_with_credits(session_factory, 1)
    inactive_id = await active_template_id(session_factory, "atlas-shamolda")
    active_id = await active_template_id(session_factory)

    async with session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        with pytest.raises(InsufficientCreditsError):
            await start_trend_generation(session, store, user, active_id, PHOTO, "image/jpeg")
        await session.rollback()
        with pytest.raises(TemplateUnavailableError):
            await start_trend_generation(session, store, user, inactive_id, PHOTO, "image/jpeg")
        with pytest.raises(InvalidPhotoError):
            await start_trend_generation(session, store, user, active_id, PHOTO, "image/gif")
    assert store.files == {}


async def test_photos_are_deleted_after_retention(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory, ScriptedText([GOOD_PLAN]))
    user_id = await user_with_credits(session_factory, 2)
    generation_id = await queue(session_factory, harness.store, user_id)
    await run_trend_generation(harness.pipeline, generation_id)
    key = (await load(session_factory, generation_id)).input_media_key
    assert key in harness.store.files

    early = await delete_expired_photos(session_factory, harness.store)
    later = await delete_expired_photos(
        session_factory, harness.store, now=datetime.now(UTC) + timedelta(hours=25)
    )

    assert (early, later) == (0, 1)
    assert key not in harness.store.files
    assert (await load(session_factory, generation_id)).input_media_key is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (GOOD_PLAN, (True, None)),
        ('```json\n{"photo_ok": false, "reject_reason": "celebrity"}\n```', (False, "celebrity")),
        ('{"photo_ok": false, "reject_reason": "something else"}', (False, "low_quality")),
    ],
)
def test_parse_plan(text: str, expected: tuple[bool, str | None]) -> None:
    plan = parse_plan(text)
    assert (plan.photo_ok, plan.reject_reason) == expected


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"image_prompt": "x"}',
        '{"photo_ok": true, "image_prompt": "", "video_prompt": ""}',
    ],
)
def test_parse_plan_rejects_bad_replies(text: str) -> None:
    with pytest.raises(ProviderFailedError):
        parse_plan(text)
