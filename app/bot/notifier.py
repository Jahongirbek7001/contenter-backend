from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.bot.keyboards import result_keyboard
from app.bot.texts import t
from app.domain.generations.trend import Outcome, RejectReason
from app.models.enums import Language


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
