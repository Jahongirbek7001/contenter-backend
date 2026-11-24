"""Google list prices used to record cost_usd per generation (docs/research-log.md).

Gemini API models bill by tokens; usage comes back on every interaction. Rates are
USD per 1M tokens. Input rates for Omni and Nano Banana are not on the public pricing
page, so the Hydrogen input rate is used as an estimate; input is a small share of
their cost (output video/image tokens dominate).
"""

from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import Resolution

_PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class TokenRates:
    input_per_million: Decimal
    output_per_million: Decimal


TOKEN_RATES: dict[str, TokenRates] = {
    "gemini-4-hydrogen": TokenRates(Decimal("1.50"), Decimal("7.50")),
    "gemini-omni-1.2-flash": TokenRates(Decimal("1.50"), Decimal("12.00")),
    "gemini-nano-banana-2.1": TokenRates(Decimal("1.50"), Decimal("30.00")),
}

FLAT_REQUEST_PRICES: dict[str, Decimal] = {
    "lyria-3-clip-preview": Decimal("0.04"),
}

# Vertex Veo, silent tier, USD per second of output.
VEO_PER_SECOND: dict[str, dict[Resolution, Decimal]] = {
    "veo-3.1-lite-generate-001": {
        Resolution.P720: Decimal("0.03"),
        Resolution.P1080: Decimal("0.05"),
    },
}


class UnknownPriceError(LookupError):
    pass


def token_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    rates = TOKEN_RATES.get(model)
    if rates is None:
        raise UnknownPriceError(f"no token rates for {model}")
    return (
        Decimal(input_tokens) * rates.input_per_million
        + Decimal(output_tokens) * rates.output_per_million
    ) / _PER_MILLION


def request_cost(model: str) -> Decimal:
    price = FLAT_REQUEST_PRICES.get(model)
    if price is None:
        raise UnknownPriceError(f"no request price for {model}")
    return price


def veo_cost(model: str, resolution: Resolution, seconds: int) -> Decimal:
    per_second = VEO_PER_SECOND.get(model, {}).get(resolution)
    if per_second is None:
        raise UnknownPriceError(f"no Veo price for {model} {resolution}")
    return per_second * seconds
