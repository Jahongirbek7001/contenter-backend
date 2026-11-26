"""Background generations (arq + Redis).

uv run arq app.worker.WorkerSettings
"""

import logging
from functools import partial
from pathlib import Path
from typing import Any, ClassVar

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from arq import cron
from arq.connections import RedisSettings

from app.bot.notifier import TelegramNotifier
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.domain.generations.cleanup import delete_expired_photos, delete_expired_videos
from app.domain.generations.talking import SpokenPipeline, run_spoken_generation
from app.domain.generations.trend import TrendPipeline, run_trend_generation
from app.domain.payments.notify import payment_notices
from app.gateway.factory import build_google_providers
from app.media.ffmpeg import compose_spoken_video, compose_trend_video
from app.media.store import LocalMediaStore

Context = dict[str, Any]
logger = logging.getLogger(__name__)


async def startup(ctx: Context) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    store = LocalMediaStore(Path(settings.media_dir))
    providers = build_google_providers(settings)
    bot = Bot(settings.telegram_bot_token.get_secret_value())
    ctx["engine"] = engine
    ctx["bot"] = bot
    ctx["store"] = store
    ctx["session_factory"] = session_factory
    notifier = TelegramNotifier(bot, settings.telegram_bot_username)
    ctx["notifier"] = notifier
    ctx["spoken_pipeline"] = SpokenPipeline(
        session_factory=session_factory,
        videos=providers.videos,
        store=store,
        notifier=notifier,
        compose=partial(compose_spoken_video, ffmpeg=settings.ffmpeg_path),
    )
    ctx["pipeline"] = TrendPipeline(
        session_factory=session_factory,
        text=providers.text,
        image=providers.image,
        music=providers.music,
        videos=providers.videos,
        store=store,
        notifier=notifier,
        compose=partial(compose_trend_video, ffmpeg=settings.ffmpeg_path),
    )


async def shutdown(ctx: Context) -> None:
    await ctx["bot"].session.close()
    await ctx["engine"].dispose()


async def trend_generation(ctx: Context, generation_id: int) -> str | None:
    outcome = await run_trend_generation(ctx["pipeline"], generation_id)
    return None if outcome is None else outcome.value


async def spoken_generation(ctx: Context, generation_id: int) -> str | None:
    outcome = await run_spoken_generation(ctx["spoken_pipeline"], generation_id)
    return None if outcome is None else outcome.value


async def payment_notification(ctx: Context, payment_id: int, referrer_id: int | None) -> bool:
    """Tells a site customer in the bot that Payme/Click credited their ⚡."""
    async with ctx["session_factory"]() as session:
        notices = await payment_notices(session, payment_id, referrer_id)
    if notices is None:
        return False
    try:
        await ctx["notifier"].send_payment_notices(notices)
    except TelegramAPIError:
        # Customers who logged in on the site but never started the bot cannot be messaged.
        logger.warning("payment %s: could not message the customer", payment_id)
        return False
    return True


async def cleanup_media(ctx: Context) -> int:
    photos = await delete_expired_photos(ctx["session_factory"], ctx["store"])
    return photos + await delete_expired_videos(ctx["session_factory"], ctx["store"])


class WorkerSettings:
    functions: ClassVar = [trend_generation, spoken_generation, payment_notification]
    cron_jobs: ClassVar = [cron(cleanup_media, minute={0, 30})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # A series is up to three ~3 minute Omni calls plus retries; retries happen inside the
    # pipeline, not by re-running jobs.
    job_timeout = 1800
    max_tries = 1
    max_jobs = 4
