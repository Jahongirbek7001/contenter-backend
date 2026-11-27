"""Customer side of the site: Telegram Login, balance, buying packs with Payme/Click."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.payments import Gateways
from app.api.ratelimit import limit_by_ip
from app.api.site.deps import SESSION_COOKIE, SessionDep, SiteUserDep
from app.core.telegram_auth import InitDataError, validate_login_widget
from app.domain.credits.service import get_balance
from app.domain.payments.orders import OrderError, create_site_order
from app.domain.promo import PromoError, redeem_promo
from app.domain.site_sessions import SESSION_TTL, end_session, start_session
from app.domain.users import Profile, get_or_create_user
from app.models import Pack, Payment, User
from app.models.enums import Language, PaymentProvider, PaymentStatus

router = APIRouter(prefix="/site", tags=["site"])

HISTORY_LIMIT = 50
REFERRAL_PREFIX = "ref_"


class TelegramLoginIn(BaseModel):
    """Exactly the fields the Telegram Login Widget signed, plus the site language."""

    id: int
    first_name: str | None = Field(default=None, max_length=256)
    last_name: str | None = Field(default=None, max_length=256)
    username: str | None = Field(default=None, max_length=64)
    photo_url: str | None = Field(default=None, max_length=1024)
    auth_date: int
    hash: str = Field(min_length=64, max_length=64)
    language: Language | None = None


class MeOut(BaseModel):
    telegram_id: int
    language: Language
    available: int
    held: int
    trial_used: bool
    referral_link: str
    providers: list[PaymentProvider]


class OrderIn(BaseModel):
    pack_code: str = Field(min_length=1, max_length=32)
    provider: Literal[PaymentProvider.PAYME, PaymentProvider.CLICK]


class OrderOut(BaseModel):
    payment_id: int
    checkout_url: str


class PaymentOut(BaseModel):
    id: int
    provider: PaymentProvider
    pack_title_uz: str
    pack_title_ru: str
    amount: int
    currency: str
    credits: int
    status: PaymentStatus
    created_at: datetime
    paid_at: datetime | None


class PromoIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class PromoOut(BaseModel):
    credits: int
    available: int


def _gateways(request: Request) -> Gateways:
    gateways: Gateways = request.app.state.gateways
    return gateways


async def _me(request: Request, session: SessionDep, user: User) -> MeOut:
    balance = await get_balance(session, user.id)
    gateways = _gateways(request)
    providers = [PaymentProvider.PAYME] if gateways.payme is not None else []
    if gateways.click is not None:
        providers.append(PaymentProvider.CLICK)
    bot_username: str = request.app.state.bot_username
    return MeOut(
        telegram_id=user.telegram_id,
        language=user.language,
        available=balance.available,
        held=balance.held,
        trial_used=user.trial_used,
        referral_link=f"https://t.me/{bot_username}?start={REFERRAL_PREFIX}{user.telegram_id}",
        providers=providers,
    )


@router.post("/auth/telegram", dependencies=[Depends(limit_by_ip("site-login", 20, 600))])
async def telegram_login(
    body: TelegramLoginIn, request: Request, response: Response, session: SessionDep
) -> MeOut:
    signed = body.model_dump(exclude={"language"}, exclude_none=True)
    bot_token: str = request.app.state.miniapp_auth.bot_token
    try:
        telegram_id = validate_login_widget(
            {key: str(value) for key, value in signed.items()}, bot_token
        )
    except InitDataError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    lookup = await get_or_create_user(
        session,
        telegram_id,
        body.language.value if body.language else None,
        profile=Profile(body.first_name, body.last_name, body.username),
    )
    if lookup.user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "blocked")
    token = await start_session(session, lookup.user.id)
    await session.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=request.app.state.admin_cookie_secure,
        samesite="lax",
        path="/",
    )
    return await _me(request, session, lookup.user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDep,
    response: Response,
    site_session: Annotated[str | None, Cookie()] = None,
) -> None:
    if site_session is not None:
        await end_session(session, site_session)
        await session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(request: Request, session: SessionDep, user: SiteUserDep) -> MeOut:
    return await _me(request, session, user)


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderIn, request: Request, session: SessionDep, user: SiteUserDep
) -> OrderOut:
    gateways = _gateways(request)
    try:
        payment = await create_site_order(session, user, body.pack_code, body.provider)
    except OrderError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.reason) from exc
    return_url = f"{gateways.site_url}/{user.language.value}/account?payment={payment.id}"
    if body.provider is PaymentProvider.PAYME and gateways.payme is not None:
        url = gateways.payme.url(payment, user.language, return_url)
    elif body.provider is PaymentProvider.CLICK and gateways.click is not None:
        url = gateways.click.url(payment, return_url)
    else:
        # Not committed: the order is rolled back.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "provider_disabled")
    await session.commit()
    return OrderOut(payment_id=payment.id, checkout_url=url)


@router.get("/payments")
async def payments(session: SessionDep, user: SiteUserDep) -> list[PaymentOut]:
    """Paid and cancelled payments, plus pending ones a provider has started on."""
    rows = await session.execute(
        select(Payment, Pack)
        .join(Pack, Pack.id == Payment.pack_id)
        .where(
            Payment.user_id == user.id,
            (Payment.status != PaymentStatus.PENDING) | Payment.provider_tx_id.is_not(None),
        )
        .order_by(Payment.id.desc())
        .limit(HISTORY_LIMIT)
    )
    return [
        PaymentOut(
            id=payment.id,
            provider=payment.provider,
            pack_title_uz=pack.title_uz,
            pack_title_ru=pack.title_ru,
            amount=payment.amount,
            currency=payment.currency,
            credits=payment.credits,
            status=payment.status,
            created_at=payment.created_at,
            paid_at=payment.paid_at,
        )
        for payment, pack in rows
    ]


# Codes are short words; without a limit they could be guessed.
@router.post("/promo", dependencies=[Depends(limit_by_ip("promo", 10, 3600))])
async def promo(body: PromoIn, session: SessionDep, user: SiteUserDep) -> PromoOut:
    try:
        credits = await redeem_promo(session, user.id, body.code, datetime.now(UTC))
    except PromoError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.reason) from exc
    available = (await get_balance(session, user.id)).available
    await session.commit()
    return PromoOut(credits=credits, available=available)
