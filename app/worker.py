"""Background generations (arq + Redis).

uv run arq app.worker.WorkerSettings
"""

import logging
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, ClassVar

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from arq import cron
from arq.connections import RedisSettings

from app.bot.alerts import cost_text, daily_text, failures_text
from app.bot.notifier import TelegramNotifier, bonus_text, campaign_text
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.domain.bonuses import broadcast_campaign, gift_recipient
from app.domain.credits.service import get_balance
from app.domain.generations.cleanup import delete_expired_photos, delete_expired_videos
from app.domain.generations.talking import SpokenPipeline, run_spoken_generation
from app.domain.generations.trend import TrendPipeline, run_trend_generation
from app.domain.payments.notify import payment_notices
from app.domain.settings import DAILY_COST_ALERT_USD, get_setting
from app.domain.stats import failed_between, report, today
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
    # HTML like the bot process: payment and bonus messages use <b>.
    bot = Bot(
        settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    ctx["engine"] = engine
    ctx["bot"] = bot
    ctx["store"] = store
    ctx["session_factory"] = session_factory
    notifier = TelegramNotifier(bot, settings.telegram_bot_username)
    ctx["notifier"] = notifier
    ctx["alert_chat_id"] = settings.alert_chat_id
    ctx["site_url"] = settings.site_url.rstrip("/")
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


async def campaign_broadcast(ctx: Context, campaign_id: int) -> int:
    """Announces a ⚡ campaign in the bot; the ⚡ were credited when it was created."""
    return await broadcast_campaign(
        ctx["session_factory"], ctx["notifier"], campaign_text, campaign_id, datetime.now(UTC)
    )


async def bonus_notice(ctx: Context, user_id: int, credits: int) -> bool:
    """Tells one customer about a ⚡ gift from the admin cabinet."""
    async with ctx["session_factory"]() as session:
        recipient = await gift_recipient(session, user_id)
        if recipient is None:
            return False
        available = (await get_balance(session, user_id)).available
    text = bonus_text(recipient.language, credits, available)
    delivered: bool = await ctx["notifier"].send(recipient.chat_id, text)
    return delivered


FAILURES_SINCE_KEY = "monitor:failures:since"
FAILURE_WINDOW = timedelta(minutes=10)


async def _alert(ctx: Context, text: str) -> bool:
    """Monitoring is off until ALERT_CHAT_ID is set."""
    if ctx["alert_chat_id"] is None:
        return False
    sent: bool = await ctx["notifier"].send(ctx["alert_chat_id"], text)
    return sent


async def monitor_failures(ctx: Context) -> int:
    """Every 10 minutes: technical failures since the last check, in one message."""
    redis = ctx["redis"]
    now = datetime.now(UTC)
    raw = await redis.get(FAILURES_SINCE_KEY)
    since = datetime.fromisoformat(raw.decode()) if raw else now - FAILURE_WINDOW
    async with ctx["session_factory"]() as session:
        failed = await failed_between(session, since, now)
    await redis.set(FAILURES_SINCE_KEY, now.isoformat())
    if failed:
        await _alert(ctx, failures_text(failed, ctx["site_url"]))
    return len(failed)


async def monitor_costs(ctx: Context) -> bool:
    """Every 30 minutes: one alert per day once model spend passes the owner's limit."""
    now = datetime.now(UTC)
    day = today(now)
    async with ctx["session_factory"]() as session:
        limit = await get_setting(session, DAILY_COST_ALERT_USD)
        if limit <= 0:
            return False
        totals = (await report(session, day, day)).totals
    if totals.cost_usd < limit:
        return False
    # SET NX: only the first check over the limit today sends the alert.
    if not await ctx["redis"].set(f"monitor:cost:{day.isoformat()}", "1", nx=True, ex=2 * 86400):
        return False
    return await _alert(ctx, cost_text(totals.cost_usd, limit, totals.generations))


async def daily_summary(ctx: Context) -> bool:
    """21:00 Tashkent: the day's users, videos, payments, cost and margin."""
    day = today(datetime.now(UTC))
    async with ctx["session_factory"]() as session:
        totals = (await report(session, day, day)).totals
    return await _alert(ctx, daily_text(day, totals))


async def cleanup_media(ctx: Context) -> int:
    photos = await delete_expired_photos(ctx["session_factory"], ctx["store"])
    return photos + await delete_expired_videos(ctx["session_factory"], ctx["store"])


class WorkerSettings:
    functions: ClassVar = [
        trend_generation,
        spoken_generation,
        payment_notification,
        campaign_broadcast,
        bonus_notice,
    ]
    cron_jobs: ClassVar = [
        cron(cleanup_media, minute={0, 30}),
        cron(monitor_failures, minute=set(range(0, 60, 10))),
        cron(monitor_costs, minute={15, 45}),
        # 16:00 UTC = 21:00 in Tashkent.
        cron(daily_summary, hour=16, minute=0),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # A series is up to three ~3 minute Omni calls plus retries; retries happen inside the
    # pipeline, not by re-running jobs.
    job_timeout = 1800
    max_tries = 1
    max_jobs = 4
