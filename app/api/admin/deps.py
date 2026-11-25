from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.domain.admin.service import resolve_session
from app.models import AdminUser
from app.models.enums import AdminRole

SESSION_COOKIE = "admin_session"
EDITOR_ROLES = frozenset({AdminRole.OWNER, AdminRole.ADMIN})

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_admin(
    session: SessionDep,
    admin_session: Annotated[str | None, Cookie()] = None,
) -> AdminUser:
    if admin_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    admin = await resolve_session(session, admin_session)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    return admin


async def editor_admin(admin: Annotated[AdminUser, Depends(current_admin)]) -> AdminUser:
    if admin.role not in EDITOR_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "read-only role")
    return admin


CurrentAdmin = Annotated[AdminUser, Depends(current_admin)]
EditorAdmin = Annotated[AdminUser, Depends(editor_admin)]
