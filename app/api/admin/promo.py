from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.admin.deps import CurrentAdmin, EditorAdmin, SessionDep
from app.domain.promo import normalize_code, valid_code
from app.models import PromoCode, PromoRedemption

router = APIRouter(prefix="/promo-codes")

PromoId = Annotated[int, Path(gt=0)]


class PromoRow(BaseModel):
    id: int
    code: str
    credits: int
    max_uses: int | None
    expires_at: datetime | None
    is_active: bool
    created_at: datetime
    redemptions: int


class PromoIn(BaseModel):
    code: str = Field(min_length=3, max_length=32)
    credits: int = Field(ge=1, le=1_000)
    max_uses: int | None = Field(default=None, ge=1, le=1_000_000)
    expires_at: datetime | None = None


class PromoPatch(BaseModel):
    is_active: bool


async def _rows(session: SessionDep, promo_id: int | None = None) -> list[PromoRow]:
    used = (
        select(PromoRedemption.promo_id, func.count().label("used"))
        .group_by(PromoRedemption.promo_id)
        .subquery()
    )
    query = (
        select(PromoCode, func.coalesce(used.c.used, 0))
        .outerjoin(used, used.c.promo_id == PromoCode.id)
        .order_by(PromoCode.id.desc())
    )
    if promo_id is not None:
        query = query.where(PromoCode.id == promo_id)
    rows = await session.execute(query)
    return [
        PromoRow(
            id=promo.id,
            code=promo.code,
            credits=promo.credits,
            max_uses=promo.max_uses,
            expires_at=promo.expires_at,
            is_active=promo.is_active,
            created_at=promo.created_at,
            redemptions=int(count),
        )
        for promo, count in rows
    ]


@router.get("")
async def list_promo_codes(session: SessionDep, _: CurrentAdmin) -> list[PromoRow]:
    return await _rows(session)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_promo_code(body: PromoIn, session: SessionDep, _: EditorAdmin) -> PromoRow:
    if not valid_code(body.code):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_code")
    promo = PromoCode(
        code=normalize_code(body.code),
        credits=body.credits,
        max_uses=body.max_uses,
        expires_at=body.expires_at,
    )
    session.add(promo)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "code_taken") from exc
    await session.commit()
    return (await _rows(session, promo.id))[0]


@router.patch("/{promo_id}")
async def update_promo_code(
    promo_id: PromoId, body: PromoPatch, session: SessionDep, _: EditorAdmin
) -> PromoRow:
    promo = await session.get(PromoCode, promo_id)
    if promo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    promo.is_active = body.is_active
    await session.commit()
    return (await _rows(session, promo_id))[0]
