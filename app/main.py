"""HTTP API for the site, mini app and admin cabinet.

uv run uvicorn app.main:app --reload
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.catalog import router as catalog_router
from app.api.miniapp import router as miniapp_router
from app.api.miniapp.deps import MiniAppAuth
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.media.store import LocalMediaStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.session_factory = create_session_factory(engine)
    app.state.arq = arq
    app.state.media_store = LocalMediaStore(Path(settings.media_dir))
    app.state.miniapp_auth = MiniAppAuth(
        bot_token=settings.telegram_bot_token.get_secret_value(),
        dev_telegram_id=settings.miniapp_dev_telegram_id,
    )
    yield
    await arq.aclose()
    await engine.dispose()


def create_app(cors_origins: list[str], admin_cookie_secure: bool = False) -> FastAPI:
    app = FastAPI(title="Contentor AI", lifespan=lifespan)
    app.state.admin_cookie_secure = admin_cookie_secure
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(catalog_router)
    app.include_router(admin_router)
    app.include_router(miniapp_router)
    return app


_settings = get_settings()
app = create_app(_settings.cors_origins, _settings.admin_cookie_secure)
