"""HTTP API for the site and admin cabinet. Run: uv run uvicorn app.main:app --reload"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.catalog import router as catalog_router
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine(get_settings().database_url)
    app.state.session_factory = create_session_factory(engine)
    yield
    await engine.dispose()


def create_app(cors_origins: list[str]) -> FastAPI:
    app = FastAPI(title="Contentor AI", lifespan=lifespan)
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
    return app


app = create_app(get_settings().cors_origins)
