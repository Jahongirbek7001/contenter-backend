from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.admin.deps import SESSION_COOKIE, CurrentAdmin, SessionDep
from app.domain.admin.service import SESSION_TTL, authenticate, end_session, start_session
from app.models import AdminUser
from app.models.enums import AdminRole

router = APIRouter(prefix="/auth")


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AdminOut(BaseModel):
    email: str
    role: AdminRole

    @classmethod
    def of(cls, admin: AdminUser) -> "AdminOut":
        return cls(email=admin.email, role=admin.role)


@router.post("/login")
async def login(
    body: LoginIn, session: SessionDep, request: Request, response: Response
) -> AdminOut:
    admin = await authenticate(session, body.email, body.password)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong email or password")
    issued = await start_session(session, admin)
    await session.commit()
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=request.app.state.admin_cookie_secure,
        samesite="lax",
        path="/",
    )
    return AdminOut.of(admin)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDep,
    response: Response,
    admin_session: Annotated[str | None, Cookie()] = None,
) -> None:
    if admin_session is not None:
        await end_session(session, admin_session)
        await session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(admin: CurrentAdmin) -> AdminOut:
    return AdminOut.of(admin)
