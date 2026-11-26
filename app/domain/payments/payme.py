"""Payme Merchant API (JSON-RPC 2.0): Payme calls us while the customer pays.

Docs: https://developer.help.paycom.uz/metody-merchant-api/
The order is our `payments` row; Payme's account field is `order_id` (set in the Payme
cabinet). Amounts are in tiyin (1 so'm = 100 tiyin).
"""

import base64
import binascii
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
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

ACCOUNT_FIELD = "order_id"
TIYIN_PER_UZS = 100
# A created transaction Payme has not performed in 12 hours is cancelled (reason 4).
TRANSACTION_TIMEOUT = timedelta(hours=12)
TIMEOUT_REASON = 4


class State(IntEnum):
    CREATED = 1
    PERFORMED = 2
    CANCELLED = -1
    CANCELLED_AFTER_PERFORM = -2


class Code(IntEnum):
    INVALID_REQUEST = -32600
    PARSE_ERROR = -32700
    METHOD_NOT_FOUND = -32601
    UNAUTHORIZED = -32504
    INVALID_AMOUNT = -31001
    TRANSACTION_NOT_FOUND = -31003
    CANNOT_CANCEL = -31007
    CANNOT_PERFORM = -31008
    # -31050..-31099: problems with the account (our order).
    ORDER_NOT_FOUND = -31050
    ORDER_BUSY = -31051
    ORDER_UNAVAILABLE = -31052


MESSAGES: dict[Code, dict[str, str]] = {
    Code.INVALID_REQUEST: {
        "uz": "Noto'g'ri so'rov",
        "ru": "Неверный запрос",
        "en": "Invalid request",
    },
    Code.PARSE_ERROR: {"uz": "JSON xato", "ru": "Ошибка JSON", "en": "Parse error"},
    Code.METHOD_NOT_FOUND: {
        "uz": "Metod topilmadi",
        "ru": "Метод не найден",
        "en": "Method not found",
    },
    Code.UNAUTHORIZED: {"uz": "Ruxsat yo'q", "ru": "Недостаточно привилегий", "en": "Unauthorized"},
    Code.INVALID_AMOUNT: {"uz": "Summa noto'g'ri", "ru": "Неверная сумма", "en": "Invalid amount"},
    Code.TRANSACTION_NOT_FOUND: {
        "uz": "Tranzaksiya topilmadi",
        "ru": "Транзакция не найдена",
        "en": "Transaction not found",
    },
    Code.CANNOT_CANCEL: {
        "uz": "Tranzaksiyani bekor qilib bo'lmaydi",
        "ru": "Невозможно отменить транзакцию",
        "en": "Unable to cancel the transaction",
    },
    Code.CANNOT_PERFORM: {
        "uz": "Tranzaksiyani bajarib bo'lmaydi",
        "ru": "Невозможно выполнить операцию",
        "en": "Unable to perform the operation",
    },
    Code.ORDER_NOT_FOUND: {
        "uz": "Buyurtma topilmadi",
        "ru": "Заказ не найден",
        "en": "Order not found",
    },
    Code.ORDER_BUSY: {
        "uz": "Buyurtma to'langan yoki to'lov kutilmoqda",
        "ru": "Заказ уже оплачен или ожидает оплаты",
        "en": "Order is already paid or awaiting payment",
    },
    Code.ORDER_UNAVAILABLE: {
        "uz": "Paket hozir sotilmaydi",
        "ru": "Пакет сейчас недоступен",
        "en": "The pack is not available",
    },
}


class PaymeError(Exception):
    def __init__(self, code: Code, data: str | None = None) -> None:
        super().__init__(f"payme error {code}")
        self.code = code
        self.data = data

    def payload(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": int(self.code), "message": MESSAGES[self.code]}
        if self.data is not None:
            error["data"] = self.data
        return error


@dataclass(frozen=True)
class Result:
    body: dict[str, Any]
    # A performed payment that credited ⚡: the user (and inviter) get a bot message.
    completed: Completed | None = None


def authorized(authorization: str | None, key: str) -> bool:
    """Payme sends `Authorization: Basic base64("Paycom:<key>")`."""
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[len("Basic ") :], validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return False
    _, _, password = decoded.partition(":")
    return hmac.compare_digest(password.encode(), key.encode())


def ms(moment: datetime | None) -> int:
    return 0 if moment is None else int(moment.timestamp() * 1000)


def state(payment: Payment) -> State:
    if payment.status is PaymentStatus.PAID:
        return State.PERFORMED
    if payment.status is PaymentStatus.CANCELLED:
        return State.CANCELLED if payment.paid_at is None else State.CANCELLED_AFTER_PERFORM
    return State.CREATED


async def handle(
    session: AsyncSession, method: str, params: dict[str, Any], now: datetime
) -> Result:
    handlers = {
        "CheckPerformTransaction": _check_perform,
        "CreateTransaction": _create,
        "PerformTransaction": _perform,
        "CancelTransaction": _cancel,
        "CheckTransaction": _check,
        "GetStatement": _statement,
    }
    handler = handlers.get(method)
    if handler is None:
        raise PaymeError(Code.METHOD_NOT_FOUND, method)
    try:
        return await handler(session, params, now)
    except (KeyError, TypeError, ValueError) as exc:
        raise PaymeError(Code.INVALID_REQUEST, str(exc)) from exc


async def _order(session: AsyncSession, params: dict[str, Any]) -> Payment:
    raw = params["account"][ACCOUNT_FIELD]
    order_id = int(raw) if str(raw).isdigit() else 0
    payment = await session.scalar(
        select(Payment)
        .where(Payment.id == order_id, Payment.provider == PaymentProvider.PAYME)
        .with_for_update()
    )
    if payment is None:
        raise PaymeError(Code.ORDER_NOT_FOUND, ACCOUNT_FIELD)
    if int(params["amount"]) != payment.amount * TIYIN_PER_UZS:
        raise PaymeError(Code.INVALID_AMOUNT)
    return payment


async def _transaction(session: AsyncSession, transaction_id: str) -> Payment:
    payment = await session.scalar(
        select(Payment)
        .where(Payment.provider == PaymentProvider.PAYME, Payment.provider_tx_id == transaction_id)
        .with_for_update()
    )
    if payment is None:
        raise PaymeError(Code.TRANSACTION_NOT_FOUND)
    return payment


async def _payable(session: AsyncSession, payment: Payment) -> None:
    try:
        await check_payable(session, payment)
    except OrderError as exc:
        raise PaymeError(Code.ORDER_UNAVAILABLE, exc.reason) from exc


def _expired(payment: Payment, now: datetime) -> bool:
    created = payment.provider_created_at
    return created is not None and now - created > TRANSACTION_TIMEOUT


def _created_body(payment: Payment) -> dict[str, Any]:
    return {
        "create_time": ms(payment.provider_created_at),
        "transaction": str(payment.id),
        "state": int(state(payment)),
    }


async def _check_perform(session: AsyncSession, params: dict[str, Any], now: datetime) -> Result:
    payment = await _order(session, params)
    if payment.status is not PaymentStatus.PENDING or payment.provider_tx_id is not None:
        raise PaymeError(Code.ORDER_BUSY, ACCOUNT_FIELD)
    await _payable(session, payment)
    return Result({"allow": True})


async def _create(session: AsyncSession, params: dict[str, Any], now: datetime) -> Result:
    transaction_id = str(params["id"])
    existing = await session.scalar(
        select(Payment)
        .where(Payment.provider == PaymentProvider.PAYME, Payment.provider_tx_id == transaction_id)
        .with_for_update()
    )
    if existing is not None:
        if state(existing) is not State.CREATED:
            raise PaymeError(Code.CANNOT_PERFORM)
        if _expired(existing, now):
            cancel_payment(existing, TIMEOUT_REASON, now)
            raise PaymeError(Code.CANNOT_PERFORM)
        return Result(_created_body(existing))

    payment = await _order(session, params)
    if payment.status is not PaymentStatus.PENDING or payment.provider_tx_id is not None:
        raise PaymeError(Code.ORDER_BUSY, ACCOUNT_FIELD)
    await _payable(session, payment)
    payment.provider_tx_id = transaction_id
    payment.provider_time = int(params["time"])
    payment.provider_created_at = now
    await session.flush()
    return Result(_created_body(payment))


async def _perform(session: AsyncSession, params: dict[str, Any], now: datetime) -> Result:
    payment = await _transaction(session, str(params["id"]))
    current = state(payment)
    completed = None
    if current is State.CREATED:
        if _expired(payment, now):
            cancel_payment(payment, TIMEOUT_REASON, now)
            raise PaymeError(Code.CANNOT_PERFORM)
        completed = await complete_payment(session, payment, now)
    elif current is not State.PERFORMED:
        raise PaymeError(Code.CANNOT_PERFORM)
    body = {"transaction": str(payment.id), "perform_time": ms(payment.paid_at), "state": 2}
    return Result(body, completed)


async def _cancel(session: AsyncSession, params: dict[str, Any], now: datetime) -> Result:
    payment = await _transaction(session, str(params["id"]))
    current = state(payment)
    if current is State.CREATED:
        cancel_payment(payment, int(params["reason"]), now)
    elif current is State.PERFORMED:
        # Credited ⚡ may already be spent; refunds go through support, not Payme.
        raise PaymeError(Code.CANNOT_CANCEL)
    return Result(
        {
            "transaction": str(payment.id),
            "cancel_time": ms(payment.cancelled_at),
            "state": int(state(payment)),
        }
    )


async def _check(session: AsyncSession, params: dict[str, Any], now: datetime) -> Result:
    payment = await _transaction(session, str(params["id"]))
    return Result(_details(payment))


def _details(payment: Payment) -> dict[str, Any]:
    return {
        "create_time": ms(payment.provider_created_at),
        "perform_time": ms(payment.paid_at),
        "cancel_time": ms(payment.cancelled_at),
        "transaction": str(payment.id),
        "state": int(state(payment)),
        "reason": payment.cancel_reason,
    }


async def _statement(session: AsyncSession, params: dict[str, Any], now: datetime) -> Result:
    payments = await session.scalars(
        select(Payment)
        .where(
            Payment.provider == PaymentProvider.PAYME,
            Payment.provider_tx_id.is_not(None),
            Payment.provider_time >= int(params["from"]),
            Payment.provider_time <= int(params["to"]),
        )
        .order_by(Payment.provider_time)
    )
    transactions = [
        {
            "id": payment.provider_tx_id,
            "time": payment.provider_time,
            "amount": payment.amount * TIYIN_PER_UZS,
            "account": {ACCOUNT_FIELD: str(payment.id)},
            **_details(payment),
        }
        for payment in payments
    ]
    return Result({"transactions": transactions})
