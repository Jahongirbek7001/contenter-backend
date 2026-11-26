from enum import StrEnum

from aiogram.filters.callback_data import CallbackData

from app.models.enums import Language, Product, Resolution, TrendAudience


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


class StyleCb(CallbackData, prefix="sty"):
    product: Product
    style_id: int


class SpokenRulesCb(CallbackData, prefix="srules"):
    product: Product
    style_id: int


class ScriptAction(StrEnum):
    APPROVE = "ok"
    REWRITE = "re"
    EDIT = "ed"


class ScriptCb(CallbackData, prefix="scr"):
    action: ScriptAction


class ResolutionCb(CallbackData, prefix="res"):
    resolution: Resolution


class OptionAction(StrEnum):
    SUBTITLES = "sub"
    CONTACT = "con"
    CREATE = "go"


class OptionCb(CallbackData, prefix="opt"):
    action: OptionAction


class BuyCb(CallbackData, prefix="buy"):
    pack_id: int


class ShopAction(StrEnum):
    PROMO = "promo"
    INVITE = "inv"


class ShopCb(CallbackData, prefix="shop"):
    action: ShopAction
