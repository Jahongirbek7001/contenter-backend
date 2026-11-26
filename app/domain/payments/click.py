"""Click SHOP-API: Click calls Prepare (action=0), then Complete (action=1).

Docs: https://docs.click.uz/click-api-request/
`merchant_trans_id` is our `payments.id`; `merchant_prepare_id` echoes it back.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.payments.orders import (
    Completed,
    OrderError,
    cancel_payment,
    check_payable,
    complete_payment,
)
from app.models import Payment
from app.models.enums import PaymentProvider, PaymentStatus

PREPARE = 0
COMPLETE = 1


class Code(IntEnum):
    SUCCESS = 0
    SIGN_FAILED = -1
    INVALID_AMOUNT = -2
    ACTION_NOT_FOUND = -3
    ALREADY_PAID = -4
    ORDER_NOT_FOUND = -5
    TRANSACTION_NOT_FOUND = -6
    UPDATE_FAILED = -7
    BAD_REQUEST = -8
    CANCELLED = -9


NOTES: dict[Code, str] = {
    Code.SUCCESS: "Success",
    Code.SIGN_FAILED: "SIGN CHECK FAILED!",
    Code.INVALID_AMOUNT: "Incorrect parameter amount",
    Code.ACTION_NOT_FOUND: "Action not found",
    Code.ALREADY_PAID: "Already paid",
    Code.ORDER_NOT_FOUND: "Order not found",
    Code.TRANSACTION_NOT_FOUND: "Transaction does not exist",
    Code.UPDATE_FAILED: "Failed to update order",
    Code.BAD_REQUEST: "Error in request from click",
    Code.CANCELLED: "Transaction cancelled",
}

REQUIRED = (
    "click_trans_id",
    "service_id",
    "merchant_trans_id",
    "amount",
    "action",
    "sign_time",
    "sign_string",
)


@dataclass(frozen=True)
class Result:
    body: dict[str, Any]
    completed: Completed | None = None


def signature(form: dict[str, str], secret_key: str, *, with_prepare_id: bool) -> str:
    parts = [form["click_trans_id"], form["service_id"], secret_key, form["merchant_trans_id"]]
    if with_prepare_id:
        parts.append(form["merchant_prepare_id"])
    parts += [form["amount"], form["action"], form["sign_time"]]
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _reply(form: dict[str, str], code: Code, **ids: int) -> Result:
    body: dict[str, Any] = {
        "click_trans_id": form.get("click_trans_id"),
        "merchant_trans_id": form.get("merchant_trans_id"),
        "error": int(code),
        "error_note": NOTES[code],
        **ids,
    }
    return Result(body)


async def handle(
    session: AsyncSession, form: dict[str, str], service_id: str, secret_key: str, now: datetime
) -> Result:
    if any(not form.get(field) for field in REQUIRED):
        return _reply(form, Code.BAD_REQUEST)
    action = form["action"]
    if action not in (str(PREPARE), str(COMPLETE)):
        return _reply(form, Code.ACTION_NOT_FOUND)
    is_complete = action == str(COMPLETE)
    if is_complete and not form.get("merchant_prepare_id"):
        return _reply(form, Code.BAD_REQUEST)
    expected = signature(form, secret_key, with_prepare_id=is_complete)
    if form["service_id"] != service_id or not hmac.compare_digest(
        expected, form["sign_string"].lower()
    ):
        return _reply(form, Code.SIGN_FAILED)

    order_id = form["merchant_trans_id"]
    payment = await session.scalar(
        select(Payment)
        .where(
            Payment.id == (int(order_id) if order_id.isdigit() else 0),
            Payment.provider == PaymentProvider.CLICK,
        )
        .with_for_update()
    )
    if payment is None:
        return _reply(form, Code.ORDER_NOT_FOUND)
    if not _amount_matches(form["amount"], payment.amount):
        return _reply(form, Code.INVALID_AMOUNT)
    if is_complete:
        return await _complete(session, form, payment, now)
    return await _prepare(session, form, payment, now)


def _amount_matches(raw: str, expected_uzs: int) -> bool:
    try:
        return Decimal(raw) == Decimal(expected_uzs)
    except InvalidOperation:
        return False


async def _prepare(
    session: AsyncSession, form: dict[str, str], payment: Payment, now: datetime
) -> Result:
    if payment.status is PaymentStatus.PAID:
        return _reply(form, Code.ALREADY_PAID)
    if payment.status is PaymentStatus.CANCELLED:
        return _reply(form, Code.CANCELLED)
    try:
        await check_payable(session, payment)
    except OrderError:
        return _reply(form, Code.ORDER_NOT_FOUND)
    # Click may prepare again with a new transaction after a failed attempt.
    payment.provider_tx_id = form["click_trans_id"]
    payment.provider_created_at = now
    await session.flush()
    return _reply(form, Code.SUCCESS, merchant_prepare_id=payment.id)


async def _complete(
    session: AsyncSession, form: dict[str, str], payment: Payment, now: datetime
) -> Result:
    if form["merchant_prepare_id"] != str(payment.id) or (
        payment.provider_tx_id != form["click_trans_id"]
    ):
        return _reply(form, Code.TRANSACTION_NOT_FOUND)
    if payment.status is PaymentStatus.PAID:
        return _reply(form, Code.ALREADY_PAID, merchant_confirm_id=payment.id)
    if payment.status is PaymentStatus.CANCELLED:
        return _reply(form, Code.CANCELLED)
    raw_error = form.get("error") or "0"
    if not raw_error.lstrip("-").isdigit():
        return _reply(form, Code.BAD_REQUEST)
    click_error = int(raw_error)
    if click_error < 0:
        # Click could not take the money (card declined, timeout...).
        cancel_payment(payment, click_error, now)
        return _reply(form, Code.CANCELLED)
    completed = await complete_payment(session, payment, now)
    result = _reply(form, Code.SUCCESS, merchant_confirm_id=payment.id)
    return Result(result.body, completed)
