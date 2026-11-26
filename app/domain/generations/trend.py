"""Trend video pipeline, run by the worker:
photo check + prompts (Hydrogen) -> first frame (Nano Banana) -> Veo 1080p 8 s
-> cached Lyria track -> ffmpeg -> Telegram. ⚡ is settled on success and released otherwise.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.generations.runner import (
    Delivery,
    Outcome,
    RejectReason,
    finish_generation,
    reject_reason,
    retry_provider,
)
from app.domain.generations.start import photo_mime_type
from app.domain.trends.media import music_prompt, save_track
from app.gateway.base import (
    ImageProvider,
    MediaInput,
    MusicProvider,
    ProviderBlockedError,
    ProviderFailedError,
    TextProvider,
    VideoRequest,
)
from app.gateway.registry import VideoProviderRegistry
from app.media.store import MediaStore
from app.models import Generation, MusicTrack, TrendTemplate, User
from app.models.enums import GenerationStatus, Language, Product, Resolution

log = structlog.get_logger(__name__)

__all__ = ["Outcome", "RejectReason", "TrendPipeline", "parse_plan", "run_trend_generation"]

TREND_SECONDS = 8
RETRY_DELAY_SECONDS = 5.0

PLAN_INSTRUCTIONS = """You prepare a short trend video from a user's selfie.
First check the photo, then write prompts. Return JSON only:
{"photo_ok": true, "reject_reason": null, "image_prompt": "...", "video_prompt": "..."}

Set photo_ok to false and reject_reason to one of these when it applies:
- "no_face": no clearly visible human face
- "several_people": more than one person in the photo
- "minor": the person may be under 18
- "celebrity": the person is a well-known public figure
- "nudity": nudity or sexual content
- "low_quality": too blurry, dark or small to keep the face recognisable
When rejected, image_prompt and video_prompt are empty strings.

Otherwise, in English:
- image_prompt: edit of the selfie into the first frame of the trend scene, vertical 9:16,
  photorealistic, keeping the person's face and identity exactly. Follow the first-frame rules.
- video_prompt: an 8 second silent vertical clip that starts from that frame: subject action,
  camera movement, lighting, mood. No dialogue, no on-screen text, no logos."""


class Notifier(Protocol):
    async def send_trend_result(
        self, chat_id: int, language: Language, video: bytes, generation_id: int, price: int
    ) -> str:
        """Sends the finished video (with a re-create button at `price`); returns file_id."""

    async def send_failure(
        self, chat_id: int, language: Language, outcome: Outcome, reason: RejectReason | None
    ) -> None: ...


Composer = Callable[[bytes, bytes | None, float], Awaitable[bytes]]


@dataclass(frozen=True)
class TrendPipeline:
    session_factory: async_sessionmaker[AsyncSession]
    text: TextProvider
    image: ImageProvider
    music: MusicProvider
    videos: VideoProviderRegistry
    store: MediaStore
    notifier: Notifier
    compose: Composer
    retry_delay_seconds: float = RETRY_DELAY_SECONDS


@dataclass(frozen=True)
class _Job:
    generation_id: int
    chat_id: int
    language: Language
    template_id: int
    scene: str
    first_frame_rules: str
    music_mood: str | None
    input_key: str
    price: int


@dataclass(frozen=True)
class Plan:
    photo_ok: bool
    reject_reason: RejectReason | None
    image_prompt: str
    video_prompt: str


async def run_trend_generation(pipeline: TrendPipeline, generation_id: int) -> Outcome | None:
    """Returns None when the generation was already picked up (duplicate job)."""
    job = await _claim(pipeline, generation_id)
    if job is None:
        return None
    cost = Decimal(0)
    try:
        photo = await pipeline.store.load(job.input_key)
        selfie = MediaInput(data=photo, mime_type=photo_mime_type(job.input_key))

        planned = await _retry(
            pipeline,
            lambda: pipeline.text.complete(PLAN_INSTRUCTIONS, _plan_prompt(job), (selfie,)),
        )
        cost += planned.cost_usd
        plan = parse_plan(planned.text)
        if not plan.photo_ok:
            await _finish(pipeline, job, Outcome.PHOTO_REJECTED, cost, reason=plan.reject_reason)
            return Outcome.PHOTO_REJECTED

        frame = await _retry(pipeline, lambda: pipeline.image.compose(plan.image_prompt, (selfie,)))
        cost += frame.cost_usd
        async with pipeline.session_factory() as session:
            provider = await pipeline.videos.resolve(session, Product.TREND)
        request = VideoRequest(
            prompt=plan.video_prompt,
            duration_seconds=TREND_SECONDS,
            resolution=Resolution.P1080,
            audio=False,
            first_frame=MediaInput(data=frame.data, mime_type=frame.mime_type),
        )
        video = await _retry(pipeline, lambda: provider.generate(request))
        cost += video.cost_usd

        music, music_cost = await _music_for(pipeline, job)
        cost += music_cost
        final = await pipeline.compose(video.data, music, float(TREND_SECONDS))
        file_id = await pipeline.notifier.send_trend_result(
            job.chat_id, job.language, final, job.generation_id, job.price
        )
    except ProviderBlockedError as exc:
        log.info("trend blocked", generation_id=generation_id, detail=str(exc))
        await _finish(pipeline, job, Outcome.BLOCKED, cost)
        return Outcome.BLOCKED
    except Exception:
        # Any failure must give the user's ⚡ back; the cause is logged with the traceback.
        log.exception("trend failed", generation_id=generation_id)
        await _finish(pipeline, job, Outcome.FAILED, cost)
        return Outcome.FAILED

    await _finish(
        pipeline,
        job,
        Outcome.SUCCEEDED,
        cost,
        delivery=Delivery(
            file_id=file_id,
            prompt=json.dumps(
                {"image_prompt": plan.image_prompt, "video_prompt": plan.video_prompt},
                ensure_ascii=False,
            ),
            provider_job_id=video.provider_job_id,
        ),
    )
    return Outcome.SUCCEEDED


def parse_plan(text: str) -> Plan:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderFailedError(f"plan is not JSON: {text[:200]}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("photo_ok"), bool):
        raise ProviderFailedError(f"plan has no photo_ok: {text[:200]}")
    if not data["photo_ok"]:
        return Plan(
            photo_ok=False,
            reject_reason=reject_reason(data.get("reject_reason")),
            image_prompt="",
            video_prompt="",
        )
    image_prompt, video_prompt = data.get("image_prompt"), data.get("video_prompt")
    if not isinstance(image_prompt, str) or not isinstance(video_prompt, str):
        raise ProviderFailedError("plan is missing prompts")
    if not image_prompt.strip() or not video_prompt.strip():
        raise ProviderFailedError("plan has empty prompts")
    return Plan(True, None, image_prompt.strip(), video_prompt.strip())


def _plan_prompt(job: _Job) -> str:
    return f"Trend scene:\n{job.scene}\n\nFirst-frame rules:\n{job.first_frame_rules}"


async def _retry[T](pipeline: TrendPipeline, call: Callable[[], Awaitable[T]]) -> T:
    return await retry_provider(pipeline.retry_delay_seconds, call)


async def _claim(pipeline: TrendPipeline, generation_id: int) -> _Job | None:
    async with pipeline.session_factory() as session, session.begin():
        generation = await session.get(Generation, generation_id, with_for_update=True)
        if generation is None or generation.status != GenerationStatus.PENDING:
            return None
        if generation.template_id is None or generation.input_media_key is None:
            raise ValueError(f"generation {generation_id} has no template or photo")
        template = await session.get(TrendTemplate, generation.template_id)
        user = await session.get(User, generation.user_id)
        if template is None or user is None:
            raise LookupError(f"generation {generation_id} references missing rows")
        generation.status = GenerationStatus.PROCESSING
        return _Job(
            generation_id=generation.id,
            chat_id=user.telegram_id,
            language=user.language,
            template_id=template.id,
            scene=template.prompt_skeleton,
            first_frame_rules=template.first_frame_instructions,
            music_mood=template.music_prompt,
            input_key=generation.input_media_key,
            price=generation.credits_cost,
        )


async def _music_for(pipeline: TrendPipeline, job: _Job) -> tuple[bytes | None, Decimal]:
    """One Lyria track per trend, reused by every generation. Music is optional: on
    failure the video goes out silent rather than failing."""
    async with pipeline.session_factory() as session:
        key = await session.scalar(
            select(MusicTrack.storage_key)
            .where(MusicTrack.template_id == job.template_id, MusicTrack.is_active)
            .order_by(MusicTrack.id.desc())
            .limit(1)
        )
    if key is not None:
        return await pipeline.store.load(key), Decimal(0)
    mood = job.music_mood
    if not mood:
        return None, Decimal(0)
    try:
        track = await _retry(
            pipeline,
            lambda: pipeline.music.compose(music_prompt(mood)),
        )
    except (ProviderBlockedError, ProviderFailedError) as exc:
        log.warning(
            "music failed, sending without music",
            generation_id=job.generation_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        return None, Decimal(0)
    async with pipeline.session_factory() as session, session.begin():
        await save_track(session, pipeline.store, job.template_id, track.data, mood)
    return track.data, track.cost_usd


async def _finish(
    pipeline: TrendPipeline,
    job: _Job,
    outcome: Outcome,
    cost: Decimal,
    *,
    reason: RejectReason | None = None,
    delivery: Delivery | None = None,
) -> None:
    await finish_generation(
        pipeline.session_factory,
        pipeline.notifier,
        job.generation_id,
        job.chat_id,
        job.language,
        outcome,
        cost,
        reason=reason,
        delivery=delivery,
    )
