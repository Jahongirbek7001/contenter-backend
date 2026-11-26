"""Payme and Click call these while a site customer pays (server to server)."""

import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Annotated, Any

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.core.config import Settings
from app.domain.payments import click, payme
from app.domain.payments.checkout import ClickCheckout, PaymeCheckout
from app.domain.payments.orders import Completed

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger(__name__)

PAYMENT_NOTIFICATION_JOB = "payment_notification"

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class Gateways:
    site_url: str
    payme: PaymeCheckout | None = None
    payme_key: str | None = None
    click: ClickCheckout | None = None
    click_secret_key: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "Gateways":
        """A provider stays off until all of its merchant credentials are set."""
        gateways = cls(site_url=settings.site_url.rstrip("/"))
        if settings.payme_merchant_id and settings.payme_key:
            gateways = replace(
                gateways,
                payme=PaymeCheckout(settings.payme_merchant_id, settings.payme_test),
                payme_key=settings.payme_key.get_secret_value(),
            )
        if settings.click_service_id and settings.click_merchant_id and settings.click_secret_key:
            gateways = replace(
                gateways,
                click=ClickCheckout(settings.click_service_id, settings.click_merchant_id),
                click_secret_key=settings.click_secret_key.get_secret_value(),
            )
        return gateways


def _gateways(request: Request) -> Gateways:
    gateways: Gateways = request.app.state.gateways
    return gateways


async def notify_paid(request: Request, completed: Completed | None) -> None:
    """The worker messages the customer (and inviter) in the bot; a Redis hiccup must not
    fail a payment the provider already considers done."""
    if completed is None or not completed.credited:
        return
    arq: ArqRedis = request.app.state.arq
    try:
        await arq.enqueue_job(
            PAYMENT_NOTIFICATION_JOB,
            completed.payment_id,
            completed.referrer_id,
            _job_id=f"payment:{completed.payment_id}",
        )
    except Exception:
        logger.exception("could not queue the notification for payment %s", completed.payment_id)


@router.post("/payme")
async def payme_rpc(
    request: Request,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """JSON-RPC: Payme expects HTTP 200 with either `result` or `error`."""
    gateways = _gateways(request)
    request_id: Any = None
    try:
        payload = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _rpc_error(None, payme.PaymeError(payme.Code.PARSE_ERROR))
    if not isinstance(payload, dict):
        return _rpc_error(None, payme.PaymeError(payme.Code.INVALID_REQUEST))
    request_id = payload.get("id")
    if gateways.payme_key is None or not payme.authorized(authorization, gateways.payme_key):
        return _rpc_error(request_id, payme.PaymeError(payme.Code.UNAUTHORIZED))
    method, params = payload.get("method"), payload.get("params")
    if not isinstance(method, str) or not isinstance(params, dict):
        return _rpc_error(request_id, payme.PaymeError(payme.Code.INVALID_REQUEST))
    try:
        result = await payme.handle(session, method, params, datetime.now(UTC))
    except payme.PaymeError as error:
        # A timed-out transaction is cancelled before the error is returned.
        await session.commit()
        return _rpc_error(request_id, error)
    await session.commit()
    await notify_paid(request, result.completed)
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result.body})


def _rpc_error(request_id: Any, error: payme.PaymeError) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": error.payload()})


@router.post("/click/prepare")
@router.post("/click/complete")
async def click_shop_api(request: Request, session: SessionDep) -> JSONResponse:
    """Prepare and Complete differ by `action`, so both URLs share one handler."""
    gateways = _gateways(request)
    form = {key: value for key, value in (await request.form()).items() if isinstance(value, str)}
    if gateways.click is None or gateways.click_secret_key is None:
        result = click.Result({"error": int(click.Code.SIGN_FAILED), "error_note": "disabled"})
        return JSONResponse(result.body)
    result = await click.handle(
        session, form, gateways.click.service_id, gateways.click_secret_key, datetime.now(UTC)
    )
    await session.commit()
    await notify_paid(request, result.completed)
    return JSONResponse(result.body)
