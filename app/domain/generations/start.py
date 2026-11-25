"""Creating a generation: price lookup, ⚡ hold and the stored input photo, in one transaction."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.credits.service import hold_credits
from app.media.store import MediaStore
from app.models import Generation, ProductPrice, TrendTemplate, User
from app.models.enums import Product, Resolution

TREND_RESOLUTION = Resolution.P1080
MAX_PHOTO_BYTES = 10 * 1024 * 1024
PHOTO_MIME_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class TemplateUnavailableError(LookupError):
    pass


class PriceUnavailableError(LookupError):
    pass


class InvalidPhotoError(ValueError):
    pass


async def trend_price(session: AsyncSession) -> int:
    credits = await session.scalar(
        select(ProductPrice.credits).where(
            ProductPrice.product == Product.TREND,
            ProductPrice.resolution == TREND_RESOLUTION,
            ProductPrice.is_active,
        )
    )
    if credits is None:
        raise PriceUnavailableError("no active trend price")
    return credits


async def start_trend_generation(
    session: AsyncSession,
    store: MediaStore,
    user: User,
    template_id: int,
    photo: bytes,
    mime_type: str,
    source_generation_id: int | None = None,
) -> Generation:
    """Raises InsufficientCreditsError when the user cannot pay; the caller commits."""
    extension = PHOTO_MIME_TYPES.get(mime_type)
    if extension is None:
        raise InvalidPhotoError(f"unsupported photo type {mime_type}")
    if not photo or len(photo) > MAX_PHOTO_BYTES:
        raise InvalidPhotoError("photo is empty or larger than 10 MB")
    template = await session.get(TrendTemplate, template_id)
    if template is None or not template.is_active:
        raise TemplateUnavailableError(f"trend {template_id} is not available")
    price = await trend_price(session)

    generation = Generation(
        user_id=user.id,
        product=Product.TREND,
        resolution=TREND_RESOLUTION,
        credits_cost=price,
        template_id=template.id,
        source_generation_id=source_generation_id,
    )
    session.add(generation)
    await session.flush()
    await hold_credits(session, user.id, generation.id, price)
    generation.input_media_key = f"inputs/{generation.id}.{extension}"
    await store.save(generation.input_media_key, photo)
    return generation


def photo_mime_type(key: str) -> str:
    extension = key.rsplit(".", 1)[-1]
    for mime, known in PHOTO_MIME_TYPES.items():
        if known == extension:
            return mime
    raise InvalidPhotoError(f"unknown photo extension in {key}")
