"""Shared Postgres enum types; one instance per type so migrations create each type once."""

from app.models.base import pg_enum
from app.models.enums import (
    GenerationStatus,
    HoldStatus,
    Language,
    LedgerKind,
    PaymentProvider,
    PaymentStatus,
    Product,
    Resolution,
)

LANGUAGE = pg_enum(Language, "language")
PRODUCT = pg_enum(Product, "product")
RESOLUTION = pg_enum(Resolution, "resolution")
GENERATION_STATUS = pg_enum(GenerationStatus, "generation_status")
LEDGER_KIND = pg_enum(LedgerKind, "ledger_kind")
HOLD_STATUS = pg_enum(HoldStatus, "hold_status")
PAYMENT_PROVIDER = pg_enum(PaymentProvider, "payment_provider")
PAYMENT_STATUS = pg_enum(PaymentStatus, "payment_status")
