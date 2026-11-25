from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.core.telegram_auth import InitDataError, validate_init_data
from app.domain.users import get_or_create_user
from app.models import User

AUTH_SCHEME = "tma "
REFERRAL_PREFIX = "ref_"

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class MiniAppAuth:
    bot_token: str
    # Local development only: browser sessions without initData act as this Telegram user.
    dev_telegram_id: int | None = None


def _referrer(start_param: str | None) -> int | None:
    if start_param and start_param.startswith(REFERRAL_PREFIX):
        tail = start_param[len(REFERRAL_PREFIX) :]
        return int(tail) if tail.isdigit() else None
    return None


async def miniapp_user(
    request: Request,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    auth: MiniAppAuth = request.app.state.miniapp_auth
    if authorization and authorization.startswith(AUTH_SCHEME):
        try:
            tg_user = validate_init_data(authorization[len(AUTH_SCHEME) :], auth.bot_token)
        except InitDataError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        lookup = await get_or_create_user(
            session, tg_user.telegram_id, tg_user.language_code, _referrer(tg_user.start_param)
        )
    elif auth.dev_telegram_id is not None:
        lookup = await get_or_create_user(session, auth.dev_telegram_id, None)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "open the app from Telegram")
    if lookup.created:
        await session.commit()
    if lookup.user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "blocked")
    return lookup.user


MiniAppUserDep = Annotated[User, Depends(miniapp_user)]
