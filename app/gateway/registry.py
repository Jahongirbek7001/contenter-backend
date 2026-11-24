from collections.abc import Callable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.base import VideoProvider
from app.models import ModelRoute
from app.models.enums import Product

VideoProviderFactory = Callable[[str], VideoProvider]


class RouteNotAvailableError(LookupError):
    def __init__(self, product: Product) -> None:
        super().__init__(f"no enabled model route for {product}")
        self.product = product


class VideoProviderRegistry:
    """Resolves product -> provider using model_routes, so routing changes need no deploy."""

    def __init__(self, factories: Mapping[str, VideoProviderFactory]) -> None:
        self._factories = dict(factories)

    async def resolve(self, session: AsyncSession, product: Product) -> VideoProvider:
        route = await session.scalar(
            select(ModelRoute).where(ModelRoute.product == product, ModelRoute.is_enabled)
        )
        if route is None or route.provider not in self._factories:
            raise RouteNotAvailableError(product)
        return self._factories[route.provider](route.model)
