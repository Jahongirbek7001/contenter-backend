from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.models import Pack

router = APIRouter(prefix="/api", tags=["catalog"])


class PackOut(BaseModel):
    code: str
    title_uz: str
    title_ru: str
    price_uzs: int
    credits: int
    bonus_credits: int
    is_one_time: bool


@router.get("/packs")
async def list_packs(session: Annotated[AsyncSession, Depends(get_session)]) -> list[PackOut]:
    packs = await session.scalars(
        select(Pack).where(Pack.is_active).order_by(Pack.sort_order, Pack.id)
    )
    return [
        PackOut(
            code=pack.code,
            title_uz=pack.title_uz,
            title_ru=pack.title_ru,
            price_uzs=pack.price_uzs,
            credits=pack.credits,
            bonus_credits=pack.bonus_credits,
            is_one_time=pack.is_one_time,
        )
        for pack in packs
    ]
