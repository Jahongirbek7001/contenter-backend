"""Bot conversation for spoken videos (talking, series):
style -> rules -> selfie -> idea (text or voice) -> script (free, rewrite/edit) -> resolution
-> subtitles/contact -> ⚡ hold and queued generation.

Telegram file ids, not bytes, are kept in the FSM; the selfie is downloaded when needed.
"""

from datetime import UTC, datetime
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.types import User as TelegramUser
from arq.connections import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.callbacks import (
    OptionAction,
    OptionCb,
    ResolutionCb,
    ScriptAction,
    ScriptCb,
    SpokenRulesCb,
    StyleCb,
)
from app.bot.handlers import photo_file
from app.bot.keyboards import (
    options_keyboard,
    resolution_keyboard,
    script_keyboard,
    spoken_rules_keyboard,
    style_keyboard,
    style_title,
)
from app.bot.profile import telegram_profile
from app.bot.texts import MENU_TEXTS, TEXTS, t
from app.domain.credits.errors import InsufficientCreditsError
from app.domain.generations.jobs import SPOKEN_JOB, job_id
from app.domain.generations.start import (
    MAX_CONTACT_CHARS,
    MAX_PHOTO_BYTES,
    InvalidPhotoError,
    PriceUnavailableError,
    StyleUnavailableError,
    UserBlockedError,
    product_price,
    product_prices,
    start_spoken_generation,
)
from app.domain.talking.script import (
    PARTS,
    Script,
    ScriptDraft,
    ScriptError,
    script_from_user,
    write_script,
)
from app.domain.users import get_or_create_user
from app.gateway.base import MediaInput, ProviderError, TextProvider
from app.media.store import MediaStore
from app.models import ScriptStyle, User
from app.models.enums import Language, Product, Resolution

router = Router(name="spoken")

MAX_DRAFTS = 5
MAX_VOICE_SECONDS = 60
CLEAR_CONTACT = "-"
MENU_PRODUCTS = {"menu_talking": Product.TALKING, "menu_series": Product.SERIES}
STARTED_KEY = {Product.TALKING: "started_talking", Product.SERIES: "started_series"}


class SpokenFlow(StatesGroup):
    waiting_photo = State()
    waiting_idea = State()
    reviewing = State()
    waiting_own_text = State()
    options = State()
    waiting_contact = State()


async def _user(session: AsyncSession, telegram_user: TelegramUser) -> User:
    lookup = await get_or_create_user(
        session,
        telegram_user.id,
        telegram_user.language_code,
        profile=telegram_profile(telegram_user),
    )
    return lookup.user


async def _language(
    session_factory: async_sessionmaker[AsyncSession], telegram_user: TelegramUser
) -> Language:
    async with session_factory() as session, session.begin():
        return (await _user(session, telegram_user)).language


async def _download(bot: Bot, file_id: str) -> bytes:
    buffer = BytesIO()
    await bot.download(file_id, destination=buffer)
    return buffer.getvalue()


def _menu_product(text: str | None) -> Product | None:
    for key, product in MENU_PRODUCTS.items():
        if text in {TEXTS[language][key] for language in Language}:
            return product
    return None


@router.message(F.text.func(lambda text: _menu_product(text) is not None))
async def spoken_menu(
    message: Message, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    product = _menu_product(message.text)
    if message.from_user is None or product is None:
        return
    await state.clear()
    async with session_factory() as session, session.begin():
        language = (await _user(session, message.from_user)).language
        styles = list(
            await session.scalars(
                select(ScriptStyle)
                .where(ScriptStyle.is_active)
                .order_by(ScriptStyle.sort_order, ScriptStyle.id)
            )
        )
    if not styles:
        await message.answer(t(language, "styles_empty"))
        return
    await message.answer(
        t(language, "choose_style", product=t(language, f"product_{product}")),
        reply_markup=style_keyboard(language, product, styles),
    )


@router.callback_query(StyleCb.filter())
async def pick_style(
    query: CallbackQuery,
    callback_data: StyleCb,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await query.answer()
    async with session_factory() as session, session.begin():
        user = await _user(session, query.from_user)
        style = await session.get(ScriptStyle, callback_data.style_id)
    if not isinstance(query.message, Message):
        return
    if style is None or not style.is_active:
        await query.message.answer(t(user.language, "style_unavailable"))
        return
    if user.rules_accepted_at is None:
        await query.message.answer(
            t(user.language, "rules"),
            reply_markup=spoken_rules_keyboard(user.language, callback_data.product, style.id),
        )
        return
    await _ask_selfie(query.message, state, user.language, callback_data.product, style.id)


@router.callback_query(SpokenRulesCb.filter())
async def accept_rules(
    query: CallbackQuery,
    callback_data: SpokenRulesCb,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await query.answer()
    async with session_factory() as session, session.begin():
        user = await _user(session, query.from_user)
        if user.rules_accepted_at is None:
            user.rules_accepted_at = datetime.now(UTC)
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
        await _ask_selfie(
            query.message, state, user.language, callback_data.product, callback_data.style_id
        )


async def _ask_selfie(
    message: Message, state: FSMContext, language: Language, product: Product, style_id: int
) -> None:
    await state.set_state(SpokenFlow.waiting_photo)
    await state.set_data({"product": product.value, "style_id": style_id, "drafts": 0})
    await message.answer(t(language, "spoken_send_selfie"))


@router.message(StateFilter(SpokenFlow.waiting_photo), F.photo | F.document)
async def receive_photo(
    message: Message, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is None:
        return
    language = await _language(session_factory, message.from_user)
    found = photo_file(message)
    if found is None:
        await message.answer(t(language, "not_a_photo"))
        return
    file_id, size, mime_type = found
    if size is not None and size > MAX_PHOTO_BYTES:
        await message.answer(t(language, "photo_too_big"))
        return
    await state.update_data(photo_id=file_id, photo_mime=mime_type)
    await state.set_state(SpokenFlow.waiting_idea)
    await message.answer(t(language, "send_idea"))


@router.message(StateFilter(SpokenFlow.waiting_photo), ~F.text.in_(MENU_TEXTS))
async def waiting_photo_other(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is not None:
        await message.answer(t(await _language(session_factory, message.from_user), "not_a_photo"))


@router.message(StateFilter(SpokenFlow.waiting_idea), F.voice | (F.text & ~F.text.in_(MENU_TEXTS)))
async def receive_idea(
    message: Message,
    bot: Bot,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    text_provider: TextProvider,
) -> None:
    if message.from_user is None:
        return
    language = await _language(session_factory, message.from_user)
    voice: MediaInput | None = None
    if message.voice is not None:
        if message.voice.duration > MAX_VOICE_SECONDS:
            await message.answer(t(language, "voice_too_long"))
            return
        voice = MediaInput(
            data=await _download(bot, message.voice.file_id),
            mime_type=message.voice.mime_type or "audio/ogg",
        )
    await _write(
        message, message.from_user, bot, state, session_factory, text_provider, message.text, voice
    )


@router.message(StateFilter(SpokenFlow.waiting_idea), ~F.text.in_(MENU_TEXTS))
async def waiting_idea_other(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is not None:
        await message.answer(t(await _language(session_factory, message.from_user), "idea_needed"))


async def _write(
    message: Message,
    telegram_user: TelegramUser,
    bot: Bot,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    text_provider: TextProvider,
    idea: str | None,
    voice: MediaInput | None,
    previous: Script | None = None,
) -> None:
    """Asks Hydrogen for a script and shows it, or explains why there is none."""
    data = await state.get_data()
    async with session_factory() as session, session.begin():
        language = (await _user(session, telegram_user)).language
        style = await session.get(ScriptStyle, int(data["style_id"]))
    if style is None or not style.is_active:
        await state.clear()
        await message.answer(t(language, "style_unavailable"))
        return
    if int(data.get("drafts", 0)) >= MAX_DRAFTS:
        await message.answer(t(language, "rewrite_limit", limit=MAX_DRAFTS))
        if previous is not None:
            # Keep the last script with its buttons so the user can approve or edit it.
            await _show_script(message, language, style, previous)
        return
    product = Product(data["product"])
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    progress = await message.answer(t(language, "writing_script"))
    try:
        selfie = MediaInput(
            data=await _download(bot, str(data["photo_id"])), mime_type=str(data["photo_mime"])
        )
        draft: ScriptDraft = await write_script(
            text_provider,
            style_instructions=style.instructions,
            language=language,
            parts=PARTS[product],
            selfie=selfie,
            idea=idea,
            voice=voice,
            previous=previous,
        )
    except ProviderError:
        await progress.edit_text(t(language, "script_failed"))
        return
    await state.update_data(drafts=int(data.get("drafts", 0)) + 1)
    if draft.photo_reason is not None:
        await state.set_state(SpokenFlow.waiting_photo)
        reason = t(language, f"failed_photo_{draft.photo_reason}")
        await progress.edit_text(f"{reason}\n{t(language, 'send_other_selfie')}")
        return
    if draft.idea_rejected or draft.script is None:
        await state.set_state(SpokenFlow.waiting_idea)
        await progress.edit_text(t(language, "idea_rejected"))
        return
    await state.update_data(script=draft.script.to_json())
    await state.set_state(SpokenFlow.reviewing)
    await progress.delete()
    await _show_script(message, language, style, draft.script)


async def _show_script(
    message: Message, language: Language, style: ScriptStyle, script: Script
) -> None:
    numbered = (
        script.lines[0]
        if len(script.lines) == 1
        else "\n\n".join(f"<b>{i}.</b> {line}" for i, line in enumerate(script.lines, 1))
    )
    await message.answer(
        t(language, "script", style=style_title(style, language), lines=numbered),
        reply_markup=script_keyboard(language),
    )


async def _flow_data(
    query: CallbackQuery, state: FSMContext, language: Language, *keys: str
) -> dict[str, object] | None:
    """FSM data when it still has `keys`; otherwise tells the user the step expired."""
    data = await state.get_data()
    if all(key in data for key in keys):
        return data
    if isinstance(query.message, Message):
        await query.message.answer(t(language, "flow_expired"))
    return None


@router.callback_query(ScriptCb.filter())
async def script_action(
    query: CallbackQuery,
    callback_data: ScriptCb,
    bot: Bot,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    text_provider: TextProvider,
) -> None:
    await query.answer()
    language = await _language(session_factory, query.from_user)
    data = await _flow_data(query, state, language, "script", "product")
    if data is None or not isinstance(query.message, Message):
        return
    await query.message.edit_reply_markup(reply_markup=None)
    script = Script.from_json(str(data["script"]))
    product = Product(str(data["product"]))
    if callback_data.action is ScriptAction.REWRITE:
        await _write(
            query.message,
            query.from_user,
            bot,
            state,
            session_factory,
            text_provider,
            script.idea,
            None,
            previous=script,
        )
    elif callback_data.action is ScriptAction.EDIT:
        await state.set_state(SpokenFlow.waiting_own_text)
        await query.message.answer(t(language, "own_text_prompt", parts=PARTS[product]))
    else:
        async with session_factory() as session:
            prices = await product_prices(session, product)
        await query.message.answer(
            t(language, "choose_resolution"), reply_markup=resolution_keyboard(language, prices)
        )


@router.message(StateFilter(SpokenFlow.waiting_own_text), F.text, ~F.text.in_(MENU_TEXTS))
async def receive_own_text(
    message: Message, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is None:
        return
    data = await state.get_data()
    async with session_factory() as session, session.begin():
        language = (await _user(session, message.from_user)).language
        style = await session.get(ScriptStyle, int(data["style_id"]))
    if style is None or "script" not in data:
        await state.clear()
        await message.answer(t(language, "flow_expired"))
        return
    script = Script.from_json(str(data["script"]))
    try:
        own = script_from_user(message.text or "", script)
    except ScriptError as exc:
        await message.answer(t(language, f"own_{exc.code}", parts=len(script.lines)))
        return
    await state.update_data(script=own.to_json())
    await state.set_state(SpokenFlow.reviewing)
    await _show_script(message, language, style, own)


@router.callback_query(ResolutionCb.filter())
async def pick_resolution(
    query: CallbackQuery,
    callback_data: ResolutionCb,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await query.answer()
    language = await _language(session_factory, query.from_user)
    data = await _flow_data(query, state, language, "script", "product")
    if data is None or not isinstance(query.message, Message):
        return
    await query.message.edit_reply_markup(reply_markup=None)
    await state.update_data(resolution=callback_data.resolution.value, subtitles=True)
    await state.set_state(SpokenFlow.options)
    await _show_options(query.message, state, session_factory, language)


async def _show_options(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    language: Language,
    edit: bool = False,
) -> None:
    data = await state.get_data()
    product, resolution = Product(data["product"]), Resolution(data["resolution"])
    async with session_factory() as session:
        price = await product_price(session, product, resolution)
    subtitles = bool(data.get("subtitles"))
    contact = data.get("contact")
    text = t(
        language,
        "options",
        resolution=resolution.value,
        subtitles=t(language, "word_on" if subtitles else "word_off"),
        contact=contact or t(language, "word_off"),
        price=price,
    )
    keyboard = options_keyboard(language, subtitles, price)
    if edit:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


@router.callback_query(StateFilter(SpokenFlow.options), OptionCb.filter())
async def option_action(
    query: CallbackQuery,
    callback_data: OptionCb,
    bot: Bot,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    arq: ArqRedis,
) -> None:
    await query.answer()
    language = await _language(session_factory, query.from_user)
    data = await _flow_data(query, state, language, "script", "resolution", "photo_id")
    if data is None or not isinstance(query.message, Message):
        return
    if callback_data.action is OptionAction.SUBTITLES:
        await state.update_data(subtitles=not data.get("subtitles"))
        await _show_options(query.message, state, session_factory, language, edit=True)
    elif callback_data.action is OptionAction.CONTACT:
        await state.set_state(SpokenFlow.waiting_contact)
        await query.message.answer(t(language, "ask_contact"))
    else:
        await query.message.edit_reply_markup(reply_markup=None)
        await _create(query.message, query.from_user, bot, state, session_factory, store, arq)


@router.message(StateFilter(SpokenFlow.waiting_contact), F.text, ~F.text.in_(MENU_TEXTS))
async def receive_contact(
    message: Message, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is None:
        return
    language = await _language(session_factory, message.from_user)
    text = (message.text or "").strip()
    contact = None if text == CLEAR_CONTACT else text[:MAX_CONTACT_CHARS]
    await state.update_data(contact=contact)
    await state.set_state(SpokenFlow.options)
    await _show_options(message, state, session_factory, language)


async def _create(
    message: Message,
    telegram_user: TelegramUser,
    bot: Bot,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    store: MediaStore,
    arq: ArqRedis,
) -> None:
    data = await state.get_data()
    product = Product(str(data["product"]))
    script = Script.from_json(str(data["script"]))
    photo = await _download(bot, str(data["photo_id"]))
    contact = data.get("contact")
    async with session_factory() as session:
        try:
            async with session.begin():
                user = await _user(session, telegram_user)
                language = user.language
                generation = await start_spoken_generation(
                    session,
                    store,
                    user,
                    product=product,
                    resolution=Resolution(str(data["resolution"])),
                    style_id=int(str(data["style_id"])),
                    language=language,
                    script_json=script.to_json(),
                    idea=script.idea,
                    photo=photo,
                    mime_type=str(data["photo_mime"]),
                    subtitles=bool(data.get("subtitles")),
                    contact_text=str(contact) if contact else None,
                )
        except InsufficientCreditsError as exc:
            await message.answer(
                t(language, "insufficient", required=exc.required, available=exc.available)
            )
            await _show_options(message, state, session_factory, language)
            return
        except (StyleUnavailableError, PriceUnavailableError):
            await state.clear()
            await message.answer(t(language, "style_unavailable"))
            return
        except InvalidPhotoError:
            await state.set_state(SpokenFlow.waiting_photo)
            await message.answer(t(language, "not_a_photo"))
            return
        except UserBlockedError:
            await state.clear()
            await message.answer(t(language, "blocked"))
            return
    await state.clear()
    await arq.enqueue_job(SPOKEN_JOB, generation.id, _job_id=job_id(generation.id))
    await message.answer(t(language, STARTED_KEY[product]))
