"""arq job names; the worker registers functions with exactly these names."""

from app.models.enums import Product

TREND_JOB = "trend_generation"
SPOKEN_JOB = "spoken_generation"


def job_for(product: Product) -> str:
    if product is Product.TREND:
        return TREND_JOB
    if product in (Product.TALKING, Product.SERIES):
        return SPOKEN_JOB
    raise ValueError(f"no job for {product}")


def job_id(generation_id: int) -> str:
    """Deduplicates enqueues of the same generation."""
    return f"generation:{generation_id}"
