import asyncio
import html

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import BufferedInputFile

from app.bot.keyboards import result_keyboard, share_keyboard
from app.bot.texts import t
from app.domain.generations.runner import Outcome, RejectReason
from app.domain.payments.notify import Notice, PaymentNotices
from app.media.ffmpeg import FRAME_SIZE
from app.models import BonusCampaign
from app.models.enums import Language, Resolution


class TelegramNotifier:
    """Delivers worker results to the user's chat (private chat id == Telegram user id)."""

    def __init__(self, bot: Bot, bot_username: str) -> None:
        self._bot = bot
        self._bot_username = bot_username

    async def send_trend_result(
        self, chat_id: int, language: Language, video: bytes, generation_id: int, price: int
    ) -> str:
        message = await self._bot.send_video(
            chat_id,
            BufferedInputFile(video, filename=f"contentor-{generation_id}.mp4"),
            caption=t(language, "result"),
            width=1080,
            height=1920,
            supports_streaming=True,
            reply_markup=result_keyboard(language, generation_id, price, self._bot_username),
        )
        if message.video is None:
            raise RuntimeError("Telegram did not return a video")
        return message.video.file_id

    async def send_spoken_result(
        self,
        chat_id: int,
        language: Language,
        video: bytes,
        generation_id: int,
        resolution: Resolution,
    ) -> str:
        width, height = FRAME_SIZE[resolution]
        message = await self._bot.send_video(
            chat_id,
            BufferedInputFile(video, filename=f"contentor-{generation_id}.mp4"),
            caption=t(language, "spoken_result"),
            width=width,
            height=height,
            supports_streaming=True,
            reply_markup=share_keyboard(language, self._bot_username),
        )
        if message.video is None:
            raise RuntimeError("Telegram did not return a video")
        return message.video.file_id

    async def send(self, chat_id: int, text: str) -> bool:
        """Best-effort message for broadcasts: False if the customer cannot be reached."""
        for _ in range(2):
            try:
                await self._bot.send_message(chat_id, text)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except TelegramAPIError:
                # Blocked the bot, deleted the account, or only ever used the site.
                return False
            else:
                return True
        return False

    async def send_payment_notices(self, notices: PaymentNotices) -> None:
        await self._bot.send_message(notices.payer.chat_id, paid_text(notices.payer))
        if notices.referrer is not None:
            await self._bot.send_message(notices.referrer.chat_id, referral_text(notices.referrer))

    async def send_failure(
        self, chat_id: int, language: Language, outcome: Outcome, reason: RejectReason | None
    ) -> None:
        await self._bot.send_message(chat_id, failure_text(language, outcome, reason))


def failure_text(language: Language, outcome: Outcome, reason: RejectReason | None) -> str:
    if outcome is Outcome.PHOTO_REJECTED:
        key = f"failed_photo_{reason or RejectReason.LOW_QUALITY}"
        return f"{t(language, key)}\n{t(language, 'failed_refund_note')}"
    if outcome is Outcome.BLOCKED:
        return t(language, "failed_blocked")
    return t(language, "failed_failed")


def paid_text(notice: Notice) -> str:
    lines = [t(notice.language, "paid", credits=notice.credits)]
    if notice.referral_bonus:
        lines.append(t(notice.language, "paid_referral", bonus=notice.referral_bonus))
    lines.append(t(notice.language, "paid_balance", available=notice.available))
    return "\n".join(lines)


def referral_text(notice: Notice) -> str:
    return t(
        notice.language, "referral_reward", bonus=notice.referral_bonus, available=notice.available
    )


def campaign_text(campaign: BonusCampaign, language: Language, available: int) -> str:
    """The admin's own words (escaped) followed by the gift and the new balance."""
    custom = campaign.message_ru if language is Language.RU else campaign.message_uz
    gift = t(language, "bonus_received", credits=campaign.credits, available=available)
    return f"{html.escape(custom)}\n\n{gift}" if custom else gift


def bonus_text(language: Language, credits: int, available: int) -> str:
    return t(language, "bonus_received", credits=credits, available=available)
