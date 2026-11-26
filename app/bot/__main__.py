"""Telegram bot (long polling for local development).

uv run python -m app.bot
"""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from arq import create_pool
from arq.connections import RedisSettings

from app.bot.handlers import router
from app.bot.spoken import router as spoken_router
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.gateway.factory import build_google_providers
from app.media.store import LocalMediaStore


async def main() -> None:
    settings = get_settings()
    bot = Bot(
        settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=RedisStorage.from_url(settings.redis_url))
    # The main router goes first: its reply-menu buttons must work from any step.
    dispatcher.include_router(router)
    dispatcher.include_router(spoken_router)
    engine = create_engine(settings.database_url)
    arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(
            bot,
            session_factory=create_session_factory(engine),
            store=LocalMediaStore(Path(settings.media_dir)),
            arq=arq,
            text_provider=build_google_providers(settings).text,
        )
    finally:
        await arq.aclose()
        await engine.dispose()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(main())
