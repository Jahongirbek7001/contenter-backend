"""Links that send the customer from the site to the Payme / Click payment page."""

import base64
from dataclasses import dataclass
from urllib.parse import urlencode

from app.domain.payments.payme import ACCOUNT_FIELD, TIYIN_PER_UZS
from app.models import Payment
from app.models.enums import Language

PAYME_CHECKOUT = "https://checkout.paycom.uz"
PAYME_TEST_CHECKOUT = "https://test.paycom.uz"
CLICK_CHECKOUT = "https://my.click.uz/services/pay"


@dataclass(frozen=True)
class PaymeCheckout:
    merchant_id: str
    test: bool

    def url(self, payment: Payment, language: Language, return_url: str) -> str:
        params = ";".join(
            (
                f"m={self.merchant_id}",
                f"ac.{ACCOUNT_FIELD}={payment.id}",
                f"a={payment.amount * TIYIN_PER_UZS}",
                f"l={language.value}",
                f"c={return_url}",
            )
        )
        base = PAYME_TEST_CHECKOUT if self.test else PAYME_CHECKOUT
        return f"{base}/{base64.b64encode(params.encode()).decode()}"


@dataclass(frozen=True)
class ClickCheckout:
    service_id: str
    merchant_id: str

    def url(self, payment: Payment, return_url: str) -> str:
        query = urlencode(
            {
                "service_id": self.service_id,
                "merchant_id": self.merchant_id,
                "amount": payment.amount,
                "transaction_param": payment.id,
                "return_url": return_url,
            }
        )
        return f"{CLICK_CHECKOUT}?{query}"
