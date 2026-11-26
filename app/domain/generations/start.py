"""Creating a generation: price lookup, ⚡ hold and the stored input photo, in one transaction."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.credits.service import hold_credits
from app.media.store import MediaStore
from app.models import Generation, ProductPrice, ScriptStyle, TrendTemplate, User
from app.models.enums import GenerationStatus, Language, Product, Resolution

TREND_RESOLUTION = Resolution.P1080
MAX_PHOTO_BYTES = 10 * 1024 * 1024
PHOTO_MIME_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class TemplateUnavailableError(LookupError):
    pass


class PriceUnavailableError(LookupError):
    pass


class InvalidPhotoError(ValueError):
    pass


class UserBlockedError(PermissionError):
    pass


SPOKEN_PRODUCTS = (Product.TALKING, Product.SERIES)
MAX_CONTACT_CHARS = 64


class StyleUnavailableError(LookupError):
    pass


async def product_price(session: AsyncSession, product: Product, resolution: Resolution) -> int:
    credits = await session.scalar(
        select(ProductPrice.credits).where(
            ProductPrice.product == product,
            ProductPrice.resolution == resolution,
            ProductPrice.is_active,
        )
    )
    if credits is None:
        raise PriceUnavailableError(f"no active price for {product} {resolution}")
    return credits


async def product_prices(session: AsyncSession, product: Product) -> dict[Resolution, int]:
    rows = await session.execute(
        select(ProductPrice.resolution, ProductPrice.credits).where(
            ProductPrice.product == product, ProductPrice.is_active
        )
    )
    return {resolution: credits for resolution, credits in rows}


async def trend_price(session: AsyncSession) -> int:
    return await product_price(session, Product.TREND, TREND_RESOLUTION)


def _photo_extension(photo: bytes, mime_type: str) -> str:
    extension = PHOTO_MIME_TYPES.get(mime_type)
    if extension is None:
        raise InvalidPhotoError(f"unsupported photo type {mime_type}")
    if not photo or len(photo) > MAX_PHOTO_BYTES:
        raise InvalidPhotoError("photo is empty or larger than 10 MB")
    return extension


async def _hold_and_store(
    session: AsyncSession, store: MediaStore, generation: Generation, photo: bytes, extension: str
) -> Generation:
    session.add(generation)
    await session.flush()
    await hold_credits(session, generation.user_id, generation.id, generation.credits_cost)
    generation.input_media_key = f"inputs/{generation.id}.{extension}"
    await store.save(generation.input_media_key, photo)
    return generation


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
    if user.is_blocked:
        raise UserBlockedError(f"user {user.id} is blocked")
    extension = _photo_extension(photo, mime_type)
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
    return await _hold_and_store(session, store, generation, photo, extension)


async def start_spoken_generation(
    session: AsyncSession,
    store: MediaStore,
    user: User,
    *,
    product: Product,
    resolution: Resolution,
    style_id: int,
    language: Language,
    script_json: str,
    idea: str,
    photo: bytes,
    mime_type: str,
    subtitles: bool,
    contact_text: str | None,
) -> Generation:
    """Talking video or series from an approved script. Raises InsufficientCreditsError
    when the user cannot pay; the caller commits."""
    if product not in SPOKEN_PRODUCTS:
        raise ValueError(f"{product} is not a spoken product")
    if user.is_blocked:
        raise UserBlockedError(f"user {user.id} is blocked")
    extension = _photo_extension(photo, mime_type)
    style = await session.get(ScriptStyle, style_id)
    if style is None or not style.is_active:
        raise StyleUnavailableError(f"style {style_id} is not available")
    contact = (contact_text or "").strip()[:MAX_CONTACT_CHARS] or None
    generation = Generation(
        user_id=user.id,
        product=product,
        resolution=resolution,
        credits_cost=await product_price(session, product, resolution),
        style_id=style.id,
        speech_language=language,
        script=script_json,
        user_input=idea,
        subtitles=subtitles,
        contact_text=contact,
    )
    return await _hold_and_store(session, store, generation, photo, extension)


def photo_mime_type(key: str) -> str:
    extension = key.rsplit(".", 1)[-1]
    for mime, known in PHOTO_MIME_TYPES.items():
        if known == extension:
            return mime
    raise InvalidPhotoError(f"unknown photo extension in {key}")


class NotRerunnableError(ValueError):
    """`code` is shown in the admin cabinet: not_failed or photo_expired."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def rerun_generation(
    session: AsyncSession, store: MediaStore, generation_id: int
) -> Generation:
    """Admin re-run of a failed or blocked generation with the same inputs. It is a normal
    order: ⚡ is held again and released if it fails again. The photo is kept only 24 h."""
    original = await session.get(Generation, generation_id)
    if original is None:
        raise LookupError(f"generation {generation_id} not found")
    if original.status not in (GenerationStatus.FAILED, GenerationStatus.BLOCKED):
        raise NotRerunnableError("not_failed")
    user = await session.get(User, original.user_id)
    if user is None or original.input_media_key is None:
        raise NotRerunnableError("photo_expired")
    try:
        photo = await store.load(original.input_media_key)
    except FileNotFoundError as exc:
        raise NotRerunnableError("photo_expired") from exc
    mime_type = photo_mime_type(original.input_media_key)
    if original.product is Product.TREND:
        if original.template_id is None:
            raise ValueError(f"trend generation {generation_id} has no template")
        return await start_trend_generation(
            session, store, user, original.template_id, photo, mime_type, original.id
        )
    if original.style_id is None or original.script is None or original.speech_language is None:
        raise ValueError(f"spoken generation {generation_id} is incomplete")
    generation = await start_spoken_generation(
        session,
        store,
        user,
        product=original.product,
        resolution=original.resolution,
        style_id=original.style_id,
        language=original.speech_language,
        script_json=original.script,
        idea=original.user_input or "",
        photo=photo,
        mime_type=mime_type,
        subtitles=original.subtitles,
        contact_text=original.contact_text,
    )
    generation.source_generation_id = original.id
    return generation
