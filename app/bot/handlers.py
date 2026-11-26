"""Bot conversation: language -> rules -> trend gallery -> selfie -> generation queued."""

from datetime import UTC, datetime
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InaccessibleMessage, Message
from aiogram.types import User as TelegramUser
from arq.connections import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.callbacks import GalleryCb, LanguageCb, PickCb, RegenCb, RulesCb
from app.bot.keyboards import gallery_keyboard, language_keyboard, main_menu, rules_keyboard
from app.bot.texts import MENU_TEXTS, TEXTS, t
from app.domain.credits.errors import InsufficientCreditsError
from app.domain.generations.jobs import TREND_JOB, job_id
from app.domain.generations.start import (
    MAX_PHOTO_BYTES,
    InvalidPhotoError,
    TemplateUnavailableError,
    UserBlockedError,
    photo_mime_type,
    start_trend_generation,
    trend_price,
)
from app.domain.users import get_or_create_user
from app.media.store import MediaStore
from app.models import Generation, TrendTemplate, User
from app.models.enums import Language, TrendAudience

router = Router(name="contentor")

REFERRAL_PREFIX = "ref_"
BADGES = {"hot": "🔥 ", "new": "🆕 ", "top": "⭐ ", "none": ""}


class TrendFlow(StatesGroup):
    waiting_photo = State()


def _menu_texts(key: str) -> set[str]:
    return {TEXTS[language][key] for language in Language}


async def _user(session: AsyncSession, telegram_user: TelegramUser) -> User:
    lookup = await get_or_create_user(session, telegram_user.id, telegram_user.language_code)
    return lookup.user


def _referrer(command: CommandObject) -> int | None:
    args = command.args or ""
    if args.startswith(REFERRAL_PREFIX) and args[len(REFERRAL_PREFIX) :].isdigit():
        return int(args[len(REFERRAL_PREFIX) :])
    return None


@router.message(CommandStart())
async def start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if message.from_user is None:
        return
    await state.clear()
    async with session_factory() as session, session.begin():
        lookup = await get_or_create_user(
            session, message.from_user.id, message.from_user.language_code, _referrer(command)
        )
        language = lookup.user.language
    if lookup.created:
        await message.answer(t(language, "choose_language"), reply_markup=language_keyboard())
        return
    await message.answer(t(language, "welcome"), reply_markup=main_menu(language))


@router.callback_query(LanguageCb.filter())
async def choose_language(
    query: CallbackQuery,
    callback_data: LanguageCb,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        user = await _user(session, query.from_user)
        user.language = callback_data.language
    language = callback_data.language
    await query.answer(t(language, "language_set"))
    if isinstance(query.message, Message):
        await query.message.edit_text(t(language, "language_set"))
        await query.message.answer(t(language, "welcome"), reply_markup=main_menu(language))


@router.message(F.text.in_(_menu_texts("menu_language")))
async def language_menu(message: Message) -> None:
    await message.answer(TEXTS[Language.UZ]["choose_language"], reply_markup=language_keyboard())


@router.message(F.text.in_(_menu_texts("menu_help")))
async def help_menu(message: Message, session_factory: async_sessionmaker[AsyncSession]) -> None:
    if message.from_user is None:
        return
    async with session_factory() as session, session.begin():
        language = (await _user(session, message.from_user)).language
    await message.answer(t(language, "help"))


async def _active_trends(session: AsyncSession, audience: TrendAudience) -> list[TrendTemplate]:
    query = select(TrendTemplate).where(TrendTemplate.is_active)
    if audience is not TrendAudience.ALL:
        query = query.where(TrendTemplate.audience.in_([TrendAudience.ALL, audience]))
    trends = await session.scalars(query.order_by(TrendTemplate.sort_order, TrendTemplate.id))
    return list(trends)


async def _show_card(
    target: Message,
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    telegram_user: TelegramUser,
    audience: TrendAudience,
    index: int,
    replace: bool,
) -> None:
    async with session_factory() as session, session.begin():
        user = await _user(session, telegram_user)
        trends = await _active_trends(session, audience)
        price = await trend_price(session) if trends else 0
    language = user.language
    if not trends:
        await target.answer(t(language, "gallery_empty"))
        return
    index %= len(trends)
    trend = trends[index]
    title = trend.title_ru if language is Language.RU else trend.title_uz
    caption = t(
        language,
        "card",
        badge=BADGES[trend.badge.value],
        title=title,
        position=f"{index + 1}/{len(trends)}",
    )
    keyboard = gallery_keyboard(language, audience, index, len(trends), trend.id, price)
    if replace:
        # Cards alternate between video and text, which Telegram cannot edit into each other.
        await target.delete()
    if trend.preview_file_id:
        await target.answer_video(trend.preview_file_id, caption=caption, reply_markup=keyboard)
    elif trend.preview_storage_key:
        # First showing after an upload: send the file once, then reuse Telegram's file_id.
        preview = await store.load(trend.preview_storage_key)
        sent = await target.answer_video(
            BufferedInputFile(preview, filename=f"{trend.slug}.mp4"),
            caption=caption,
            reply_markup=keyboard,
            width=720,
            height=1280,
            supports_streaming=True,
        )
        if sent.video is not None:
            await _remember_preview(session_factory, trend.id, trend.preview_storage_key, sent)
    else:
        await target.answer(caption, reply_markup=keyboard)


async def _remember_preview(
    session_factory: async_sessionmaker[AsyncSession], trend_id: int, key: str, sent: Message
) -> None:
    if sent.video is None:
        return
    async with session_factory() as session, session.begin():
        trend = await session.get(TrendTemplate, trend_id, with_for_update=True)
        # Skip if the preview was replaced while we were uploading.
        if trend is not None and trend.preview_storage_key == key:
            trend.preview_file_id = sent.video.file_id


@router.message(F.text.in_(_menu_texts("menu_trends")))
async def trends_menu(
    message: Message, session_factory: async_sessionmaker[AsyncSession], store: MediaStore
) -> None:
    if message.from_user is None:
        return
    await _show_card(
        message, session_factory, store, message.from_user, TrendAudience.ALL, 0, replace=False
    )


@router.callback_query(GalleryCb.filter())
async def gallery(
    query: CallbackQuery,
    callback_data: GalleryCb,
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
) -> None:
    await query.answer()
    if not isinstance(query.message, Message):
        return
    await _show_card(
        query.message,
        session_factory,
        store,
        query.from_user,
        callback_data.audience,
        callback_data.index,
        replace=True,
    )


async def _ask_selfie(
    target: Message | InaccessibleMessage | None,
    state: FSMContext,
    language: Language,
    trend: TrendTemplate,
) -> None:
    await state.set_state(TrendFlow.waiting_photo)
    await state.update_data(template_id=trend.id)
    if isinstance(target, Message):
        title = trend.title_ru if language is Language.RU else trend.title_uz
        await target.answer(t(language, "send_selfie", title=title))


@router.callback_query(PickCb.filter())
async def pick_trend(
    query: CallbackQuery,
    callback_data: PickCb,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await query.answer()
    async with session_factory() as session, session.begin():
        user = await _user(session, query.from_user)
        trend = await session.get(TrendTemplate, callback_data.template_id)
    language = user.language
    if trend is None or not trend.is_active:
        if isinstance(query.message, Message):
            await query.message.answer(t(language, "trend_unavailable"))
        return
    if user.rules_accepted_at is None:
        if isinstance(query.message, Message):
            await query.message.answer(
                t(language, "rules"), reply_markup=rules_keyboard(language, trend.id)
            )
        return
    await _ask_selfie(query.message, state, language, trend)


@router.callback_query(RulesCb.filter())
async def accept_rules(
    query: CallbackQuery,
    callback_data: RulesCb,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await query.answer()
    async with session_factory() as session, session.begin():
        user = await _user(session, query.from_user)
        if user.rules_accepted_at is None:
            user.rules_accepted_at = datetime.now(UTC)
        trend = await session.get(TrendTemplate, callback_data.template_id)
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
    if trend is None or not trend.is_active:
        if isinstance(query.message, Message):
            await query.message.answer(t(user.language, "trend_unavailable"))
        return
    await _ask_selfie(query.message, state, user.language, trend)


def photo_file(message: Message) -> tuple[str, int | None, str] | None:
    """(file_id, size, mime type) of a photo or an image sent as a file."""
    if message.photo:
        largest = message.photo[-1]
        return largest.file_id, largest.file_size, "image/jpeg"
    document = message.document
    if document is not None and (document.mime_type or "").startswith("image/"):
        return document.file_id, document.file_size, document.mime_type or "image/jpeg"
    return None


async def _queue(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    arq: ArqRedis,
    telegram_user: TelegramUser,
    template_id: int,
    photo: bytes,
    mime_type: str,
    source_generation_id: int | None = None,
) -> bool:
    """Creates the generation and queues it. Returns False when the user was told why not."""
    async with session_factory() as session:
        try:
            async with session.begin():
                user = await _user(session, telegram_user)
                language = user.language
                generation = await start_trend_generation(
                    session, store, user, template_id, photo, mime_type, source_generation_id
                )
        except InsufficientCreditsError as exc:
            await message.answer(
                t(language, "insufficient", required=exc.required, available=exc.available)
            )
            return False
        except TemplateUnavailableError:
            await message.answer(t(language, "trend_unavailable"))
            return False
        except InvalidPhotoError:
            await message.answer(t(language, "not_a_photo"))
            return False
        except UserBlockedError:
            await message.answer(t(language, "blocked"))
            return False
    await arq.enqueue_job(TREND_JOB, generation.id, _job_id=job_id(generation.id))
    await message.answer(t(language, "started"))
    return True


@router.message(StateFilter(TrendFlow.waiting_photo), F.photo | F.document)
async def receive_photo(
    message: Message,
    bot: Bot,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    arq: ArqRedis,
) -> None:
    if message.from_user is None:
        return
    async with session_factory() as session, session.begin():
        language = (await _user(session, message.from_user)).language
    found = photo_file(message)
    if found is None:
        await message.answer(t(language, "not_a_photo"))
        return
    file_id, size, mime_type = found
    if size is not None and size > MAX_PHOTO_BYTES:
        await message.answer(t(language, "photo_too_big"))
        return
    buffer = BytesIO()
    await bot.download(file_id, destination=buffer)
    template_id = int((await state.get_data())["template_id"])
    if await _queue(
        message,
        session_factory,
        store,
        arq,
        message.from_user,
        template_id,
        buffer.getvalue(),
        mime_type,
    ):
        await state.clear()


@router.message(StateFilter(TrendFlow.waiting_photo), ~F.text.in_(MENU_TEXTS))
async def waiting_photo_other(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is None:
        return
    async with session_factory() as session, session.begin():
        language = (await _user(session, message.from_user)).language
    await message.answer(t(language, "not_a_photo"))


@router.callback_query(RegenCb.filter())
async def regenerate(
    query: CallbackQuery,
    callback_data: RegenCb,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    arq: ArqRedis,
) -> None:
    await query.answer()
    if not isinstance(query.message, Message):
        return
    async with session_factory() as session, session.begin():
        user = await _user(session, query.from_user)
        generation = await session.get(Generation, callback_data.generation_id)
        if generation is None or generation.user_id != user.id or generation.template_id is None:
            return
        trend = await session.get(TrendTemplate, generation.template_id)
    if trend is None:
        await query.message.answer(t(user.language, "trend_unavailable"))
        return
    key = generation.input_media_key
    photo = await _load_or_none(store, key)
    if key is None or photo is None:
        await query.message.answer(t(user.language, "regen_need_photo"))
        await _ask_selfie(None, state, user.language, trend)
        return
    await _queue(
        query.message,
        session_factory,
        store,
        arq,
        query.from_user,
        trend.id,
        photo,
        photo_mime_type(key),
        source_generation_id=generation.id,
    )


async def _load_or_none(store: MediaStore, key: str | None) -> bytes | None:
    if key is None:
        return None
    try:
        return await store.load(key)
    except FileNotFoundError:
        return None
