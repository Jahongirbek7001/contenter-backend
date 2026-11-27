"""Owner alerts in Telegram (Uzbek; ALERT_CHAT_ID). Formatting only, no I/O."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from app.domain.stats import Totals
from app.models import Generation

MAX_LISTED = 10


def _usd(value: Decimal) -> str:
    return f"${value:.2f}"


def failures_text(failed: Sequence[Generation], admin_url: str) -> str:
    lines = [f"⚠️ <b>{len(failed)} ta generatsiya xato bilan tugadi</b> (⚡ qaytarildi)"]
    for generation in failed[:MAX_LISTED]:
        error = generation.error_code or "xato"
        lines.append(f"#{generation.id} · {generation.product.value} · {error}")
    if len(failed) > MAX_LISTED:
        lines.append(f"…va yana {len(failed) - MAX_LISTED} ta")
    lines.append(f"{admin_url}/admin/generations")
    return "\n".join(lines)


def cost_text(spent: Decimal, limit: int, generations: int) -> str:
    return (
        f"💸 <b>Bugungi model xarajati {_usd(spent)}</b> — chegara ${limit} dan oshdi.\n"
        f"Bugun generatsiyalar: {generations}. Chegara: Admin → Bonuslar → Sozlamalar."
    )


def daily_text(day: date, totals: Totals) -> str:
    return "\n".join(
        (
            f"📊 <b>{day:%d.%m.%Y} hisoboti</b>",
            f"Yangi mijozlar: {totals.new_users}",
            (
                f"Videolar: {totals.generations} "
                f"(tayyor {totals.succeeded} · xato {totals.failed} · blok {totals.blocked})"
            ),
            (
                f"To'lovlar: {totals.payments} — {totals.revenue_uzs:,} so'm + "
                f"{totals.revenue_stars} ⭐ (~{_usd(totals.revenue_usd)})"
            ).replace(",", " "),
            f"Model xarajati: {_usd(totals.cost_usd)}",
            f"Marja: ~{_usd(totals.margin_usd)}",
            (
                f"⚡ sotildi {totals.credits_sold} · sovg'a {totals.credits_gifted} · "
                f"sarflandi {totals.credits_spent}"
            ),
        )
    )
