"""Prices (⚡ per product) and packs (so'm / Stars per ⚡), edited without a deploy."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.admin.deps import CurrentAdmin, EditorAdmin, SessionDep
from app.models import Pack, ProductPrice
from app.models.enums import Product, Resolution

router = APIRouter(prefix="/catalog")

RowId = Annotated[int, Path(gt=0)]


class PriceOut(BaseModel):
    id: int
    product: Product
    resolution: Resolution
    credits: int
    is_active: bool


class PricePatch(BaseModel):
    credits: int | None = Field(default=None, ge=1, le=1_000)
    is_active: bool | None = None


class PackFields(BaseModel):
    title_uz: str = Field(min_length=1, max_length=64)
    title_ru: str = Field(min_length=1, max_length=64)
    price_uzs: int = Field(ge=1_000, le=100_000_000)
    # None: not sold inside the bot.
    price_stars: int | None = Field(default=None, ge=1, le=100_000)
    credits: int = Field(ge=1, le=100_000)
    bonus_credits: int = Field(default=0, ge=0, le=100_000)
    is_one_time: bool = False
    sort_order: int = Field(default=0, ge=0, le=100_000)
    is_active: bool = True


class PackIn(PackFields):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[a-z0-9_-]+$")


class PackPatch(BaseModel):
    title_uz: str | None = Field(default=None, min_length=1, max_length=64)
    title_ru: str | None = Field(default=None, min_length=1, max_length=64)
    price_uzs: int | None = Field(default=None, ge=1_000, le=100_000_000)
    price_stars: int | None = Field(default=None, ge=1, le=100_000)
    credits: int | None = Field(default=None, ge=1, le=100_000)
    bonus_credits: int | None = Field(default=None, ge=0, le=100_000)
    is_one_time: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    is_active: bool | None = None


class PackOut(PackIn):
    id: int

    @classmethod
    def of(cls, pack: Pack) -> "PackOut":
        return cls(
            id=pack.id,
            code=pack.code,
            title_uz=pack.title_uz,
            title_ru=pack.title_ru,
            price_uzs=pack.price_uzs,
            price_stars=pack.price_stars,
            credits=pack.credits,
            bonus_credits=pack.bonus_credits,
            is_one_time=pack.is_one_time,
            sort_order=pack.sort_order,
            is_active=pack.is_active,
        )


def _price(row: ProductPrice) -> PriceOut:
    return PriceOut(
        id=row.id,
        product=row.product,
        resolution=row.resolution,
        credits=row.credits,
        is_active=row.is_active,
    )


@router.get("/prices")
async def prices(session: SessionDep, _: CurrentAdmin) -> list[PriceOut]:
    rows = await session.scalars(
        select(ProductPrice).order_by(ProductPrice.product, ProductPrice.resolution)
    )
    return [_price(row) for row in rows]


@router.patch("/prices/{price_id}")
async def update_price(
    price_id: RowId, body: PricePatch, session: SessionDep, _: EditorAdmin
) -> PriceOut:
    row = await session.get(ProductPrice, price_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "price not found")
    # Orders already placed keep the ⚡ they were charged; only new ones use this.
    for key, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(row, key, value)
    await session.commit()
    return _price(row)


@router.get("/packs")
async def packs(session: SessionDep, _: CurrentAdmin) -> list[PackOut]:
    rows = await session.scalars(select(Pack).order_by(Pack.sort_order, Pack.id))
    return [PackOut.of(pack) for pack in rows]


@router.post("/packs", status_code=status.HTTP_201_CREATED)
async def create_pack(body: PackIn, session: SessionDep, _: EditorAdmin) -> PackOut:
    pack = Pack(**body.model_dump())
    session.add(pack)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "code_taken") from exc
    await session.commit()
    return PackOut.of(pack)


@router.patch("/packs/{pack_id}")
async def update_pack(
    pack_id: RowId, body: PackPatch, session: SessionDep, _: EditorAdmin
) -> PackOut:
    pack = await session.get(Pack, pack_id)
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pack not found")
    # price_stars may be cleared (null) to take a pack off the bot's shelf.
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key != "price_stars":
            continue
        setattr(pack, key, value)
    await session.commit()
    return PackOut.of(pack)
