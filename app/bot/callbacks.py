from aiogram.filters.callback_data import CallbackData

from app.models.enums import Language, TrendAudience


class LanguageCb(CallbackData, prefix="lang"):
    language: Language


class RulesCb(CallbackData, prefix="rules"):
    template_id: int


class GalleryCb(CallbackData, prefix="gal"):
    audience: TrendAudience
    index: int


class PickCb(CallbackData, prefix="pick"):
    template_id: int


class RegenCb(CallbackData, prefix="regen"):
    generation_id: int
