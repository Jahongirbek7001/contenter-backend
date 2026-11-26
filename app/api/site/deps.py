from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.domain.site_sessions import resolve_session
from app.models import User

SESSION_COOKIE = "site_session"

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def site_user(
    session: SessionDep,
    site_session: Annotated[str | None, Cookie()] = None,
) -> User:
    if site_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    user = await resolve_session(session, site_session)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "blocked")
    return user


SiteUserDep = Annotated[User, Depends(site_user)]
