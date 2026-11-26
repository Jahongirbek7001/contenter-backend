"""The models and the hand-written migrations describe the same schema."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Base


async def test_models_match_migrations(session_factory: async_sessionmaker[AsyncSession]) -> None:
    def diff(connection: Connection) -> list[object]:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return list(compare_metadata(context, Base.metadata))

    async with session_factory() as session:
        connection = await session.connection()
        changes = await connection.run_sync(diff)
    assert changes == []
