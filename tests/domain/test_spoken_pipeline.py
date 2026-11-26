import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.credits.errors import InsufficientCreditsError
from app.domain.credits.service import get_balance, grant_bonus
from app.domain.generations.cleanup import delete_expired_videos
from app.domain.generations.runner import Outcome, RejectReason
from app.domain.generations.start import StyleUnavailableError, start_spoken_generation
from app.domain.generations.talking import SpokenPipeline, run_spoken_generation
from app.domain.talking.script import (
    Script,
    ScriptError,
    parse_script,
    script_from_user,
    write_script,
)
from app.gateway.base import (
    MediaInput,
    ProviderBlockedError,
    ProviderFailedError,
    TextResult,
    VideoResult,
)
from app.gateway.capabilities import OMNI_1_2_FLASH
from app.gateway.providers.fake import FakeVideoProvider
from app.gateway.registry import VideoProviderRegistry
from app.media.ffmpeg import Segment
from app.models import Generation, ScriptStyle, User
from app.models.enums import GenerationStatus, Language, Product, Resolution

SessionFactory = async_sessionmaker[AsyncSession]
PHOTO = b"\xff\xd8jpeg"
SELFIE = MediaInput(PHOTO, "image/jpeg")
BIBLE = "A bright clothing shop, waist-up framing, warm voice."
SERIES = Script("Winter jackets sale", ("Part one.", "Part two.", "Part three."), BIBLE)
TALKING = Script("Winter jackets sale", ("Only line.",), BIBLE)


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


class FlakyExtendProvider(FakeVideoProvider):
    """Extension number `fail_from` and later fail, like series part 3 in the S1 probe."""

    def __init__(self, fail_from: int, error: Exception) -> None:
        super().__init__("omni-test", OMNI_1_2_FLASH)
        self.fail_from = fail_from
        self.error = error
        self.extensions: list[str] = []

    async def extend(self, continuation_id: str, prompt: str, duration_seconds: int) -> VideoResult:
        self.extensions.append(prompt)
        if len(self.extensions) >= self.fail_from:
            raise self.error
        return await super().extend(continuation_id, prompt, duration_seconds)


@dataclass
class FakeNotifier:
    results: list[tuple[int, Resolution]] = field(default_factory=list)
    failures: list[Outcome] = field(default_factory=list)

    async def send_spoken_result(
        self,
        chat_id: int,
        language: Language,
        video: bytes,
        generation_id: int,
        resolution: Resolution,
    ) -> str:
        self.results.append((generation_id, resolution))
        return f"file-{generation_id}"

    async def send_failure(
        self, chat_id: int, language: Language, outcome: Outcome, reason: RejectReason | None
    ) -> None:
        self.failures.append(outcome)


@dataclass
class Composer:
    calls: list[tuple[list[Segment], bool, str | None]] = field(default_factory=list)

    async def __call__(
        self,
        segments: Sequence[Segment],
        resolution: Resolution,
        subtitles: bool,
        contact: str | None,
    ) -> bytes:
        self.calls.append((list(segments), subtitles, contact))
        return b"final-mp4"


@dataclass
class Harness:
    pipeline: SpokenPipeline
    store: MemoryStore
    notifier: FakeNotifier
    compose: Composer
    video: FakeVideoProvider


def make_harness(factory: SessionFactory, video: FakeVideoProvider | None = None) -> Harness:
    store, notifier, compose = MemoryStore(), FakeNotifier(), Composer()
    provider = video or FakeVideoProvider("omni-test", OMNI_1_2_FLASH)
    pipeline = SpokenPipeline(
        session_factory=factory,
        videos=VideoProviderRegistry({"gemini": lambda model: provider}),
        store=store,
        notifier=notifier,
        compose=compose,
        retry_delay_seconds=0,
    )
    return Harness(pipeline, store, notifier, compose, provider)


async def style_id(factory: SessionFactory, slug: str = "sotuv") -> int:
    async with factory() as session:
        found = await session.scalar(select(ScriptStyle.id).where(ScriptStyle.slug == slug))
    assert found is not None
    return found


async def user_with_credits(factory: SessionFactory, credits: int) -> int:
    async with factory() as session, session.begin():
        user = User(telegram_id=7101)
        session.add(user)
        await session.flush()
        if credits:
            await grant_bonus(session, user.id, credits, "test")
        return user.id


async def queue(
    factory: SessionFactory,
    store: MemoryStore,
    user_id: int,
    product: Product = Product.SERIES,
    resolution: Resolution = Resolution.P720,
    script: Script = SERIES,
) -> int:
    style = await style_id(factory)
    async with factory() as session, session.begin():
        user = await session.get(User, user_id)
        assert user is not None
        generation = await start_spoken_generation(
            session,
            store,
            user,
            product=product,
            resolution=resolution,
            style_id=style,
            language=Language.UZ,
            script_json=script.to_json(),
            idea=script.idea,
            photo=PHOTO,
            mime_type="image/jpeg",
            subtitles=True,
            contact_text="  +998 90 123 45 67  ",
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


async def test_series_price_is_held_by_resolution(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory)
    user_id = await user_with_credits(session_factory, 12)

    generation_id = await queue(session_factory, harness.store, user_id)

    assert await available(session_factory, user_id) == 3  # 720p series = 9 ⚡
    generation = await load(session_factory, generation_id)
    assert generation.contact_text == "+998 90 123 45 67"
    assert generation.speech_language is Language.UZ
    with pytest.raises(InsufficientCreditsError):
        await queue(session_factory, harness.store, user_id)


async def test_talking_video_is_one_omni_call(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory)
    user_id = await user_with_credits(session_factory, 5)
    generation_id = await queue(
        session_factory, harness.store, user_id, Product.TALKING, Resolution.P1080, TALKING
    )

    outcome = await run_spoken_generation(harness.pipeline, generation_id)

    assert outcome is Outcome.SUCCEEDED
    request = harness.video.requests[0]
    assert (request.duration_seconds, request.audio, request.resolution) == (
        10,
        True,
        Resolution.P1080,
    )
    assert "«Only line.»" in request.prompt and BIBLE in request.prompt
    assert harness.notifier.results == [(generation_id, Resolution.P1080)]
    generation = await load(session_factory, generation_id)
    assert generation.status is GenerationStatus.SUCCEEDED
    assert generation.output_media_key == f"outputs/{generation_id}.mp4"
    assert harness.store.files[generation.output_media_key] == b"final-mp4"
    assert await available(session_factory, user_id) == 0


async def test_series_extends_one_continuous_video(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory)
    user_id = await user_with_credits(session_factory, 9)
    generation_id = await queue(session_factory, harness.store, user_id)

    assert await run_spoken_generation(harness.pipeline, generation_id) is Outcome.SUCCEEDED

    [(segments, subtitles, contact)] = harness.compose.calls
    assert [segment.lines for segment in segments] == [SERIES.lines]
    assert (subtitles, contact) == (True, "+998 90 123 45 67")
    assert len(harness.video.requests) == 1
    assert (await load(session_factory, generation_id)).provider_job_id == (
        "gen-1,gen-1+ext,gen-1+ext+ext"
    )


@pytest.mark.parametrize(
    "error", [ProviderFailedError("connection reset"), ProviderBlockedError("prohibited")]
)
async def test_failed_extension_falls_back_to_separate_parts(
    session_factory: SessionFactory, error: Exception
) -> None:
    video = FlakyExtendProvider(fail_from=2, error=error)
    harness = make_harness(session_factory, video)
    user_id = await user_with_credits(session_factory, 9)
    generation_id = await queue(session_factory, harness.store, user_id)

    assert await run_spoken_generation(harness.pipeline, generation_id) is Outcome.SUCCEEDED

    [(segments, _, _)] = harness.compose.calls
    assert [segment.lines for segment in segments] == [
        ("Part one.", "Part two."),
        ("Part three.",),
    ]
    # Technical failures are retried, a block is not; then part 3 becomes a fresh clip.
    retries = 3 if isinstance(error, ProviderFailedError) else 1
    assert len(video.extensions) == 1 + retries
    assert len(video.requests) == 2
    assert "«Part three.»" in video.requests[-1].prompt
    assert await available(session_factory, user_id) == 0


async def test_blocked_first_part_refunds(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory)
    user_id = await user_with_credits(session_factory, 9)
    blocked = Script("x", ("[blocked] one", "two", "three"), BIBLE)
    generation_id = await queue(session_factory, harness.store, user_id, script=blocked)

    assert await run_spoken_generation(harness.pipeline, generation_id) is Outcome.BLOCKED

    assert (await load(session_factory, generation_id)).status is GenerationStatus.BLOCKED
    assert harness.notifier.failures == [Outcome.BLOCKED]
    assert await available(session_factory, user_id) == 9
    assert harness.compose.calls == []


async def test_missing_photo_refunds_and_runs_once(session_factory: SessionFactory) -> None:
    video = FlakyExtendProvider(fail_from=1, error=ProviderFailedError("down"))
    harness = make_harness(session_factory, video)
    user_id = await user_with_credits(session_factory, 9)
    generation_id = await queue(session_factory, harness.store, user_id)
    harness.store.files.clear()  # the photo is gone: the job cannot even start

    assert await run_spoken_generation(harness.pipeline, generation_id) is Outcome.FAILED
    assert await available(session_factory, user_id) == 9
    assert await run_spoken_generation(harness.pipeline, generation_id) is None


async def test_inactive_style_cannot_be_ordered(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory)
    user_id = await user_with_credits(session_factory, 9)
    async with session_factory() as session, session.begin():
        style = await session.get(ScriptStyle, await style_id(session_factory))
        assert style is not None
        style.is_active = False
    try:
        with pytest.raises(StyleUnavailableError):
            await queue(session_factory, harness.store, user_id)
    finally:
        async with session_factory() as session, session.begin():
            style = await session.get(ScriptStyle, await style_id(session_factory))
            assert style is not None
            style.is_active = True


async def test_finished_videos_expire_after_30_days(session_factory: SessionFactory) -> None:
    harness = make_harness(session_factory)
    user_id = await user_with_credits(session_factory, 5)
    generation_id = await queue(
        session_factory, harness.store, user_id, Product.TALKING, Resolution.P1080, TALKING
    )
    await run_spoken_generation(harness.pipeline, generation_id)
    key = f"outputs/{generation_id}.mp4"

    soon = await delete_expired_videos(session_factory, harness.store)
    later = await delete_expired_videos(
        session_factory, harness.store, now=datetime.now(UTC) + timedelta(days=31)
    )

    assert (soon, later) == (0, 1)
    assert key not in harness.store.files
    assert (await load(session_factory, generation_id)).output_media_key is None


# Script writing


@dataclass
class ScriptedText:
    reply: str
    prompts: list[str] = field(default_factory=list)
    media: list[tuple[MediaInput, ...]] = field(default_factory=list)

    async def complete(
        self, instructions: str, prompt: str, media: tuple[MediaInput, ...]
    ) -> TextResult:
        self.prompts.append(prompt)
        self.media.append(media)
        return TextResult(self.reply, Decimal("0.004"))


def reply(**overrides: object) -> str:
    data: dict[str, object] = {
        "photo_ok": True,
        "reject_reason": None,
        "idea_ok": True,
        "idea": "Qishki kurtkalar",
        "lines": ["Birinchi qator.", "Ikkinchi qator.", "Uchinchi qator."],
        "story_bible": BIBLE,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


async def test_voice_idea_is_sent_to_hydrogen_with_the_selfie() -> None:
    text = ScriptedText(reply())
    voice = MediaInput(b"OggS", "audio/ogg")

    draft = await write_script(
        text,
        style_instructions="Sell it.",
        language=Language.UZ,
        parts=3,
        selfie=SELFIE,
        idea=None,
        voice=voice,
    )

    assert draft.script is not None and len(draft.script.lines) == 3
    assert text.media == [(SELFIE, voice)]
    assert "Uzbek (Latin script)" in text.prompts[0]
    assert "attached voice message" in text.prompts[0]


async def test_rewrite_asks_for_a_different_version() -> None:
    text = ScriptedText(reply())
    await write_script(
        text,
        style_instructions="POV.",
        language=Language.RU,
        parts=3,
        selfie=SELFIE,
        idea="idea",
        previous=SERIES,
    )
    assert "do not repeat" in text.prompts[0] and "Part two." in text.prompts[0]


@pytest.mark.parametrize(
    ("raw", "photo_reason", "idea_rejected"),
    [
        (reply(photo_ok=False, reject_reason="minor"), RejectReason.MINOR, False),
        (reply(photo_ok=False, reject_reason="???"), RejectReason.LOW_QUALITY, False),
        (reply(idea_ok=False, lines=[]), None, True),
    ],
)
def test_rejections_carry_no_script(
    raw: str, photo_reason: RejectReason | None, idea_rejected: bool
) -> None:
    draft = parse_script(raw, 3, Decimal(0))
    assert (draft.script, draft.photo_reason, draft.idea_rejected) == (
        None,
        photo_reason,
        idea_rejected,
    )


@pytest.mark.parametrize(
    "raw",
    ["not json", reply(lines=["only one"]), reply(story_bible=""), reply(lines=["a", "", "c"])],
)
def test_malformed_scripts_are_provider_failures(raw: str) -> None:
    with pytest.raises(ProviderFailedError):
        parse_script(raw, 3, Decimal(0))


def test_user_text_replaces_lines_but_keeps_the_bible() -> None:
    own = script_from_user("Bir.\n\n  Ikki. \nUch.", SERIES)
    assert own.lines == ("Bir.", "Ikki.", "Uch.")
    assert own.story_bible == BIBLE
    assert Script.from_json(own.to_json()) == own


@pytest.mark.parametrize(
    ("text", "code"), [("one line only", "wrong_parts"), ("a\nb\n" + "so'z " * 27, "too_long")]
)
def test_user_text_is_validated(text: str, code: str) -> None:
    with pytest.raises(ScriptError) as error:
        script_from_user(text, SERIES)
    assert error.value.code == code
