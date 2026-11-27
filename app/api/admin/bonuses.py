"""⚡ gift campaigns and the owner-editable settings (welcome gift, cost alert)."""

import logging
from datetime import UTC, datetime
from typing import Literal

from arq.connections import ArqRedis
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.admin.deps import CurrentAdmin, EditorAdmin, SessionDep
from app.domain.bonuses import SEGMENTS, create_campaign, segment_size
from app.domain.settings import SETTINGS, all_settings, set_setting
from app.models import BonusCampaign

router = APIRouter()
logger = logging.getLogger(__name__)

CAMPAIGN_JOB = "campaign_broadcast"
Segment = Literal["all", "buyers", "non_buyers", "active_30d"]


class CampaignIn(BaseModel):
    credits: int = Field(ge=1, le=100)
    segment: Segment
    message_uz: str = Field(default="", max_length=1000)
    message_ru: str = Field(default="", max_length=1000)


class CampaignOut(BaseModel):
    id: int
    credits: int
    segment: str
    message_uz: str
    message_ru: str
    created_by: str
    recipients: int
    sent: int
    finished_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, campaign: BonusCampaign) -> "CampaignOut":
        return cls(
            id=campaign.id,
            credits=campaign.credits,
            segment=campaign.segment,
            message_uz=campaign.message_uz,
            message_ru=campaign.message_ru,
            created_by=campaign.created_by,
            recipients=campaign.recipients,
            sent=campaign.sent,
            finished_at=campaign.finished_at,
            created_at=campaign.created_at,
        )


@router.get("/bonuses/segments")
async def segments(session: SessionDep, _: CurrentAdmin) -> dict[str, int]:
    """How many customers each campaign audience reaches right now."""
    now = datetime.now(UTC)
    return {segment: await segment_size(session, segment, now) for segment in SEGMENTS}


@router.get("/bonuses/campaigns")
async def campaigns(session: SessionDep, _: CurrentAdmin) -> list[CampaignOut]:
    rows = await session.scalars(select(BonusCampaign).order_by(BonusCampaign.id.desc()).limit(50))
    return [CampaignOut.of(campaign) for campaign in rows]


@router.post("/bonuses/campaigns", status_code=status.HTTP_201_CREATED)
async def start_campaign(
    body: CampaignIn, request: Request, session: SessionDep, admin: EditorAdmin
) -> CampaignOut:
    campaign = await create_campaign(
        session,
        credits=body.credits,
        segment=body.segment,
        message_uz=body.message_uz,
        message_ru=body.message_ru,
        created_by=admin.email,
        now=datetime.now(UTC),
    )
    await session.commit()
    arq: ArqRedis = request.app.state.arq
    try:
        await arq.enqueue_job(CAMPAIGN_JOB, campaign.id, _job_id=f"campaign:{campaign.id}")
    except Exception:
        # The ⚡ are credited either way; the announcement can be resent by the worker later.
        logger.exception("could not queue campaign %s", campaign.id)
    return CampaignOut.of(campaign)


@router.get("/settings")
async def get_settings(session: SessionDep, _: CurrentAdmin) -> dict[str, int]:
    return await all_settings(session)


@router.put("/settings")
async def update_settings(
    body: dict[str, int], session: SessionDep, _: EditorAdmin
) -> dict[str, int]:
    for key, value in body.items():
        spec = SETTINGS.get(key)
        if spec is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown setting {key}")
        try:
            await set_setting(session, spec, value)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return await all_settings(session)
