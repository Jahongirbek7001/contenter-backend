from enum import StrEnum


class Language(StrEnum):
    UZ = "uz"
    RU = "ru"


class Product(StrEnum):
    TREND = "trend"
    TALKING = "talking"
    SERIES = "series"
    UPSCALE = "upscale"


class Resolution(StrEnum):
    P360 = "360p"
    P720 = "720p"
    P1080 = "1080p"


class GenerationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class LedgerKind(StrEnum):
    PURCHASE = "purchase"
    BONUS = "bonus"
    SPEND = "spend"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class HoldStatus(StrEnum):
    ACTIVE = "active"
    SETTLED = "settled"
    RELEASED = "released"


class PaymentProvider(StrEnum):
    STARS = "stars"
    PAYME = "payme"
    CLICK = "click"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class AdminRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    SUPPORT = "support"


class TrendBadge(StrEnum):
    NONE = "none"
    HOT = "hot"
    NEW = "new"
    TOP = "top"


class TrendAudience(StrEnum):
    ALL = "all"
    WOMEN = "women"
    MEN = "men"
