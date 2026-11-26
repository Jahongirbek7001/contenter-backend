import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import create_engine, create_session_factory

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://contentor:contentor@localhost:15433/contentor_test",
)
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Tables filled by tests; seeded catalog tables (prices, packs, routes) are kept.
TEST_DATA_TABLES = (
    "credit_ledger, credit_holds, payments, generations, music_tracks, users, "
    "admin_sessions, admin_users, site_sessions, promo_redemptions, promo_codes"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Runs the real migrations, so every test run also checks that they apply cleanly."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    config.attributes["configure_logger"] = False
    asyncio.run(_reset_schema())
    command.upgrade(config, "head")


async def _reset_schema() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TEST_DATA_TABLES} RESTART IDENTITY CASCADE"))
    yield create_session_factory(engine)
    await engine.dispose()
