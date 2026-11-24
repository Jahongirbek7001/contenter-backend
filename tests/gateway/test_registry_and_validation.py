import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.gateway.base import (
    MediaInput,
    ProviderBlockedError,
    UnsupportedRequestError,
    VideoRequest,
)
from app.gateway.capabilities import OMNI_1_2_FLASH, VEO_3_1_LITE
from app.gateway.providers.fake import BLOCKED_MARKER, FakeVideoProvider
from app.gateway.registry import RouteNotAvailableError, VideoProviderRegistry
from app.models import ModelRoute
from app.models.enums import Product, Resolution

PHOTO = MediaInput(data=b"jpg", mime_type="image/jpeg")


def trend_request(**overrides: object) -> VideoRequest:
    values: dict[str, object] = {
        "prompt": "dance",
        "duration_seconds": 8,
        "resolution": Resolution.P1080,
        "audio": False,
        "first_frame": PHOTO,
    }
    values.update(overrides)
    return VideoRequest(**values)  # type: ignore[arg-type]


async def test_veo_lite_accepts_trend_request() -> None:
    provider = FakeVideoProvider("veo", VEO_3_1_LITE)

    result = await provider.generate(trend_request())

    assert result.provider_job_id == "gen-1"


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_seconds": 10},
        {"resolution": Resolution.P360},
        {"audio": True},
        {"reference_images": (PHOTO,)},
    ],
)
async def test_veo_lite_rejects_unsupported_requests(overrides: dict[str, object]) -> None:
    provider = FakeVideoProvider("veo", VEO_3_1_LITE)

    with pytest.raises(UnsupportedRequestError):
        await provider.generate(trend_request(**overrides))


async def test_omni_rejects_more_than_six_reference_images() -> None:
    provider = FakeVideoProvider("omni", OMNI_1_2_FLASH)
    request = trend_request(duration_seconds=10, audio=True, reference_images=(PHOTO,) * 7)

    with pytest.raises(UnsupportedRequestError):
        await provider.generate(request)


async def test_blocked_prompt_raises_blocked_error() -> None:
    provider = FakeVideoProvider("veo", VEO_3_1_LITE)

    with pytest.raises(ProviderBlockedError):
        await provider.generate(trend_request(prompt=f"x {BLOCKED_MARKER}"))


def registry() -> VideoProviderRegistry:
    return VideoProviderRegistry(
        {
            "vertex": lambda model: FakeVideoProvider(model, VEO_3_1_LITE),
            "gemini": lambda model: FakeVideoProvider(model, OMNI_1_2_FLASH),
        }
    )


async def test_registry_routes_products_from_seeded_routes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        trend = await registry().resolve(session, Product.TREND)
        talking = await registry().resolve(session, Product.TALKING)

    assert trend.capabilities is VEO_3_1_LITE
    assert talking.capabilities is OMNI_1_2_FLASH


async def test_registry_refuses_disabled_route(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(ModelRoute).where(ModelRoute.product == Product.TREND).values(is_enabled=False)
        )
        with pytest.raises(RouteNotAvailableError):
            await registry().resolve(session, Product.TREND)
        await session.rollback()
