"""Shared by every generation pipeline: provider retries, outcomes and the final
settle/release of the ⚡ hold with the user's apology message."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.credits.service import release_hold, settle_hold
from app.gateway.base import ProviderFailedError
from app.models import Generation
from app.models.enums import GenerationStatus, Language

log = structlog.get_logger(__name__)

PROVIDER_ATTEMPTS = 3


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    PHOTO_REJECTED = "photo_rejected"
    BLOCKED = "blocked"
    FAILED = "failed"


class RejectReason(StrEnum):
    NO_FACE = "no_face"
    SEVERAL_PEOPLE = "several_people"
    MINOR = "minor"
    CELEBRITY = "celebrity"
    NUDITY = "nudity"
    LOW_QUALITY = "low_quality"


def reject_reason(raw: object) -> RejectReason:
    """Unknown or missing reasons from the model fall back to low_quality."""
    if isinstance(raw, str) and raw in set(RejectReason):
        return RejectReason(raw)
    return RejectReason.LOW_QUALITY


class FailureNotifier(Protocol):
    async def send_failure(
        self, chat_id: int, language: Language, outcome: Outcome, reason: RejectReason | None
    ) -> None: ...


async def retry_provider[T](delay_seconds: float, call: Callable[[], Awaitable[T]]) -> T:
    """Retries technical failures only; a safety block is final."""
    for attempt in range(1, PROVIDER_ATTEMPTS + 1):
        try:
            return await call()
        except ProviderFailedError as exc:
            if attempt == PROVIDER_ATTEMPTS:
                raise
            log.warning("provider call failed, retrying", attempt=attempt, error=str(exc))
            await asyncio.sleep(delay_seconds * attempt)
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class Delivery:
    """What a successful generation leaves behind."""

    file_id: str
    prompt: str
    provider_job_id: str
    output_media_key: str | None = None


_STATUS = {
    Outcome.SUCCEEDED: GenerationStatus.SUCCEEDED,
    Outcome.PHOTO_REJECTED: GenerationStatus.FAILED,
    Outcome.BLOCKED: GenerationStatus.BLOCKED,
    Outcome.FAILED: GenerationStatus.FAILED,
}


async def finish_generation(
    session_factory: async_sessionmaker[AsyncSession],
    notifier: FailureNotifier,
    generation_id: int,
    chat_id: int,
    language: Language,
    outcome: Outcome,
    cost: Decimal,
    *,
    reason: RejectReason | None = None,
    delivery: Delivery | None = None,
) -> None:
    if (outcome is Outcome.SUCCEEDED) != (delivery is not None):
        raise ValueError("a delivery is required for success and only for success")
    async with session_factory() as session, session.begin():
        generation = await session.get(Generation, generation_id, with_for_update=True)
        if generation is None:
            raise LookupError(f"generation {generation_id} disappeared")
        generation.status = _STATUS[outcome]
        generation.cost_usd = cost
        generation.finished_at = datetime.now(UTC)
        if delivery is not None:
            generation.telegram_file_id = delivery.file_id
            generation.prompt = delivery.prompt
            generation.provider_job_id = delivery.provider_job_id
            generation.output_media_key = delivery.output_media_key
            await settle_hold(session, generation.id)
        else:
            generation.error_code = f"{outcome}:{reason}" if reason else str(outcome)
            await release_hold(session, generation.id)
    if outcome is not Outcome.SUCCEEDED:
        try:
            await notifier.send_failure(chat_id, language, outcome, reason)
        except Exception:
            # ⚡ is already back; a failed apology message must not undo that.
            log.exception("failure notice not delivered", generation_id=generation_id)
