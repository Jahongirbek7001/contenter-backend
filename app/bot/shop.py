"""⚡ balance and shop inside the bot: Telegram Stars packs, promo codes, invite link.

Inside Telegram only Stars are allowed for digital goods; the bot never links to the
site's cheaper Payme/Click prices (docs/plan.md).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from aiogram.types import User as TelegramUser
from arq.connections import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.ratelimit import RateLimiter
from app.bot.callbacks import BuyCb, ShopAction, ShopCb
from app.bot.keyboards import invite_keyboard, pack_title, shop_keyboard
from app.bot.notifier import paid_text, referral_text
from app.bot.profile import telegram_profile
from app.bot.texts import MENU_TEXTS, TEXTS, t
from app.domain.credits.service import get_balance
from app.domain.payments.notify import payment_notices
from app.domain.payments.orders import (
    REFERRAL_BONUS,
    STARS,
    OrderError,
    record_stars_payment,
    sellable_pack,
)
from app.domain.promo import PromoError, redeem_promo
from app.domain.users import get_or_create_user
from app.models import Pack, User
from app.models.enums import Language

router = Router(name="shop")

PAYLOAD_PREFIX = "pack:"
REFERRAL_PREFIX = "ref_"


class ShopFlow(StatesGroup):
    waiting_promo = State()


@dataclass(frozen=True)
class ShopConfig:
    bot_username: str
    site_url: str
    support_contact: str | None

    def terms_url(self, language: Language) -> str:
        return f"{self.site_url}/{language.value}/offer"


def _menu_texts(key: str) -> set[str]:
    return {TEXTS[language][key] for language in Language}


async def _user(session: AsyncSession, telegram_user: TelegramUser) -> User:
    lookup = await get_or_create_user(
        session,
        telegram_user.id,
        telegram_user.language_code,
        profile=telegram_profile(telegram_user),
    )
    return lookup.user


async def _stars_packs(session: AsyncSession) -> list[Pack]:
    packs = await session.scalars(
        select(Pack)
        .where(Pack.is_active, Pack.price_stars.is_not(None))
        .order_by(Pack.sort_order, Pack.id)
    )
    return list(packs)


def _visible(packs: list[Pack], user: User) -> list[Pack]:
    return [pack for pack in packs if not (pack.is_one_time and user.trial_used)]


@router.message(F.text.in_(_menu_texts("menu_balance")))
async def balance_menu(
    message: Message, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is None:
        return
    await state.clear()
    async with session_factory() as session, session.begin():
        user = await _user(session, message.from_user)
        balance = await get_balance(session, user.id)
        packs = _visible(await _stars_packs(session), user)
    language = user.language
    if balance.held:
        text = t(language, "balance_held", available=balance.available, held=balance.held)
    else:
        text = t(language, "balance", available=balance.available)
    text += t(language, "shop_title") if packs else t(language, "shop_empty")
    await message.answer(text, reply_markup=shop_keyboard(language, packs))


def _order_error(language: Language, error: OrderError) -> str:
    return t(language, f"order_{error.reason}")


@router.callback_query(BuyCb.filter())
async def buy(
    query: CallbackQuery,
    callback_data: BuyCb,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        user = await _user(session, query.from_user)
        pack = await session.get(Pack, callback_data.pack_id)
        try:
            pack = await sellable_pack(session, user, pack)
        except OrderError as exc:
            await query.answer(_order_error(user.language, exc), show_alert=True)
            return
        if pack.price_stars is None:
            await query.answer(t(user.language, "order_pack_unavailable"), show_alert=True)
            return
        language, stars = user.language, pack.price_stars
        credits, title = pack.credits + pack.bonus_credits, pack_title(pack, language)
    await query.answer()
    await bot.send_invoice(
        chat_id=query.from_user.id,
        title=t(language, "invoice_title", title=title, credits=credits)[:32],
        description=t(language, "invoice_description", credits=credits),
        payload=f"{PAYLOAD_PREFIX}{callback_data.pack_id}",
        currency=STARS,
        prices=[LabeledPrice(label=f"{credits} ⚡", amount=stars)],
    )


def _pack_id(payload: str) -> int | None:
    tail = payload.removeprefix(PAYLOAD_PREFIX)
    return int(tail) if payload.startswith(PAYLOAD_PREFIX) and tail.isdigit() else None


@router.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Last check before Telegram takes the Stars; must be answered within 10 seconds."""
    pack_id = _pack_id(query.invoice_payload)
    async with session_factory() as session, session.begin():
        user = await _user(session, query.from_user)
        language = user.language
        pack = await session.get(Pack, pack_id) if pack_id is not None else None
        try:
            pack = await sellable_pack(session, user, pack)
        except OrderError as exc:
            await query.answer(ok=False, error_message=_order_error(language, exc))
            return
        price_ok = query.currency == STARS and pack.price_stars == query.total_amount
    if not price_ok:
        # The price changed after the invoice was sent; a fresh invoice shows the new one.
        await query.answer(ok=False, error_message=t(language, "order_pack_unavailable"))
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(
    message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    payment = message.successful_payment
    if payment is None or message.from_user is None:
        return
    pack_id = _pack_id(payment.invoice_payload)
    if pack_id is None:
        return
    async with session_factory() as session, session.begin():
        user = await _user(session, message.from_user)
        completed = await record_stars_payment(
            session,
            user,
            pack_id,
            payment.telegram_payment_charge_id,
            payment.total_amount,
            datetime.now(UTC),
        )
        if not completed.credited:
            return
        notices = await payment_notices(session, completed.payment_id, completed.referrer_id)
    if notices is None:
        return
    await message.answer(paid_text(notices.payer))
    if notices.referrer is not None:
        await bot.send_message(notices.referrer.chat_id, referral_text(notices.referrer))


@router.callback_query(ShopCb.filter(F.action == ShopAction.INVITE))
async def invite(
    query: CallbackQuery,
    shop_config: ShopConfig,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session.begin():
        language = (await _user(session, query.from_user)).language
    link = f"https://t.me/{shop_config.bot_username}?start={REFERRAL_PREFIX}{query.from_user.id}"
    await query.answer()
    if query.message is not None:
        await query.message.answer(
            t(language, "invite", bonus=REFERRAL_BONUS, link=link),
            reply_markup=invite_keyboard(language, link),
        )


@router.callback_query(ShopCb.filter(F.action == ShopAction.PROMO))
async def ask_promo(
    query: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session, session.begin():
        language = (await _user(session, query.from_user)).language
    await state.set_state(ShopFlow.waiting_promo)
    await query.answer()
    if query.message is not None:
        await query.message.answer(t(language, "promo_ask"))


PROMO_LIMIT = 10
PROMO_WINDOW_SECONDS = 3600


@router.message(StateFilter(ShopFlow.waiting_promo), F.text, ~F.text.in_(MENU_TEXTS))
async def receive_promo(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    arq: ArqRedis,
) -> None:
    if message.from_user is None or message.text is None:
        return
    limiter = RateLimiter(arq)
    if not await limiter.allow(
        f"bot-promo:{message.from_user.id}", PROMO_LIMIT, PROMO_WINDOW_SECONDS
    ):
        await state.clear()
        await message.answer(
            t(Language.UZ, "promo_too_many") + "\n" + t(Language.RU, "promo_too_many")
        )
        return
    async with session_factory() as session, session.begin():
        user = await _user(session, message.from_user)
        language = user.language
        try:
            credits = await redeem_promo(session, user.id, message.text, datetime.now(UTC))
        except PromoError as exc:
            text = t(language, f"promo_{exc.reason}")
        else:
            available = (await get_balance(session, user.id)).available
            text = t(language, "promo_ok", credits=credits, available=available)
    await state.clear()
    await message.answer(text)


@router.message(Command("paysupport"))
async def paysupport(
    message: Message, shop_config: ShopConfig, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Telegram requires bots selling for Stars to answer /paysupport."""
    if message.from_user is None:
        return
    async with session_factory() as session, session.begin():
        language = (await _user(session, message.from_user)).language
    contact = shop_config.support_contact or shop_config.site_url
    await message.answer(
        t(
            language,
            "paysupport",
            contact=contact,
            telegram_id=message.from_user.id,
            terms=shop_config.terms_url(language),
        )
    )


@router.message(Command("terms"))
async def terms(
    message: Message, shop_config: ShopConfig, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    if message.from_user is None:
        return
    async with session_factory() as session, session.begin():
        language = (await _user(session, message.from_user)).language
    await message.answer(shop_config.terms_url(language))
