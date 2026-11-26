"""Spoken video pipeline (talking 10 s, series 3x10 s), run by the worker:
Omni generate from the selfie -> extend per extra part -> ffmpeg subtitles/contact -> Telegram.

Extend returns the whole video so far and keeps voice and scene continuous. The S1 probe saw
part 3 fail on extend twice, so when an extension fails the remaining parts are generated as
separate clips from the selfie and joined by ffmpeg instead of failing the series.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.generations.runner import (
    Delivery,
    FailureNotifier,
    Outcome,
    finish_generation,
    retry_provider,
)
from app.domain.generations.start import SPOKEN_PRODUCTS, photo_mime_type
from app.domain.talking.script import (
    PART_SECONDS,
    Script,
    continuation_prompt,
    speech_prompt,
)
from app.gateway.base import (
    MediaInput,
    ProviderBlockedError,
    ProviderFailedError,
    VideoProvider,
    VideoRequest,
    VideoResult,
)
from app.gateway.registry import VideoProviderRegistry
from app.media.ffmpeg import Segment
from app.media.store import MediaStore
from app.models import Generation, User
from app.models.enums import GenerationStatus, Language, Product, Resolution

log = structlog.get_logger(__name__)

RETRY_DELAY_SECONDS = 5.0


class SpokenNotifier(FailureNotifier, Protocol):
    async def send_spoken_result(
        self,
        chat_id: int,
        language: Language,
        video: bytes,
        generation_id: int,
        resolution: Resolution,
    ) -> str:
        """Sends the finished video; returns its Telegram file_id."""


SpokenComposer = Callable[[Sequence[Segment], Resolution, bool, str | None], Awaitable[bytes]]


@dataclass(frozen=True)
class SpokenPipeline:
    session_factory: async_sessionmaker[AsyncSession]
    videos: VideoProviderRegistry
    store: MediaStore
    notifier: SpokenNotifier
    compose: SpokenComposer
    retry_delay_seconds: float = RETRY_DELAY_SECONDS


@dataclass(frozen=True)
class _Job:
    generation_id: int
    chat_id: int
    language: Language
    product: Product
    resolution: Resolution
    speech_language: Language
    script: Script
    subtitles: bool
    contact: str | None
    input_key: str


async def run_spoken_generation(pipeline: SpokenPipeline, generation_id: int) -> Outcome | None:
    """Returns None when the generation was already picked up (duplicate job)."""
    job = await _claim(pipeline, generation_id)
    if job is None:
        return None
    cost = Decimal(0)
    job_ids: list[str] = []
    try:
        photo = await pipeline.store.load(job.input_key)
        selfie = MediaInput(data=photo, mime_type=photo_mime_type(job.input_key))
        async with pipeline.session_factory() as session:
            provider = await pipeline.videos.resolve(session, job.product)

        lines, bible = job.script.lines, job.script.story_bible
        first = await _generate(pipeline, provider, job, selfie, lines[0])
        cost += first.cost_usd
        job_ids.append(first.provider_job_id)
        segments = [Segment(first.data, (lines[0],))]
        chain: VideoResult | None = first
        for line in lines[1:]:
            if chain is not None and chain.continuation_id:
                try:
                    chain = await _extend(pipeline, provider, job, chain.continuation_id, line)
                except (ProviderBlockedError, ProviderFailedError) as exc:
                    log.warning(
                        "extend failed, generating the part separately",
                        generation_id=generation_id,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    chain = None
                else:
                    cost += chain.cost_usd
                    job_ids.append(chain.provider_job_id)
                    # The extension holds every part so far; it replaces the first segment.
                    segments[0] = Segment(chain.data, (*segments[0].lines, line))
                    continue
            clip = await _generate(pipeline, provider, job, selfie, line)
            cost += clip.cost_usd
            job_ids.append(clip.provider_job_id)
            segments.append(Segment(clip.data, (line,)))

        final = await pipeline.compose(segments, job.resolution, job.subtitles, job.contact)
        output_key = f"outputs/{job.generation_id}.mp4"
        await pipeline.store.save(output_key, final)
        file_id = await pipeline.notifier.send_spoken_result(
            job.chat_id, job.language, final, job.generation_id, job.resolution
        )
    except ProviderBlockedError as exc:
        log.info("spoken video blocked", generation_id=generation_id, detail=str(exc))
        await _finish(pipeline, job, Outcome.BLOCKED, cost)
        return Outcome.BLOCKED
    except Exception:
        # Any failure must give the user's ⚡ back; the cause is logged with the traceback.
        log.exception("spoken video failed", generation_id=generation_id)
        await _finish(pipeline, job, Outcome.FAILED, cost)
        return Outcome.FAILED

    delivery = Delivery(
        file_id=file_id,
        prompt=speech_prompt(job.speech_language, lines[0], bible),
        provider_job_id=",".join(job_ids),
        output_media_key=output_key,
    )
    await _finish(pipeline, job, Outcome.SUCCEEDED, cost, delivery)
    return Outcome.SUCCEEDED


async def _generate(
    pipeline: SpokenPipeline,
    provider: VideoProvider,
    job: _Job,
    selfie: MediaInput,
    line: str,
) -> VideoResult:
    request = VideoRequest(
        prompt=speech_prompt(job.speech_language, line, job.script.story_bible),
        duration_seconds=PART_SECONDS,
        resolution=job.resolution,
        audio=True,
        first_frame=selfie,
    )
    return await retry_provider(pipeline.retry_delay_seconds, lambda: provider.generate(request))


async def _extend(
    pipeline: SpokenPipeline,
    provider: VideoProvider,
    job: _Job,
    continuation_id: str,
    line: str,
) -> VideoResult:
    prompt = continuation_prompt(job.speech_language, line, job.script.story_bible)
    return await retry_provider(
        pipeline.retry_delay_seconds,
        lambda: provider.extend(continuation_id, prompt, PART_SECONDS),
    )


async def _claim(pipeline: SpokenPipeline, generation_id: int) -> _Job | None:
    async with pipeline.session_factory() as session, session.begin():
        generation = await session.get(Generation, generation_id, with_for_update=True)
        if generation is None or generation.status != GenerationStatus.PENDING:
            return None
        if (
            generation.product not in SPOKEN_PRODUCTS
            or generation.input_media_key is None
            or generation.script is None
            or generation.speech_language is None
        ):
            raise ValueError(f"generation {generation_id} is not a complete spoken video")
        user = await session.get(User, generation.user_id)
        if user is None:
            raise LookupError(f"generation {generation_id} has no user")
        generation.status = GenerationStatus.PROCESSING
        return _Job(
            generation_id=generation.id,
            chat_id=user.telegram_id,
            language=user.language,
            product=generation.product,
            resolution=generation.resolution,
            speech_language=generation.speech_language,
            script=Script.from_json(generation.script),
            subtitles=generation.subtitles,
            contact=generation.contact_text,
            input_key=generation.input_media_key,
        )


async def _finish(
    pipeline: SpokenPipeline,
    job: _Job,
    outcome: Outcome,
    cost: Decimal,
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
        delivery=delivery,
    )
